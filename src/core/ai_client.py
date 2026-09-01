"""Tầng 5 — AI fallback qua API OpenAI-compatible (DeepSeek / OpenAI / Ollama / LM Studio).

Nguyên tắc:
- MẶC ĐỊNH TẮT. Chỉ chạy khi bật ở cả Settings lẫn profile VÀ vẫn thiếu field bắt buộc.
- Chỉ gửi TEXT đã trích, không gửi ảnh trang.
- Few-shot prompt dựng động từ các correction đã duyệt của chính profile đó.
- Mọi field AI trả về phải qua validate của profile; fail thì LOẠI BỎ, không nhận bừa.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from .models import Profile
from .validators import validate_field_value

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "Bạn là trợ lý trích dữ liệu từ chứng từ logistics. "
    "Chỉ trả về JSON hợp lệ, không giải thích, không markdown. "
    "Field nào không tìm thấy chắc chắn trong văn bản thì trả chuỗi rỗng — "
    "TUYỆT ĐỐI không đoán, không bịa giá trị."
)


@dataclass
class AiSettings:
    base_url: str = ""
    model: str = ""
    api_key: str = ""
    timeout: int = 60
    max_chars: int = 12000
    temperature: float = 0.0


@dataclass
class FewShotExample:
    """1 ví dụ đã được người dùng duyệt: đoạn text -> field chuẩn."""

    text: str
    fields: dict[str, str] = field(default_factory=dict)


class Transport(Protocol):
    """Cho phép test tiêm transport giả, không gọi mạng thật."""

    def __call__(self, url: str, payload: dict[str, Any], headers: dict[str, str], timeout: int) -> dict[str, Any]:
        ...


def _http_transport(
    url: str, payload: dict[str, Any], headers: dict[str, str], timeout: int
) -> dict[str, Any]:
    import urllib.request

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


# ------------------------------------------------------------------- prompt


def build_messages(
    profile: Profile,
    text: str,
    missing_fields: list[str],
    examples: list[FewShotExample] | None = None,
    max_chars: int = 12000,
) -> list[dict[str, str]]:
    """Dựng messages few-shot. Ví dụ lấy từ correction đã duyệt của chính profile này."""
    wanted = missing_fields or [f.name for f in profile.fields]
    descriptions = []
    for name in wanted:
        spec = profile.field_by_name(name)
        label = spec.label if spec else name
        hint = ""
        if spec and spec.validate == "date":
            hint = f" (ngày, định dạng {profile.date_formats[0] if profile.date_formats else 'dd/mm/yyyy'})"
        elif spec and spec.validate == "container":
            hint = " (số container 11 ký tự theo ISO 6346)"
        descriptions.append(f'- "{name}": {label}{hint}')

    instruction = (
        f"Loại chứng từ: {profile.doctype or profile.name}.\n"
        "Trích các field sau từ văn bản và trả về đúng JSON với các khóa này:\n"
        + "\n".join(descriptions)
    )

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": instruction},
    ]

    # Few-shot: dạy bằng chính các lần người dùng đã sửa tay và duyệt
    for ex in (examples or [])[:5]:
        messages.append({"role": "user", "content": f"VĂN BẢN:\n{ex.text[:2000]}"})
        messages.append(
            {
                "role": "assistant",
                "content": json.dumps(
                    {k: v for k, v in ex.fields.items() if k in wanted}, ensure_ascii=False
                ),
            }
        )

    messages.append({"role": "user", "content": f"VĂN BẢN:\n{text[:max_chars]}"})
    return messages


_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def parse_response(content: str) -> dict[str, str]:
    """Bóc JSON khỏi câu trả lời (model hay bọc trong ```json). Hỏng -> dict rỗng."""
    if not content:
        return {}
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", text)
    m = _JSON_RE.search(text)
    if not m:
        return {}
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): ("" if v is None else str(v)).strip() for k, v in data.items()}


def validate_ai_fields(
    profile: Profile, raw: dict[str, str], wanted: list[str] | None = None
) -> tuple[dict[str, str], list[str]]:
    """Lọc output của AI qua rule validate của profile.

    Trả (field hợp lệ, danh sách field bị loại). Field không khai báo trong profile bị bỏ.
    """
    accepted: dict[str, str] = {}
    rejected: list[str] = []
    allowed = set(wanted) if wanted else {f.name for f in profile.fields}

    for name, value in raw.items():
        if name not in allowed:
            rejected.append(name)
            continue
        spec = profile.field_by_name(name)
        if spec is None or not str(value).strip():
            rejected.append(name)
            continue
        ok, normalized = validate_field_value(
            str(value),
            spec.validate,
            date_formats=profile.date_formats,
            regex=spec.validate_regex,
        )
        # Có validate_regex thì luôn bắt buộc phải khớp, kể cả khi validate=none
        if ok and spec.validate_regex and spec.validate != "regex":
            try:
                if not re.search(spec.validate_regex, normalized, re.IGNORECASE):
                    ok = False
            except re.error:
                logger.warning("validate_regex hỏng ở field %s", name)
        if ok:
            accepted[name] = normalized
        else:
            rejected.append(name)

    return accepted, rejected


# ------------------------------------------------------------------- client


class AiClient:
    """Client tối giản cho endpoint /chat/completions kiểu OpenAI."""

    def __init__(self, settings: AiSettings, transport: Callable | None = None) -> None:
        self.settings = settings
        self._transport = transport or _http_transport

    @property
    def configured(self) -> bool:
        return bool(self.settings.base_url and self.settings.model)

    def _endpoint(self) -> str:
        base = self.settings.base_url.rstrip("/")
        return base if base.endswith("/chat/completions") else f"{base}/chat/completions"

    def complete(self, messages: list[dict[str, str]]) -> str:
        """Gọi model, trả nội dung text. Lỗi mạng/parse -> chuỗi rỗng (không làm hỏng batch)."""
        if not self.configured:
            return ""
        headers = {"Content-Type": "application/json"}
        if self.settings.api_key:
            headers["Authorization"] = f"Bearer {self.settings.api_key}"
        payload = {
            "model": self.settings.model,
            "messages": messages,
            "temperature": self.settings.temperature,
            "stream": False,
        }
        try:
            data = self._transport(self._endpoint(), payload, headers, self.settings.timeout)
            return str(data["choices"][0]["message"]["content"])
        except Exception as exc:
            # Không log payload: chứa nội dung chứng từ của khách hàng
            logger.error("Gọi AI thất bại: %s", type(exc).__name__)
            return ""

    def extract(
        self,
        profile: Profile,
        text: str,
        missing_fields: list[str],
        examples: list[FewShotExample] | None = None,
    ) -> tuple[dict[str, str], list[str]]:
        """Trích field còn thiếu bằng AI rồi validate. Trả (field nhận, field bị loại)."""
        messages = build_messages(
            profile, text, missing_fields, examples, self.settings.max_chars
        )
        content = self.complete(messages)
        return validate_ai_fields(profile, parse_response(content), missing_fields)

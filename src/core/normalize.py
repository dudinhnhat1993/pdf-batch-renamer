"""Từ điển chuẩn hóa tên công ty: alias -> tên chuẩn.

Chứng từ logistics viết tên hãng tàu mỗi nơi một kiểu ("HLAG", "HAPAG-LLOYD AG",
"Hapag Lloyd Co., Ltd") — module này quy về đúng 1 tên để đặt file cho nhất quán.
File JSON sửa được trong GUI, không cần đụng code.
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from pathlib import Path

logger = logging.getLogger(__name__)

# Đuôi pháp lý cắt bỏ khi so khớp — không ảnh hưởng tên chuẩn ghi ra file
_LEGAL_SUFFIXES = [
    "CO LTD",
    "CO",
    "COMPANY LIMITED",
    "COMPANY",
    "LIMITED",
    "LTD",
    "JSC",
    "JOINT STOCK COMPANY",
    "CORPORATION",
    "CORP",
    "INCORPORATED",
    "INC",
    "GMBH",
    "AG",
    "SA",
    "NV",
    "BV",
    "PTE LTD",
    "PTE",
    "LLC",
    "PLC",
    "TNHH",
    "CTY",
    "CONG TY",
]


def _strip_accents(text: str) -> str:
    """Bỏ dấu tiếng Việt (đ/Đ xử lý riêng vì NFD không tách được)."""
    text = text.replace("đ", "d").replace("Đ", "D")
    return "".join(c for c in unicodedata.normalize("NFD", text) if not unicodedata.combining(c))


def match_key(value: str) -> str:
    """Khóa so khớp: bỏ dấu, viết hoa, bỏ dấu câu, gom khoảng trắng."""
    text = _strip_accents(value or "").upper()
    text = re.sub(r"[^A-Z0-9]+", " ", text)
    return " ".join(text.split())


def _without_suffix(key: str) -> str:
    """Cắt các đuôi pháp lý ở cuối, lặp tới khi không cắt được nữa."""
    changed = True
    while changed:
        changed = False
        for suffix in _LEGAL_SUFFIXES:
            if key.endswith(" " + suffix):
                key = key[: -(len(suffix) + 1)].strip()
                changed = True
    return key


class CompanyDictionary:
    """Mapping alias -> tên chuẩn. Tra cứu 2 vòng: nguyên văn, rồi bỏ đuôi pháp lý."""

    def __init__(self, aliases: dict[str, str] | None = None) -> None:
        self._raw: dict[str, str] = dict(aliases or {})
        self._index: dict[str, str] = {}
        self._index_nosuffix: dict[str, str] = {}
        self._reindex()

    def _reindex(self) -> None:
        self._index.clear()
        self._index_nosuffix.clear()
        for alias, canonical in self._raw.items():
            key = match_key(alias)
            if not key:
                continue
            self._index[key] = canonical
            self._index_nosuffix.setdefault(_without_suffix(key), canonical)
            # Chính tên chuẩn cũng phải tự khớp với nó
            ckey = match_key(canonical)
            self._index.setdefault(ckey, canonical)
            self._index_nosuffix.setdefault(_without_suffix(ckey), canonical)

    # ------------------------------------------------------------------- API

    @property
    def aliases(self) -> dict[str, str]:
        return dict(self._raw)

    def normalize(self, value: str) -> str:
        """Trả tên chuẩn nếu khớp từ điển, không khớp thì trả lại chuỗi đã dọn khoảng trắng."""
        if not value:
            return ""
        cleaned = " ".join(value.split())
        key = match_key(cleaned)
        if not key:
            return cleaned
        if key in self._index:
            return self._index[key]
        nosuffix = _without_suffix(key)
        if nosuffix in self._index:
            return self._index[nosuffix]
        if nosuffix in self._index_nosuffix:
            return self._index_nosuffix[nosuffix]
        return cleaned

    def add(self, alias: str, canonical: str) -> None:
        self._raw[alias] = canonical
        self._reindex()

    def remove(self, alias: str) -> None:
        self._raw.pop(alias, None)
        self._reindex()

    # ------------------------------------------------------------------ file

    @classmethod
    def load(cls, path: Path | str | None) -> CompanyDictionary:
        """Load từ JSON. File thiếu hoặc hỏng -> từ điển rỗng, app vẫn chạy."""
        if not path:
            return cls()
        p = Path(path)
        if not p.exists():
            return cls()
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.error("Từ điển công ty hỏng (%s) — bỏ qua chuẩn hóa", exc)
            return cls()
        aliases = data.get("aliases", data) if isinstance(data, dict) else {}
        return cls({str(k): str(v) for k, v in aliases.items()})

    def save(self, path: Path | str) -> Path:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        payload = {"aliases": dict(sorted(self._raw.items()))}
        p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return p

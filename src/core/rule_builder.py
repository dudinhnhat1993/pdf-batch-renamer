"""Sinh rule từ thao tác trực quan của người dùng (nền của Visual Rule Builder).

Người dùng bôi chọn giá trị trên trang -> module này sinh 2–3 regex ứng viên kèm
GIẢI THÍCH BẰNG TIẾNG VIỆT. Người dùng không cần hiểu regex vẫn dùng được, nhưng
nhìn giải thích lâu dần sẽ học được.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .models import MatchCondition, PageText, Zone
from .rules import RULE_FLAGS

# Ký tự thường gặp trong mã chứng từ logistics — dùng cho regex "lỏng"
LOOSE_VALUE_CLASS = r"[A-Z0-9][A-Z0-9\-/._]*"


@dataclass
class RegexCandidate:
    """1 regex ứng viên kèm lời giải thích cho người dùng cuối."""

    pattern: str
    explanation: str
    kind: str  # label | shape | line
    confidence: float = 0.5
    label: str = ""

    def test(self, text: str) -> str:
        """Chạy thử trên text, trả giá trị bắt được (rỗng nếu không trúng)."""
        try:
            m = re.search(self.pattern, text, RULE_FLAGS)
        except re.error:
            return ""
        if not m:
            return ""
        return (m.group(1) if m.groups() else m.group(0)).strip()


# --------------------------------------------------------------- mô tả hình dạng


@dataclass
class _Run:
    kind: str  # upper | lower | digit | space | other
    text: str


def _classify(ch: str) -> str:
    if ch.isdigit():
        return "digit"
    if ch.isspace():
        return "space"
    if ch.isalpha():
        return "upper" if ch.isupper() else "lower"
    return "other"


def _runs(value: str) -> list[_Run]:
    """Cắt chuỗi thành các đoạn cùng loại ký tự: 'ABCU123456' -> [upper x4, digit x6]."""
    runs: list[_Run] = []
    for ch in value:
        kind = _classify(ch)
        if runs and runs[-1].kind == kind:
            runs[-1].text += ch
        else:
            runs.append(_Run(kind, ch))
    return runs


def shape_pattern(value: str) -> str:
    """Regex mô tả đúng hình dạng của giá trị mẫu (chặt)."""
    parts: list[str] = []
    for run in _runs(value):
        n = len(run.text)
        if run.kind == "digit":
            parts.append(rf"\d{{{n}}}" if n > 1 else r"\d")
        elif run.kind == "upper":
            parts.append(rf"[A-Z]{{{n}}}" if n > 1 else r"[A-Z]")
        elif run.kind == "lower":
            parts.append(rf"[a-z]{{{n}}}" if n > 1 else r"[a-z]")
        elif run.kind == "space":
            parts.append(r"\s+")
        else:
            parts.append(re.escape(run.text))
    return "".join(parts)


def describe_shape(value: str) -> str:
    """Giải thích hình dạng bằng tiếng Việt: '4 chữ in hoa, rồi 7 chữ số'."""
    words: list[str] = []
    for run in _runs(value):
        n = len(run.text)
        if run.kind == "digit":
            words.append(f"{n} chữ số")
        elif run.kind == "upper":
            words.append(f"{n} chữ in hoa")
        elif run.kind == "lower":
            words.append(f"{n} chữ thường")
        elif run.kind == "space":
            words.append("khoảng trắng")
        else:
            words.append(f"dấu '{run.text}'")
    return ", rồi ".join(words) if words else "chuỗi bất kỳ"


# ------------------------------------------------------------------ nhãn


def _line_containing(text: str, value: str) -> tuple[str, str, str]:
    """Trả (cả dòng, phần trước giá trị, phần sau giá trị) của dòng chứa giá trị."""
    for line in text.splitlines():
        idx = line.find(value)
        if idx >= 0:
            return line, line[:idx], line[idx + len(value) :]
    return "", "", ""


def guess_label(text: str, value: str, max_words: int = 4) -> str:
    """Đoán nhãn đứng trước giá trị trên cùng dòng, vd 'B/L No.'."""
    _, before, _ = _line_containing(text, value)
    before = before.strip().rstrip(":-#").strip()
    if not before:
        return ""
    words = before.split()
    return " ".join(words[-max_words:]) if words else ""


def label_pattern(label: str, value_pattern: str) -> str:
    """Ghép nhãn + phần bắt giá trị.

    Phần ngăn cách để lỏng ([\\s:.\\-#]*) để nhãn người dùng gõ thiếu dấu chấm hay
    thừa dấu hai chấm vẫn khớp — chứng từ mỗi hãng viết một kiểu.
    """
    tokens = [re.escape(t) for t in label.split() if t]
    if not tokens:
        return f"({value_pattern})"
    return r"\s*".join(tokens) + r"[\s:.\-#]*(" + value_pattern + r")"


# ------------------------------------------------------------- sinh ứng viên


def generate_candidates(
    text: str, value: str, *, label_hint: str = "", limit: int = 3
) -> list[RegexCandidate]:
    """Sinh các regex ứng viên cho giá trị người dùng vừa bôi chọn.

    Thứ tự: nhãn + giá trị lỏng (bền nhất) -> nhãn + hình dạng chặt -> chỉ hình dạng.
    Ứng viên nào chạy thử trên chính file mẫu mà không ra đúng giá trị sẽ bị loại.
    """
    value = (value or "").strip()
    if not value:
        return []

    label = label_hint.strip() or guess_label(text, value)
    strict = shape_pattern(value)
    shape_words = describe_shape(value)
    candidates: list[RegexCandidate] = []

    if label:
        candidates.append(
            RegexCandidate(
                pattern=label_pattern(label, LOOSE_VALUE_CLASS),
                explanation=(
                    f"Tìm nhãn “{label}” rồi lấy cụm chữ-số đứng ngay sau nó "
                    "(bỏ qua dấu hai chấm và khoảng trắng thừa)."
                ),
                kind="label",
                confidence=0.9,
                label=label,
            )
        )
        candidates.append(
            RegexCandidate(
                pattern=label_pattern(label, strict),
                explanation=(
                    f"Tìm nhãn “{label}” rồi lấy giá trị có đúng dạng: {shape_words}. "
                    "Chặt hơn, nhưng chứng từ đổi định dạng là hỏng."
                ),
                kind="label",
                confidence=0.75,
                label=label,
            )
        )

    candidates.append(
        RegexCandidate(
            pattern=r"\b(" + strict + r")\b",
            explanation=(
                f"Không cần nhãn: tìm bất kỳ chuỗi nào có dạng {shape_words}. "
                "Dùng khi nhãn hay thay đổi, nhưng dễ bắt nhầm chuỗi khác giống dạng."
            ),
            kind="shape",
            confidence=0.6,
        )
    )

    # Chỉ giữ ứng viên thật sự bắt đúng giá trị trên file mẫu
    valid = [c for c in candidates if c.test(text) == value]
    fallback = [c for c in candidates if c not in valid and c.test(text)]
    ordered = sorted(valid, key=lambda c: -c.confidence) + sorted(
        fallback, key=lambda c: -c.confidence
    )

    seen: set[str] = set()
    unique: list[RegexCandidate] = []
    for c in ordered:
        if c.pattern in seen:
            continue
        seen.add(c.pattern)
        unique.append(c)
    return unique[:limit]


# --------------------------------------------------------------- điều kiện


def condition_from_keyword(keyword: str) -> MatchCondition:
    """Tạo điều kiện nhận diện từ keyword người dùng click trên trang xem trước."""
    return MatchCondition(kind="keyword", value=" ".join((keyword or "").split()), case_sensitive=False)


# ------------------------------------------------------------------ zonal


def zone_from_bbox(
    bbox: tuple[float, float, float, float],
    page_width: float,
    page_height: float,
    page: int = 0,
    padding: float = 0.01,
) -> Zone:
    """Đổi khung chữ nhật người dùng kéo (đơn vị point) thành Zone theo tỉ lệ 0..1."""
    if page_width <= 0 or page_height <= 0:
        return Zone(page=page)
    x0, y0, x1, y1 = bbox
    return Zone(
        page=page,
        x0=max(0.0, min(x0, x1) / page_width - padding),
        y0=max(0.0, min(y0, y1) / page_height - padding),
        x1=min(1.0, max(x0, x1) / page_width + padding),
        y1=min(1.0, max(y0, y1) / page_height + padding),
    )


def zone_around_words(page: PageText, words, padding: float = 0.01) -> Zone | None:
    """Tạo vùng bao quanh dãy từ người dùng bôi chọn."""
    if not words or not page.width or not page.height:
        return None
    bbox = (
        min(w.x0 for w in words),
        min(w.y0 for w in words),
        max(w.x1 for w in words),
        max(w.y1 for w in words),
    )
    return zone_from_bbox(bbox, page.width, page.height, page.index, padding)


# --------------------------------------------------------- giải thích regex

_EXPLAIN_RULES: list[tuple[str, str]] = [
    (r"\\d\{(\d+)\}", "{0} chữ số"),
    (r"\[A-Z\]\{(\d+)\}", "{0} chữ in hoa"),
    (r"\[a-z\]\{(\d+)\}", "{0} chữ thường"),
    (r"\\d\+", "một hoặc nhiều chữ số"),
    (r"\\d", "1 chữ số"),
    (r"\\s\*", "khoảng trắng tùy ý"),
    (r"\\s\+", "khoảng trắng"),
    (r"\\b", ""),
]


def explain_pattern(pattern: str) -> str:
    """Dịch thô 1 regex sang tiếng Việt để người dùng đọc hiểu rule mình đang dùng."""
    text = pattern
    for rx, template in _EXPLAIN_RULES:
        text = re.sub(rx, lambda m, t=template: t.format(*m.groups()), text)
    text = text.replace(r"[:\-#]?", " dấu ngăn cách tùy chọn ")
    text = re.sub(r"\((.*?)\)", r"[lấy: \1]", text)
    text = text.replace("\\", "").replace(LOOSE_VALUE_CLASS, "cụm chữ và số")
    return " ".join(text.split())

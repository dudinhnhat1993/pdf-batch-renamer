"""Validate giá trị nghiệp vụ: số container ISO 6346 và ngày tháng theo format của profile."""

from __future__ import annotations

import logging
import re
from datetime import date, datetime

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------- ISO 6346

# Bảng giá trị chữ cái theo ISO 6346: A=10, sau đó tăng dần nhưng BỎ QUA mọi bội số của 11
_LETTER_VALUES: dict[str, int] = {}
_v = 10
for _ch in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
    while _v % 11 == 0:
        _v += 1
    _LETTER_VALUES[_ch] = _v
    _v += 1

CONTAINER_RE = re.compile(r"^([A-Z]{3})([UJZ])(\d{6})(\d)$")


def normalize_container(value: str) -> str:
    """Bỏ khoảng trắng, gạch nối và viết hoa — chứng từ hay ghi 'ABCU 123456 7'."""
    return re.sub(r"[\s\-_.]", "", value or "").upper()


def container_check_digit(owner_and_serial: str) -> int | None:
    """Tính check digit cho 10 ký tự đầu (4 chữ + 6 số). Trả None nếu đầu vào sai dạng."""
    s = normalize_container(owner_and_serial)
    if len(s) != 10 or not s[:4].isalpha() or not s[4:].isdigit():
        return None
    total = 0
    for i, ch in enumerate(s):
        val = _LETTER_VALUES[ch] if ch.isalpha() else int(ch)
        total += val * (2**i)
    # Phần dư 10 được quy về 0 theo chuẩn
    return total % 11 % 10


def is_valid_container(value: str) -> bool:
    """Kiểm tra số container 11 ký tự kèm check digit chuẩn ISO 6346."""
    s = normalize_container(value)
    m = CONTAINER_RE.match(s)
    if not m:
        return False
    expected = container_check_digit(s[:10])
    return expected is not None and expected == int(s[10])


# ------------------------------------------------------------------------ ngày

# Token của format thân thiện người dùng -> directive của strptime.
# Quét từ trái sang phải, ưu tiên token dài trước để "yyyy" không bị "yy" ăn mất.
_PARSE_TOKENS: list[tuple[str, str]] = [
    ("yyyy", "%Y"),
    ("MMMM", "%B"),
    ("mmmm", "%B"),
    ("MMM", "%b"),
    ("mmm", "%b"),
    ("yy", "%y"),
    ("MM", "%m"),
    ("mm", "%m"),
    ("dd", "%d"),
    ("HH", "%H"),
    ("hh", "%H"),
    ("ss", "%S"),
]


def to_strptime(fmt: str) -> str:
    """Đổi format kiểu 'dd/mm/yyyy' sang chuỗi directive của datetime."""
    out: list[str] = []
    i = 0
    while i < len(fmt):
        for token, directive in _PARSE_TOKENS:
            if fmt.startswith(token, i):
                out.append(directive)
                i += len(token)
                break
        else:
            ch = fmt[i]
            out.append("%%" if ch == "%" else ch)
            i += 1
    return "".join(out)


# Năm 2 chữ số: <= 49 là thế kỷ 21, còn lại là thế kỷ 20.
# Chứng từ logistics hay ghi "17/7/26"; mốc mặc định của Python (00-68 -> 20xx) sẽ hiểu
# "60" thành 2060 — vô lý với chứng từ, nên chốt mốc riêng ở đây.
TWO_DIGIT_YEAR_PIVOT = 49


def _has_two_digit_year(fmt: str) -> bool:
    return "yy" in fmt and "yyyy" not in fmt


def _apply_year_pivot(parsed: date) -> date:
    """Chỉnh lại thế kỷ cho khớp mốc của app (Python mặc định 00-68 -> 20xx)."""
    yy = parsed.year % 100
    if TWO_DIGIT_YEAR_PIVOT < yy <= 99 and parsed.year >= 2000:
        return parsed.replace(year=parsed.year - 100)
    return parsed


def parse_date(value: str, formats: list[str] | None = None) -> date | None:
    """Parse ngày theo các format của profile, thử lần lượt. Ngày không hợp lệ -> None."""
    if not value:
        return None
    cleaned = " ".join(value.split()).strip(" .,;:")
    for fmt in formats or ["dd/mm/yyyy"]:
        try:
            parsed = datetime.strptime(cleaned, to_strptime(fmt)).date()
        except (ValueError, TypeError):
            continue
        return _apply_year_pivot(parsed) if _has_two_digit_year(fmt) else parsed
    return None


_OUTPUT_TOKENS: list[tuple[str, str]] = [
    ("yyyy", "%Y"),
    ("yy", "%y"),
    ("MMM", "%b"),
    ("mmm", "%b"),
    ("MM", "%m"),
    ("mm", "%m"),  # trong format xuất, mm cũng là tháng (không phải phút)
    ("dd", "%d"),
]

DEFAULT_DATE_OUTPUT = "yyyy-MM-dd"


def format_date(value: date, fmt: str = DEFAULT_DATE_OUTPUT) -> str:
    """Ghi ngày ra tên file. Mặc định yyyy-MM-dd để Explorer sắp xếp đúng thứ tự."""
    out: list[str] = []
    i = 0
    while i < len(fmt):
        for token, directive in _OUTPUT_TOKENS:
            if fmt.startswith(token, i):
                out.append(value.strftime(directive))
                i += len(token)
                break
        else:
            out.append(fmt[i])
            i += 1
    return "".join(out)


def validate_field_value(
    value: str, kind: str, *, date_formats: list[str] | None = None, regex: str = ""
) -> tuple[bool, str]:
    """Validate 1 giá trị theo kiểu khai báo trong FieldSpec.

    Trả (hợp lệ, giá trị đã chuẩn hóa). Giá trị không hợp lệ bị loại bỏ, không nhận bừa.
    """
    value = (value or "").strip()
    if not value:
        return False, ""

    if kind == "container":
        norm = normalize_container(value)
        return (True, norm) if is_valid_container(norm) else (False, "")

    if kind == "date":
        parsed = parse_date(value, date_formats)
        # Giữ nguyên chuỗi gốc; namer sẽ tự format lại khi render token {doc_date}
        return (True, value) if parsed else (False, "")

    if kind == "regex" and regex:
        try:
            return (True, value) if re.search(regex, value) else (False, "")
        except re.error:
            logger.warning("Regex validate không hợp lệ: %s", regex)
            return True, value

    return True, value

"""Render template đặt tên -> tên file hợp lệ trên Windows.

Token: {doc_date} {number} {company} {doctype} {original_name} {counter} + field tự đặt.
Định dạng riêng cho ngày: {doc_date:ddMMyyyy}. Số đếm: {counter:03}.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from datetime import date, datetime
from pathlib import Path

from .errors import TemplateError
from .validators import DEFAULT_DATE_OUTPUT, format_date, parse_date

logger = logging.getLogger(__name__)

TOKEN_RE = re.compile(r"\{([A-Za-z0-9_]+)(?::([^}]*))?\}")

# Ký tự Windows cấm trong tên file
FORBIDDEN_RE = re.compile(r'[\\/:*?"<>|]')
CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")

# Tên thiết bị bị Windows chiếm dụng — đặt trùng là không tạo được file
RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}

BUILTIN_TOKENS = ("doc_date", "number", "company", "doctype", "original_name", "counter")

MAX_NAME_LENGTH = 120


def strip_accents(text: str) -> str:
    """Bỏ dấu tiếng Việt — tùy chọn cho phần mềm kế toán cũ không đọc được Unicode."""
    text = text.replace("đ", "d").replace("Đ", "D")
    return "".join(c for c in unicodedata.normalize("NFD", text) if not unicodedata.combining(c))


def sanitize(name: str, *, remove_accents: bool = False) -> str:
    """Bỏ ký tự cấm và ký tự điều khiển, gom khoảng trắng."""
    text = FORBIDDEN_RE.sub("", name or "")
    text = re.sub(r"\s+", " ", text)
    text = CONTROL_RE.sub("", text)
    if remove_accents:
        text = strip_accents(text)
    text = text.strip()
    # Windows không cho tên kết thúc bằng dấu chấm hoặc khoảng trắng
    return text.rstrip(". ")


def tidy_separators(name: str) -> str:
    """Dọn dấu phân cách thừa do field rỗng để lại: 'INV__2026' -> 'INV_2026'."""
    text = re.sub(r"[_\-]{2,}", lambda m: m.group(0)[0], name)
    text = re.sub(r"[_\-]\s+|\s+[_\-]", lambda m: m.group(0).strip(), text)
    return text.strip(" _-")


def truncate(stem: str, limit: int) -> str:
    """Cắt tên quá dài nhưng giữ phần đuôi phân biệt (thường là số chứng từ)."""
    if len(stem) <= limit or limit <= 0:
        return stem
    if limit <= 3:
        return stem[:limit]
    head = (limit - 1) * 3 // 5
    tail = limit - 1 - head
    return f"{stem[:head]}~{stem[-tail:]}" if tail > 0 else stem[:limit]


def finalize_filename(
    stem: str,
    extension: str = ".pdf",
    *,
    max_length: int = MAX_NAME_LENGTH,
    remove_accents: bool = False,
) -> str:
    """Chốt tên file: làm sạch, chống tên thiết bị, giới hạn độ dài kể cả phần đuôi."""
    clean = tidy_separators(sanitize(stem, remove_accents=remove_accents))
    if not clean:
        clean = "khong-ten"
    if clean.upper() in RESERVED_NAMES or clean.split(".")[0].upper() in RESERVED_NAMES:
        clean = f"_{clean}"
    clean = truncate(clean, max(1, max_length - len(extension)))
    return f"{clean}{extension}"


# ------------------------------------------------------------------ template


def template_tokens(template: str) -> list[str]:
    """Danh sách token xuất hiện trong template (dùng để validate trong GUI)."""
    return [m.group(1) for m in TOKEN_RE.finditer(template or "")]


def _render_counter(value: str, spec: str) -> str:
    """{counter} mặc định 3 chữ số; {counter:05} thì 5 chữ số."""
    digits = 3
    if spec:
        m = re.match(r"0?(\d+)", spec)
        if m:
            digits = int(m.group(1))
    try:
        return str(int(value)).zfill(digits)
    except (TypeError, ValueError):
        return value or ""


def _render_date(value: str, spec: str, date_formats: list[str] | None) -> str:
    """Parse ngày theo format của profile rồi ghi ra theo format của template."""
    if not value:
        return ""
    if isinstance(value, (date, datetime)):
        parsed: date | None = value if isinstance(value, date) else value.date()
    else:
        parsed = parse_date(str(value), date_formats)
    if parsed is None:
        # Không parse được thì giữ nguyên chuỗi gốc, chỉ bỏ ký tự cấm
        return sanitize(str(value))
    return format_date(parsed, spec or DEFAULT_DATE_OUTPUT)


def render_template(
    template: str,
    values: dict[str, str],
    *,
    date_formats: list[str] | None = None,
    date_fields: set[str] | None = None,
    strict: bool = False,
) -> str:
    """Render template thành tên cơ sở (chưa gồm đuôi file và hậu tố chống trùng).

    Token không có giá trị -> chuỗi rỗng, sau đó tidy_separators dọn dấu phân cách thừa.
    strict=True thì token lạ ném TemplateError (dùng khi lưu rule trong GUI).
    """
    if not template:
        raise TemplateError("Template đặt tên đang để trống")

    date_fields = date_fields or {"doc_date"}
    unknown: list[str] = []

    def replace(m: re.Match[str]) -> str:
        name, spec = m.group(1), m.group(2) or ""
        if name not in values:
            unknown.append(name)
            return ""
        raw = values.get(name) or ""
        if name == "counter":
            return _render_counter(str(raw), spec)
        if name in date_fields:
            return _render_date(raw, spec, date_formats)
        return sanitize(str(raw))

    rendered = TOKEN_RE.sub(replace, template)
    if strict and unknown:
        raise TemplateError("Template dùng token không tồn tại: " + ", ".join(sorted(set(unknown))))
    return tidy_separators(rendered)


# ----------------------------------------------------------------- thư mục


def render_subfolder(pattern: str, when: date | None = None) -> Path:
    """Đổi mẫu thư mục con ({YYYY}-{MM}-{DD}, {YYYY}/{MM}...) thành đường dẫn tương đối."""
    d = when or date.today()
    mapping = {
        "YYYY": d.strftime("%Y"),
        "YY": d.strftime("%y"),
        "MM": d.strftime("%m"),
        "DD": d.strftime("%d"),
    }
    text = TOKEN_RE.sub(lambda m: mapping.get(m.group(1), ""), pattern or "")
    parts = [sanitize(p) for p in re.split(r"[\\/]+", text) if sanitize(p)]
    return Path(*parts) if parts else Path()


# ------------------------------------------------------------ chống trùng tên


def unique_name(
    directory: Path,
    filename: str,
    *,
    reserved: set[str] | None = None,
    max_length: int = MAX_NAME_LENGTH,
) -> str:
    """Thêm hậu tố _01, _02... khi tên đã tồn tại trên đĩa hoặc đã bị job khác giữ chỗ."""
    reserved = reserved or set()
    stem, extension = Path(filename).stem, Path(filename).suffix

    def taken(candidate: str) -> bool:
        return candidate.casefold() in reserved or (directory / candidate).exists()

    if not taken(filename):
        return filename

    for i in range(1, 1000):
        suffix = f"_{i:02d}"
        limit = max(1, max_length - len(extension) - len(suffix))
        candidate = f"{truncate(stem, limit)}{suffix}{extension}"
        if not taken(candidate):
            return candidate

    # Cực hiếm: 999 file trùng tên — dùng timestamp để chắc chắn không đè file nào
    stamp = datetime.now().strftime("%H%M%S%f")
    return f"{truncate(stem, max(1, max_length - len(extension) - len(stamp) - 1))}_{stamp}{extension}"

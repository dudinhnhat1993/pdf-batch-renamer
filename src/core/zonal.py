"""Tầng 2 — đọc text theo vùng tọa độ cố định trên trang.

Vùng lưu theo tỉ lệ 0..1 nên đổi khổ giấy hay DPI vẫn đúng chỗ.
Trang có text layer thì lọc từ theo bbox; trang scan thì cắt ảnh vùng đó rồi OCR.
"""

from __future__ import annotations

import logging
import re

from .models import PageText, Word, Zone
from .ocr import OcrEngine
from .pdfdoc import PdfDocument

logger = logging.getLogger(__name__)


def zone_to_rect(zone: Zone, width: float, height: float) -> tuple[float, float, float, float]:
    """Quy vùng tỉ lệ về tọa độ point của trang, tự sửa nếu user kéo khung ngược chiều."""
    x0, x1 = sorted((zone.x0 * width, zone.x1 * width))
    y0, y1 = sorted((zone.y0 * height, zone.y1 * height))
    return x0, y0, x1, y1


def words_in_zone(page: PageText, zone: Zone) -> list[Word]:
    """Lấy các từ có tâm nằm trong vùng — dùng tâm để từ dính mép không bị mất."""
    if not page.width or not page.height:
        return []
    x0, y0, x1, y1 = zone_to_rect(zone, page.width, page.height)
    hits = []
    for w in page.words:
        cx, cy = w.center
        if x0 <= cx <= x1 and y0 <= cy <= y1:
            hits.append(w)
    return hits


def _join_words(words: list[Word], line_tolerance: float = 3.0) -> str:
    """Ghép từ thành dòng theo tọa độ y, giữ đúng thứ tự đọc trái->phải, trên->dưới."""
    if not words:
        return ""
    ordered = sorted(words, key=lambda w: (round(w.y0, 1), w.x0))
    lines: list[list[Word]] = [[ordered[0]]]
    for w in ordered[1:]:
        if abs(w.y0 - lines[-1][0].y0) <= line_tolerance:
            lines[-1].append(w)
        else:
            lines.append([w])
    return "\n".join(
        " ".join(x.text for x in sorted(line, key=lambda w: w.x0)) for line in lines
    )


def text_in_zone(page: PageText, zone: Zone) -> str:
    """Text nằm trong vùng, lấy từ text layer của trang."""
    return _join_words(words_in_zone(page, zone))


# Cách lọc giá trị bên trong vùng — vùng thường bắt cả cụm, cần tinh lọc thêm 1 bước
ZONE_FILTERS = ("none", "label", "line", "regex")


def zone_lines(text: str) -> list[str]:
    """Các dòng có nội dung trong vùng."""
    return [line.strip() for line in (text or "").splitlines() if line.strip()]


# "Nhãn" trên chứng từ: cụm CHỮ ngắn rồi tới dấu hai chấm — "B/L No.:", "Date of Issue:".
# Phải đứng đầu dòng hoặc sau khoảng trắng, và không chứa chữ số, nếu không regex sẽ ăn
# lẹm vào giữa giá trị (HLCUSGN2412345) rồi cắt nhầm.
LABEL_RE = re.compile(r"(?:^|(?<=\s))[A-Za-zÀ-ỹ][A-Za-zÀ-ỹ/.\-' ]{0,24}:")

# Cách cắt phần đuôi sau khi đã lấy được đoạn đứng sau nhãn
ZONE_STOPS = ("", "label", "gap", "regex")


def count_labels(text: str) -> int:
    return len(LABEL_RE.findall(text or ""))


def zone_looks_ambiguous(text: str) -> bool:
    """Vùng có vẻ chứa nhiều hơn 1 giá trị -> nên nhắc người dùng lọc thêm.

    Xét cả 3 dấu hiệu: nhiều dòng, nhiều cụm giống-nhãn trên cùng dòng, hoặc quá nhiều từ.
    Dấu hiệu thứ hai là quan trọng nhất khi vùng bị gộp thành 1 dòng dài.
    """
    lines = zone_lines(text)
    if len(lines) > 1:
        return True
    if not lines:
        return False
    if count_labels(lines[0]) >= 2:
        return True
    return len(lines[0].split()) > 3


def describe_ambiguity(text: str) -> str:
    """Nói ĐÚNG tín hiệu nào khiến vùng bị coi là chứa nhiều giá trị.

    Người dùng cần biết app dựa vào đâu để còn biết chỉnh cách lọc cho trúng.
    """
    lines = zone_lines(text)
    if not lines:
        return ""

    signals = []
    if len(lines) > 1:
        signals.append(f"vùng có {len(lines)} dòng")
    labels = count_labels(text)
    if labels >= 2:
        signals.append(f"phát hiện {labels} cụm giống nhãn (chữ rồi tới dấu hai chấm)")
    if len(lines) == 1 and labels < 2 and len(lines[0].split()) > 3:
        signals.append(f"dòng duy nhất có {len(lines[0].split())} từ")
    return "; ".join(signals)


def apply_zone_stop(remainder: str, stop: str = "", stop_value: str = "") -> str:
    """Cắt phần đuôi của đoạn đứng sau nhãn.

    ""      : lấy hết phần còn lại
    label   : dừng ngay trước nhãn kế tiếp ("Date of Issue:")
    gap     : dừng ở chỗ có từ 2 khoảng trắng liên tiếp (cột kế bên trên biểu mẫu)
    regex   : lấy theo biểu thức trong phần còn lại
    """
    remainder = (remainder or "").strip()
    if not remainder or not stop:
        return remainder

    if stop == "label":
        match = LABEL_RE.search(remainder)
        return remainder[: match.start()].strip(" -–|\t") if match else remainder

    if stop == "gap":
        parts = re.split(r"\s{2,}", remainder, maxsplit=1)
        return parts[0].strip()

    if stop == "regex" and stop_value:
        try:
            m = re.search(stop_value, remainder, re.IGNORECASE)
        except re.error:
            logger.warning("Regex dừng không hợp lệ: %s", stop_value)
            return remainder
        if not m:
            return ""
        return (m.group(1) if m.groups() else m.group(0)).strip()

    return remainder


def apply_zone_filter(
    text: str,
    kind: str = "none",
    value: str = "",
    stop: str = "",
    stop_value: str = "",
) -> str:
    """Tinh lọc giá trị bên trong vùng.

    none  : lấy nguyên text trong vùng
    label : lấy phần đứng sau nhãn (vd "B/L No.") rồi cắt đuôi theo `stop`
    line  : lấy dòng thứ N (đếm từ 1, chỉ tính dòng có nội dung)
    regex : lấy theo biểu thức, ưu tiên nhóm bắt đầu tiên
    """
    text = (text or "").strip()
    if not text or kind in ("", "none"):
        return text

    if kind == "label":
        label = (value or "").strip()
        if not label:
            return text
        for line in zone_lines(text):
            index = line.casefold().find(label.casefold())
            if index >= 0:
                remainder = line[index + len(label) :].strip(" :.-#\t")
                return apply_zone_stop(remainder, stop, stop_value)
        return ""

    if kind == "line":
        lines = zone_lines(text)
        try:
            number = int(value)
        except (TypeError, ValueError):
            return text
        return lines[number - 1] if 1 <= number <= len(lines) else ""

    if kind == "regex":
        if not value:
            return text
        try:
            m = re.search(value, text, re.IGNORECASE | re.MULTILINE)
        except re.error:
            logger.warning("Regex lọc vùng không hợp lệ: %s", value)
            return text
        if not m:
            return ""
        return (m.group(1) if m.groups() else m.group(0)).strip()

    return text


def extract_zone(
    doc: PdfDocument,
    zone: Zone,
    ocr: OcrEngine | None = None,
    dpi: int = 300,
) -> tuple[str, tuple[float, float, float, float] | None]:
    """Đọc vùng trên 1 trang. Không có text layer thì cắt ảnh vùng đó và OCR.

    Trả (text, bbox theo point). Trang vượt quá số trang của file -> ("", None).
    """
    if zone.page < 0 or zone.page >= doc.page_count:
        return "", None

    page = doc.page_text(zone.page)
    width, height = (page.width, page.height) if page.width else doc.page_size(zone.page)
    rect = zone_to_rect(zone, width, height)

    text = text_in_zone(page, zone) if page.words else ""
    if text.strip():
        return text.strip(), rect

    # Vùng rỗng trên text layer -> nhiều khả năng là ảnh scan, thử OCR đúng vùng đó
    if ocr is not None and ocr.available:
        try:
            image = doc.render_page(zone.page, dpi=dpi, clip=rect)
            return ocr.image_to_text(image).strip(), rect
        except Exception as exc:
            logger.warning("OCR vùng thất bại trang %s: %s", zone.page, exc)
    return "", rect

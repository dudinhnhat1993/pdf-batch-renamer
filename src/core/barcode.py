"""Tầng 3 — quét barcode/QR trên N trang đầu (số container, số booking...).

pyzbar là binding của thư viện C zbar, trên Windows cần Visual C++ Redistributable 2013.
Thiếu nó thì import chết ngay lúc load, nên ở đây bọc lại: tầng 3 tự tắt và ghi cảnh báo,
KHÔNG làm chết app (quyết định #10 trong CLAUDE.md).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from .pdfdoc import PdfDocument

logger = logging.getLogger(__name__)

_decode = None
AVAILABLE = False
UNAVAILABLE_REASON = ""

try:  # pragma: no cover - phụ thuộc môi trường
    from pyzbar.pyzbar import decode as _decode  # type: ignore

    AVAILABLE = True
except Exception as exc:  # ImportError hoặc OSError khi thiếu VC++ Redistributable
    UNAVAILABLE_REASON = (
        f"Không dùng được pyzbar ({exc}). "
        "Cài Visual C++ Redistributable 2013 x64 để bật tầng quét barcode."
    )
    logger.warning(UNAVAILABLE_REASON)


@dataclass
class BarcodeHit:
    data: str
    kind: str
    page: int
    bbox: tuple[float, float, float, float] | None = None


def scan_document(doc: PdfDocument, max_pages: int = 3, dpi: int = 300) -> list[BarcodeHit]:
    """Quét barcode/QR trên tối đa max_pages trang đầu. Trả danh sách theo thứ tự trang."""
    if not AVAILABLE:
        return []

    hits: list[BarcodeHit] = []
    scale = doc.render_scale(dpi)
    for index in range(min(max_pages, doc.page_count)):
        try:
            image = doc.render_page(index, dpi=dpi)
            for sym in _decode(image):
                try:
                    data = sym.data.decode("utf-8", errors="replace").strip()
                except Exception:
                    continue
                if not data:
                    continue
                r = sym.rect
                hits.append(
                    BarcodeHit(
                        data=data,
                        kind=str(sym.type),
                        page=index,
                        bbox=(
                            r.left / scale,
                            r.top / scale,
                            (r.left + r.width) / scale,
                            (r.top + r.height) / scale,
                        ),
                    )
                )
        except Exception as exc:
            logger.warning("Quét barcode lỗi ở trang %s: %s", index, exc)
    return hits

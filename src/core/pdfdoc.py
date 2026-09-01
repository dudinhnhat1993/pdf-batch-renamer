"""Mở PDF an toàn (kể cả file có mật khẩu) và render trang thành ảnh.

Gom về 1 chỗ để extractor / zonal / barcode / GUI dùng chung, và để test mock dễ.
Text layer + tọa độ lấy bằng pdfplumber; render ảnh dùng PyMuPDF.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from .errors import PasswordProtectedError, PdfOpenError
from .models import PageText, Word

logger = logging.getLogger(__name__)


class PdfDocument:
    """Handle 1 file PDF. Dùng như context manager để chắc chắn đóng file."""

    def __init__(self, path: Path | str, passwords: list[str] | None = None) -> None:
        import pymupdf as fitz  # tên mới của PyMuPDF; 'import fitz' đã deprecated

        self.path = Path(path)
        self.password = ""
        self._plumber: Any = None
        self._page_cache: dict[int, PageText] = {}

        if not self.path.exists():
            raise PdfOpenError(f"Không tìm thấy file: {self.path.name}")

        try:
            self.doc = fitz.open(str(self.path))
        except Exception as exc:
            raise PdfOpenError(f"Không mở được PDF: {self.path.name} ({exc})") from exc

        # PDF có mật khẩu: thử lần lượt danh sách password trong Settings, kể cả chuỗi rỗng
        if self.doc.needs_pass:
            for pwd in ["", *(passwords or [])]:
                if self.doc.authenticate(pwd):
                    self.password = pwd
                    break
            else:
                self.doc.close()
                raise PasswordProtectedError(
                    f"PDF có mật khẩu, không password nào trong Settings mở được: {self.path.name}"
                )

    # ------------------------------------------------------------------ cơ bản

    @property
    def page_count(self) -> int:
        return self.doc.page_count

    def close(self) -> None:
        try:
            self.doc.close()
        except Exception:
            pass
        if self._plumber is not None:
            try:
                self._plumber.close()
            except Exception:
                pass
            self._plumber = None

    def __enter__(self) -> PdfDocument:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ------------------------------------------------------------------- text

    def _plumber_doc(self):
        if self._plumber is None:
            import pdfplumber

            self._plumber = pdfplumber.open(
                str(self.path), password=self.password or ""
            )
        return self._plumber

    def page_text(self, index: int) -> PageText:
        """Text layer + bbox từng từ của 1 trang. Trang không có text layer trả text rỗng."""
        if index in self._page_cache:
            return self._page_cache[index]

        page = self._plumber_doc().pages[index]
        words = [
            Word(
                text=w["text"],
                x0=float(w["x0"]),
                y0=float(w["top"]),
                x1=float(w["x1"]),
                y1=float(w["bottom"]),
            )
            for w in page.extract_words(use_text_flow=False, keep_blank_chars=False)
        ]
        result = PageText(
            index=index,
            width=float(page.width),
            height=float(page.height),
            text=page.extract_text() or "",
            words=words,
        )
        self._page_cache[index] = result
        return result

    def page_size(self, index: int) -> tuple[float, float]:
        rect = self.doc[index].rect
        return float(rect.width), float(rect.height)

    # ------------------------------------------------------------------ render

    def render_page(self, index: int, dpi: int = 300, clip: tuple | None = None):
        """Render trang (hoặc 1 vùng) thành ảnh PIL. clip theo đơn vị point của trang."""
        import pymupdf as fitz
        from PIL import Image

        page = self.doc[index]
        rect = fitz.Rect(*clip) if clip else None
        pix = page.get_pixmap(dpi=dpi, clip=rect, alpha=False)
        return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)

    def render_scale(self, dpi: int) -> float:
        """Số pixel trên 1 point ở dpi cho trước — dùng để quy bbox OCR về tọa độ trang."""
        return dpi / 72.0

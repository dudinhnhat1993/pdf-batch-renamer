"""Retina PDF canvas + preview dock.

Rendering contract
------------------
* Pages are rasterised at `devicePixelRatio * metrics.canvas_oversampling`
  (2.0 by default) and the QImage carries that DPR, so Qt downsamples with
  smooth filtering — text and QR codes stay crisp on 100% and 150% displays.
* Word boxes come from PyMuPDF `page.get_text("words")` in PDF points and are
  mapped to widget space through a single QTransform, so hit-testing stays
  correct at any zoom.
* Hover paints the blue token, click/drag paints the green token; Ctrl+click
  adds to the selection instead of replacing it (multi-word, multi-line).
"""

from __future__ import annotations

from dataclasses import dataclass

import fitz  # PyMuPDF
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QImage, QPainter, QPen, QPixmap, QTransform
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QScrollArea, QToolButton, QVBoxLayout, QWidget,
)

from src.ui.theme import Theme, qcolor


@dataclass(frozen=True)
class Word:
    rect: QRectF   # PDF points
    text: str
    line: int


class PdfCanvas(QWidget):
    words_selected = Signal(list)   # list[Word]
    zone_drawn = Signal(QRectF)     # normalised 0..1 rect for zonal extraction

    def __init__(self, theme: Theme, parent=None) -> None:
        super().__init__(parent)
        self.theme = theme
        self.setMouseTracking(True)
        self.doc: fitz.Document | None = None
        self.page_index = 0
        self.zoom = 1.0
        self.zonal_mode = False
        self._pixmap: QPixmap | None = None
        self._words: list[Word] = []
        self._hover: int | None = None
        self._selected: set[int] = set()
        self._drag_origin: QPointF | None = None
        self._drag_rect: QRectF | None = None

    # ------------------------------------------------------------ loading
    def load(self, path: str, page_index: int = 0) -> None:
        self.doc = fitz.open(path)
        self.page_index = page_index
        self._selected.clear()
        self.render_page()

    @property
    def page_count(self) -> int:
        return self.doc.page_count if self.doc else 0

    def render_page(self) -> None:
        if not self.doc:
            return
        page = self.doc[self.page_index]
        oversample = float(self.theme.metric("canvas_oversampling"))
        dpr = self.devicePixelRatioF() * oversample
        matrix = fitz.Matrix(self.zoom * dpr, self.zoom * dpr)
        pix = page.get_pixmap(matrix=matrix, alpha=False)

        image = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format_RGB888)
        image = image.copy()                 # detach from the PyMuPDF buffer
        image.setDevicePixelRatio(dpr)
        self._pixmap = QPixmap.fromImage(image)

        self._words = [
            Word(QRectF(x0, y0, x1 - x0, y1 - y0), text, line)
            for x0, y0, x1, y1, text, _block, line, _wno in page.get_text("words")
        ]
        self.setFixedSize(self._pixmap.size() / dpr)
        self.update()

    def set_zoom(self, zoom: float) -> None:
        self.zoom = max(0.25, min(6.0, zoom))
        self.render_page()

    def fit_width(self, viewport_width: int) -> None:
        if not self.doc:
            return
        page_width = self.doc[self.page_index].rect.width
        self.set_zoom((viewport_width - 32) / page_width)

    # --------------------------------------------------------- transforms
    def _to_widget(self) -> QTransform:
        return QTransform().scale(self.zoom, self.zoom)

    def _word_at(self, pos: QPointF) -> int | None:
        t = self._to_widget()
        for i, w in enumerate(self._words):
            if t.mapRect(w.rect).contains(pos):
                return i
        return None

    # ------------------------------------------------------------ painting
    def paintEvent(self, _event) -> None:
        if not self._pixmap:
            return
        p = QPainter(self)
        p.setRenderHints(QPainter.SmoothPixmapTransform | QPainter.Antialiasing)
        p.drawPixmap(0, 0, self._pixmap)

        c = self.theme.palette["pdf_canvas"]
        t = self._to_widget()

        for i in self._selected:
            r = t.mapRect(self._words[i].rect)
            p.fillRect(r, qcolor(c["selected_fill"]))
            p.setPen(QPen(qcolor(c["selected_stroke"]), 1))
            p.drawRect(r)

        if self._hover is not None and self._hover not in self._selected:
            r = t.mapRect(self._words[self._hover].rect)
            p.fillRect(r, qcolor(c["hover_fill"]))
            p.setPen(QPen(qcolor(c["hover_stroke"]), 1))
            p.drawRect(r)

        if self._drag_rect is not None:
            p.fillRect(self._drag_rect, qcolor(c["zone_fill"]))
            pen = QPen(qcolor(c["zone_stroke"]), 1.5)
            pen.setStyle(Qt.DashLine)
            p.setPen(pen)
            p.drawRect(self._drag_rect)

    # ------------------------------------------------------------- events
    def mouseMoveEvent(self, event) -> None:
        if self._drag_origin is not None:
            self._drag_rect = QRectF(self._drag_origin, event.position()).normalized()
            self.update()
            return
        hover = self._word_at(event.position())
        if hover != self._hover:
            self._hover = hover
            self.setCursor(Qt.PointingHandCursor if hover is not None else Qt.ArrowCursor)
            self.update()

    def mousePressEvent(self, event) -> None:
        if self.zonal_mode:
            self._drag_origin = event.position()
            return
        idx = self._word_at(event.position())
        if idx is None:
            self._selected.clear()
        elif event.modifiers() & Qt.ControlModifier:
            self._selected.symmetric_difference_update({idx})
        else:
            self._selected = {idx}
        self.update()
        self.words_selected.emit([self._words[i] for i in sorted(self._selected)])

    def mouseReleaseEvent(self, _event) -> None:
        if self._drag_origin is None or self._drag_rect is None:
            self._drag_origin = None
            return
        w, h = max(self.width(), 1), max(self.height(), 1)
        r = self._drag_rect
        self.zone_drawn.emit(QRectF(r.x() / w, r.y() / h, r.width() / w, r.height() / h))
        self._drag_origin = None
        self._drag_rect = None
        self.update()

    def wheelEvent(self, event) -> None:
        if event.modifiers() & Qt.ControlModifier:
            self.set_zoom(self.zoom * (1.1 if event.angleDelta().y() > 0 else 0.9))
            event.accept()
        else:
            event.ignore()


class PdfPreviewDock(QWidget):
    """Header (file name, page nav, zoom) + canvas + legend."""

    def __init__(self, theme: Theme, parent=None) -> None:
        super().__init__(parent)
        self.theme = theme
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        header = QWidget(self)
        header.setObjectName("PreviewDockHeader")
        h = QHBoxLayout(header)
        h.setContentsMargins(10, 0, 10, 0)
        h.setSpacing(4)
        self.lbl_file = QLabel("—", header)
        self.lbl_file.setToolTip("Nhấp đúp để mở file gốc")
        self.btn_prev = QToolButton(header); self.btn_prev.setText("‹")
        self.lbl_page = QLabel("Trang 0 / 0", header)
        self.btn_next = QToolButton(header); self.btn_next.setText("›")
        self.btn_zoom_out = QToolButton(header); self.btn_zoom_out.setText("−")
        self.btn_zoom_in = QToolButton(header); self.btn_zoom_in.setText("+")
        self.btn_fit = QToolButton(header); self.btn_fit.setText("⊡ Vừa khung")
        h.addWidget(self.lbl_file, 1)
        for w in (self.btn_prev, self.lbl_page, self.btn_next,
                  self.btn_zoom_out, self.btn_zoom_in, self.btn_fit):
            h.addWidget(w)
        root.addWidget(header)

        self.scroll = QScrollArea(self)
        self.scroll.setObjectName("PdfCanvasScroll")
        self.scroll.setWidgetResizable(False)
        self.scroll.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        self.canvas = PdfCanvas(theme, self.scroll)
        self.scroll.setWidget(self.canvas)
        root.addWidget(self.scroll, 1)

        legend = QLabel(
            "Rê chuột: sáng từ  ·  Click / bôi: chọn  ·  Ctrl+Click: chọn nhiều  ·  "
            "Ctrl+Lăn: zoom  ·  Retina 2×", self)
        legend.setObjectName("PreviewLegend")
        legend.setContentsMargins(12, 8, 12, 8)
        root.addWidget(legend)

        self.btn_prev.clicked.connect(lambda: self.goto_page(self.canvas.page_index - 1))
        self.btn_next.clicked.connect(lambda: self.goto_page(self.canvas.page_index + 1))
        self.btn_zoom_in.clicked.connect(lambda: self.canvas.set_zoom(self.canvas.zoom * 1.15))
        self.btn_zoom_out.clicked.connect(lambda: self.canvas.set_zoom(self.canvas.zoom / 1.15))
        self.btn_fit.clicked.connect(lambda: self.canvas.fit_width(self.scroll.viewport().width()))

    def open(self, path: str, name: str) -> None:
        self.canvas.load(path)
        self.lbl_file.setText(name)
        self.canvas.fit_width(self.scroll.viewport().width())
        self._sync_page_label()

    def goto_page(self, index: int) -> None:
        if not self.canvas.doc:
            return
        self.canvas.page_index = max(0, min(self.canvas.page_count - 1, index))
        self.canvas.render_page()
        self._sync_page_label()

    def _sync_page_label(self) -> None:
        self.lbl_page.setText(f"Trang {self.canvas.page_index + 1} / {self.canvas.page_count}")

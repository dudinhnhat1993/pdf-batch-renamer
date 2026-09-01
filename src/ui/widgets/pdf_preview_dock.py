"""PDF preview dock with full page rendering, zoom, and text/zone selection.

Design spec:
- Retina 2x oversampling for sharp typography on HighDPI / standard monitors.
- Selection modes: text highlighting (click/drag), multi-selection with Ctrl, and box dragging.
- Zero file locking: loads via byte stream so moving/renaming never triggers [WinError 32].
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import fitz
from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QImage,
    QPainter,
    QPen,
    QPixmap,
    QTransform,
)
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from src.ui.qt_helpers import open_in_explorer
from src.ui.theme import Theme, qcolor



@dataclass
class Word:
    rect: QRectF
    text: str
    line: int


class PdfCanvas(QWidget):
    text_selected = Signal(str, list)  # (merged text, list of Word objects)
    zone_dragged = Signal(QRectF)  # normalized (0..1) rect

    def __init__(self, theme: Theme, parent=None) -> None:
        super().__init__(parent)
        self.theme = theme
        self.doc: fitz.Document | None = None
        self.page_index = 0
        self.zoom = 1.0
        self.mode = "text"  # "text" | "zone"

        self._pixmap: QPixmap | None = None
        self._words: list[Word] = []
        self._hover: int | None = None
        self._selected: set[int] = set()

        self._drag_origin: QPointF | None = None
        self._drag_rect: QRectF | None = None
        self.setMouseTracking(True)

    # ------------------------------------------------------------ loading
    def load(self, path: Path | str | None, page_index: int = 0) -> None:
        self.close_doc()
        if not path:
            self.update()
            return
        p = Path(path)
        if not p.exists() or p.suffix.lower() != ".pdf":
            self.update()
            return

        try:
            # Read bytes to avoid holding a Windows file handle lock
            data = p.read_bytes()
            self.doc = fitz.open(stream=data, filetype="pdf")
            self.page_index = min(page_index, max(0, self.doc.page_count - 1))
            self._selected.clear()
            self.render_page()
        except Exception:
            self.close_doc()

    def close_doc(self) -> None:
        if self.doc is not None:
            try:
                self.doc.close()
            except Exception:
                pass
            self.doc = None
        self._pixmap = None
        self._words = []
        self._hover = None
        self._selected.clear()
        self.setFixedSize(0, 0)
        self.update()

    def close_document(self) -> None:
        self.close_doc()

    @property
    def page_count(self) -> int:
        return self.doc.page_count if self.doc else 0

    def render_page(self) -> None:
        if not self.doc or self.page_count == 0:
            return
        page = self.doc[self.page_index]
        oversample = float(self.theme.metric("canvas_oversampling") or 2.0)
        dpr = (self.devicePixelRatioF() or 1.0) * oversample
        matrix = fitz.Matrix(self.zoom * dpr, self.zoom * dpr)
        pix = page.get_pixmap(matrix=matrix, alpha=False)

        image = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format.Format_RGB888)
        image = image.copy()  # detach from the PyMuPDF buffer
        image.setDevicePixelRatio(dpr)
        self._pixmap = QPixmap.fromImage(image)

        self._words = [
            Word(QRectF(x0, y0, x1 - x0, y1 - y0), text, line)
            for x0, y0, x1, y1, text, _block, line, _wno in page.get_text("words")
        ]
        self.setFixedSize(int(pix.width / dpr), int(pix.height / dpr))
        self.update()

    def set_zoom(self, zoom: float) -> None:
        self.zoom = max(0.25, min(6.0, zoom))
        self.render_page()

    def zoom_in(self) -> None:
        self.set_zoom(self.zoom * 1.15)

    def zoom_out(self) -> None:
        self.set_zoom(self.zoom / 1.15)

    def fit_width(self, viewport_width: int = 400) -> None:
        if not self.doc or self.page_count == 0:
            return
        page_width = self.doc[self.page_index].rect.width
        if page_width > 0:
            self.set_zoom(max(0.2, (viewport_width - 32) / page_width))

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
        p.setRenderHints(QPainter.RenderHint.SmoothPixmapTransform | QPainter.RenderHint.Antialiasing)
        p.drawPixmap(0, 0, self._pixmap)

        c = self.theme.palette.get("pdf_canvas", {})
        t = self._to_widget()

        for i in self._selected:
            if i < len(self._words):
                r = t.mapRect(self._words[i].rect)
                sel_fill = qcolor(c.get("selected_fill", "rgba(22,163,74,0.25)"))
                sel_stroke = qcolor(c.get("selected_stroke", "#16a34a"))
                p.fillRect(r, sel_fill)
                p.setPen(QPen(sel_stroke, 1.5))
                p.drawRoundedRect(r, 2.0, 2.0)

        if self._hover is not None and self._hover not in self._selected and self._hover < len(self._words):
            r = t.mapRect(self._words[self._hover].rect)
            hov_fill = qcolor(c.get("hover_fill", "rgba(2,132,199,0.18)"))
            hov_stroke = qcolor(c.get("hover_stroke", "#0284c7"))
            p.fillRect(r, hov_fill)
            p.setPen(QPen(hov_stroke, 1.0))
            p.drawRoundedRect(r, 2.0, 2.0)

        if self._drag_rect is not None:
            p.fillRect(self._drag_rect, qcolor(c.get("zone_fill", "rgba(31,111,235,0.12)")))
            pen = QPen(qcolor(c.get("zone_stroke", "#1f6feb")), 1.5)
            pen.setStyle(Qt.PenStyle.DashLine)
            p.setPen(pen)
            p.drawRect(self._drag_rect)

    # ------------------------------------------------------------- events
    def mouseMoveEvent(self, event) -> None:
        if self._drag_origin is not None:
            self._drag_rect = QRectF(self._drag_origin, event.position()).normalized()
            self.update()
            return

        w_idx = self._word_at(event.position())
        if w_idx != self._hover:
            self._hover = w_idx
            self.setCursor(Qt.CursorShape.PointingHandCursor if w_idx is not None else Qt.CursorShape.ArrowCursor)
            self.update()

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if self.mode == "zone":
            self._drag_origin = event.position()
            self._drag_rect = QRectF(self._drag_origin, QSize(0, 0))
            return

        w_idx = self._word_at(event.position())
        ctrl = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
        if w_idx is not None:
            if ctrl:
                if w_idx in self._selected:
                    self._selected.remove(w_idx)
                else:
                    self._selected.add(w_idx)
            else:
                self._selected = {w_idx}
            self._emit_selection()
            self.update()
        else:
            if not ctrl:
                self._selected.clear()
                self._drag_origin = event.position()
                self._drag_rect = QRectF(self._drag_origin, QSize(0, 0))
                self.update()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if self._drag_origin is not None:
            if self.mode == "zone":
                if self.doc and self.page_count > 0:
                    pw = self.doc[self.page_index].rect.width * self.zoom
                    ph = self.doc[self.page_index].rect.height * self.zoom
                    if pw > 0 and ph > 0 and self._drag_rect:
                        norm = QRectF(
                            self._drag_rect.x() / pw,
                            self._drag_rect.y() / ph,
                            self._drag_rect.width() / pw,
                            self._drag_rect.height() / ph,
                        )
                        self.zone_dragged.emit(norm)
            else:
                if self._drag_rect:
                    t = self._to_widget()
                    for i, w in enumerate(self._words):
                        if self._drag_rect.intersects(t.mapRect(w.rect)):
                            self._selected.add(i)
                    self._emit_selection()
            self._drag_origin = None
            self._drag_rect = None
            self.update()

    def wheelEvent(self, event) -> None:
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y()
            if delta > 0:
                self.zoom_in()
            else:
                self.zoom_out()
            event.accept()
        else:
            super().wheelEvent(event)

    def _emit_selection(self) -> None:
        sorted_indices = sorted(self._selected)
        words = [self._words[i] for i in sorted_indices if i < len(self._words)]
        text = " ".join(w.text for w in words)
        self.text_selected.emit(text, words)


class PdfPreviewDock(QWidget):
    def __init__(self, theme: Theme, parent=None) -> None:
        super().__init__(parent)
        self.theme = theme
        self._current_path: Path | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        header = QWidget(self)
        header.setObjectName("PreviewDockHeader")
        h = QHBoxLayout(header)
        h.setContentsMargins(12, 6, 12, 6)
        h.setSpacing(6)

        self.lbl_file = QLabel("—", header)
        self.lbl_file.setObjectName("PreviewFileName")
        self.lbl_file.setToolTip("Nhấp đúp để mở file gốc")
        self.lbl_file.mouseDoubleClickEvent = self._on_file_double_clicked

        self.btn_prev = QToolButton(header)
        self.btn_prev.setText("<")
        self.btn_prev.setToolTip("Trang trước")

        self.lbl_page = QLabel("Trang 0 / 0", header)

        self.btn_next = QToolButton(header)
        self.btn_next.setText(">")
        self.btn_next.setToolTip("Trang sau")

        self.btn_zoom_out = QToolButton(header)
        self.btn_zoom_out.setText("-")
        self.btn_zoom_out.setToolTip("Thu nhỏ (hoặc Ctrl+Lăn chuột)")

        self.btn_zoom_in = QToolButton(header)
        self.btn_zoom_in.setText("+")
        self.btn_zoom_in.setToolTip("Phóng to (hoặc Ctrl+Lăn chuột)")

        self.btn_fit = QToolButton(header)
        self.btn_fit.setText("Vừa khung")
        self.btn_fit.setToolTip("Canh vừa chiều rộng khung nhìn")

        h.addWidget(self.lbl_file, 1)
        for w in (
            self.btn_prev,
            self.lbl_page,
            self.btn_next,
            self.btn_zoom_out,
            self.btn_zoom_in,
            self.btn_fit,
        ):
            h.addWidget(w)
        root.addWidget(header)

        self.scroll = QScrollArea(self)
        self.scroll.setObjectName("PdfCanvasScroll")
        self.scroll.setWidgetResizable(False)
        self.scroll.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        self.canvas = PdfCanvas(theme, self.scroll)
        self.scroll.setWidget(self.canvas)
        root.addWidget(self.scroll, 1)

        legend = QLabel(
            "Rê chuột: sáng từ  ·  Click / bôi: chọn  ·  Ctrl+Click: chọn nhiều  ·  Ctrl+Lăn: zoom  ·  Retina 2x",
            self,
        )
        legend.setObjectName("PreviewLegend")
        legend.setContentsMargins(12, 8, 12, 8)
        root.addWidget(legend)

        self.btn_prev.clicked.connect(lambda: self.goto_page(self.canvas.page_index - 1))
        self.btn_next.clicked.connect(lambda: self.goto_page(self.canvas.page_index + 1))
        self.btn_zoom_in.clicked.connect(self.canvas.zoom_in)
        self.btn_zoom_out.clicked.connect(self.canvas.zoom_out)
        self.btn_fit.clicked.connect(lambda: self.canvas.fit_width(self.scroll.viewport().width()))

        # Backward compatibility properties
        self.file_name_label = self.lbl_file
        self.page_label = self.lbl_page
        self.view = self.canvas

    @property
    def _total_pages(self) -> int:
        return self.canvas.page_count

    def _prev_page(self) -> None:
        self.goto_page(self.canvas.page_index - 1)

    def _next_page(self) -> None:
        self.goto_page(self.canvas.page_index + 1)

    def _on_file_double_clicked(self, _event) -> None:
        if self._current_path and self._current_path.exists():
            open_in_explorer(self._current_path)

    def load_file(self, path: Path | str | None) -> None:
        if not path:
            self.clear()
            return
        p = Path(path)
        self._current_path = p
        self.lbl_file.setText(p.name)
        self.lbl_file.setToolTip(str(p))
        self.canvas.load(p)
        self.canvas.fit_width(self.scroll.viewport().width())
        self._sync_page_label()

    def open(self, path: str, name: str) -> None:
        self.load_file(path)

    def close_doc(self) -> None:
        self.clear()

    def close_document(self) -> None:
        self.clear()

    def clear(self) -> None:
        self._current_path = None
        self.lbl_file.setText("Chưa chọn file")
        self.lbl_file.setToolTip("")
        self.lbl_page.setText("0 / 0")
        self.canvas.close_doc()

    def goto_page(self, index: int) -> None:
        if not self.canvas.doc:
            return
        self.canvas.page_index = max(0, min(self.canvas.page_count - 1, index))
        self.canvas.render_page()
        self._sync_page_label()

    def _sync_page_label(self) -> None:
        total = self.canvas.page_count
        cur = (self.canvas.page_index + 1) if total > 0 else 0
        self.lbl_page.setText(f"{cur} / {total}")

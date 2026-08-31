"""Xem trang PDF kèm lớp phủ vị trí từng từ.

Đây là nền của Visual Rule Builder: người dùng click vào 1 từ (tạo điều kiện nhận diện)
hoặc bôi chọn một đoạn (tạo field). Trang scan cũng dùng được vì bbox từ OCR và bbox từ
text layer đều quy về cùng đơn vị point của trang.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QGraphicsPixmapItem,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..core.models import PageText, Word
from .qt_helpers import pil_to_qpixmap

logger = logging.getLogger(__name__)

# Kéo dưới ngưỡng này coi như click chọn 1 từ, không phải bôi chọn cả đoạn
CLICK_THRESHOLD_PX = 6


class PdfPageView(QGraphicsView):
    """Hiển thị 1 trang và cho chọn từ bằng click hoặc bôi chọn."""

    wordClicked = Signal(str)  # text của từ được click
    textSelected = Signal(str, list)  # (text đã ghép, list[Word])
    rectDragged = Signal(tuple)  # bbox theo point của trang — dành cho zonal ở bước sau

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setMouseTracking(True)

        self._pixmap_item: QGraphicsPixmapItem | None = None
        self._page: PageText | None = None
        self._scale = 1.0  # pixel ảnh trên 1 point của trang
        self._selection: list[Word] = []
        self._hover: Word | None = None
        self._drag_start = None
        self._drag_rect: QRectF | None = None
        # Tự canh vừa khung cho tới khi người dùng tự zoom lần đầu
        self._user_zoomed = False
        # "text" = bôi chọn chữ (mặc định); "zone" = kéo khung vùng cho tầng zonal
        self._mode = "text"

    # ------------------------------------------------------------------ nạp

    def load_page(self, pixmap: QPixmap, page: PageText, dpi: int = 150) -> None:
        """Nạp ảnh trang đã render kèm PageText tương ứng (text layer hoặc OCR)."""
        self._scene.clear()
        self._pixmap_item = self._scene.addPixmap(pixmap)
        self._scene.setSceneRect(QRectF(pixmap.rect()))
        self._page = page
        self._scale = dpi / 72.0
        self._selection = []
        self._hover = None
        self._drag_rect = None
        self.resetTransform()
        self.fit_width()
        self.viewport().update()

    def fit_width(self) -> None:
        """Canh trang vừa bề ngang khung nhìn."""
        if self._pixmap_item is None:
            return
        width = self._pixmap_item.pixmap().width()
        available = self.viewport().width() - 4
        if width and available > 0:
            factor = max(0.05, available / width)
            self.resetTransform()
            self.scale(factor, factor)
        self._user_zoomed = False

    def zoom(self, factor: float) -> None:
        self.scale(factor, factor)
        self._user_zoomed = True

    def resizeEvent(self, event) -> None:
        """Khung nhìn đổi kích thước thì canh lại.

        Lúc load_page() chạy, widget thường chưa có kích thước thật (chưa layout xong),
        nên nếu không canh lại ở đây thì trang hiện ra bé xíu giữa khung.
        """
        super().resizeEvent(event)
        if not self._user_zoomed:
            self.fit_width()

    @property
    def has_words(self) -> bool:
        return bool(self._page and self._page.words)

    @property
    def mode(self) -> str:
        return self._mode

    def set_mode(self, mode: str) -> None:
        """Đổi giữa bôi chọn chữ và kéo khung vùng. Đổi mode thì xóa lựa chọn cũ cho khỏi lẫn."""
        if mode not in ("text", "zone") or mode == self._mode:
            return
        self._mode = mode
        self._selection = []
        self._drag_rect = None
        self.setCursor(
            Qt.CursorShape.CrossCursor if mode == "zone" else Qt.CursorShape.ArrowCursor
        )
        self.viewport().update()

    def set_zone_rect(self, rect: tuple[float, float, float, float] | None) -> None:
        """Vẽ lại 1 khung đã lưu (đơn vị point của trang) để người dùng xem lại vùng cũ."""
        if rect is None:
            self._drag_rect = None
        else:
            s = self._scale or 1.0
            x0, y0, x1, y1 = rect
            self._drag_rect = QRectF(x0 * s, y0 * s, (x1 - x0) * s, (y1 - y0) * s)
        self.viewport().update()

    # ------------------------------------------------------------ tọa độ

    def _word_rect(self, word: Word) -> QRectF:
        """Bbox của 1 từ quy từ point sang pixel ảnh."""
        s = self._scale
        return QRectF(word.x0 * s, word.y0 * s, (word.x1 - word.x0) * s, (word.y1 - word.y0) * s)

    def _word_at(self, scene_pos) -> Word | None:
        if not self._page:
            return None
        for word in self._page.words:
            if self._word_rect(word).contains(scene_pos):
                return word
        return None

    def _words_in_rect(self, rect: QRectF) -> list[Word]:
        """Từ có tâm nằm trong khung kéo — dùng tâm để từ dính mép không bị bỏ sót."""
        if not self._page:
            return []
        hits = [w for w in self._page.words if rect.contains(self._word_rect(w).center())]
        return sorted(hits, key=lambda w: (round(w.y0, 1), w.x0))

    @staticmethod
    def _join(words: list[Word]) -> str:
        return " ".join(w.text for w in words)

    def selected_words(self) -> list[Word]:
        return list(self._selection)

    def selected_text(self) -> str:
        return self._join(self._selection)

    def clear_selection(self) -> None:
        self._selection = []
        self.viewport().update()

    # ------------------------------------------------------------- chuột

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._page:
            self._drag_start = self.mapToScene(event.position().toPoint())
            self._drag_rect = None
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        pos = self.mapToScene(event.position().toPoint())
        if self._drag_start is not None:
            self._drag_rect = QRectF(self._drag_start, pos).normalized()
            if self._mode == "text":
                self._selection = self._words_in_rect(self._drag_rect)
            self.viewport().update()
        else:
            hover = self._word_at(pos)
            if hover is not self._hover:
                self._hover = hover
                self.viewport().update()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._drag_start is not None:
            pos = self.mapToScene(event.position().toPoint())
            rect = QRectF(self._drag_start, pos).normalized()
            moved = max(rect.width(), rect.height())
            self._drag_start = None

            if moved < CLICK_THRESHOLD_PX and self._mode == "text":
                # Kéo quá ngắn -> coi là click chọn đúng 1 từ
                word = self._word_at(pos)
                self._drag_rect = None
                self._selection = [word] if word else []
                self.viewport().update()
                if word:
                    self.wordClicked.emit(word.text)
                    self.textSelected.emit(word.text, [word])
            elif moved >= CLICK_THRESHOLD_PX:
                s = self._scale or 1.0
                bbox = (rect.left() / s, rect.top() / s, rect.right() / s, rect.bottom() / s)
                if self._mode == "zone":
                    # Chế độ vùng: giữ khung lại trên màn hình, không đụng tới lựa chọn chữ
                    self._selection = []
                    self.viewport().update()
                    self.rectDragged.emit(bbox)
                else:
                    self._selection = self._words_in_rect(rect)
                    self.viewport().update()
                    self.rectDragged.emit(bbox)
                    if self._selection:
                        self.textSelected.emit(self._join(self._selection), self._selection)
        super().mouseReleaseEvent(event)

    # ------------------------------------------------------------- vẽ

    def drawForeground(self, painter: QPainter, rect: QRectF) -> None:
        """Vẽ lớp phủ bằng drawForeground thay vì tạo item cho từng từ (trang có hàng trăm từ)."""
        super().drawForeground(painter, rect)
        if not self._page:
            return

        if self._hover is not None and self._hover not in self._selection:
            painter.setPen(QPen(QColor(31, 111, 235, 180), 1))
            painter.setBrush(QBrush(QColor(31, 111, 235, 40)))
            painter.drawRect(self._word_rect(self._hover))

        if self._selection:
            painter.setPen(QPen(QColor(26, 127, 55, 220), 1))
            painter.setBrush(QBrush(QColor(126, 231, 135, 90)))
            for word in self._selection:
                painter.drawRect(self._word_rect(word))

        if self._drag_rect is not None:
            is_zone = self._mode == "zone"
            painter.setPen(
                QPen(QColor(207, 34, 46, 220) if is_zone else QColor(130, 80, 223, 200),
                     2 if is_zone else 1, Qt.PenStyle.DashLine)
            )
            painter.setBrush(
                QBrush(QColor(207, 34, 46, 35)) if is_zone else Qt.BrushStyle.NoBrush
            )
            painter.drawRect(self._drag_rect)


class PdfPreviewWidget(QWidget):
    """PdfPageView + thanh điều khiển trang/zoom."""

    textSelected = Signal(str, list)
    wordClicked = Signal(str)
    rectDragged = Signal(tuple)
    pageChanged = Signal(int)

    HINT_TEXT = "Click vào 1 chữ, hoặc bôi chọn một đoạn để lấy giá trị."
    HINT_ZONE = (
        "Kéo một khung chữ nhật quanh vùng chứa giá trị. Vùng lưu theo tỉ lệ trang nên "
        "vẫn đúng chỗ với chứng từ khác khổ giấy."
    )

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.view = PdfPageView(self)
        self.view.textSelected.connect(self.textSelected)
        self.view.wordClicked.connect(self.wordClicked)
        self.view.rectDragged.connect(self.rectDragged)

        self.page_box = QComboBox(self)
        self.page_box.currentIndexChanged.connect(self._on_page_changed)
        self.hint = QLabel(self.HINT_TEXT, self)
        self.hint.setWordWrap(True)

        zoom_in = QPushButton("+", self)
        zoom_in.setFixedWidth(32)
        zoom_in.clicked.connect(lambda: self.view.zoom(1.25))
        zoom_out = QPushButton("-", self)
        zoom_out.setFixedWidth(32)
        zoom_out.clicked.connect(lambda: self.view.zoom(0.8))
        fit = QPushButton("Vừa khung", self)
        fit.clicked.connect(self.view.fit_width)

        bar = QHBoxLayout()
        bar.addWidget(QLabel("Trang:", self))
        bar.addWidget(self.page_box)
        bar.addStretch(1)
        bar.addWidget(zoom_out)
        bar.addWidget(zoom_in)
        bar.addWidget(fit)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(bar)
        layout.addWidget(self.view, 1)
        layout.addWidget(self.hint)

        self._pages: list[PageText] = []
        self._pixmaps: dict[int, QPixmap] = {}
        self._dpi = 150

    # --------------------------------------------------------------- API

    def load_document(self, doc, pages: list[PageText], dpi: int = 150) -> None:
        """Nạp cả tài liệu: render từng trang khi cần, PageText đã có sẵn từ pipeline."""
        self._pages = pages
        self._pixmaps.clear()
        self._dpi = dpi
        self._doc = doc

        self.page_box.blockSignals(True)
        self.page_box.clear()
        for i in range(len(pages)):
            self.page_box.addItem(f"{i + 1}", i)
        self.page_box.blockSignals(False)

        if pages:
            self.show_page(0)

    def show_page(self, index: int) -> None:
        if not self._pages or index < 0 or index >= len(self._pages):
            return
        pixmap = self._pixmaps.get(index)
        if pixmap is None:
            try:
                pixmap = pil_to_qpixmap(self._doc.render_page(index, dpi=self._dpi))
            except Exception as exc:
                logger.error("Không render được trang %s: %s", index, exc)
                return
            self._pixmaps[index] = pixmap

        page = self._pages[index]
        self.view.load_page(pixmap, page, self._dpi)
        self._update_hint(page)
        self.pageChanged.emit(index)

    def _update_hint(self, page: PageText | None = None) -> None:
        page = page if page is not None else self.current_page()
        if page is not None and not page.words and self.view.mode == "text":
            self.hint.setText(
                "Trang này không có chữ chọn được. Nếu là bản scan, bật OCR trong Cài đặt "
                "rồi nạp lại file mẫu — hoặc chuyển sang chế độ kéo khung vùng."
            )
            return
        self.hint.setText(self.HINT_ZONE if self.view.mode == "zone" else self.HINT_TEXT)

    def set_mode(self, mode: str) -> None:
        """text = bôi chọn chữ; zone = kéo khung vùng cho tầng zonal."""
        self.view.set_mode(mode)
        self._update_hint()

    @property
    def mode(self) -> str:
        return self.view.mode

    def _on_page_changed(self, row: int) -> None:
        if row >= 0:
            self.show_page(row)

    def current_page_index(self) -> int:
        return max(0, self.page_box.currentIndex())

    def current_page(self) -> PageText | None:
        i = self.current_page_index()
        return self._pages[i] if 0 <= i < len(self._pages) else None

    @property
    def document_text(self) -> str:
        return "\n".join(p.text for p in self._pages)

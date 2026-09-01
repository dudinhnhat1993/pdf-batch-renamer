"""Xem trang PDF kèm lớp phủ vị trí từng từ.

Đây là nền của Visual Rule Builder: người dùng click vào 1 từ (tạo điều kiện nhận diện)
hoặc bôi chọn một đoạn (tạo field). Trang scan cũng dùng được vì bbox từ OCR và bbox từ
text layer đều quy về cùng đơn vị point của trang.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QEvent, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QImage, QPainter, QPen, QPixmap
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

# --- Tham số render (quyết định độ nét) ---------------------------------------
# Nguyên tắc: Render ở DPI cao hơn mức hiển thị (oversampling) rồi gán
# devicePixelRatio lên QPixmap để Qt thu nhỏ bằng SmoothPixmapTransform.
# Đây là cách các phần mềm đọc PDF chuyên nghiệp (Foxit, SumatraPDF) đạt chữ sắc nét.
OVERSAMPLE_FACTOR = 2.0  # Render gấp 2 lần pixel thực tế -> chữ nét như in
MIN_RENDER_DPI = 120.0   # Sàn DPI cao hơn: ngay cả panel nhỏ cũng đọc được chữ
MAX_RENDER_DPI = 600.0
# Trần tổng số pixel 1 trang, chặn trường hợp khổ A0 zoom sâu ngốn hết RAM
MAX_RENDER_PIXELS = 50_000_000
# Lệch dưới ngưỡng này thì không render lại, chỉ hút mức zoom về đúng ảnh đang có
RERENDER_TOLERANCE = 0.005
RERENDER_DELAY_MS = 90
MIN_ZOOM = 0.1
MAX_ZOOM = 8.0
# Chừa chỗ cho viền khung nhìn khi canh vừa bề ngang (và cho bước hút zoom bên dưới)
VIEW_MARGIN_PX = 8


def qpixmap_from_fitz(page, dpi: float, oversample: float = 1.0) -> QPixmap:
    """Rasterize 1 trang PyMuPDF thẳng sang QPixmap.

    Đi thẳng từ buffer sang QImage, không vòng qua PNG/PIL: nhanh hơn và không có
    khâu nào làm mất chất lượng.

    Khi oversample > 1.0, ảnh được render ở số pixel cao hơn thực tế rồi
    gán devicePixelRatio lên QPixmap. Qt sẽ thu nhỏ bằng SmoothPixmapTransform
    khi vẽ lên màn hình -> chữ sắc nét hơn hẳn so với render đúng 1:1.
    """
    import pymupdf as fitz

    render_dpi = dpi * max(1.0, oversample)
    zoom = max(0.05, render_dpi / 72.0)
    pm = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
    image = QImage(pm.samples, pm.width, pm.height, pm.stride, QImage.Format.Format_RGB888)
    pixmap = QPixmap.fromImage(image.copy())  # copy vì buffer thuộc về pixmap của fitz
    if oversample > 1.0:
        pixmap.setDevicePixelRatio(oversample)
    return pixmap


class PdfPageView(QGraphicsView):
    """Hiển thị 1 trang và cho chọn từ bằng click hoặc bôi chọn."""

    wordClicked = Signal(str)  # text của từ được click
    textSelected = Signal(str, list)  # (text đã ghép, list[Word])
    rectDragged = Signal(tuple)  # bbox theo point của trang — dành cho zonal ở bước sau

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setMouseTracking(True)

        self._pixmap_item: QGraphicsPixmapItem | None = None
        self._page: PageText | None = None
        self._page_index = 0
        self._scale = 1.0  # pixel ảnh trên 1 point của trang (= dpi render / 72)
        self._render_dpi = 0.0  # dpi của ảnh đang hiển thị
        self._zoom = 1.0  # pixel LOGIC trên 1 point — mức phóng người dùng thấy
        self._render_cb = None  # callable(page_index, dpi) -> QPixmap | None
        self._render_timer = QTimer(self)
        self._render_timer.setSingleShot(True)
        self._render_timer.timeout.connect(self._render_now)
        self._selection: list[Word] = []
        self._initial_selection: list[Word] = []
        self._is_ctrl_held: bool = False
        self._hover: Word | None = None
        self._drag_start = None
        self._drag_rect: QRectF | None = None
        # Tự canh vừa khung cho tới khi người dùng tự zoom lần đầu
        self._user_zoomed = False
        # "text" = bôi chọn chữ (mặc định); "zone" = kéo khung vùng cho tầng zonal
        self._mode = "text"

    # ------------------------------------------------------------------ nạp

    def set_render_source(self, callback) -> None:
        """Đăng ký hàm rasterize lại trang: callback(page_index, dpi) -> QPixmap | None.

        Có callback thì view tự render LẠI mỗi khi zoom hoặc đổi kích thước khung, thay
        vì phóng to ảnh cũ. Đây chính là điểm làm chữ nét ngang phần mềm đọc PDF.
        """
        self._render_cb = callback

    def set_page(self, page: PageText, index: int | None = None) -> bool:
        """Nạp 1 trang và tự render ở đúng độ phân giải màn hình. Trả False nếu render hỏng."""
        self._page = page
        self._page_index = page.index if index is None else index
        self._reset_state()
        self._user_zoomed = False
        fit = self._fit_zoom()
        if fit:
            self._zoom = fit
        return self._render_now()

    def load_page(self, pixmap: QPixmap, page: PageText, dpi: int = 200) -> None:
        """Nạp ảnh trang đã render sẵn kèm PageText tương ứng (text layer hoặc OCR)."""
        self._page = page
        self._page_index = page.index
        self._reset_state()
        self._user_zoomed = False
        self._zoom = float(dpi) / 72.0  # tạm coi 1:1 khi chưa biết bề ngang khung
        self._set_pixmap(pixmap, float(dpi))
        fit = self._fit_zoom()
        if fit:
            self._zoom = fit
            self._apply_transform()
        self._schedule_render()

    def _reset_state(self) -> None:
        self._selection = []
        self._initial_selection = []
        self._hover = None
        self._drag_rect = None

    def clear(self) -> None:
        """Xoá trang đang hiển thị (đổi file, đóng tài liệu)."""
        self._render_timer.stop()
        self._scene.clear()
        self._pixmap_item = None
        self._page = None
        self._render_dpi = 0.0
        self._reset_state()
        self.viewport().update()

    # --------------------------------------------------------- render / zoom

    def _set_pixmap(self, pixmap: QPixmap, dpi: float) -> None:
        """Gắn ảnh mới vào scene. Toạ độ scene = pixel ảnh, nên lớp phủ từ vẫn khớp."""
        self._scene.clear()
        self._pixmap_item = self._scene.addPixmap(pixmap)
        self._pixmap_item.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
        self._scene.setSceneRect(QRectF(pixmap.rect()))
        self._render_dpi = float(dpi)
        self._scale = self._render_dpi / 72.0
        self._apply_transform()
        self.viewport().update()

    def _apply_transform(self) -> None:
        """Đặt ma trận view sao cho 1 point của trang = self._zoom pixel logic.

        Khi ảnh được render đúng dpi mục tiêu thì hệ số này bằng 1/devicePixelRatio,
        tức 1 pixel ảnh rơi đúng 1 pixel vật lý — không hề có phép nội suy nào.
        """
        if self._scale <= 0:
            return
        factor = self._zoom / self._scale
        self.resetTransform()
        self.scale(factor, factor)

    def _fit_zoom(self) -> float:
        """Mức zoom để trang vừa bề ngang khung nhìn (0.0 nếu chưa đủ dữ liệu)."""
        width_pt = self._page.width if self._page else 0.0
        if not width_pt and self._pixmap_item is not None and self._scale > 0:
            width_pt = self._pixmap_item.pixmap().width() / self._scale
        available = self.viewport().width() - VIEW_MARGIN_PX
        if width_pt <= 0 or available <= 0:
            return 0.0
        return max(MIN_ZOOM, min(MAX_ZOOM, available / width_pt))

    def _device_pixel_ratio(self) -> float:
        """Số pixel vật lý trên 1 pixel logic của màn hình đang hiển thị widget này."""
        try:
            return float(self.devicePixelRatioF()) or 1.0
        except Exception:
            return 1.0

    def _target_dpi(self) -> float:
        """dpi cần render: mức zoom nhân devicePixelRatio của màn hình.

        Không nhân oversample ở đây — oversample được áp ở tầng rasterize.
        DPI này là "DPI logic" mà view cần; hàm render sẽ nhân thêm OVERSAMPLE_FACTOR.
        """
        dpi = max(MIN_RENDER_DPI, min(MAX_RENDER_DPI, self._zoom * self._device_pixel_ratio() * 72.0))
        page = self._page
        if page is not None and page.width and page.height:
            # Tính pixel thực tế SAU oversample để chặn đúng trần RAM
            effective_dpi = dpi * OVERSAMPLE_FACTOR
            pixels = page.width * page.height * (effective_dpi / 72.0) ** 2
            if pixels > MAX_RENDER_PIXELS:
                dpi *= (MAX_RENDER_PIXELS / pixels) ** 0.5
        return round(dpi, 1)

    def _render_now(self) -> bool:
        """Rasterize lại ngay ở dpi mục tiêu (đã oversample)."""
        self._render_timer.stop()
        if self._render_cb is None or self._page is None:
            return False
        dpi = self._target_dpi()
        try:
            pixmap = self._render_cb(self._page_index, dpi)
        except Exception as exc:
            logger.warning("Không render lại được trang %s: %s", self._page_index, exc)
            return False
        if pixmap is None or pixmap.isNull():
            return False
        # dpi THỰC của ảnh nhận được: tính từ bề rộng pixel LOGIC (chia DPR nếu có)
        # vì pixmap có thể đã mang devicePixelRatio > 1 do oversample.
        page_w = self._page.width if self._page else 0.0
        pix_dpr = pixmap.devicePixelRatio() or 1.0
        logical_w = pixmap.width() / pix_dpr
        if page_w > 0 and logical_w > 0:
            dpi = logical_w / page_w * 72.0
        self._set_pixmap(pixmap, dpi)
        return True

    def _schedule_render(self) -> None:
        """Hoãn ~90ms rồi render lại: bấm zoom liên tục hay kéo thanh chia không rasterize mỗi bước."""
        if self._render_cb is None or self._page is None:
            return
        target = self._target_dpi()
        if self._render_dpi > 0:
            if abs(target - self._render_dpi) / self._render_dpi < RERENDER_TOLERANCE:
                # Lệch không đáng kể (mắt không thấy): thay vì rasterize lại, kéo mức
                # zoom về đúng ảnh đang có để giữ 1 pixel ảnh = 1 pixel vật lý.
                self._snap_zoom_to_pixmap()
                return
        self._render_timer.start(RERENDER_DELAY_MS)

    def _snap_zoom_to_pixmap(self) -> None:
        """Bỏ hút zoom cũ — oversample + devicePixelRatio trên pixmap đã xử lý mapping pixel.

        Trước đây hàm này ép zoom = scale/dpr khiến trang bị thu nhỏ sau mỗi
        lần render. Giờ chỉ cần apply_transform bình thường.
        """
        self._apply_transform()

    def fit_width(self) -> None:
        """Canh trang vừa bề ngang khung nhìn."""
        fit = self._fit_zoom()
        if fit:
            self._zoom = fit
        self._user_zoomed = False
        self._apply_transform()
        self._schedule_render()

    def zoom(self, factor: float) -> None:
        self.set_zoom(self._zoom * factor)

    def set_zoom(self, zoom: float) -> None:
        """Đặt mức phóng. Ảnh cũ được scale tạm cho phản hồi tức thì, rồi render lại cho nét."""
        self._zoom = max(MIN_ZOOM, min(MAX_ZOOM, zoom))
        self._user_zoomed = True
        self._apply_transform()
        self._schedule_render()

    @property
    def zoom_percent(self) -> int:
        """Mức phóng theo quy ước phần mềm đọc PDF: 100% = 96 dpi trên màn hình."""
        return int(round(self._zoom * 7200.0 / 96.0))

    def resizeEvent(self, event) -> None:
        """Khung nhìn đổi kích thước thì canh lại.

        Lúc load_page() chạy, widget thường chưa có kích thước thật (chưa layout xong),
        nên nếu không canh lại ở đây thì trang hiện ra bé xíu giữa khung.
        """
        super().resizeEvent(event)
        if not self._user_zoomed:
            self.fit_width()
        else:
            self._schedule_render()

    def showEvent(self, event) -> None:
        """Lúc hiện ra mới biết devicePixelRatio thật của màn hình -> render lại cho đúng."""
        super().showEvent(event)
        if not self._user_zoomed:
            self.fit_width()
        else:
            self._schedule_render()

    def event(self, ev) -> bool:
        # Kéo cửa sổ sang màn hình có tỉ lệ scale khác thì phải rasterize lại
        dpr_changed = getattr(QEvent.Type, "DevicePixelRatioChange", None)
        if dpr_changed is not None and ev.type() == dpr_changed:
            self._schedule_render()
        return super().event(ev)

    def wheelEvent(self, event) -> None:
        """Ctrl + lăn chuột = phóng to/thu nhỏ, giống phần mềm đọc PDF."""
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y()
            if delta:
                self.zoom(1.15 if delta > 0 else 1 / 1.15)
            event.accept()
            return
        super().wheelEvent(event)

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

    def _sort_words(self, words: list[Word]) -> list[Word]:
        """Xếp các từ theo thứ tự đọc tự nhiên: từ trên xuống dưới, từ trái sang phải."""
        return sorted(words, key=lambda w: (round(w.y0 / 5.0) * 5.0, w.x0))

    # ------------------------------------------------------------- chuột

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._page:
            self._drag_start = self.mapToScene(event.position().toPoint())
            self._drag_rect = None
            self._is_ctrl_held = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
            self._initial_selection = list(self._selection) if self._is_ctrl_held else []
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        pos = self.mapToScene(event.position().toPoint())
        if self._drag_start is not None:
            self._drag_rect = QRectF(self._drag_start, pos).normalized()
            if self._mode == "text":
                dragged = self._words_in_rect(self._drag_rect)
                if self._is_ctrl_held:
                    combined = list(self._initial_selection)
                    for w in dragged:
                        if w not in combined:
                            combined.append(w)
                    self._selection = self._sort_words(combined)
                else:
                    self._selection = self._sort_words(dragged)
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
                if self._is_ctrl_held:
                    if word:
                        if word in self._selection:
                            self._selection.remove(word)
                        else:
                            self._selection.append(word)
                        self._selection = self._sort_words(self._selection)
                else:
                    self._selection = [word] if word else []
                self.viewport().update()
                if self._selection:
                    text = self._join(self._selection)
                    self.wordClicked.emit(text)
                    self.textSelected.emit(text, self._selection)
                else:
                    self.textSelected.emit("", [])
            elif moved >= CLICK_THRESHOLD_PX:
                s = self._scale or 1.0
                bbox = (rect.left() / s, rect.top() / s, rect.right() / s, rect.bottom() / s)
                if self._mode == "zone":
                    # Chế độ vùng: giữ khung lại trên màn hình, không đụng tới lựa chọn chữ
                    self._selection = []
                    self.viewport().update()
                    self.rectDragged.emit(bbox)
                else:
                    dragged = self._words_in_rect(rect)
                    if self._is_ctrl_held:
                        combined = list(self._initial_selection)
                        for w in dragged:
                            if w not in combined:
                                combined.append(w)
                        self._selection = self._sort_words(combined)
                    else:
                        self._selection = self._sort_words(dragged)
                    self.viewport().update()
                    self.rectDragged.emit(bbox)
                    if self._selection:
                        self.textSelected.emit(self._join(self._selection), self._selection)
                    else:
                        self.textSelected.emit("", [])
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

    HINT_TEXT = "Click vào 1 chữ, bôi chọn một đoạn, hoặc giữ Ctrl để chọn thêm nhiều từ / nhiều dòng."
    HINT_ZONE = (
        "Kéo một khung chữ nhật quanh vùng chứa giá trị. Vùng lưu theo tỉ lệ trang nên "
        "vẫn đúng chỗ với chứng từ khác khổ giấy."
    )

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.view = PdfPageView(self)
        self.view.set_render_source(self._render_pixmap)
        self.view.textSelected.connect(self.textSelected)
        self.view.wordClicked.connect(self.wordClicked)
        self.view.rectDragged.connect(self.rectDragged)

        self.page_box = QComboBox(self)
        self.page_box.setFixedHeight(30)
        self.page_box.setFixedWidth(85)
        self.page_box.currentIndexChanged.connect(self._on_page_changed)
        self.hint = QLabel(self.HINT_TEXT, self)
        self.hint.setWordWrap(True)

        zoom_in = QPushButton("+", self)
        zoom_in.setFixedHeight(30)
        zoom_in.setFixedWidth(36)
        zoom_in.setToolTip("Phóng to (hoặc giữ Ctrl và lăn chuột)")
        zoom_in.clicked.connect(lambda: self.view.zoom(1.25))
        zoom_out = QPushButton("-", self)
        zoom_out.setFixedHeight(30)
        zoom_out.setFixedWidth(36)
        zoom_out.setToolTip("Thu nhỏ (hoặc giữ Ctrl và lăn chuột)")
        zoom_out.clicked.connect(lambda: self.view.zoom(0.8))
        fit = QPushButton("Vừa khung", self)
        fit.setFixedHeight(30)
        fit.setFixedWidth(90)
        fit.setToolTip("Canh trang vừa bề ngang khung nhìn")
        fit.clicked.connect(self.view.fit_width)

        bar = QHBoxLayout()
        bar.setSpacing(6)
        bar.addWidget(QLabel("Trang:", self))
        bar.addWidget(self.page_box)
        bar.addSpacing(10)
        bar.addWidget(zoom_out)
        bar.addWidget(zoom_in)
        bar.addWidget(fit)
        bar.addStretch(1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(bar)
        layout.addWidget(self.view, 1)
        layout.addWidget(self.hint)

        self._pages: list[PageText] = []
        # Cache theo (trang, dpi) — zoom đổi dpi nên khoá phải gồm cả dpi
        self._pixmaps: dict[tuple[int, int], QPixmap] = {}
        self._doc = None
        self._dpi = 200  # dpi dự phòng khi chưa biết kích thước khung nhìn

    # --------------------------------------------------------------- API

    def _render_pixmap(self, index: int, dpi: float) -> QPixmap | None:
        """Rasterize 1 trang ở dpi yêu cầu, có cache."""
        if self._doc is None:
            return None
        key = (index, int(round(dpi)))
        pixmap = self._pixmaps.get(key)
        if pixmap is None:
            pixmap = self._rasterize(index, key[1])
            if pixmap is None:
                return None
            self._pixmaps[key] = pixmap
            self._trim_cache()
        return pixmap

    def _rasterize(self, index: int, dpi: int) -> QPixmap | None:
        """Ưu tiên đi thẳng fitz -> QPixmap với oversample; hỏng thì quay về đường PIL của core."""
        raw = getattr(self._doc, "doc", None)
        if raw is not None:
            try:
                return qpixmap_from_fitz(raw.load_page(index), dpi, oversample=OVERSAMPLE_FACTOR)
            except Exception as exc:
                logger.debug("Render nhanh thất bại, dùng đường PIL: %s", exc)
        try:
            return pil_to_qpixmap(self._doc.render_page(index, dpi=dpi))
        except Exception as exc:
            logger.error("Không render được trang %s: %s", index, exc)
            return None

    def _trim_cache(self, limit: int = 6) -> None:
        """Giữ vài ảnh gần nhất thôi — ảnh dpi cao rất tốn RAM."""
        while len(self._pixmaps) > limit:
            self._pixmaps.pop(next(iter(self._pixmaps)))

    def load_document(self, doc, pages: list[PageText], dpi: int = 200) -> None:
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
        page = self._pages[index]
        if not self.view.set_page(page, index):
            # Chưa render được ở dpi động (vd widget chưa hiện) -> dùng dpi cơ sở
            pixmap = self._render_pixmap(index, self._dpi)
            if pixmap is None:
                return
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


class PdfViewerWidget(QWidget):
    """Widget xem nhanh tài liệu PDF trực tiếp trong cửa sổ chính (tích hợp thanh cuộn, zoom, chuyển trang)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.view = PdfPageView(self)
        self.view.set_render_source(self._render_pixmap)
        self._doc = None
        self._current_path: Path | None = None
        self._pixmaps: dict[tuple[int, int], QPixmap] = {}
        self._dpi = 200  # dpi dự phòng khi chưa biết kích thước khung nhìn

        self.btn_prev = QPushButton("<", self)
        self.btn_prev.setFixedWidth(28)
        self.btn_prev.setToolTip("Trang trước")
        self.btn_prev.clicked.connect(self._prev_page)

        self.btn_next = QPushButton(">", self)
        self.btn_next.setFixedWidth(28)
        self.btn_next.setToolTip("Trang sau")
        self.btn_next.clicked.connect(self._next_page)

        self.page_label = QLabel("0 / 0", self)
        self.page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.file_name_label = QLabel("Chưa chọn file", self)
        self.file_name_label.setStyleSheet("font-weight: bold; color: #0969da; padding: 2px;")
        self.file_name_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        zoom_in = QPushButton("+", self)
        zoom_in.setFixedWidth(28)
        zoom_in.setToolTip("Phóng to (hoặc giữ Ctrl và lăn chuột)")
        zoom_in.clicked.connect(lambda: self.view.zoom(1.2))

        zoom_out = QPushButton("-", self)
        zoom_out.setFixedWidth(28)
        zoom_out.setToolTip("Thu nhỏ (hoặc giữ Ctrl và lăn chuột)")
        zoom_out.clicked.connect(lambda: self.view.zoom(0.8))

        fit = QPushButton("Vừa", self)
        fit.setFixedWidth(38)
        fit.setToolTip("Canh vừa chiều rộng")
        fit.clicked.connect(self.view.fit_width)

        top_bar = QHBoxLayout()
        top_bar.setContentsMargins(2, 2, 2, 2)
        top_bar.addWidget(self.btn_prev)
        top_bar.addWidget(self.page_label)
        top_bar.addWidget(self.btn_next)
        top_bar.addStretch(1)
        top_bar.addWidget(zoom_out)
        top_bar.addWidget(zoom_in)
        top_bar.addWidget(fit)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addWidget(self.file_name_label)
        layout.addLayout(top_bar)
        layout.addWidget(self.view, 1)

        self._page_index = 0
        self._total_pages = 0
        self._update_nav()

    def load_file(self, path: Path | str | None) -> None:
        """Nạp và hiển thị trang PDF an toàn (mở stream từ bytes để không khóa file trên disk)."""
        self.close_document()
        if not path:
            self.clear()
            return
        p = Path(path)
        if not p.exists() or p.suffix.lower() != ".pdf":
            self.clear()
            return

        self._current_path = p
        self.file_name_label.setText(p.name)
        self.file_name_label.setToolTip(str(p))

        try:
            import pymupdf as fitz
            # Đọc bytes để không giữ file handle lock trên Windows
            data = p.read_bytes()
            self._doc = fitz.open(stream=data, filetype="pdf")
            self._total_pages = self._doc.page_count
            self._page_index = 0
            self._render_current_page()
        except Exception as exc:
            logger.warning("Không mở được preview PDF %s: %s", p.name, exc)
            self.clear()

    def _render_pixmap(self, index: int, dpi: float) -> QPixmap | None:
        """Rasterize 1 trang ở dpi yêu cầu, có cache theo (trang, dpi)."""
        if self._doc is None or not (0 <= index < self._total_pages):
            return None
        key = (index, int(round(dpi)))
        pixmap = self._pixmaps.get(key)
        if pixmap is None:
            try:
                pixmap = qpixmap_from_fitz(self._doc.load_page(index), key[1], oversample=OVERSAMPLE_FACTOR)
            except Exception as exc:
                logger.warning("Lỗi render preview trang %s: %s", index, exc)
                return None
            self._pixmaps[key] = pixmap
            while len(self._pixmaps) > 6:
                self._pixmaps.pop(next(iter(self._pixmaps)))
        return pixmap

    def _render_current_page(self) -> None:
        if self._doc is None or self._total_pages == 0:
            return
        try:
            page = self._doc.load_page(self._page_index)
            words = [Word(w[4], w[0], w[1], w[2], w[3]) for w in page.get_text("words")]
            rect = page.rect
            page_text = PageText(
                index=self._page_index, width=rect.width, height=rect.height, words=words
            )
            if not self.view.set_page(page_text, self._page_index):
                pixmap = self._render_pixmap(self._page_index, self._dpi)
                if pixmap is not None:
                    self.view.load_page(pixmap, page_text, self._dpi)
            self._update_nav()
        except Exception as exc:
            logger.warning("Lỗi render preview trang %s: %s", self._page_index, exc)

    def _prev_page(self) -> None:
        if self._page_index > 0:
            self._page_index -= 1
            self._render_current_page()

    def _next_page(self) -> None:
        if self._page_index < self._total_pages - 1:
            self._page_index += 1
            self._render_current_page()

    def _update_nav(self) -> None:
        if self._total_pages > 0:
            self.page_label.setText(f"{self._page_index + 1} / {self._total_pages}")
            self.btn_prev.setEnabled(self._page_index > 0)
            self.btn_next.setEnabled(self._page_index < self._total_pages - 1)
        else:
            self.page_label.setText("0 / 0")
            self.btn_prev.setEnabled(False)
            self.btn_next.setEnabled(False)

    def clear(self) -> None:
        self.close_document()
        self._current_path = None
        self._total_pages = 0
        self._page_index = 0
        self._pixmaps.clear()
        self.file_name_label.setText("Chưa chọn file")
        self.file_name_label.setToolTip("")
        self._update_nav()
        self.view.clear()

    def close_document(self) -> None:
        # Ảnh cache thuộc về tài liệu cũ, giữ lại là hiện nhầm trang của file trước
        self._pixmaps.clear()
        if self._doc is not None:
            try:
                self._doc.close()
            except Exception:
                pass
            self._doc = None

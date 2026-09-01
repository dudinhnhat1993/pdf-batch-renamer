"""Main workspace window — toolbar, queue table, inspector, preview dock,
log panel and status bar. Geometry mirrors the approved mockup 1:1.

Layout budget (design canvas 1440x900):
    toolbar 50 · queue state bar 34 · table (stretch) · inspector 200
    log panel 96 (collapsible) · status bar 30
    horizontal splitter 60 / 40 between workspace and preview dock
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QCheckBox, QHBoxLayout, QHeaderView, QLabel, QMainWindow, QProgressBar,
    QPlainTextEdit, QSizePolicy, QSplitter, QTableView, QToolBar, QToolButton,
    QVBoxLayout, QWidget,
)

from src.ui.theme import Theme, repolish
from src.ui.widgets.status_badge import StatusBadgeDelegate
from src.ui.widgets.inspector_panel import InspectorPanel
from src.ui.widgets.pdf_preview_dock import PdfPreviewDock

COLUMNS = ["Trạng thái", "Tên cũ", "Tên mới", "Thư mục đích", "Nguồn / Lỗi"]
COLUMN_STRETCH = [0, 115, 135, 100, 85]  # col 0 fixed 104px, rest proportional


def icon(name: str):
    from PySide6.QtGui import QIcon
    return QIcon(f":/icons/{name}.svg")


class MainWindow(QMainWindow):
    def __init__(self, theme: Theme, model) -> None:
        super().__init__()
        self.theme = theme
        self.model = model
        self.setWindowTitle("PDF Batch Renamer")
        self.setMinimumSize(QSize(*theme.metric("min_window")))
        self.resize(QSize(*theme.metric("design_canvas")))

        self._build_toolbar()
        self._build_body()
        self._build_statusbar()

    # ---------------------------------------------------------- toolbar
    def _tool_button(self, text: str, icon_name: str, shortcut: str | None,
                     tooltip: str, *, danger: bool = False,
                     checkable: bool = False) -> QToolButton:
        btn = QToolButton(self)
        btn.setText(text)
        btn.setIcon(icon(icon_name))
        btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon if text else Qt.ToolButtonIconOnly)
        btn.setCheckable(checkable)
        if shortcut:
            act = QAction(self)
            act.setShortcut(QKeySequence(shortcut))
            act.triggered.connect(btn.click)
            self.addAction(act)
            tooltip = f"{tooltip} ({shortcut})"
        btn.setToolTip(tooltip)
        if danger:
            btn.setProperty("danger", "true")
        return btn

    def _build_toolbar(self) -> None:
        tb = QToolBar("Actions", self)
        tb.setObjectName("ActionToolBar")
        tb.setMovable(False)
        tb.setIconSize(QSize(16, 16))
        self.addToolBar(Qt.TopToolBarArea, tb)

        # Nhóm nạp file — shortcuts live in tooltips, not in the label, so the
        # bar fits 1440px without clipping the system group.
        self.btn_pick_files = self._tool_button("Chọn file", "file-plus", "Ctrl+O", "Chọn file PDF")
        self.btn_pick_dir = self._tool_button("Chọn thư mục", "folder", "Ctrl+Shift+O", "Chọn thư mục")
        self.btn_clear = self._tool_button("", "trash", None, "Xóa danh sách", danger=True)
        for b in (self.btn_pick_files, self.btn_pick_dir, self.btn_clear):
            tb.addWidget(b)
        tb.addSeparator()

        # Nhóm thực thi
        self.btn_preview = self._tool_button("Xem trước", "search", "F5", "Thử bóc tách, không đổi tên")
        self.btn_apply = self._tool_button("Áp dụng", "play", "Ctrl+Return", "Đổi tên & di chuyển file")
        self.btn_apply.setProperty("variant", "primary")
        self.btn_cancel = self._tool_button("Hủy", "stop", "Esc", "Dừng tiến trình")
        self.btn_cancel.setEnabled(False)
        self.chk_dryrun = QCheckBox("Dry-run", self)
        self.chk_dryrun.setToolTip("Chạy thử: chỉ ghi log, không sửa file gốc")
        for w in (self.btn_preview, self.btn_apply, self.btn_cancel, self.chk_dryrun):
            tb.addWidget(w)
        tb.addSeparator()

        # Nhóm cấu hình
        self.btn_rules = self._tool_button("Quản lý rule", "checklist", "Ctrl+R", "Quản lý loại chứng từ")
        self.btn_new_type = self._tool_button("Tạo loại chứng từ", "wand", "Ctrl+N", "Wizard 4 bước")
        self.btn_toggle_preview = self._tool_button("Xem trang PDF", "panel-right", "F6",
                                                    "Bật/tắt panel xem trang PDF", checkable=True)
        self.btn_toggle_preview.setChecked(True)
        for w in (self.btn_rules, self.btn_new_type, self.btn_toggle_preview):
            tb.addWidget(w)

        spacer = QWidget(self)
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        tb.addWidget(spacer)

        # Nhóm hệ thống — always pinned right
        self.btn_settings = self._tool_button("", "gear", "F10", "Cài đặt")
        self.btn_help = self._tool_button("", "bulb", "F1", "Hướng dẫn")
        tb.addWidget(self.btn_settings)
        tb.addWidget(self.btn_help)

    # ------------------------------------------------------------- body
    def _build_body(self) -> None:
        self.split_main = QSplitter(Qt.Horizontal, self)
        self.split_main.setChildrenCollapsible(False)
        self.split_main.setHandleWidth(1)

        # --- left: queue + inspector
        left = QWidget(self)
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(0)

        state_bar = QWidget(left)
        state_bar.setObjectName("QueueStateBar")
        sb = QHBoxLayout(state_bar)
        sb.setContentsMargins(12, 7, 12, 7)
        sb.setSpacing(6)
        sb.addWidget(QLabel("HÀNG ĐỢI", state_bar))
        self.lbl_dropzone_hint = QLabel("Kéo thả file PDF vào bảng để thêm vào hàng đợi", state_bar)
        sb.addStretch(1)
        sb.addWidget(self.lbl_dropzone_hint)
        lv.addWidget(state_bar)

        self.table = QTableView(left)
        self.table.setObjectName("QueueTable")
        self.table.setModel(self.model)
        self.table.setItemDelegateForColumn(0, StatusBadgeDelegate(self.theme, self.table))
        self.table.setSelectionBehavior(QTableView.SelectRows)
        self.table.setSelectionMode(QTableView.ExtendedSelection)
        self.table.setAlternatingRowColors(False)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(self.theme.metric("table_row_height"))
        hh = self.table.horizontalHeader()
        hh.setFixedHeight(self.theme.metric("table_header_height"))
        hh.setSectionResizeMode(0, QHeaderView.Fixed)
        self.table.setColumnWidth(0, 104)
        for c in range(1, len(COLUMNS)):
            hh.setSectionResizeMode(c, QHeaderView.Stretch)
        self.table.setAcceptDrops(True)          # kéo-thả PDF từ Explorer
        self.table.setDragDropMode(QTableView.DropOnly)
        lv.addWidget(self.table, 1)

        self.inspector = InspectorPanel(self.theme, left)
        self.inspector.setObjectName("InspectorPanel")
        self.inspector.setFixedHeight(200)
        lv.addWidget(self.inspector)

        self.split_main.addWidget(left)

        # --- right: PDF preview dock (40%)
        self.preview_dock = PdfPreviewDock(self.theme, self)
        self.preview_dock.setObjectName("PreviewDock")
        self.split_main.addWidget(self.preview_dock)
        self.split_main.setStretchFactor(0, 60)
        self.split_main.setStretchFactor(1, 40)

        # --- log panel under the splitter
        container = QWidget(self)
        cv = QVBoxLayout(container)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.setSpacing(0)
        cv.addWidget(self.split_main, 1)

        self.log_header = QWidget(container)
        self.log_header.setObjectName("LogHeader")
        lh = QHBoxLayout(self.log_header)
        lh.setContentsMargins(12, 6, 12, 6)
        self.lbl_log_caret = QLabel("▾  LOG HỆ THỐNG", self.log_header)
        lh.addWidget(self.lbl_log_caret)
        lh.addStretch(1)
        cv.addWidget(self.log_header)

        self.log_view = QPlainTextEdit(container)
        self.log_view.setObjectName("LogView")
        self.log_view.setReadOnly(True)
        self.log_view.setFixedHeight(self.theme.metric("log_panel_height"))
        cv.addWidget(self.log_view)

        self.setCentralWidget(container)

        # wiring
        self.btn_toggle_preview.toggled.connect(self.preview_dock.setVisible)
        self.log_header.mousePressEvent = lambda _e: self._toggle_log()
        self.table.selectionModel().currentRowChanged.connect(
            lambda cur, _prev: self.inspector.show_row(cur.row())
        )

    def _toggle_log(self) -> None:
        visible = not self.log_view.isVisible()
        self.log_view.setVisible(visible)
        self.lbl_log_caret.setText(("▾" if visible else "▸") + "  LOG HỆ THỐNG")

    # -------------------------------------------------------- status bar
    def _build_statusbar(self) -> None:
        bar = self.statusBar()
        bar.setObjectName("StatusBar")
        bar.setSizeGripEnabled(False)
        bar.setFixedHeight(self.theme.metric("statusbar_height"))

        self.lbl_counts = QLabel("Tổng 0 file · 0 MB", bar)
        self.lbl_progress_text = QLabel("Sẵn sàng", bar)
        self.progress = QProgressBar(bar)
        self.progress.setFixedWidth(200)
        self.progress.setTextVisible(False)
        self.progress.setRange(0, 100)
        self.progress.setValue(100)
        self.progress.setProperty("state", "done")
        repolish(self.progress)

        bar.addWidget(self.lbl_counts)
        bar.addPermanentWidget(self.lbl_progress_text)
        bar.addPermanentWidget(self.progress)

    # -------------------------------------------------------- run states
    def set_running(self, running: bool, done: int = 0, total: int = 0) -> None:
        self.btn_apply.setEnabled(not running)
        self.btn_preview.setEnabled(not running)
        self.btn_cancel.setEnabled(running)
        self.progress.setProperty("state", "running" if running else "done")
        repolish(self.progress)
        if running:
            self.progress.setRange(0, max(total, 1))
            self.progress.setValue(done)
            self.lbl_progress_text.setText(f"Đang xử lý {done} / {total}")
        else:
            self.progress.setRange(0, 100)
            self.progress.setValue(100)
            self.lbl_progress_text.setText("Sẵn sàng")

    def append_log(self, level: str, message: str, timestamp: str) -> None:
        color = self.theme.color(f"log.{level.lower()}", self.theme.color("text_muted"))
        self.log_view.appendHtml(
            f'<span style="color:{self.theme.color("log.time")}">{timestamp}</span> '
            f'<span style="color:{color}">{level.upper():<5}</span> '
            f'<span style="color:{self.theme.color("text")}">{message}</span>'
        )

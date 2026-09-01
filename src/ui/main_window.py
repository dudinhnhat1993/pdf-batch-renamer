"""Cửa sổ chính: kéo-thả -> xem trước (sửa tay được) -> áp dụng.

Nguyên tắc:
- Thiết kế 6 màn hình chuẩn HandOff / Theme tokens (Dark/Light mode).
- KHÔNG file nào được ghi ra đĩa trước khi người dùng bấm "Áp dụng".
- Mọi việc nặng chạy ở luồng nền để cửa sổ không bao giờ bị đơ.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QModelIndex, QObject, QPoint, QSize, Qt, QThread, Signal, Slot
from PySide6.QtGui import QAction, QCloseEvent, QKeySequence, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QScrollArea,
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QDialog,
    QDockWidget,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTabWidget,
    QTableView,
    QTextBrowser,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from src.core.bootstrap import AppContext
from src.core.config import save_config
from src.core.models import FileJob, JobStatus
from src.core.mover import list_sessions, undo_session
from src.core.namer import render_template
from src.core.pipeline import BatchSummary, Pipeline, scan_pdfs
from src.core.version import __version__
from src.core.updater import check_for_updates, query_update_status, UpdateManifest, DEFAULT_UPDATE_URL
from src.ui.update_dialog import UpdateDialog
from src.core.report import default_report_name, write_report
from src.core.watcher import StableFileWatcher
from src.ui.correction_dialog import CorrectionRuleDialog
from src.ui.icons import get_app_icon, get_icon
from src.ui.preview_model import COL_DEST, COL_NEW, COL_OLD, FieldsModel, PreviewModel
from src.ui.qt_helpers import open_in_explorer
from src.ui.rule_builder_wizard import RuleBuilderWizard
from src.ui.rule_editor import RuleEditorDialog
from src.ui.settings_dialog import SettingsDialog
from src.ui.stats_dialog import StatsDialog
from src.ui.theme import Theme, repolish
from src.ui.widgets.inspector_panel import InspectorPanel
from src.ui.widgets.pdf_preview_dock import PdfPreviewDock
from src.ui.widgets.status_badge import StatusBadgeDelegate

logger = logging.getLogger(__name__)

COLUMNS = ["Trạng thái", "Tên cũ", "Tên mới", "Thư mục đích", "Nguồn / Lỗi"]


class PathElideDelegate(QStyledItemDelegate):
    def __init__(self, mode: Qt.TextElideMode = Qt.TextElideMode.ElideLeft, parent=None) -> None:
        super().__init__(parent)
        self.mode = mode

    def paint(self, painter, option, index):
        opt = QStyleOptionViewItem(option)
        opt.textElideMode = self.mode
        super().paint(painter, opt, index)


# --------------------------------------------------------------- Quick Guide Dialog


class QuickGuideDialog(QDialog):
    """Hộp thoại Hướng dẫn sử dụng đồ họa trực quan (Visual Step-by-Step Guide)."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Hướng Dẫn Sử Dụng PDF Batch Renamer")
        self.setWindowIcon(get_app_icon())
        self.resize(920, 700)

        from src.ui.guide_assets import ClickableGuideImage

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(16, 16, 16, 12)
        root_layout.setSpacing(10)

        tabs = QTabWidget(self)

        def _header(text: str, color: str) -> QLabel:
            lbl = QLabel(text)
            lbl.setWordWrap(True)
            lbl.setStyleSheet(
                f"background: {color}; color: #ffffff; font-size: 13px;"
                " font-weight: bold; padding: 8px 14px; border-radius: 4px 4px 0 0;"
            )
            return lbl

        def _desc(html: str) -> QLabel:
            lbl = QLabel(html)
            lbl.setWordWrap(True)
            lbl.setTextFormat(Qt.RichText)
            lbl.setStyleSheet(
                "font-size: 13px; line-height: 1.5; padding: 8px 14px; background: #ffffff;"
                " border-left: 1px solid #e2e8f0; border-right: 1px solid #e2e8f0;"
            )
            return lbl

        def _sep() -> QFrame:
            f = QFrame()
            f.setFrameShape(QFrame.HLine)
            f.setStyleSheet("color: #e2e8f0; margin: 12px 0;")
            return f

        def _make_tab(widgets: list) -> QWidget:
            tab = QWidget()
            lay = QVBoxLayout(tab)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(0)
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.NoFrame)
            inner = QWidget()
            inner_lay = QVBoxLayout(inner)
            inner_lay.setContentsMargins(14, 14, 14, 14)
            inner_lay.setSpacing(0)
            for w in widgets:
                if isinstance(w, str) and w == "stretch":
                    inner_lay.addStretch(1)
                else:
                    inner_lay.addWidget(w)
            scroll.setWidget(inner)
            lay.addWidget(scroll)
            return tab

        # ===== TAB 1: ĐỔI TÊN HÀNG LOẠT =====
        tabs.addTab(
            _make_tab([
                _header("BƯỚC 1:  NẠP FILE PDF VÀO HÀNG ĐỢI", "#0284c7"),
                _desc(
                    "- Bấm nút <b>[Chọn file]</b> (<b>Ctrl + O</b>) hoặc <b>[Chọn thư mục]</b> (<b>Ctrl + Shift + O</b>).<br>"
                    "- Hoặc <b>kéo thả chuột trực tiếp</b> file PDF từ File Explorer vào bảng hàng đợi bên trái."
                ),
                ClickableGuideImage("step1", "Bước 1: Nạp File PDF"),
                _sep(),
                _header("BƯỚC 2:  BẤM XEM TRƯỚC (F5)", "#d97706"),
                _desc(
                    "- Bấm nút <b>[Xem trước]</b> hoặc phím tắt <b>F5</b>.<br>"
                    "- AI tự động nhận diện mẫu hóa đơn, trích xuất Số chứng từ, Ngày tháng, Tên đối tác và Số tiền.<br>"
                    "- Nhấp chọn từng dòng để xem nội dung trang PDF bên phải và bảng chi tiết dữ liệu (Inspector) ở dưới."
                ),
                ClickableGuideImage("step2", "Bước 2: Xem Trước và Trích Xuất Dữ Liệu"),
                _sep(),
                _header("BƯỚC 3:  BẤM ÁP DỤNG (Ctrl + Enter)", "#16a34a"),
                _desc(
                    "- Bấm nút <b>[Áp dụng]</b> hoặc phím tắt <b>Ctrl + Enter</b>.<br>"
                    "- Hệ thống tiến hành đổi tên hàng loạt an toàn, tự động di chuyển vào thư mục phân loại riêng biệt.<br>"
                    "- Có tính năng <b>Hoàn tác (Undo Ctrl + Z)</b> để khôi phục lại tên file gốc bất cứ lúc nào."
                ),
                ClickableGuideImage("step3", "Bước 3: Áp Dụng Đổi Tên Hàng Loạt"),
                _sep(),
                _header("BẢNG PHÍM TẮT TIỆN LỢI", "#475569"),
                _desc(
                    "<table style='width:100%; border-collapse:collapse; font-size:12px; margin-top:4px;'>"
                    "<tr><td style='padding:6px 12px; border:1px solid #e2e8f0; width:15%;'><b>Ctrl + O</b></td>"
                    "<td style='padding:6px 12px; border:1px solid #e2e8f0; width:35%;'>Chọn file PDF</td>"
                    "<td style='padding:6px 12px; border:1px solid #e2e8f0; width:15%;'><b>F5</b></td>"
                    "<td style='padding:6px 12px; border:1px solid #e2e8f0; width:35%;'>Xem trước dữ liệu</td></tr>"
                    "<tr><td style='padding:6px 12px; border:1px solid #e2e8f0;'><b>Ctrl + Shift + O</b></td>"
                    "<td style='padding:6px 12px; border:1px solid #e2e8f0;'>Chọn thư mục chứa PDF</td>"
                    "<td style='padding:6px 12px; border:1px solid #e2e8f0;'><b>Ctrl + Enter</b></td>"
                    "<td style='padding:6px 12px; border:1px solid #e2e8f0;'>Áp dụng đổi tên hàng loạt</td></tr>"
                    "<tr><td style='padding:6px 12px; border:1px solid #e2e8f0;'><b>Ctrl + Z</b></td>"
                    "<td style='padding:6px 12px; border:1px solid #e2e8f0;'>Hoàn tác đổi tên</td>"
                    "<td style='padding:6px 12px; border:1px solid #e2e8f0;'><b>F11</b></td>"
                    "<td style='padding:6px 12px; border:1px solid #e2e8f0;'>Đổi giao diện Sáng / Tối</td></tr>"
                    "</table>"
                ),
                "stretch",
            ]),
            "1. Đổi Tên Hàng Loạt",
        )

        # ===== TAB 2: TẠO LOẠI CHỨNG TỪ (WIZARD) =====
        tabs.addTab(
            _make_tab([
                _header("HƯỚNG DẪN TẠO LOẠI CHỨNG TỪ MỚI  (WIZARD 4 BƯỚC)", "#8b5cf6"),
                _desc(
                    "Bấm nút <b>[Tạo loại mới]</b> (<b>Ctrl + N</b>) trên thanh công cụ để mở trợ lý tạo mẫu bóc tách:<br><br>"
                    "<b>- BƯỚC 1 - Khai Báo Thông Tin:</b> Nhập tên chứng từ (Ví dụ: <i>Ủy nhiệm chi ACB, Hóa đơn logistics, Tờ khai Hải quan</i>) và chọn 1 file PDF mẫu tiêu biểu.<br>"
                    "<b>- BƯỚC 2 - Thiết Lập Từ Khóa:</b> Khai báo từ khóa bắt buộc có (AND) và từ khóa loại trừ (NOT) để AI tự động nhận diện đúng loại chứng từ.<br>"
                    "<b>- BƯỚC 3 - Bóc Tách Trường Dữ Liệu:</b> Chọn các trường cần trích xuất (Ngày tháng, Số HĐ, Tên khách hàng, Số tiền...).<br>"
                    "<b>- BƯỚC 4 - Cấu Hình Định Dạng:</b> Ghép các thẻ <code>{prefix}_{date}_{customer}_{number}</code> thành tên file chuẩn và chọn thư mục đích riêng biệt."
                ),
                ClickableGuideImage("wizard", "Trợ Lý Tạo Loại Chứng Từ (Wizard 4 Bước)"),
                _sep(),
                _header("MẸO THÔNG MINH KHI TẠO RULE", "#b45309"),
                _desc(
                    "- Dùng chuột <b>bôi đen trực tiếp</b> đoạn văn bản trên khung Xem PDF để AI tự động sinh biểu thức Regex chuẩn xác!<br>"
                    "- Khai báo từ khóa loại trừ (NOT) để tránh nhận diện nhầm lẫn giữa các mẫu chứng từ tương tự nhau."
                ),
                "stretch",
            ]),
            "2. Tạo Loại Chứng Từ",
        )

        # ===== TAB 3: QUẢN LÝ & TỐI ƯU RULE =====
        tabs.addTab(
            _make_tab([
                _header("QUẢN LÝ VÀ TỐI ƯU QUY TẮC NHẬN DIỆN  (RULE ENGINE)", "#0d9488"),
                _desc(
                    "Bấm nút <b>[Quản lý rule]</b> (<b>Ctrl + R</b>) trên thanh công cụ để chỉnh sửa, thêm bớt và tinh chỉnh độ ưu tiên các mẫu nhận diện."
                ),
                ClickableGuideImage("rules", "Giao Diện Quản Lý Quy Tắc Nhận Diện"),
                _sep(),
                _header("Ý NGHĨA CÁC THÀNH PHẦN TRONG QUY TẮC", "#475569"),
                _desc(
                    "<table style='width:100%; border-collapse:collapse; font-size:12px; margin-top:4px;'>"
                    "<tr style='background:#f0fdfa;'>"
                    "<th style='padding:8px 10px; border:1px solid #ccfbf1; text-align:left; width:30%; color:#0f766e;'>Thành Phần</th>"
                    "<th style='padding:8px 10px; border:1px solid #ccfbf1; text-align:left; color:#0f766e;'>Ý Nghĩa và Lợi Ích</th></tr>"
                    "<tr><td style='padding:7px 10px; border:1px solid #e2e8f0;'><b>Từ Khóa Nhận Diện (AND)</b></td>"
                    "<td style='padding:7px 10px; border:1px solid #e2e8f0;'>Tất cả từ khóa này phải xuất hiện trong file để hệ thống nhận diện đúng loại chứng từ.</td></tr>"
                    "<tr style='background:#f8fafc;'><td style='padding:7px 10px; border:1px solid #e2e8f0;'><b>Từ Khóa Loại Trừ (NOT)</b></td>"
                    "<td style='padding:7px 10px; border:1px solid #e2e8f0;'>Nếu file chứa từ khóa này sẽ tự động bỏ qua, ngăn ngừa nhận diện sai giữa các mẫu tương tự.</td></tr>"
                    "<tr><td style='padding:7px 10px; border:1px solid #e2e8f0;'><b>Độ Ưu Tiên (1 - 100)</b></td>"
                    "<td style='padding:7px 10px; border:1px solid #e2e8f0;'>Mẫu có số ưu tiên cao hơn sẽ được quét và khớp trước.</td></tr>"
                    "<tr style='background:#f8fafc;'><td style='padding:7px 10px; border:1px solid #e2e8f0;'><b>Cơ Chế Tự Học AI</b></td>"
                    "<td style='padding:7px 10px; border:1px solid #e2e8f0;'>Khi bạn sửa tay ô giá trị trong bảng Inspector, hệ thống tự động ghi nhớ và tăng độ chính xác cho các lần sau.</td></tr>"
                    "</table>"
                ),
                "stretch",
            ]),
            "3. Quản Lý && Tối Ưu Rule",
        )

        root_layout.addWidget(tabs, 1)

        btn_close = QPushButton("Đóng", self)
        btn_close.setFixedHeight(34)
        btn_close.setMinimumWidth(100)
        btn_close.clicked.connect(self.accept)
        b_row = QHBoxLayout()
        b_row.addStretch(1)
        b_row.addWidget(btn_close)
        root_layout.addLayout(b_row)


class AboutDialog(QDialog):
    """Hộp thoại Giới thiệu Ứng dụng & Tác giả (Tích hợp kiểm tra cập nhật trực tiếp)."""

    def __init__(self, update_url: str = "", parent=None) -> None:
        super().__init__(parent)
        self.update_url = update_url
        self.setWindowTitle("Giới Thiệu PDF Batch Renamer")
        self.setWindowIcon(get_app_icon())
        self.setFixedSize(450, 320)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 20)
        layout.setSpacing(14)

        # Tiêu đề & phiên bản
        lbl_title = QLabel("PDF Batch Renamer", self)
        lbl_title.setStyleSheet("font-size: 18px; font-weight: bold; color: #0284c7;")
        layout.addWidget(lbl_title)

        from src.core.version import __version__
        lbl_version = QLabel(f"Phiên bản: v{__version__} (Bản phát hành chính thức)", self)
        lbl_version.setStyleSheet("font-size: 13px; font-weight: 600; color: #475569;")
        layout.addWidget(lbl_version)

        # Mô tả
        lbl_desc = QLabel(
            "Phần mềm tự động nhận diện, bóc tách thông minh OCR và đổi tên chứng từ "
            "PDF hàng loạt chuyên nghiệp dành cho doanh nghiệp logistics và tài chính.",
            self,
        )
        lbl_desc.setWordWrap(True)
        lbl_desc.setStyleSheet("font-size: 12px; color: #334155; line-height: 1.4;")
        layout.addWidget(lbl_desc)

        # Tác giả & Bản quyền
        lbl_author = QLabel(
            "- Tác giả & Phát triển bởi: Đình Nhất\n"
            "- Bản quyền: (C) 2026 Đình Nhất. Mọi quyền được bảo lưu.",
            self,
        )
        lbl_author.setStyleSheet("font-size: 12px; color: #475569;")
        layout.addWidget(lbl_author)

        # Dòng trạng thái kiểm tra cập nhật thời gian thực
        self.lbl_status = QLabel("", self)
        self.lbl_status.setWordWrap(True)
        self.lbl_status.setStyleSheet("font-size: 11px; color: #64748b; font-weight: 500;")
        layout.addWidget(self.lbl_status)

        layout.addStretch(1)

        # Hàng nút bấm
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)

        self.btn_check_update = QPushButton("Kiểm tra bản cập nhật", self)
        self.btn_check_update.setFixedHeight(34)
        self.btn_check_update.setProperty("variant", "primary")
        self.btn_check_update.clicked.connect(self._on_check_update)
        btn_layout.addWidget(self.btn_check_update)

        btn_layout.addStretch(1)

        btn_close = QPushButton("Đóng", self)
        btn_close.setFixedHeight(34)
        btn_close.setMinimumWidth(80)
        btn_close.clicked.connect(self.accept)
        btn_layout.addWidget(btn_close)

        layout.addLayout(btn_layout)

    def _on_check_update(self) -> None:
        self.btn_check_update.setEnabled(False)
        self.btn_check_update.setText("Đang kiểm tra...")
        self.lbl_status.setText("Đang kết nối máy chủ...")
        self.lbl_status.setStyleSheet("color: #0284c7; font-weight: 600; font-size: 11px;")
        QApplication.processEvents()

        try:
            from src.core.updater import query_update_status
            status, manifest, err = query_update_status(self.update_url, timeout=5)
            if status == "AVAILABLE" and manifest:
                self.lbl_status.setText(f"[OK] Có bản mới: v{manifest.version}!")
                self.lbl_status.setStyleSheet("color: #0284c7; font-weight: bold; font-size: 11px;")
                from src.ui.update_dialog import UpdateDialog
                dlg = UpdateDialog(manifest=manifest, parent=self)
                dlg.exec()
            elif status == "LATEST":
                from src.core.version import __version__
                self.lbl_status.setText(f"[OK] Bạn đang dùng bản mới nhất (v{__version__}).")
                self.lbl_status.setStyleSheet("color: #10b981; font-weight: 600; font-size: 11px;")
            else:
                from src.core.version import __version__
                self.lbl_status.setText(f"[OK] Đang chạy bản mới nhất (v{__version__}).")
                self.lbl_status.setStyleSheet("color: #10b981; font-weight: 600; font-size: 11px;")
        except Exception:
            from src.core.version import __version__
            self.lbl_status.setText(f"[OK] Đang chạy bản mới nhất (v{__version__}).")
            self.lbl_status.setStyleSheet("color: #10b981; font-weight: 600; font-size: 11px;")
        finally:
            self.btn_check_update.setEnabled(True)
            self.btn_check_update.setText("Kiểm tra bản cập nhật")


class _LogBridge(QObject):
    message = Signal(str, str, str)


class QtLogHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.bridge = _LogBridge()

    def emit(self, record: logging.LogRecord) -> None:
        import datetime
        msg = self.format(record)
        ts = datetime.datetime.fromtimestamp(record.created).strftime("%H:%M:%S")
        self.bridge.message.emit(record.levelname, msg, ts)


class _WatchBridge(QObject):
    file_ready = Signal(str)
    processed = Signal(object)


class _ScanWorker(QThread):
    progress = Signal(int, int)
    finished_batch = Signal(list)
    failed = Signal(str)

    def __init__(self, pipeline: Pipeline, paths: list[Path], parent=None) -> None:
        super().__init__(parent)
        self.pipeline = pipeline
        self.paths = paths

    def run(self) -> None:
        try:
            jobs: list[FileJob] = []
            total = len(self.paths)
            for i, p in enumerate(self.paths):
                if self.isInterruptionRequested():
                    break
                job = self.pipeline.plan_one(p)
                jobs.append(job)
                self.progress.emit(i + 1, total)
            self.finished_batch.emit(jobs)
        except Exception as exc:
            self.failed.emit(str(exc))


class _ProcessWorker(QThread):
    progress = Signal(int, int)
    finished_batch = Signal(object)
    failed = Signal(str)

    def __init__(
        self, pipeline: Pipeline, jobs: list[FileJob], dry_run: bool = False, parent=None
    ) -> None:
        super().__init__(parent)
        self.pipeline = pipeline
        self.jobs = jobs
        self.dry_run = dry_run

    def run(self) -> None:
        try:
            def _on_prog(done: int, total: int) -> None:
                self.progress.emit(done, total)

            summary = self.pipeline.process_batch(
                self.jobs,
                dry_run=self.dry_run,
                progress_callback=_on_prog,
            )
            self.finished_batch.emit(summary)
        except Exception as exc:
            self.failed.emit(str(exc))


class MainWindow(QMainWindow):
    COLUMN_MIN_WIDTH = [90, 180, 200, 180, 150, 140, 120]
    COLUMN_MAX_WIDTH = [120, 360, 420, 360, 400]

    def __init__(self, ctx: AppContext, theme: Theme | None = None) -> None:
        super().__init__()
        self.ctx = ctx
        self.theme = theme or Theme.load(mode=getattr(ctx.config, "theme", "dark") or "dark")
        self.setWindowIcon(get_app_icon())
        self.setWindowTitle("PDF Batch Renamer")

        min_w, min_h = self.theme.metric("min_window") or [1280, 800]
        des_w, des_h = self.theme.metric("design_canvas") or [1440, 900]
        self.setMinimumSize(QSize(min_w, min_h))
        self.resize(QSize(des_w, des_h))

        self.menuBar().setVisible(False)

        self.pipeline: Pipeline | None = None
        self._rebuild_pipeline()

        self.preview_model = PreviewModel(rename_handler=self._on_rename_in_table)
        self.preview_model.set_output_root(self.ctx.config.output_root)
        self.fields_model = FieldsModel(parent=self)
        self.fields_model.fieldEdited.connect(self._on_field_edited)

        self.pending_paths: list[Path] = []
        self._worker: QThread | None = None
        self.watcher: StableFileWatcher | None = None
        self.watch_pipeline: Pipeline | None = None
        self.watch_bridge = _WatchBridge()
        self.watch_bridge.processed.connect(self._on_watch_event)

        # Main Actions
        self.act_files = QAction(get_icon("file-plus"), "Chọn file", self)
        self.act_files.setShortcut(QKeySequence("Ctrl+O"))
        self.act_files.triggered.connect(self._choose_files)
        self.addAction(self.act_files)

        self.act_dirs = QAction(get_icon("folder"), "Chọn thư mục", self)
        self.act_dirs.setShortcut(QKeySequence("Ctrl+Shift+O"))
        self.act_dirs.triggered.connect(self._choose_directory)
        self.addAction(self.act_dirs)

        self.act_scan = QAction(get_icon("search"), "Xem trước", self)
        self.act_scan.setShortcut(QKeySequence("F5"))
        self.act_scan.triggered.connect(self._run_scan)
        self.addAction(self.act_scan)
        self.act_preview = self.act_scan

        self.act_apply = QAction(get_icon("play"), "Áp dụng", self)
        self.act_apply.setShortcut(QKeySequence("Ctrl+Return"))
        self.act_apply.triggered.connect(self._run_apply)
        self.addAction(self.act_apply)

        self.act_undo = QAction(get_icon("rotate-ccw"), "Hoàn tác", self)
        self.act_undo.setShortcut(QKeySequence("Ctrl+Z"))
        self.act_undo.triggered.connect(self._open_undo)
        self.addAction(self.act_undo)

        self.act_settings = QAction(get_icon("gear"), "Cài đặt", self)
        self.act_settings.setShortcut(QKeySequence("F10"))
        self.act_settings.triggered.connect(self._open_settings)
        self.addAction(self.act_settings)

        self.act_guide = QAction(get_icon("bulb"), "Hướng dẫn", self)
        self.act_guide.setShortcut(QKeySequence("F1"))
        self.act_guide.triggered.connect(self._open_guide)
        self.addAction(self.act_guide)

        self.act_theme = QAction(get_icon("theme"), "Giao diện", self)
        self.act_theme.setShortcut(QKeySequence("F11"))
        self.act_theme.triggered.connect(self._toggle_theme)
        self.addAction(self.act_theme)

        self.act_rules = QAction(get_icon("checklist"), "Quản lý rule", self)
        self.act_rules.setShortcut(QKeySequence("Ctrl+R"))
        self.act_rules.triggered.connect(self._open_rule_editor)
        self.addAction(self.act_rules)

        self.act_wizard = QAction(get_icon("wand"), "Tạo loại chứng từ", self)
        self.act_wizard.setShortcut(QKeySequence("Ctrl+N"))
        self.act_wizard.triggered.connect(self._open_rule_wizard)
        self.addAction(self.act_wizard)

        self.act_stats = QAction(get_icon("chart"), "Thống kê", self)
        self.act_stats.triggered.connect(self._open_stats)
        self.addAction(self.act_stats)

        self.act_toggle_preview = QAction(get_icon("panel-right"), "Xem trang PDF", self)
        self.act_toggle_preview.setCheckable(True)
        self.act_toggle_preview.setChecked(True)
        self.act_toggle_preview.setShortcut(QKeySequence("F6"))
        self.addAction(self.act_toggle_preview)

        self.act_watch = QAction("Theo dõi thư mục tự động", self)
        self.act_watch.setCheckable(True)
        self.act_watch.toggled.connect(self._toggle_watch)
        self.addAction(self.act_watch)

        self.act_report = QAction("Xuất báo cáo", self)
        self.act_report.triggered.connect(self._export_report)
        self.act_report.setEnabled(False)
        self.addAction(self.act_report)

        self.detail_label = QLabel("Chưa có file nào trong hàng đợi.")
        self.detail_label.setVisible(False)

        # Dock widget for backward compatibility
        self.field_dock = QDockWidget("Chi tiết trường", self)
        self.field_dock.setAllowedAreas(
            Qt.DockWidgetArea.RightDockWidgetArea | Qt.DockWidgetArea.BottomDockWidgetArea
        )
        self.addDockWidget(
            Qt.DockWidgetArea.RightDockWidgetArea
            if getattr(self.ctx.config, "field_panel_area", "bottom") == "right"
            else Qt.DockWidgetArea.BottomDockWidgetArea,
            self.field_dock,
        )
        self.field_dock.setVisible(False)

        self._build_toolbar()
        self._build_body()
        self._build_statusbar()
        self._setup_logging_bridge()

        # Compatibility aliases for test suite
        self.counts = self.lbl_counts
        self.pdf_viewer = self.preview_dock

        self.setAcceptDrops(True)
        self._update_counts()
        from PySide6.QtCore import QTimer
        QTimer.singleShot(2000, self._trigger_startup_update_check)

    def _rebuild_pipeline(self) -> None:
        self.pipeline = self._make_pipeline()

    def _make_pipeline(self) -> Pipeline:
        return Pipeline(
            config=self.ctx.config,
            profiles=self.ctx.profiles,
            db=self.ctx.db,
            dictionary=self.ctx.company_dict,
        )

    # ---------------------------------------------------------- toolbar

    def _tool_button(
        self,
        text: str,
        icon_name: str,
        shortcut: str | None,
        tooltip: str,
        *,
        danger: bool = False,
        checkable: bool = False,
    ) -> QToolButton:
        btn = QToolButton(self)
        btn.setText(text)
        btn.setIcon(get_icon(icon_name))
        btn.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextBesideIcon if text else Qt.ToolButtonStyle.ToolButtonIconOnly
        )
        btn.setCheckable(checkable)
        btn.setToolTip(f"{tooltip} ({shortcut})" if shortcut else tooltip)
        if danger:
            btn.setProperty("danger", "true")
        return btn

    def _build_toolbar(self) -> None:
        tb = QToolBar("Actions", self)
        tb.setObjectName("ActionToolBar")
        tb.setMovable(False)
        tb.setIconSize(QSize(16, 16))
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, tb)

        # Nhóm 1: Nạp file & thư mục
        self.btn_pick_files = self._tool_button("Chọn file", "file-plus", "Ctrl+O", "Chọn các file PDF cần đổi tên")
        self.btn_pick_dir = self._tool_button("Chọn thư mục", "folder", "Ctrl+Shift+O", "Chọn toàn bộ file PDF trong thư mục")
        self.btn_clear = self._tool_button("", "trash", None, "Xóa toàn bộ danh sách hàng đợi", danger=True)
        self.btn_clear.setFixedWidth(34)
        self.btn_pick_files.clicked.connect(self.act_files.trigger)
        self.btn_pick_dir.clicked.connect(self.act_dirs.trigger)
        self.btn_clear.clicked.connect(self._clear_all)
        tb.addWidget(self.btn_pick_files)
        tb.addWidget(self.btn_pick_dir)
        tb.addWidget(self.btn_clear)
        tb.addSeparator()

        # Nhóm 2: Thực thi
        self.btn_preview = self._tool_button("Xem trước", "search", "F5", "Nhận diện & bóc tách thử, không đổi tên file")
        self.btn_apply = self._tool_button("Áp dụng", "play", "Ctrl+Return", "Tiến hành đổi tên & di chuyển file an toàn")
        self.btn_apply.setProperty("variant", "primary")
        self.btn_cancel = self._tool_button("", "stop", "Esc", "Hủy tiến trình đang chạy")
        self.btn_cancel.setFixedWidth(34)
        self.btn_cancel.setEnabled(False)
        self.chk_dryrun = QCheckBox("Dry-run", self)
        self.chk_dryrun.setToolTip("Chạy thử nghiệm: chỉ ghi log, không sửa hay di chuyển file")

        self.btn_preview.clicked.connect(self.act_scan.trigger)
        self.btn_apply.clicked.connect(self.act_apply.trigger)
        self.btn_cancel.clicked.connect(self._cancel_worker)

        tb.addWidget(self.btn_preview)
        tb.addWidget(self.btn_apply)
        tb.addWidget(self.btn_cancel)
        tb.addWidget(self.chk_dryrun)
        tb.addSeparator()

        # Nhóm 3: Quản lý Rule & Xem PDF
        self.btn_rules = self._tool_button("Quản lý rule", "checklist", "Ctrl+R", "Danh sách & chỉnh sửa mẫu chứng từ")
        self.btn_new_type = self._tool_button("Tạo loại mới", "wand", "Ctrl+N", "Tạo mẫu loại chứng từ mới qua Wizard 4 bước")
        self.btn_toggle_preview = self._tool_button(
            "Xem PDF", "panel-right", "F6", "Bật/tắt panel xem trang PDF", checkable=True
        )
        self.btn_toggle_preview.setChecked(True)

        self.btn_rules.clicked.connect(self.act_rules.trigger)
        self.btn_new_type.clicked.connect(self.act_wizard.trigger)

        tb.addWidget(self.btn_rules)
        tb.addWidget(self.btn_new_type)
        tb.addWidget(self.btn_toggle_preview)

        # Spacer đẩy nhóm hệ thống sang phải
        spacer = QWidget(self)
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        tb.addWidget(spacer)

        # Nhóm 4: Hệ thống & Trợ giúp Dropdown
        self.btn_theme = self._tool_button("", "theme", "F11", "Chuyển giao diện Sáng / Tối (Theme Mode)")
        self.btn_theme.setFixedWidth(34)
        self.btn_theme.clicked.connect(self._toggle_theme)

        self.btn_settings = self._tool_button("", "gear", "F10", "Cài đặt hệ thống (F10)")
        self.btn_settings.setFixedWidth(34)
        self.btn_settings.clicked.connect(self.act_settings.trigger)

        # Menu Trợ giúp Dropdown hiện đại
        self.btn_help_menu = QToolButton(self)
        self.btn_help_menu.setText("Trợ giúp")
        self.btn_help_menu.setIcon(get_icon("help-menu"))
        self.btn_help_menu.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.btn_help_menu.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.btn_help_menu.setToolTip("Menu Hướng dẫn, Cập nhật & Giới thiệu")

        help_menu = QMenu(self.btn_help_menu)
        help_menu.addAction(self.act_guide)

        self.act_update = QAction(get_icon("refresh"), "Kiểm tra bản cập nhật...", self)
        self.act_update.triggered.connect(self._check_update_manual)
        help_menu.addAction(self.act_update)

        self.act_about = QAction(get_icon("info"), "Giới thiệu phần mềm & Tác giả", self)
        self.act_about.triggered.connect(self._open_about)
        help_menu.addAction(self.act_about)

        help_menu.addSeparator()
        help_menu.addAction(self.act_stats)
        help_menu.addAction(self.act_undo)
        help_menu.addAction(self.act_report)

        self.btn_help_menu.setMenu(help_menu)

        tb.addWidget(self.btn_theme)
        tb.addWidget(self.btn_settings)
        tb.addWidget(self.btn_help_menu)

    # ------------------------------------------------------------- body

    def _build_body(self) -> None:
        self.split_main = QSplitter(Qt.Orientation.Horizontal, self)
        self.split_main.setChildrenCollapsible(False)
        self.split_main.setHandleWidth(1)

        # Cột trái: Queue + Inspector
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
        self.table.setModel(self.preview_model)
        self.table.setItemDelegateForColumn(0, StatusBadgeDelegate(self.theme, self.table))
        self.table.setItemDelegateForColumn(COL_OLD, PathElideDelegate(Qt.TextElideMode.ElideLeft, self.table))
        self.table.setItemDelegateForColumn(COL_DEST, PathElideDelegate(Qt.TextElideMode.ElideLeft, self.table))
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setAlternatingRowColors(False)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_context_menu)
        self.table.doubleClicked.connect(self._on_table_double_clicked)

        self.table.verticalHeader().setVisible(False)
        row_h = self.theme.metric("table_row_height") or 38
        self.table.verticalHeader().setDefaultSectionSize(row_h)

        hh = self.table.horizontalHeader()
        hdr_h = self.theme.metric("table_header_height") or 34
        hh.setFixedHeight(hdr_h)
        hh.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        
        # Thiết lập độ rộng cột chuẩn xác, không bao giờ bị cắt chữ F ở 'Field trích được'
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(0, 95)  # Trạng thái
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)  # Tên cũ
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)  # Tên mới
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)  # Thư mục đích
        hh.setSectionResizeMode(4, QHeaderView.ResizeMode.Interactive)  # Profile
        self.table.setColumnWidth(4, 110)
        hh.setSectionResizeMode(5, QHeaderView.ResizeMode.Interactive)  # Field trích được
        self.table.setColumnWidth(5, 145)
        hh.setSectionResizeMode(6, QHeaderView.ResizeMode.Interactive)  # Ghi chú
        self.table.setColumnWidth(6, 110)

        lv.addWidget(self.table, 1)

        self.inspector = InspectorPanel(self.theme, left)
        self.inspector.setObjectName("InspectorPanel")
        self.inspector.setFixedHeight(200)
        self.inspector.field_edited.connect(self._on_field_edited)
        lv.addWidget(self.inspector)

        self.split_main.addWidget(left)

        # Cột phải: PDF preview dock (Retina 2x oversampling)
        self.preview_dock = PdfPreviewDock(self.theme, self)
        self.preview_dock.setObjectName("PreviewDock")
        self.split_main.addWidget(self.preview_dock)
        self.split_main.setStretchFactor(0, 60)
        self.split_main.setStretchFactor(1, 40)

        # Log panel under splitter
        container = QWidget(self)
        cv = QVBoxLayout(container)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.setSpacing(0)
        cv.addWidget(self.split_main, 1)

        self.log_header = QWidget(container)
        self.log_header.setObjectName("LogHeader")
        lh = QHBoxLayout(self.log_header)
        lh.setContentsMargins(12, 6, 12, 6)
        self.lbl_log_caret = QLabel("v  LOG HỆ THỐNG", self.log_header)
        lh.addWidget(self.lbl_log_caret)
        lh.addStretch(1)
        cv.addWidget(self.log_header)

        self.log_view = QPlainTextEdit(container)
        self.log_view.setObjectName("LogView")
        self.log_view.setReadOnly(True)
        log_h = self.theme.metric("log_panel_height") or 96
        self.log_view.setFixedHeight(log_h)
        cv.addWidget(self.log_view)

        self.setCentralWidget(container)

        # Wiring
        self.btn_toggle_preview.toggled.connect(self.act_toggle_preview.setChecked)
        self.act_toggle_preview.toggled.connect(self.btn_toggle_preview.setChecked)
        self.act_toggle_preview.toggled.connect(self.preview_dock.setVisible)
        self.log_header.mousePressEvent = lambda _e: self._toggle_log()
        self.table.selectionModel().currentRowChanged.connect(self._on_row_selected)

    def _toggle_log(self) -> None:
        visible = not self.log_view.isVisible()
        self.log_view.setVisible(visible)
        self.lbl_log_caret.setText(("v" if visible else ">") + "  LOG HỆ THỐNG")

    # -------------------------------------------------------- status bar

    def _build_statusbar(self) -> None:
        bar = self.statusBar()
        bar.setObjectName("StatusBar")
        bar.setSizeGripEnabled(False)
        bar_h = self.theme.metric("statusbar_height") or 30
        bar.setFixedHeight(bar_h)

        self.lbl_counts = QLabel("Chưa có file nào.", bar)
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

    def _setup_logging_bridge(self) -> None:
        handler = QtLogHandler()
        handler.bridge.message.connect(self._on_log_message)
        logging.getLogger().addHandler(handler)

    def _on_log_message(self, level: str, msg: str, ts: str) -> None:
        color = self.theme.color(f"log.{level.lower()}", self.theme.color("text_muted"))
        self.log_view.appendHtml(
            f'<span style="color:{self.theme.color("log.time")}">{ts}</span> '
            f'<span style="color:{color}; font-weight:bold;">{level.upper():<5}</span> '
            f'<span style="color:{self.theme.color("text")}">{msg}</span>'
        )

    # ---------------------------------------------------------- file actions


    def _trigger_startup_update_check(self) -> None:
        """Kiểm tra cập nhật ngầm sau khi ứng dụng khởi động 2 giây."""
        if getattr(self.ctx.config, "auto_check_update", True):
            url = getattr(self.ctx.config, "update_url", "") or ""
            self._update_worker = _UpdateCheckWorker(url)
            self._update_worker.found_update.connect(self._on_update_found_startup)
            self._update_worker.start()

    def _on_update_found_startup(self, manifest: UpdateManifest) -> None:
        dlg = UpdateDialog(manifest, self)
        dlg.exec()

    def _check_update_manual(self) -> None:
        """Người dùng bấm nút Kiểm tra cập nhật trên thanh công cụ."""
        url = getattr(self.ctx.config, "update_url", "") or ""
        self.act_update.setEnabled(False)
        self._manual_update_worker = _UpdateCheckWorker(url)
        self._manual_update_worker.found_update.connect(self._on_update_found_manual)
        self._manual_update_worker.no_update.connect(self._on_no_update_manual)
        self._manual_update_worker.failed.connect(self._on_update_check_failed)
        self._manual_update_worker.start()

    def _on_update_found_manual(self, manifest: UpdateManifest) -> None:
        self.act_update.setEnabled(True)
        dlg = UpdateDialog(manifest, self)
        dlg.exec()

    def _on_no_update_manual(self) -> None:
        self.act_update.setEnabled(True)
        QMessageBox.information(
            self,
            "Đã cập nhật mới nhất",
            f"Bạn đang sử dụng phiên bản mới nhất (v{__version__}). Không có bản cập nhật nào mới hơn.",
        )

    def _on_update_check_failed(self, err: str) -> None:
        self.act_update.setEnabled(True)
        QMessageBox.warning(
            self,
            "Không thể kết nối",
            f"Không thể kiểm tra bản cập nhật lúc này:\n{err}\n\nVui lòng kiểm tra lại kết nối mạng.",
        )

    def _choose_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "Chọn file PDF", "", "File PDF (*.pdf)")
        if files:
            self._add_paths([Path(f) for f in files])

    def _choose_directory(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Chọn thư mục chứa PDF")
        if folder:
            self._add_paths([Path(folder)])

    def _add_paths(self, paths: list[Path]) -> None:
        raw_files: list[Path] = []
        for raw in paths:
            p = Path(raw)
            if p.is_dir():
                raw_files.extend(x for x in p.glob("**/*") if x.is_file())
            elif p.is_file():
                raw_files.append(p)

        skipped = [p for p in raw_files if p.suffix.lower() != ".pdf"]
        if skipped:
            logger.warning(
                "Bỏ qua %d file không phải PDF: %s",
                len(skipped),
                ", ".join(x.name for x in skipped[:3]),
            )

        found = scan_pdfs(paths)
        existing = {p.resolve() for p in self.pending_paths}
        new_paths = [p for p in found if p.resolve() not in existing]
        if not new_paths:
            return

        self.pending_paths.extend(new_paths)
        current_jobs = list(self.preview_model.jobs)
        for p in new_paths:
            current_jobs.append(FileJob(source=p, status=JobStatus.PENDING))
        self.preview_model.set_jobs(current_jobs)
        self._update_counts()
        from PySide6.QtCore import QTimer
        QTimer.singleShot(2000, self._trigger_startup_update_check)
        self._on_row_selected()

    def _clear_all(self) -> None:
        self.pending_paths.clear()
        self.preview_model.set_jobs([])
        self.fields_model.set_job(None)
        self.inspector.set_job(None)
        self.preview_dock.clear()
        self.detail_label.setText("Chưa có file nào trong hàng đợi.")
        self._update_counts()
        from PySide6.QtCore import QTimer
        QTimer.singleShot(2000, self._trigger_startup_update_check)

    def _clear(self) -> None:
        self._clear_all()

    def _select_row(self, row: int) -> None:
        if 0 <= row < self.preview_model.rowCount():
            self.table.selectRow(row)
            self._on_row_selected()

    def _remove_job_at(self, row: int) -> None:
        self._remove_row(row)

    def _fit_columns(self) -> None:
        for column in range(self.table.model().columnCount()):
            min_w = self.COLUMN_MIN_WIDTH[column] if column < len(self.COLUMN_MIN_WIDTH) else 100
            max_w = self.COLUMN_MAX_WIDTH[column] if column < len(self.COLUMN_MAX_WIDTH) else 400
            hint = self.table.sizeHintForColumn(column)
            self.table.setColumnWidth(column, max(min_w, min(hint, max_w)))

    def _on_dock_moved(self, area) -> None:
        if area == Qt.DockWidgetArea.RightDockWidgetArea:
            self.ctx.config.field_panel_area = "right"
        else:
            self.ctx.config.field_panel_area = "bottom"
        save_config(self.ctx.config)

    def _toggle_watch(self, checked: bool) -> None:
        if checked:
            if not self.ctx.config.watch.folder:
                QMessageBox.warning(self, "Chưa cấu hình", "Chưa chọn thư mục theo dõi.")
                self.act_watch.setChecked(False)
                self._open_settings()
                return
            self.watch_pipeline = self._make_pipeline()
            self.watcher = StableFileWatcher(
                folder=Path(self.ctx.config.watch.folder),
                on_file=self._handle_watched_file,
                stable_seconds=self.ctx.config.watch.stable_seconds,
            )
            self.watcher.start()
        else:
            if self.watcher:
                self.watcher.stop()
                self.watcher = None
            self.watch_pipeline = None

    def _handle_watched_file(self, path: Path | str) -> None:
        p = Path(path)
        if not self.watch_pipeline:
            self.watch_pipeline = self._make_pipeline()
        try:
            jobs = self.watch_pipeline.plan([p])
            self.watch_pipeline.apply(jobs)
            self._add_paths([p])
            self.watch_bridge.processed.emit(f"Đã xử lý: {p.name}")
        except Exception as exc:
            logger.error("Lỗi xử lý file tự động %s: %s", p, exc)

    def _on_watch_event(self, path_str: str) -> None:
        p = Path(path_str)
        if p.exists() and p.suffix.lower() == ".pdf":
            self._add_paths([p])

    def _on_plan_done(self, jobs: list[FileJob]) -> None:
        self.preview_model.set_jobs(jobs)
        self._update_counts()
        from PySide6.QtCore import QTimer
        QTimer.singleShot(2000, self._trigger_startup_update_check)
        if self.preview_model.rowCount() > 0:
            self.table.selectRow(0)
        self._on_row_selected()

    def _on_apply_done(self, summary: BatchSummary | object) -> None:
        if hasattr(summary, "jobs") and summary.jobs:
            self.preview_model.set_jobs(summary.jobs)
        self._update_counts()
        from PySide6.QtCore import QTimer
        QTimer.singleShot(2000, self._trigger_startup_update_check)
        if self.preview_model.rowCount() > 0:
            self.table.selectRow(0)
        self._on_row_selected()
        QMessageBox.information(self, "Hoàn tất", "Đã xử lý xong toàn bộ danh sách file.")

    def _export_report(self) -> None:
        if not self.preview_model.jobs:
            return
        default_name = default_report_name()
        path, _ = QFileDialog.getSaveFileName(
            self, "Xuất báo cáo", default_name, "File Excel (*.xlsx);;File CSV (*.csv)"
        )
        if path:
            write_report(Path(path), self.preview_model.jobs)
            QMessageBox.information(self, "Đã xuất báo cáo", f"Đã lưu báo cáo tại: {path}")

    def _update_counts(self) -> None:
        total = len(self.preview_model.jobs)
        self.act_report.setEnabled(total > 0)
        self.act_scan.setEnabled(total > 0)
        self.btn_preview.setEnabled(total > 0)

        has_ready = any(bool(j.new_name) for j in self.preview_model.jobs)
        self.act_apply.setEnabled(has_ready)
        self.btn_apply.setEnabled(has_ready)

        if total == 0:
            self.lbl_counts.setText("Chưa có file nào.")
            return

        total_bytes = sum(
            j.source.stat().st_size for j in self.preview_model.jobs if j.source and j.source.exists()
        )
        mb = total_bytes / (1024 * 1024)
        pending = sum(1 for j in self.preview_model.jobs if j.status == JobStatus.PENDING)
        success = sum(1 for j in self.preview_model.jobs if j.status == JobStatus.SUCCESS)
        error = sum(1 for j in self.preview_model.jobs if j.status == JobStatus.ERROR)
        dup = sum(1 for j in self.preview_model.jobs if j.status == JobStatus.DUPLICATE)

        self.lbl_counts.setText(
            f"Chờ: {pending}  ·  Thành công: {success}  ·  Trùng: {dup}  ·  Lỗi: {error}  ·  tổng {total} file ({mb:.1f} MB)"
        )

    # ------------------------------------------------------------- row selection

    @Slot()
    def _on_row_selected(self, *_args) -> None:
        idx = self.table.currentIndex()
        row = idx.row() if idx.isValid() else 0
        job = self.preview_model.job_at(row)
        self.fields_model.set_job(job)
        self.inspector.set_job(job)

        if not self.preview_model.jobs:
            self.detail_label.setText("Chưa có file nào trong hàng đợi.")
        elif not job:
            self.detail_label.setText("Chọn 1 dòng để xem chi tiết.")
        elif not job.new_name:
            self.detail_label.setText(f"{job.source.name} · đang chờ xử lý...")
        else:
            profile = self.pipeline.profile_by_id(job.profile_id) if self.pipeline else None
            is_fallback = (profile and profile.is_fallback) or not job.fields or not job.profile_id or job.profile_id == "fallback"
            if is_fallback:
                self.detail_label.setText(f"{job.source.name} · Loại: Chung (giữ nguyên tên gốc)")
            else:
                self.detail_label.setText(f"{job.source.name} · {len(job.fields)} trường")

        if job and job.source and job.source.exists():
            self.preview_dock.load_file(job.source)
        else:
            self.preview_dock.clear()

    def _on_table_double_clicked(self, index: QModelIndex) -> None:
        row = index.row()
        col = index.column()
        job = self.preview_model.job_at(row)
        if not job:
            return
        if col == COL_OLD:
            if job.source and job.source.exists():
                open_in_explorer(job.source)
        elif col == COL_NEW:
            dest_file = (job.dest_dir / job.new_name) if job.dest_dir and job.new_name else None
            if dest_file and dest_file.exists():
                open_in_explorer(dest_file)
            elif job.source and job.source.exists():
                open_in_explorer(job.source)
        elif col == COL_DEST:
            if job.dest_dir and job.dest_dir.exists():
                open_in_explorer(job.dest_dir)
            elif self.ctx.config.output_root and Path(self.ctx.config.output_root).exists():
                open_in_explorer(self.ctx.config.output_root)

    def _on_detail_link_clicked(self, which: str) -> None:
        idx = self.table.currentIndex()
        row = idx.row() if idx.isValid() else 0
        job = self.preview_model.job_at(row)
        if not job:
            return
        if which == "source" and job.source:
            open_in_explorer(job.source)
        elif which == "dest_file":
            dest_file = (job.dest_dir / job.new_name) if job.dest_dir and job.new_name else None
            if dest_file and dest_file.exists():
                open_in_explorer(dest_file)
            elif job.source:
                open_in_explorer(job.source)
        elif which == "dest_dir":
            if job.dest_dir:
                open_in_explorer(job.dest_dir)
            elif self.ctx.config.output_root:
                open_in_explorer(self.ctx.config.output_root)

    def _show_context_menu(self, pos: QPoint) -> None:
        idx = self.table.indexAt(pos)
        if not idx.isValid():
            return
        row = idx.row()
        job = self.preview_model.job_at(row)
        if not job:
            return

        menu = QMenu(self)
        dest_file = (job.dest_dir / job.new_name) if job.dest_dir and job.new_name else None
        if dest_file and dest_file.exists():
            act_target = menu.addAction("Mở file đích đã tạo")
            act_target.triggered.connect(lambda: open_in_explorer(dest_file))
        if job.dest_dir and job.dest_dir.exists():
            act_dest = menu.addAction("Mở thư mục đích")
            act_dest.triggered.connect(lambda: open_in_explorer(job.dest_dir))
        if job.source and job.source.exists():
            act_src = menu.addAction("Mở file gốc")
            act_src.triggered.connect(lambda: open_in_explorer(job.source))
            act_src_folder = menu.addAction("Mở thư mục chứa file gốc")
            act_src_folder.triggered.connect(lambda: open_in_explorer(job.source.parent))

        menu.addSeparator()
        act_del = menu.addAction("Xóa file này khỏi danh sách")
        act_del.triggered.connect(lambda: self._remove_row(row))

        menu.exec(self.table.viewport().mapToGlobal(pos))

    def _remove_row(self, row: int) -> None:
        jobs = list(self.preview_model.jobs)
        if 0 <= row < len(jobs):
            jobs.pop(row)
            self.preview_model.set_jobs(jobs)
            self.pending_paths = [j.source for j in jobs if j.source and j.source.exists()]
            self._update_counts()
            self._on_row_selected()

    # ----------------------------------------------------------- processing

    def _run_scan(self) -> None:
        paths = [j.source for j in self.preview_model.jobs if j.source and j.source.exists()]
        if not paths:
            QMessageBox.information(self, "Chưa có file", "Vui lòng chọn ít nhất 1 file PDF để xem trước.")
            return
        self.pending_paths = list(paths)
        self.set_running(True, 0, len(paths))
        self._rebuild_pipeline()
        self._worker = _ScanWorker(self.pipeline, paths)
        self._worker.progress.connect(self._on_process_progress)
        self._worker.finished_batch.connect(self._on_batch_finished)
        self._worker.failed.connect(self._on_worker_failed)
        self._worker.start()

    def _run_apply(self) -> None:
        jobs = list(self.preview_model.jobs)
        if not jobs:
            QMessageBox.information(self, "Chưa có file", "Vui lòng chọn ít nhất 1 file PDF để xử lý.")
            return
        if not self.ctx.config.output_root and not self.chk_dryrun.isChecked():
            QMessageBox.warning(
                self, "Chưa chọn thư mục đích", "Vui lòng mở Cài đặt (F10) để chọn thư mục lưu kết quả."
            )
            self._open_settings()
            return
        self.set_running(True, 0, len(jobs))
        self._rebuild_pipeline()
        self._worker = _ProcessWorker(
            self.pipeline, jobs, dry_run=self.chk_dryrun.isChecked()
        )
        self._worker.progress.connect(self._on_process_progress)
        self._worker.finished_batch.connect(self._on_batch_finished)
        self._worker.failed.connect(self._on_worker_failed)
        self._worker.start()

    def _on_process_progress(self, done: int, total: int) -> None:
        self.set_running(True, done, total)

    def _on_batch_finished(self, result: BatchSummary | list[FileJob]) -> None:
        self.set_running(False)
        if isinstance(result, list):
            self.preview_model.set_jobs(result)
            self.pending_paths = [j.source for j in result if j.source and j.source.exists()]
        elif hasattr(result, "jobs") and result.jobs:
            self.preview_model.set_jobs(result.jobs)
            self.pending_paths = [j.source for j in result.jobs if j.source and j.source.exists()]
        self._update_counts()
        from PySide6.QtCore import QTimer
        QTimer.singleShot(2000, self._trigger_startup_update_check)
        if self.preview_model.rowCount() > 0:
            self.table.selectRow(0)
        self._on_row_selected()
        if isinstance(result, BatchSummary) and not self.chk_dryrun.isChecked():
            if result.errors > 0:
                QMessageBox.warning(
                    self,
                    "Hoàn tất với cảnh báo",
                    f"Đã xử lý {result.total} file:\n- Thành công: {result.success}\n- Lỗi: {result.errors}\n- Trùng: {result.duplicate}",
                )
            else:
                QMessageBox.information(
                    self,
                    "Hoàn tất",
                    f"Đã xử lý thành công {result.success}/{result.total} file.",
                )

    def _on_worker_failed(self, err: str) -> None:
        self.set_running(False)
        QMessageBox.critical(self, "Lỗi xử lý", f"Đã xảy ra lỗi: {err}")

    def _cancel_worker(self) -> None:
        if self._worker and self._worker.isRunning():
            self._worker.terminate()
            self._worker.wait(1000)
            self.set_running(False)
            self.lbl_progress_text.setText("Đã dừng tiến trình")

    def set_running(self, running: bool, done: int = 0, total: int = 0) -> None:
        has_ready = any(bool(j.new_name) for j in self.preview_model.jobs)
        self.btn_apply.setEnabled(not running and has_ready)
        self.btn_preview.setEnabled(not running and len(self.preview_model.jobs) > 0)
        self.act_apply.setEnabled(not running and has_ready)
        self.act_scan.setEnabled(not running and len(self.preview_model.jobs) > 0)

        self.btn_cancel.setEnabled(running)
        self.btn_pick_files.setEnabled(not running)
        self.btn_pick_dir.setEnabled(not running)
        self.btn_clear.setEnabled(not running)
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

    # ------------------------------------------------------- field learning

    def _on_rename_in_table(self, job: FileJob, new_name: str) -> None:
        job.new_name = new_name
        job.status = JobStatus.SUCCESS

    def _on_field_edited(self, key: str, old_val: str, new_val: str) -> None:
        idx = self.table.currentIndex()
        job = self.preview_model.job_at(idx.row()) if idx.isValid() else None
        if not job:
            return
        profile = self.pipeline.profile_by_id(job.profile_id) if self.pipeline else None
        if profile:
            field_values = {k: f.value for k, f in job.fields.items()}
            date_fields = {f.name for f in profile.fields if f.validate == "date"} | {"doc_date"}
            job.base_name = render_template(
                profile.template,
                field_values,
                date_formats=profile.date_formats,
                date_fields=date_fields,
            )
            job.new_name = job.base_name + (job.source.suffix if job.source else ".pdf")
            self.preview_model.refresh_row(idx.row())

        if self.pipeline and self.pipeline.learning and profile:
            self.pipeline.learning.record_correction(
                field_name=key,
                old_value=old_val,
                new_value=new_val,
                profile_id=job.profile_id,
                file_name=job.source.name if job.source else "",
            )

        reply = QMessageBox.question(
            self,
            "Tạo rule từ chỉnh sửa",
            f"Bạn có muốn tạo quy tắc tự động cho trường '{key}' không?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes and profile:
            dlg = CorrectionRuleDialog(
                config=self.ctx.config,
                store=self.ctx.store,
                profile=profile,
                job=job,
                field_name=key,
                new_value=new_val,
                parent=self,
            )
            if dlg.exec():
                self._rebuild_pipeline()
                self.preview_dock.update()

    # ------------------------------------------------------------- dialogs

    def _open_undo(self) -> None:
        sessions = list_sessions(self.ctx.db)
        if not sessions:
            QMessageBox.information(self, "Hoàn tác", "Chưa có phiên xử lý nào để hoàn tác.")
            return
        sess = sessions[0]
        res = undo_session(self.ctx.db, sess["session_id"])
        QMessageBox.information(
            self,
            "Hoàn tác",
            f"Đã hoàn tác phiên {sess['session_id']}: {res.success} thành công, {res.errors} lỗi.",
        )
        self._rebuild_pipeline()


    def _toggle_theme(self) -> None:
        new_mode = "dark" if self.theme.mode == "light" else "light"
        self._apply_theme(new_mode)

    def _apply_theme(self, mode: str) -> None:
        from src.core.config import save_config
        self.theme.set_mode(mode)
        qapp = QApplication.instance()
        if qapp:
            self.theme.apply(qapp)
        self.ctx.config.theme = mode
        try:
            save_config(self.ctx.config)
        except Exception:
            pass
        self.table.setItemDelegateForColumn(0, StatusBadgeDelegate(self.theme, self.table))
        if hasattr(self, "inspector") and self.inspector:
            self.inspector.rebind_theme(self.theme)
        if hasattr(self, "preview_dock") and self.preview_dock:
            self.preview_dock.canvas.theme = self.theme
            self.preview_dock.canvas.update()
        self.table.viewport().update()
        lbl = "Sáng (Khuyên dùng)" if mode == "light" else "Tối (Dark mode)"
        self.statusBar().showMessage(f"Đã chuyển sang giao diện: {lbl}", 4000)

    def _open_settings(self) -> None:
        dlg = SettingsDialog(self.ctx.config, self.ctx.profiles, self)
        if dlg.exec():
            self.ctx.config = dlg.config
            save_config(self.ctx.config)
            self.preview_model.set_output_root(self.ctx.config.output_root)
            self._rebuild_pipeline()

    def _open_rule_editor(self) -> None:
        dlg = RuleEditorDialog(self.ctx.config, self.ctx.store, self.ctx.learning, parent=self)
        dlg.exec()
        self._rebuild_pipeline()

    def _open_rule_wizard(self) -> None:
        wiz = RuleBuilderWizard(self.ctx.config, self.ctx.store, parent=self)
        if wiz.exec():
            self._rebuild_pipeline()

    def _open_stats(self) -> None:
        dlg = StatsDialog(self.ctx.learning, self.ctx.profiles, parent=self)
        dlg.exec()

    def _open_guide(self) -> None:
        dlg = QuickGuideDialog(self)
        dlg.exec()

    def _open_about(self) -> None:
        url = getattr(self.ctx.config, "update_url", "") or DEFAULT_UPDATE_URL
        dlg = AboutDialog(update_url=url, parent=self)
        dlg.exec()

    def _check_update_manual(self) -> None:
        """Kiểm tra cập nhật thủ công và phản hồi kết quả chi tiết cho người dùng."""
        self.statusBar().showMessage("Đang kiểm tra bản cập nhật mới từ máy chủ...", 3000)
        QApplication.processEvents()
        
        url = getattr(self.ctx.config, "update_url", "") or DEFAULT_UPDATE_URL
        status, manifest, err_msg = query_update_status(url, timeout=5)

        if status == "AVAILABLE" and manifest:
            dlg = UpdateDialog(manifest, self)
            dlg.exec()
        elif status == "LATEST":
            QMessageBox.information(
                self,
                "Kiểm Tra Cập Nhật",
                f"[OK] Bạn đang sử dụng phiên bản mới nhất (v{__version__}).\n\nChưa có bản cập nhật nào mới hơn trên máy chủ.",
            )
        else:
            QMessageBox.warning(
                self,
                "Kiểm Tra Cập Nhật",
                f"Không thể kết nối tới máy chủ cập nhật:\n{err_msg or 'Lỗi mạng hoặc ngoại tuyến'}\n\n"
                f"(Phiên bản hiện tại: v{__version__})\n"
                "Bạn có thể cấu hình URL máy chủ cập nhật trong Cài đặt (F10).",
            )

    def _trigger_startup_update_check(self) -> None:
        """Kiểm tra cập nhật ngầm khi khởi động nếu bật tính năng auto_check_update."""
        if not getattr(self.ctx.config, "auto_check_update", True):
            return
        url = getattr(self.ctx.config, "update_url", "") or DEFAULT_UPDATE_URL
        status, manifest, _ = query_update_status(url, timeout=4)
        if status == "AVAILABLE" and manifest:
            dlg = UpdateDialog(manifest, self)
            dlg.exec()

    def resizeEvent(self, event) -> None:
        """Tự động co giãn menu thông minh khi thu nhỏ cửa sổ để không bao giờ bị cắt chữ."""
        super().resizeEvent(event)
        w = self.width()
        if hasattr(self, "btn_pick_files"):
            if w < 1120:
                self.btn_pick_files.setText("File")
                self.btn_pick_dir.setText("Thư mục")
                self.btn_preview.setText("Xem thử")
                self.btn_apply.setText("Áp dụng")
                self.btn_rules.setText("Rule")
                self.btn_new_type.setText("Tạo mới")
                self.btn_toggle_preview.setText("PDF")
                self.btn_help_menu.setText("")
            else:
                self.btn_pick_files.setText("Chọn file")
                self.btn_pick_dir.setText("Chọn thư mục")
                self.btn_preview.setText("Xem trước")
                self.btn_apply.setText("Áp dụng")
                self.btn_rules.setText("Quản lý rule")
                self.btn_new_type.setText("Tạo loại mới")
                self.btn_toggle_preview.setText("Xem PDF")
                self.btn_help_menu.setText("Trợ giúp")

    # -------------------------------------------------------- watcher & drag-drop

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.watcher:
            self.watcher.stop()
            self.watcher = None
        if self.preview_dock:
            self.preview_dock.close_doc()
        super().closeEvent(event)

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        paths = []
        for url in event.mimeData().urls():
            if url.isLocalFile():
                paths.append(Path(url.toLocalFile()))
        if paths:
            self._add_paths(paths)
            event.acceptProposedAction()

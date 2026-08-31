"""Cửa sổ chính: kéo-thả -> xem trước (sửa tay được) -> áp dụng.

Nguyên tắc giữ nguyên từ core: KHÔNG file nào được ghi ra đĩa trước khi người dùng bấm
"Áp dụng". Mọi việc nặng chạy ở luồng nền để cửa sổ không bị đơ.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QThread, Signal, Slot
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QDockWidget,
    QFileDialog,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QSplitter,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ..core.bootstrap import AppContext, RepeatFilter, quiet_noisy_libraries
from ..core.config import save_config
from ..core.learning import LearningStore
from ..core.models import FileJob, JobStatus
from ..core.mover import Mover, list_sessions, undo_session
from ..core.pipeline import BatchSummary, Pipeline, scan_pdfs
from ..core.report import default_report_name, write_report
from ..core.watcher import StableFileWatcher
from .correction_dialog import CorrectionRuleDialog
from .preview_model import COL_DEST, COL_OLD, FieldsModel, PreviewModel
from .qt_helpers import ElideDelegate
from .rule_builder_wizard import RuleBuilderWizard
from .rule_editor import RuleEditorDialog
from .settings_dialog import SettingsDialog
from .stats_dialog import StatsDialog

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------- logging


class _LogBridge(QObject):
    message = Signal(str)


class _WatchBridge(QObject):
    """Luồng watcher không được đụng vào widget — mọi thứ đi qua signal về luồng GUI."""

    processed = Signal(str)


class QtLogHandler(logging.Handler):
    """Đẩy log vào panel trong cửa sổ. Dùng signal để an toàn khi log từ luồng nền."""

    def __init__(self) -> None:
        super().__init__()
        self.bridge = _LogBridge()
        self.setFormatter(logging.Formatter("%(levelname)s  %(message)s"))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.bridge.message.emit(self.format(record))
        except Exception:
            pass


# -------------------------------------------------------------------- worker


class PlanWorker(QObject):
    """Chạy pipeline.plan() ở luồng nền."""

    progress = Signal(int, int, str)
    finished = Signal(list)
    failed = Signal(str)

    def __init__(self, pipeline: Pipeline, paths: list[Path], dry_run: bool) -> None:
        super().__init__()
        self.pipeline = pipeline
        self.paths = paths
        self.dry_run = dry_run

    @Slot()
    def run(self) -> None:
        try:
            jobs = self.pipeline.plan(
                self.paths,
                dry_run=self.dry_run,
                progress=lambda job, done, total: self.progress.emit(done, total, job.source.name),
            )
            self.finished.emit(jobs)
        except Exception as exc:
            logger.exception("Quét chứng từ thất bại")
            self.failed.emit(str(exc))


class ApplyWorker(QObject):
    """Chạy pipeline.apply() ở luồng nền."""

    progress = Signal(int, int, str)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, pipeline: Pipeline, jobs: list[FileJob]) -> None:
        super().__init__()
        self.pipeline = pipeline
        self.jobs = jobs

    @Slot()
    def run(self) -> None:
        try:
            summary = self.pipeline.apply(
                self.jobs,
                progress=lambda job, done, total: self.progress.emit(done, total, job.source.name),
            )
            self.finished.emit(summary)
        except Exception as exc:
            logger.exception("Áp dụng thất bại")
            self.failed.emit(str(exc))


# --------------------------------------------------------------------- window


class MainWindow(QMainWindow):
    def __init__(self, context: AppContext) -> None:
        super().__init__()
        self.ctx = context
        self.setWindowTitle("PDF Batch Renamer")
        self.resize(1280, 800)
        self.setAcceptDrops(True)

        self.pipeline: Pipeline | None = None
        self.thread: QThread | None = None
        self.worker: QObject | None = None
        self.pending_paths: list[Path] = []
        self.watcher: StableFileWatcher | None = None
        self.watch_pipeline: Pipeline | None = None
        self.watch_bridge = _WatchBridge()

        self._build_ui()
        self._build_actions()
        self._attach_log()
        self._update_actions()

    # ----------------------------------------------------------------- UI

    def _build_ui(self) -> None:
        self.preview_model = PreviewModel(rename_handler=self._rename_job)
        self.preview_model.jobEdited.connect(lambda _row: self._update_counts())
        self.preview_model.set_output_root(self.ctx.config.output_root)

        self.table = QTableView()
        self.table.setModel(self.preview_model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setAlternatingRowColors(True)
        # Cắt ở GIỮA: đầu tên (ngày, loại chứng từ) và đuôi (số, .pdf) đều còn nhìn được
        self.table.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(True)
        for column, width in enumerate((80, 220, 310, 220, 120, 200)):
            self.table.setColumnWidth(column, width)
        # Cột đường dẫn: cắt ĐẦU để giữ phần đuôi (…\output\2026-08-31) — chỗ có thông tin
        self._elide_left = ElideDelegate(Qt.TextElideMode.ElideLeft, self)
        self.table.setItemDelegateForColumn(COL_DEST, self._elide_left)
        self.table.setItemDelegateForColumn(COL_OLD, self._elide_left)
        self.table.selectionModel().selectionChanged.connect(self._on_row_selected)

        self.fields_model = FieldsModel()
        self.fields_model.fieldEdited.connect(self._on_field_edited)
        self.fields_table = QTableView()
        self.fields_table.setModel(self.fields_model)
        self.fields_table.verticalHeader().setVisible(False)
        self.fields_table.horizontalHeader().setStretchLastSection(True)

        self.detail_label = QLabel("Chọn 1 dòng để xem và sửa field.")
        self.detail_label.setWordWrap(True)

        detail = QWidget()
        detail_layout = QVBoxLayout(detail)
        detail_layout.setContentsMargins(6, 6, 6, 6)
        hint = QLabel("Sửa trực tiếp ở cột Giá trị")
        hint.setWordWrap(True)
        detail_layout.addWidget(hint)
        detail_layout.addWidget(self.fields_table, 1)
        detail_layout.addWidget(self.detail_label)

        # Panel field là dock: neo được cả PHẢI lẫn DƯỚI. Mặc định DƯỚI vì cột "Tên mới"
        # rất dài, bảng chính cần hết chiều ngang.
        self.field_dock = QDockWidget("Field trích được", self)
        self.field_dock.setObjectName("fieldDock")
        self.field_dock.setAllowedAreas(
            Qt.DockWidgetArea.RightDockWidgetArea | Qt.DockWidgetArea.BottomDockWidgetArea
        )
        self.field_dock.setWidget(detail)
        self.addDockWidget(self._configured_dock_area(), self.field_dock)
        self.field_dock.dockLocationChanged.connect(self._on_dock_moved)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(2000)

        main = QSplitter(Qt.Orientation.Vertical)
        main.addWidget(self.table)
        main.addWidget(self.log_view)
        main.setStretchFactor(0, 5)
        main.setStretchFactor(1, 1)
        self.setCentralWidget(main)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        self.progress.setMaximumWidth(240)
        self.counts = QLabel("Chưa có file nào.")
        self.statusBar().addPermanentWidget(self.progress)
        self.statusBar().addWidget(self.counts)

    def _build_actions(self) -> None:
        bar = self.addToolBar("Chính")
        bar.setMovable(False)

        self.act_files = QAction("Chọn file", self)
        self.act_files.triggered.connect(self._pick_files)
        self.act_folder = QAction("Chọn thư mục", self)
        self.act_folder.triggered.connect(self._pick_folder)
        self.act_clear = QAction("Xóa danh sách", self)
        self.act_clear.triggered.connect(self._clear)

        self.act_scan = QAction("Xem trước", self)
        self.act_scan.setShortcut(QKeySequence("F5"))
        self.act_scan.triggered.connect(self._start_plan)
        self.act_apply = QAction("Áp dụng", self)
        self.act_apply.setShortcut(QKeySequence("Ctrl+Return"))
        self.act_apply.triggered.connect(self._start_apply)
        self.act_cancel = QAction("Hủy", self)
        self.act_cancel.triggered.connect(self._cancel)
        self.act_undo = QAction("Hoàn tác phiên gần nhất", self)
        self.act_undo.triggered.connect(self._undo_last)

        self.act_rules = QAction("Tạo loại chứng từ…", self)
        self.act_rules.triggered.connect(self._open_rule_builder)
        self.act_manage_rules = QAction("Quản lý rule…", self)
        self.act_manage_rules.triggered.connect(self._open_rule_editor)
        self.act_settings = QAction("Cài đặt", self)
        self.act_settings.triggered.connect(self._open_settings)

        self.act_report = QAction("Xuất báo cáo…", self)
        self.act_report.triggered.connect(self._export_report)
        self.act_stats = QAction("Thống kê", self)
        self.act_stats.triggered.connect(self._open_stats)
        self.act_watch = QAction("Theo dõi thư mục", self)
        self.act_watch.setCheckable(True)
        self.act_watch.toggled.connect(self._toggle_watch)

        self.dry_run = QCheckBox("Dry-run (không ghi file)")

        for action in (self.act_files, self.act_folder, self.act_clear):
            bar.addAction(action)
        bar.addSeparator()
        bar.addAction(self.act_scan)
        bar.addAction(self.act_apply)
        bar.addAction(self.act_cancel)
        bar.addWidget(self.dry_run)
        bar.addSeparator()
        bar.addAction(self.act_report)
        bar.addAction(self.act_stats)
        bar.addAction(self.act_watch)
        bar.addSeparator()
        bar.addAction(self.act_undo)
        bar.addSeparator()
        bar.addAction(self.act_rules)
        bar.addAction(self.act_manage_rules)
        bar.addAction(self.act_settings)

    def _attach_log(self) -> None:
        self.watch_bridge.processed.connect(self._on_watch_processed)
        quiet_noisy_libraries()
        handler = QtLogHandler()
        handler.bridge.message.connect(self.log_view.appendPlainText)
        handler.setLevel(logging.INFO)
        # Gom dòng trùng: 1 file PDF hỏng font có thể đẻ ra hàng chục dòng giống hệt
        self._repeat_filter = RepeatFilter(max_repeats=1)
        handler.addFilter(self._repeat_filter)
        logging.getLogger().addHandler(handler)
        self._log_handler = handler

    # ------------------------------------------------------------- dock

    def _configured_dock_area(self) -> Qt.DockWidgetArea:
        area = (self.ctx.config.field_panel_area or "bottom").lower()
        return (
            Qt.DockWidgetArea.RightDockWidgetArea
            if area == "right"
            else Qt.DockWidgetArea.BottomDockWidgetArea
        )

    @Slot(Qt.DockWidgetArea)
    def _on_dock_moved(self, area: Qt.DockWidgetArea) -> None:
        """Nhớ vị trí người dùng chọn để lần sau mở lại đúng chỗ đó."""
        name = "right" if area == Qt.DockWidgetArea.RightDockWidgetArea else "bottom"
        if name == self.ctx.config.field_panel_area:
            return
        self.ctx.config.field_panel_area = name
        try:
            save_config(self.ctx.config)
        except Exception:
            logger.exception("Không lưu được vị trí panel field")

    # ------------------------------------------------------------ kéo thả

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        paths = [Path(url.toLocalFile()) for url in event.mimeData().urls() if url.isLocalFile()]
        if paths:
            self._add_paths(paths)
            event.acceptProposedAction()

    # ------------------------------------------------------------- nguồn

    def _add_paths(self, paths: list[Path]) -> None:
        self.pending_paths.extend(paths)
        found = scan_pdfs(self.pending_paths)
        self.counts.setText(f"Đã nạp {len(found)} file PDF. Bấm “Xem trước” để xử lý.")
        logger.info("Đã nạp %s file PDF từ %s đường dẫn", len(found), len(paths))
        self._update_actions()

    def _pick_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "Chọn file PDF", "", "PDF (*.pdf)")
        if files:
            self._add_paths([Path(f) for f in files])

    def _pick_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Chọn thư mục")
        if folder:
            self._add_paths([Path(folder)])

    def _clear(self) -> None:
        self.pending_paths.clear()
        self.preview_model.set_jobs([])
        self.fields_model.set_job(None)
        self._on_row_selected()
        self.counts.setText("Chưa có file nào.")
        self._update_actions()

    # -------------------------------------------------------------- chạy

    def _make_pipeline(self) -> Pipeline | None:
        config = self.ctx.config
        if not config.output_root:
            QMessageBox.warning(
                self, "Chưa cấu hình",
                "Chưa chọn thư mục output. Mở Cài đặt để chọn trước khi xử lý.",
            )
            self._open_settings()
            return None
        profiles = self.ctx.profiles
        if not profiles:
            QMessageBox.warning(
                self, "Chưa có rule",
                "Chưa có profile nào. Dùng “Tạo loại chứng từ…” để tạo rule đầu tiên.",
            )
            return None
        try:
            return Pipeline(config, profiles, self.ctx.db)
        except Exception as exc:
            QMessageBox.critical(self, "Không khởi tạo được", str(exc))
            return None

    def _start_plan(self) -> None:
        if self.thread is not None:
            return
        self._repeat_filter.reset()
        if not scan_pdfs(self.pending_paths):
            QMessageBox.information(self, "Chưa có file", "Kéo thả hoặc chọn file PDF trước.")
            return
        pipeline = self._make_pipeline()
        if pipeline is None:
            return

        self.pipeline = pipeline
        self.preview_model.set_output_root(self.ctx.config.output_root)
        worker = PlanWorker(pipeline, list(self.pending_paths), self.dry_run.isChecked())
        worker.finished.connect(self._on_plan_done)
        worker.failed.connect(self._on_worker_failed)
        self._run_worker(worker, "Đang đọc chứng từ…")

    def _start_apply(self) -> None:
        if self.thread is not None or self.pipeline is None:
            return
        jobs = self.preview_model.jobs
        if not jobs:
            return
        if self.dry_run.isChecked():
            QMessageBox.information(
                self, "Đang ở chế độ Dry-run",
                "Bỏ tick Dry-run rồi chạy lại “Xem trước” nếu bạn muốn ghi file thật.",
            )
            return

        ready = sum(1 for j in jobs if j.status == JobStatus.PENDING)
        errors = sum(1 for j in jobs if j.status == JobStatus.ERROR)
        mode = "CHUYỂN (move)" if self.ctx.config.mode == "move" else "sao chép (copy)"
        answer = QMessageBox.question(
            self, "Xác nhận áp dụng",
            f"Sẽ {mode} {ready} file sang thư mục output.\n"
            f"{errors} file lỗi sẽ được đưa vào thư mục cách ly _Loi kèm lý do.\n\nTiếp tục?",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        worker = ApplyWorker(self.pipeline, jobs)
        worker.finished.connect(self._on_apply_done)
        worker.failed.connect(self._on_worker_failed)
        self._run_worker(worker, "Đang ghi file…")

    def _run_worker(self, worker: QObject, message: str) -> None:
        self.thread = QThread(self)
        self.worker = worker
        worker.moveToThread(self.thread)
        self.thread.started.connect(worker.run)
        worker.progress.connect(self._on_progress)
        self.progress.setVisible(True)
        self.progress.setRange(0, 0)
        self.statusBar().showMessage(message)
        self._update_actions(busy=True)
        self.thread.start()

    def _finish_worker(self) -> None:
        if self.thread is not None:
            self.thread.quit()
            self.thread.wait(5000)
            self.thread = None
        self.worker = None
        self.progress.setVisible(False)
        self._update_actions()

    @Slot(int, int, str)
    def _on_progress(self, done: int, total: int, name: str) -> None:
        self.progress.setRange(0, total)
        self.progress.setValue(done)
        self.statusBar().showMessage(f"{done}/{total} — {name}")

    # Trần và sàn độ rộng từng cột sau khi co theo nội dung
    COLUMN_MAX_WIDTH = (110, 300, 420, 300, 160, 320)
    COLUMN_MIN_WIDTH = (70, 150, 220, 130, 90, 140)

    def _fit_columns(self) -> None:
        """Co cột theo nội dung thật của batch vừa nạp, nhưng có trần để bảng không vỡ."""
        self.table.resizeColumnsToContents()
        for column, limit in enumerate(self.COLUMN_MAX_WIDTH):
            width = self.table.columnWidth(column)
            floor = self.COLUMN_MIN_WIDTH[column]
            if width > limit:
                self.table.setColumnWidth(column, limit)
            elif width < floor:
                self.table.setColumnWidth(column, floor)

    def _select_row(self, row: int) -> None:
        """Chọn lại 1 dòng sau khi model bị reset — nếu không panel field sẽ trống trơn."""
        if not self.preview_model.jobs:
            self._on_row_selected()
            return
        row = max(0, min(row, len(self.preview_model.jobs) - 1))
        self.table.selectRow(row)
        self._on_row_selected()

    def _current_row(self) -> int:
        rows = self.table.selectionModel().selectedRows()
        return rows[0].row() if rows else 0

    @Slot(list)
    def _on_plan_done(self, jobs: list) -> None:
        self._finish_worker()
        self.preview_model.set_jobs(jobs)
        self._fit_columns()
        self._update_counts()
        self._select_row(0)
        warned = [j for j in jobs if j.warnings]
        if warned:
            names = ", ".join(j.source.name for j in warned[:3])
            logger.warning(
                "%s file có cảnh báo (cột “Ghi chú”, cột cuối bên phải của bảng): %s%s",
                len(warned), names, " …" if len(warned) > 3 else "",
            )

    @Slot(object)
    def _on_apply_done(self, summary: BatchSummary) -> None:
        self._finish_worker()
        row = self._current_row()
        self.preview_model.set_jobs(self.preview_model.jobs)
        self._update_counts()
        self._select_row(row)
        text = (
            f"Thành công {summary.success} · Trùng {summary.duplicate} · Lỗi {summary.errors}"
        )
        if summary.log_path:
            text += f"\n\nOperation log (dùng cho Hoàn tác):\n{summary.log_path}"
        QMessageBox.information(self, "Xong", text)
        self.pending_paths.clear()

    @Slot(str)
    def _on_worker_failed(self, message: str) -> None:
        self._finish_worker()
        QMessageBox.critical(self, "Lỗi", message)

    def _cancel(self) -> None:
        if self.pipeline is not None:
            self.pipeline.cancel()
            self.statusBar().showMessage("Đang hủy…")

    # ------------------------------------------------------------ sửa tay

    def _rename_job(self, job: FileJob, new_stem: str) -> None:
        if self.pipeline is None:
            return
        self.pipeline.rename_manually(job, new_stem)
        logger.info("Đổi tên thủ công: %s -> %s", job.source.name, job.new_name)

    @Slot()
    def _on_row_selected(self, *_args) -> None:
        job = self._current_job()
        self.fields_model.set_job(job)
        if job is None:
            self.detail_label.setText(
                "Chọn 1 dòng ở bảng bên trên để xem và sửa field."
                if self.preview_model.jobs
                else "Chưa có file nào trong danh sách."
            )
            return

        parts = []
        if not job.fields:
            profile = self.pipeline.profile_by_id(job.profile_id) if self.pipeline else None
            if profile is not None and profile.is_fallback:
                parts.append(
                    f"Profile {profile.name} không trích field — giữ nguyên tên gốc."
                )
            elif job.status == JobStatus.DUPLICATE:
                parts.append("File đã xử lý trước đó nên không chạy lại pipeline.")
            else:
                parts.append("Không trích được field nào từ chứng từ này.")

        parts.append(f"Nguồn: {job.source}")
        if job.layers_used:
            parts.append("Tầng đã dùng: " + ", ".join(x.label_vi for x in job.layers_used))
        if job.warnings:
            parts.append("Lưu ý: " + " · ".join(job.warnings))
        if job.message:
            parts.append(job.message)
        self.detail_label.setText("\n".join(parts))

    def _current_job(self) -> FileJob | None:
        rows = self.table.selectionModel().selectedRows()
        return self.preview_model.job_at(rows[0].row()) if rows else None

    @Slot(str, str, str)
    def _on_field_edited(self, name: str, old_value: str, new_value: str) -> None:
        """User sửa field trong Preview: dựng lại tên file và ghi nhận làm dữ liệu học."""
        job = self._current_job()
        if job is None or self.pipeline is None:
            return

        profile = self.pipeline.profile_by_id(job.profile_id)
        if profile is not None:
            if job.dest_dir and job.new_name:
                self.pipeline.mover.release(job.dest_dir, job.new_name)
            self.pipeline.build_name(job, profile, dry_run=True)

        correction_id = 0
        try:
            correction_id = self.pipeline.learning.record_correction(
                field_name=name,
                old_value=old_value,
                new_value=new_value,
                profile_id=job.profile_id,
                file_hash=job.file_hash,
                file_name=job.source.name,
                rule_version=profile.version if profile else 0,
                context=job.source.name,
            )
        except Exception:
            logger.exception("Không ghi được correction")

        rows = self.table.selectionModel().selectedRows()
        if rows:
            self.preview_model.refresh_row(rows[0].row())
        self.statusBar().showMessage(
            f"Đã ghi nhận chỉnh sửa “{name}”. Tên file mới: {job.new_name}", 6000
        )
        if profile is not None and correction_id:
            self._offer_rule_from_correction(profile, job, name, new_value, correction_id)

    def _offer_rule_from_correction(
        self, profile, job: FileJob, name: str, new_value: str, correction_id: int
    ) -> None:
        """Hỏi có muốn biến chỉnh sửa này thành rule không. Người dùng luôn có quyền từ chối."""
        answer = QMessageBox.question(
            self,
            "Tạo rule từ chỉnh sửa này?",
            f"Bạn vừa sửa “{name}” thành “{new_value}”.\n\n"
            "Muốn app tự lấy đúng giá trị này ở các file sau không?\n"
            "(App sẽ đề xuất cách tìm và chạy regression test, bạn duyệt rồi mới lưu.)",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        dialog = CorrectionRuleDialog(
            self.ctx.config, self.ctx.store, profile, job, name, new_value, self
        )
        if dialog.exec() != QDialog.DialogCode.Accepted or dialog.saved_profile is None:
            return

        # Rule đã được duyệt -> ghi correction thành dữ liệu học kèm text để tầng 5 dùng lại
        try:
            self.pipeline.learning.approve_correction(
                correction_id,
                text=dialog.document.text if dialog.document else "",
                fields={**job.field_values(), name: new_value},
                profile_id=job.profile_id,
                file_hash=job.file_hash,
                rule_version=dialog.saved_profile.version,
            )
        except Exception:
            logger.exception("Không ghi được dữ liệu học từ correction")
        self.statusBar().showMessage(
            f"Đã thêm cách tìm mới cho “{name}” vào profile "
            f"{dialog.saved_profile.name} (v{dialog.saved_profile.version}).",
            8000,
        )

    # ------------------------------------------------------------- công cụ

    def _undo_last(self) -> None:
        sessions = list_sessions()
        if not sessions:
            QMessageBox.information(self, "Không có gì để hoàn tác", "Chưa có phiên nào được ghi.")
            return
        latest = sessions[0]
        answer = QMessageBox.question(
            self, "Hoàn tác phiên gần nhất",
            f"Khôi phục lại phiên:\n{latest.name}\n\n"
            "File đã ghi ra output sẽ bị xóa; nếu chạy chế độ Move thì file gốc được trả về "
            "chỗ cũ. Tiếp tục?",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        undone, errors = undo_session(latest)
        message = f"Đã hoàn tác {undone} thao tác."
        if errors:
            message += "\n\nKhông hoàn tác được:\n" + "\n".join(errors[:10])
        QMessageBox.information(self, "Hoàn tác", message)
        logger.info("Hoàn tác phiên %s: %s thao tác, %s lỗi", latest.name, undone, len(errors))

    def _open_settings(self) -> None:
        dialog = SettingsDialog(self.ctx.config, self.ctx.profiles, self)
        if dialog.exec() == SettingsDialog.DialogCode.Accepted:
            logger.info("Đã lưu cài đặt")
            self.preview_model.set_output_root(self.ctx.config.output_root)
            self._cleanup_backups()
            self._update_actions()

    def _cleanup_backups(self) -> None:
        config = self.ctx.config
        if not config.output_root or config.backup_retention_days <= 0:
            return
        try:
            removed = Mover(config).cleanup_backups()
            if removed:
                logger.info("Đã dọn %s thư mục backup quá hạn", removed)
        except Exception:
            logger.exception("Dọn backup thất bại")

    # ------------------------------------------------------- báo cáo/thống kê

    def _export_report(self) -> None:
        jobs = self.preview_model.jobs
        if not jobs:
            return
        path, selected = QFileDialog.getSaveFileName(
            self,
            "Xuất báo cáo",
            default_report_name(),
            "CSV cho Excel (*.csv);;Excel (*.xlsx)",
        )
        if not path:
            return
        if selected.startswith("Excel") and not path.lower().endswith(".xlsx"):
            path += ".xlsx"
        try:
            written = write_report(path, jobs)
        except Exception as exc:
            logger.exception("Xuất báo cáo thất bại")
            QMessageBox.critical(self, "Lỗi", str(exc))
            return
        logger.info("Đã xuất báo cáo %s dòng: %s", len(jobs), written)
        QMessageBox.information(self, "Đã xuất báo cáo", str(written))

    def _open_stats(self) -> None:
        learning = self.pipeline.learning if self.pipeline else LearningStore(self.ctx.db)
        StatsDialog(learning, self.ctx.profiles, self).exec()

    # --------------------------------------------------------- watch folder

    def _toggle_watch(self, enabled: bool) -> None:
        if not enabled:
            self._stop_watch()
            return

        folder = self.ctx.config.watch.folder
        if not folder or not Path(folder).is_dir():
            QMessageBox.warning(
                self,
                "Chưa chọn thư mục theo dõi",
                "Mở Cài đặt > Watch folder để chọn thư mục trước.",
            )
            self.act_watch.setChecked(False)
            self._open_settings()
            return

        pipeline = self._make_pipeline()
        if pipeline is None:
            self.act_watch.setChecked(False)
            return

        self.watch_pipeline = pipeline
        try:
            self.watcher = StableFileWatcher(
                folder,
                self._handle_watched_file,
                stable_seconds=self.ctx.config.watch.stable_seconds,
            )
            self.watcher.start()
        except Exception as exc:
            logger.exception("Không bật được theo dõi thư mục")
            QMessageBox.critical(self, "Không bật được", str(exc))
            self.watcher = None
            self.act_watch.setChecked(False)
            return

        logger.info("Bắt đầu theo dõi thư mục %s", folder)
        self.statusBar().showMessage(f"Đang theo dõi: {folder}", 8000)

    def _stop_watch(self) -> None:
        if self.watcher is not None:
            self.watcher.stop()
            self.watcher = None
            logger.info("Đã dừng theo dõi thư mục")
        self.watch_pipeline = None

    def _handle_watched_file(self, path: Path) -> None:
        """Chạy trên LUỒNG WATCHER — không được đụng widget, chỉ phát signal."""
        pipeline = self.watch_pipeline
        if pipeline is None:
            return
        try:
            job = pipeline.plan_one(
                path, forced_profile=self.ctx.config.watch.pinned_profile or ""
            )
            pipeline.apply([job])
            self.watch_bridge.processed.emit(
                f"[{job.status.label_vi}] {path.name} -> {job.new_name or job.message}"
            )
        except Exception as exc:
            logger.exception("Xử lý file từ thư mục theo dõi thất bại: %s", path)
            self.watch_bridge.processed.emit(f"[Lỗi] {path.name}: {exc}")

    @Slot(str)
    def _on_watch_processed(self, message: str) -> None:
        logger.info("Watch folder: %s", message)
        self.statusBar().showMessage(message, 6000)

    def _open_rule_editor(self) -> None:
        learning = self.pipeline.learning if self.pipeline else LearningStore(self.ctx.db)
        dialog = RuleEditorDialog(self.ctx.config, self.ctx.store, learning, self)
        dialog.exec()
        logger.info("Đã đóng cửa sổ quản lý rule — %s profile", len(self.ctx.profiles))

    def _open_rule_builder(self) -> None:
        wizard = RuleBuilderWizard(self.ctx.config, self.ctx.store, self)
        if wizard.exec() == RuleBuilderWizard.DialogCode.Accepted and wizard.saved_profile:
            logger.info("Đã tạo profile mới: %s", wizard.saved_profile.name)
            self.statusBar().showMessage(
                f"Đã tạo profile “{wizard.saved_profile.name}”. Chạy lại Xem trước để áp dụng.",
                8000,
            )

    # ------------------------------------------------------------ trạng thái

    def _update_counts(self) -> None:
        jobs = self.preview_model.jobs
        if not jobs:
            self.counts.setText("Chưa có file nào.")
            return
        counts = {status: 0 for status in JobStatus}
        for job in jobs:
            counts[job.status] += 1
        self.counts.setText(
            " · ".join(
                f"{status.label_vi}: {n}" for status, n in counts.items() if n
            )
            + f"  (tổng {len(jobs)})"
        )

    def _update_actions(self, busy: bool = False) -> None:
        has_jobs = bool(self.preview_model.jobs)
        self.act_scan.setEnabled(not busy)
        self.act_apply.setEnabled(not busy and has_jobs and not self.dry_run.isChecked())
        self.act_cancel.setEnabled(busy)
        self.act_files.setEnabled(not busy)
        self.act_folder.setEnabled(not busy)
        self.act_clear.setEnabled(not busy)
        self.act_undo.setEnabled(not busy)
        self.act_rules.setEnabled(not busy)
        self.act_manage_rules.setEnabled(not busy)
        self.act_settings.setEnabled(not busy)
        self.act_report.setEnabled(not busy and has_jobs)
        self.act_stats.setEnabled(not busy)

    def closeEvent(self, event) -> None:
        self._stop_watch()
        if self.thread is not None:
            answer = QMessageBox.question(
                self, "Đang xử lý", "Vẫn còn việc đang chạy. Đóng app luôn?"
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            if self.pipeline is not None:
                self.pipeline.cancel()
            self._finish_worker()
        logging.getLogger().removeHandler(self._log_handler)
        super().closeEvent(event)

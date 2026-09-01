"""Hộp thoại Thông báo và Tải bản cập nhật mới (Modern Slim Fluent UI)."""

from __future__ import annotations
import tempfile
from pathlib import Path
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QProgressBar,
    QTextBrowser,
    QWidget,
    QMessageBox,
)
from src.core.updater import (
    UpdateManifest,
    download_update_file,
    apply_installer_update,
    apply_portable_update,
    is_running_as_frozen_installer,
)
from src.core.version import __version__
from src.ui.icons import get_app_icon


class _DownloadWorker(QThread):
    progress = Signal(int, int, float)  # downloaded, total, speed_mb
    completed = Signal(Path)
    failed = Signal(str)

    def __init__(self, asset_url: str, dest_path: Path, sha256: str) -> None:
        super().__init__()
        self.asset_url = asset_url
        self.dest_path = dest_path
        self.sha256 = sha256
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        success = download_update_file(
            self.asset_url,
            self.dest_path,
            expected_sha256=self.sha256,
            progress_callback=lambda d, t, s: self.progress.emit(d, t, s),
            cancel_flag=lambda: self._cancelled,
        )
        if success and not self._cancelled:
            self.completed.emit(self.dest_path)
        elif not self._cancelled:
            self.failed.emit("Tải file cập nhật hoặc xác thực mã băm SHA256 thất bại.")


class UpdateDialog(QDialog):
    """Hộp thoại hiển thị thông tin bản cập nhật mới và tiến trình tải về."""

    def __init__(self, manifest: UpdateManifest, parent=None) -> None:
        super().__init__(parent)
        self.manifest = manifest
        self.downloaded_path: Path | None = None
        self._worker: _DownloadWorker | None = None
        self.is_installer = is_running_as_frozen_installer()

        self.setWindowTitle("Đã có bản cập nhật mới")
        self.setWindowIcon(get_app_icon())
        self.resize(540, 420)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)

        # Header
        title_box = QWidget()
        title_lay = QVBoxLayout(title_box)
        title_lay.setContentsMargins(0, 0, 0, 0)
        title_lay.setSpacing(4)

        header_lbl = QLabel(f"Phiên bản mới: v{manifest.version}")
        header_lbl.setStyleSheet("font-size: 16px; font-weight: 700; color: #0284c7;")
        curr_lbl = QLabel(f"Phiên bản hiện tại: v{__version__}" + (f"  ·  Ngày phát hành: {manifest.release_date}" if manifest.release_date else ""))
        curr_lbl.setStyleSheet("font-size: 11.5px; color: #64748b;")

        title_lay.addWidget(header_lbl)
        title_lay.addWidget(curr_lbl)
        layout.addWidget(title_box)

        # Changelog browser
        changelog_title = QLabel("Những điểm mới & nâng cấp:")
        changelog_title.setStyleSheet("font-weight: 600; font-size: 12.5px;")
        layout.addWidget(changelog_title)

        self.browser = QTextBrowser()
        self.browser.setStyleSheet("background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px; padding: 8px;")
        html_lines = ["<ul style='margin-left: -15px; line-height: 1.5;'>"]
        for item in manifest.changelog:
            html_lines.append(f"<li style='margin-bottom: 4px;'>{item}</li>")
        html_lines.append("</ul>")
        self.browser.setHtml("".join(html_lines))
        layout.addWidget(self.browser, 1)

        # Progress bar (hidden initially)
        self.progress_container = QWidget()
        prog_lay = QVBoxLayout(self.progress_container)
        prog_lay.setContentsMargins(0, 0, 0, 0)
        prog_lay.setSpacing(4)
        self.lbl_progress = QLabel("Đang chuẩn bị tải...")
        self.lbl_progress.setStyleSheet("font-size: 11.5px; color: #64748b;")
        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(8)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        prog_lay.addWidget(self.lbl_progress)
        prog_lay.addWidget(self.progress_bar)
        self.progress_container.setVisible(False)
        layout.addWidget(self.progress_container)

        # Buttons
        self.btn_update = QPushButton("Cập nhật ngay")
        self.btn_update.setFixedHeight(32)
        self.btn_update.setMinimumWidth(120)
        self.btn_update.setProperty("variant", "primary")
        self.btn_update.clicked.connect(self._start_download)

        self.btn_later = QPushButton("Để sau")
        self.btn_later.setFixedHeight(32)
        self.btn_later.setMinimumWidth(80)
        self.btn_later.clicked.connect(self.reject)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        btn_row.addStretch(1)
        btn_row.addWidget(self.btn_later)
        btn_row.addWidget(self.btn_update)
        layout.addLayout(btn_row)

    def _start_download(self) -> None:
        asset = self.manifest.installer if self.is_installer else self.manifest.portable
        if not asset and self.manifest.installer:
            asset = self.manifest.installer
        elif not asset and self.manifest.portable:
            asset = self.manifest.portable

        if not asset or not asset.url:
            QMessageBox.warning(self, "Không tìm thấy liên kết", "Gói cập nhật chưa có đường dẫn tải về.")
            return

        ext = ".exe" if (asset.url.endswith(".exe") or self.is_installer) else ".zip"
        dest_path = Path(tempfile.gettempdir()) / f"PDFBatchRenamer_v{self.manifest.version}{ext}"

        self.btn_update.setEnabled(False)
        self.btn_update.setText("Đang tải...")
        self.btn_later.setText("Hủy")
        self.progress_container.setVisible(True)

        self._worker = _DownloadWorker(asset.url, dest_path, asset.sha256)
        self._worker.progress.connect(self._on_progress)
        self._worker.completed.connect(self._on_download_complete)
        self._worker.failed.connect(self._on_download_failed)
        self._worker.start()

    def _on_progress(self, downloaded: int, total: int, speed_mb: float) -> None:
        if total > 0:
            pct = int((downloaded / total) * 100)
            self.progress_bar.setValue(pct)
            mb_d = downloaded / (1024 * 1024)
            mb_t = total / (1024 * 1024)
            self.lbl_progress.setText(f"Đang tải: {mb_d:.1f}/{mb_t:.1f} MB ({pct}%)  ·  {speed_mb:.1f} MB/s")
        else:
            mb_d = downloaded / (1024 * 1024)
            self.lbl_progress.setText(f"Đang tải: {mb_d:.1f} MB  ·  {speed_mb:.1f} MB/s")

    def _on_download_complete(self, file_path: Path) -> None:
        self.downloaded_path = file_path
        self.lbl_progress.setText("Đã tải xong! Chuẩn bị nâng cấp...")
        self.progress_bar.setValue(100)

        reply = QMessageBox.question(
            self,
            "Sẵn sàng cài đặt",
            f"Đã tải xong bản cập nhật v{self.manifest.version}. Ứng dụng cần khởi động lại để hoàn tất nâng cấp. Bạn có muốn áp dụng ngay?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )

        if reply == QMessageBox.StandardButton.Yes:
            if file_path.suffix.lower() == ".exe":
                apply_installer_update(file_path)
            else:
                apply_portable_update(file_path)
            import sys
            from PySide6.QtWidgets import QApplication
            QApplication.quit()
            sys.exit(0)
        else:
            self.accept()

    def _on_download_failed(self, err: str) -> None:
        self.btn_update.setEnabled(True)
        self.btn_update.setText("Thử lại")
        self.lbl_progress.setText("Tải thất bại.")
        QMessageBox.critical(self, "Lỗi cập nhật", err)

    def reject(self) -> None:
        if self._worker and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait(1000)
        super().reject()

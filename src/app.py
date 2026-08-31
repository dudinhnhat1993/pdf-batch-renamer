"""Điểm vào GUI: python -m src.app (hoặc PDFBatchRenamer.exe sau khi build)."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

if __package__ in (None, ""):  # chạy trực tiếp: python src/app.py
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication, QMessageBox

from src.core.bootstrap import build_context, setup_logging

logger = logging.getLogger(__name__)


def main() -> int:
    setup_logging()
    app = QApplication(sys.argv)
    app.setApplicationName("PDF Batch Renamer")
    app.setOrganizationName("PDFBatchRenamer")

    try:
        context = build_context()
    except Exception as exc:
        logger.exception("Không khởi tạo được app")
        QMessageBox.critical(None, "Không khởi động được", str(exc))
        return 2

    from src.ui.main_window import MainWindow

    window = MainWindow(context)
    window.show()

    if not context.config.output_root:
        window.statusBar().showMessage(
            "Chưa chọn thư mục output — mở Cài đặt để chọn trước khi xử lý.", 10000
        )

    code = app.exec()
    context.close()
    return code


if __name__ == "__main__":
    sys.exit(main())

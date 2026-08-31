"""Dashboard 30 ngày: tỉ lệ match theo profile, để biết rule nào cần chỉnh.

Kèm 2 nút xuất dữ liệu học: dataset JSONL (fine-tune / few-shot) và danh sách correction.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from ..core.learning import LearningStore
from ..core.models import Profile
from ..core.report import ProfileStat, profile_stats

logger = logging.getLogger(__name__)

HEADERS = ["Profile", "Tổng file", "Thành công", "Trùng", "Lỗi", "Tỉ lệ thành công", "Nhận xét"]

HEALTH_COLORS = {
    "Tốt": "#1a7f37",
    "Cần để mắt": "#9a6700",
    "Nên chỉnh rule": "#cf222e",
}


class StatsDialog(QDialog):
    """Bảng thống kê + xuất dataset. Không sửa gì, chỉ đọc."""

    def __init__(self, learning: LearningStore, profiles: list[Profile], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Thống kê 30 ngày")
        self.resize(880, 560)
        self.learning = learning
        self.profiles = profiles

        self.period = QComboBox()
        for label, days in (("7 ngày", 7), ("30 ngày", 30), ("90 ngày", 90)):
            self.period.addItem(label, days)
        self.period.setCurrentIndex(1)
        self.period.currentIndexChanged.connect(self.reload)

        self.table = QTableWidget(0, len(HEADERS))
        self.table.setHorizontalHeaderLabels(HEADERS)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)

        self.summary = QLabel()
        self.summary.setWordWrap(True)

        export_dataset = QPushButton("Xuất dataset JSONL…")
        export_dataset.setToolTip(
            "Bộ (text, field chuẩn) đã qua chỉnh sửa của người dùng — dùng cho few-shot "
            "hoặc fine-tune sau này."
        )
        export_dataset.clicked.connect(self._export_dataset)

        top = QHBoxLayout()
        top.addWidget(QLabel("Khoảng thời gian:"))
        top.addWidget(self.period)
        top.addStretch(1)
        top.addWidget(export_dataset)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText("Đóng")
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.table, 1)
        layout.addWidget(self.summary)
        layout.addWidget(buttons)

        self.reload()

    # ---------------------------------------------------------------- dữ liệu

    def stats(self) -> list[ProfileStat]:
        names = {p.id: p.name for p in self.profiles}
        return profile_stats(self.learning, names, self.period.currentData())

    def reload(self) -> None:
        rows = self.stats()
        self.table.setRowCount(len(rows))
        for r, stat in enumerate(rows):
            values = [
                stat.profile_name,
                str(stat.total),
                str(stat.success),
                str(stat.duplicates),
                str(stat.errors),
                f"{stat.success_rate}%",
                stat.health,
            ]
            for c, value in enumerate(values):
                item = QTableWidgetItem(value)
                if c:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if c == len(values) - 1:
                    item.setForeground(QColor(HEALTH_COLORS.get(stat.health, "#57606a")))
                self.table.setItem(r, c, item)

        total = sum(s.total for s in rows)
        success = sum(s.success for s in rows)
        pending = len(self.learning.corrections(status="new"))
        if not total:
            self.summary.setText(
                "Chưa có dữ liệu trong khoảng này. Chạy một batch rồi quay lại xem."
            )
            return
        self.summary.setText(
            f"Tổng {total} file, thành công {success} ({round(success * 100 / total, 1)}%). "
            f"Có {pending} chỉnh sửa tay chưa được duyệt thành rule."
        )

    # ----------------------------------------------------------------- xuất

    def _export_dataset(self) -> None:
        from PySide6.QtWidgets import QFileDialog

        path, _ = QFileDialog.getSaveFileName(
            self, "Xuất dataset", "dataset.jsonl", "JSON Lines (*.jsonl)"
        )
        if not path:
            return
        try:
            count = self.learning.export_jsonl(Path(path))
        except Exception as exc:
            logger.exception("Xuất dataset thất bại")
            QMessageBox.critical(self, "Lỗi", str(exc))
            return
        QMessageBox.information(
            self, "Đã xuất", f"Đã ghi {count} dòng vào:\n{path}"
        )

"""Status badge painting for the queue table.

QSS cannot draw a pill inside a QTableView cell, so the badge is a delegate.
Colors come from theme_tokens.json — nothing is hardcoded here.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QStyle, QStyledItemDelegate

from src.ui.theme import Theme, qcolor

STATUS_ROLE = Qt.ItemDataRole.UserRole + 1

_NORM_MAP = {
    "pending": "PENDING",
    "chờ": "PENDING",
    "processing": "PROCESSING",
    "đang xử lý": "PROCESSING",
    "success": "SUCCESS",
    "thành công": "SUCCESS",
    "duplicate": "DUPLICATE",
    "trùng": "DUPLICATE",
    "trùng lặp": "DUPLICATE",
    "error": "ERROR",
    "lỗi": "ERROR",
}


class StatusBadgeDelegate(QStyledItemDelegate):
    H = 22
    PAD_X = 10
    RADIUS = 11

    def __init__(self, theme: Theme, parent=None) -> None:
        super().__init__(parent)
        self.theme = theme

    def _normalize_code(self, raw: any) -> str:
        if hasattr(raw, "value"):
            raw = raw.value
        s = str(raw or "").strip().lower()
        return _NORM_MAP.get(s, s.upper() or "PENDING")

    def paint(self, painter: QPainter, option, index) -> None:
        raw_code = index.data(STATUS_ROLE)
        if raw_code is None:
            raw_code = index.data(Qt.ItemDataRole.DisplayRole)
        code = self._normalize_code(raw_code)
        spec = self.theme.status(code)

        opt = option
        if opt.state & QStyle.StateFlag.State_HasFocus:
            opt.state &= ~QStyle.StateFlag.State_HasFocus

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

        font = QFont(painter.font())
        font.setPointSizeF(8.5)
        font.setBold(True)
        painter.setFont(font)

        text = spec.get("label", code)
        fm = painter.fontMetrics()
        w = max(58, fm.horizontalAdvance(text) + self.PAD_X * 2)
        r = QRectF(
            opt.rect.left() + 8,
            opt.rect.center().y() - self.H / 2,
            w,
            self.H,
        )

        path = QPainterPath()
        path.addRoundedRect(r, self.RADIUS, self.RADIUS)
        painter.fillPath(path, qcolor(spec["bg"]))
        painter.setPen(QPen(qcolor(spec["border"]), 1))
        painter.drawPath(path)

        painter.setPen(qcolor(spec["fg"]))
        painter.drawText(r, Qt.AlignmentFlag.AlignCenter, text)
        painter.restore()

    def sizeHint(self, option, index) -> QSize:
        row_h = self.theme.metric("table_row_height") or 38
        return QSize(96, row_h)

"""Status badge painting for the queue table.

QSS cannot draw a pill inside a QTableView cell, so the badge is a delegate.
Colors come from theme_tokens.json — nothing is hardcoded here.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QStyle, QStyledItemDelegate

from src.ui.theme import Theme, qcolor

STATUS_ROLE = Qt.UserRole + 1  # store "PENDING" / "SUCCESS" / ... on the item


class StatusBadgeDelegate(QStyledItemDelegate):
    H = 20
    PAD_X = 9
    RADIUS = 10

    def __init__(self, theme: Theme, parent=None) -> None:
        super().__init__(parent)
        self.theme = theme

    def paint(self, painter: QPainter, option, index) -> None:
        code = index.data(STATUS_ROLE) or "PENDING"
        spec = self.theme.status(code)

        # row background (selection / error tint) is drawn by the view's QSS,
        # so only clear the focus rect here.
        opt = option
        if opt.state & QStyle.State_HasFocus:
            opt.state &= ~QStyle.State_HasFocus

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)

        font = QFont(painter.font())
        font.setPointSizeF(8.5)
        font.setWeight(QFont.DemiBold)
        painter.setFont(font)

        text = spec["label"]
        w = painter.fontMetrics().horizontalAdvance(text) + self.PAD_X * 2
        r = QRectF(opt.rect.left() + 10,
                   opt.rect.center().y() - self.H / 2,
                   w, self.H)

        path = QPainterPath()
        path.addRoundedRect(r, self.RADIUS, self.RADIUS)
        painter.fillPath(path, qcolor(spec["bg"]))
        painter.setPen(QPen(qcolor(spec["border"]), 1))
        painter.drawPath(path)

        painter.setPen(qcolor(spec["fg"]))
        painter.drawText(r, Qt.AlignCenter, text)
        painter.restore()

    def sizeHint(self, option, index) -> QSize:
        return QSize(104, self.theme.metric("table_row_height"))

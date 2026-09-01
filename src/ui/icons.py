"""Bộ Icon vector sắc nét, phong cách Modern Fluent / Lucide UI."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QIcon,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)

from src.core.config import assets_dir


def _create_pixmap(size: int = 48) -> tuple[QPixmap, QPainter]:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    return pixmap, painter


def make_app_icon(size: int = 256) -> QIcon:
    pixmap, p = _create_pixmap(size)
    s = size / 100.0

    # 1. Thân tài liệu PDF
    doc = QPainterPath()
    doc.moveTo(20 * s, 10 * s)
    doc.lineTo(60 * s, 10 * s)
    doc.lineTo(80 * s, 30 * s)
    doc.lineTo(80 * s, 90 * s)
    doc.lineTo(20 * s, 90 * s)
    doc.closeSubpath()

    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(QColor("#E11D48")))  # Crimson
    p.drawPath(doc)

    # 2. Góc gấp tài liệu
    fold = QPainterPath()
    fold.moveTo(60 * s, 10 * s)
    fold.lineTo(60 * s, 30 * s)
    fold.lineTo(80 * s, 30 * s)
    fold.closeSubpath()
    p.setBrush(QBrush(QColor("#FDA4AF")))  # Rose light
    p.drawPath(fold)

    # 3. Chữ PDF
    font = QFont("Arial", int(14 * s), QFont.Weight.Black)
    p.setFont(font)
    p.setPen(QColor("#FFFFFF"))
    p.drawText(QRectF(22 * s, 34 * s, 56 * s, 24 * s), Qt.AlignmentFlag.AlignCenter, "PDF")

    # 4. Huy hiệu Rename (Amber Badge)
    p.setBrush(QBrush(QColor("#F59E0B")))  # Amber
    p.setPen(QPen(QColor("#FFFFFF"), 3 * s))
    p.drawRoundedRect(QRectF(38 * s, 56 * s, 50 * s, 34 * s), 6 * s, 6 * s)

    # Mũi tên rename A -> B
    p.setPen(QPen(QColor("#FFFFFF"), 3 * s, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    p.drawLine(QPointF(46 * s, 73 * s), QPointF(78 * s, 73 * s))
    p.drawLine(QPointF(70 * s, 65 * s), QPointF(78 * s, 73 * s))
    p.drawLine(QPointF(70 * s, 81 * s), QPointF(78 * s, 73 * s))

    p.end()
    return QIcon(pixmap)


def make_file_add_icon(size: int = 48) -> QIcon:
    """Modern Lucide File-Plus."""
    pixmap, p = _create_pixmap(size)
    s = size / 24.0

    # Trang tài liệu mềm mại
    doc = QPainterPath()
    doc.moveTo(14 * s, 2 * s)
    doc.lineTo(6 * s, 2 * s)
    doc.quadTo(4 * s, 2 * s, 4 * s, 4 * s)
    doc.lineTo(4 * s, 20 * s)
    doc.quadTo(4 * s, 22 * s, 6 * s, 22 * s)
    doc.lineTo(18 * s, 22 * s)
    doc.quadTo(20 * s, 22 * s, 20 * s, 20 * s)
    doc.lineTo(20 * s, 8 * s)
    doc.lineTo(14 * s, 2 * s)

    p.setPen(QPen(QColor("#0284C7"), 1.8 * s, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    p.setBrush(QBrush(QColor("#F0F9FF")))
    p.drawPath(doc)

    # Góc gấp
    p.drawLine(QPointF(14 * s, 2 * s), QPointF(14 * s, 8 * s))
    p.drawLine(QPointF(14 * s, 8 * s), QPointF(20 * s, 8 * s))

    # Dấu +
    p.setPen(QPen(QColor("#0284C7"), 2.2 * s, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.drawLine(QPointF(12 * s, 12 * s), QPointF(12 * s, 18 * s))
    p.drawLine(QPointF(9 * s, 15 * s), QPointF(15 * s, 15 * s))

    p.end()
    return QIcon(pixmap)


def make_folder_add_icon(size: int = 48) -> QIcon:
    """Modern Lucide Folder."""
    pixmap, p = _create_pixmap(size)
    s = size / 24.0

    folder = QPainterPath()
    folder.moveTo(4 * s, 20 * s)
    folder.lineTo(20 * s, 20 * s)
    folder.quadTo(22 * s, 20 * s, 22 * s, 18 * s)
    folder.lineTo(22 * s, 9 * s)
    folder.quadTo(22 * s, 7 * s, 20 * s, 7 * s)
    folder.lineTo(12 * s, 7 * s)
    folder.lineTo(10 * s, 4.5 * s)
    folder.quadTo(9 * s, 4 * s, 8 * s, 4 * s)
    folder.lineTo(4 * s, 4 * s)
    folder.quadTo(2 * s, 4 * s, 2 * s, 6 * s)
    folder.lineTo(2 * s, 18 * s)
    folder.quadTo(2 * s, 20 * s, 4 * s, 20 * s)

    p.setPen(QPen(QColor("#D97706"), 1.8 * s, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    p.setBrush(QBrush(QColor("#FFFBEB")))
    p.drawPath(folder)

    # Chi tiết dòng folder
    p.drawLine(QPointF(2 * s, 9 * s), QPointF(22 * s, 9 * s))

    p.end()
    return QIcon(pixmap)


def make_clear_icon(size: int = 48) -> QIcon:
    """Modern Lucide Trash."""
    pixmap, p = _create_pixmap(size)
    s = size / 24.0

    p.setPen(QPen(QColor("#EF4444"), 1.8 * s, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    p.setBrush(Qt.BrushStyle.NoBrush)

    # Thân thùng rác
    body = QPainterPath()
    body.moveTo(5 * s, 6 * s)
    body.lineTo(6 * s, 19 * s)
    body.quadTo(6 * s, 21 * s, 8 * s, 21 * s)
    body.lineTo(16 * s, 21 * s)
    body.quadTo(18 * s, 21 * s, 18 * s, 19 * s)
    body.lineTo(19 * s, 6 * s)
    p.drawPath(body)

    # Nắp & Tay cầm
    p.drawLine(QPointF(3 * s, 6 * s), QPointF(21 * s, 6 * s))
    p.drawLine(QPointF(9 * s, 6 * s), QPointF(9 * s, 3.5 * s))
    p.drawLine(QPointF(9 * s, 3.5 * s), QPointF(15 * s, 3.5 * s))
    p.drawLine(QPointF(15 * s, 3.5 * s), QPointF(15 * s, 6 * s))

    # Khe rãnh
    p.drawLine(QPointF(10 * s, 10 * s), QPointF(10 * s, 17 * s))
    p.drawLine(QPointF(14 * s, 10 * s), QPointF(14 * s, 17 * s))

    p.end()
    return QIcon(pixmap)


def make_scan_icon(size: int = 48) -> QIcon:
    """Modern Search / Preview."""
    pixmap, p = _create_pixmap(size)
    s = size / 24.0

    p.setPen(QPen(QColor("#0284C7"), 2.0 * s, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    p.setBrush(QBrush(QColor("#F0F9FF")))
    p.drawEllipse(QRectF(3.5 * s, 3.5 * s, 12 * s, 12 * s))

    p.setPen(QPen(QColor("#0284C7"), 2.5 * s, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.drawLine(QPointF(12.5 * s, 12.5 * s), QPointF(20.5 * s, 20.5 * s))

    p.end()
    return QIcon(pixmap)


def make_apply_icon(size: int = 48) -> QIcon:
    """Modern Lucide Play / Apply."""
    pixmap, p = _create_pixmap(size)
    s = size / 24.0

    play = QPainterPath()
    play.moveTo(7 * s, 4 * s)
    play.lineTo(19 * s, 12 * s)
    play.lineTo(7 * s, 20 * s)
    play.closeSubpath()

    p.setPen(QPen(QColor("#10B981"), 1.8 * s, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    p.setBrush(QBrush(QColor("#ECFDF5")))
    p.drawPath(play)

    p.end()
    return QIcon(pixmap)


def make_cancel_icon(size: int = 48) -> QIcon:
    """Modern Lucide Square / Stop."""
    pixmap, p = _create_pixmap(size)
    s = size / 24.0

    p.setPen(QPen(QColor("#EF4444"), 1.8 * s, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    p.setBrush(QBrush(QColor(239, 68, 68, 35)))
    p.drawRoundedRect(QRectF(6 * s, 6 * s, 12 * s, 12 * s), 2.0 * s, 2.0 * s)

    p.end()
    return QIcon(pixmap)


def make_undo_icon(size: int = 48) -> QIcon:
    """Modern Lucide Rotate-CCW / Undo."""
    pixmap, p = _create_pixmap(size)
    s = size / 24.0

    p.setPen(QPen(QColor("#8B5CF6"), 2.0 * s, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    p.setBrush(Qt.BrushStyle.NoBrush)

    arc = QPainterPath()
    arc.arcMoveTo(QRectF(4 * s, 5 * s, 16 * s, 16 * s), 0)
    arc.arcTo(QRectF(4 * s, 5 * s, 16 * s, 16 * s), 0, 220)
    p.drawPath(arc)

    # Mũi tên
    p.drawLine(QPointF(3 * s, 12 * s), QPointF(7.5 * s, 7.5 * s))
    p.drawLine(QPointF(3 * s, 12 * s), QPointF(8.5 * s, 14 * s))

    p.end()
    return QIcon(pixmap)


def make_manage_rules_icon(size: int = 48) -> QIcon:
    """Modern Lucide List-Checks / Rule Manager."""
    pixmap, p = _create_pixmap(size)
    s = size / 24.0

    p.setPen(QPen(QColor("#0D9488"), 1.8 * s, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    p.setBrush(Qt.BrushStyle.NoBrush)

    # Dòng 1 check
    p.drawLine(QPointF(3 * s, 6 * s), QPointF(5 * s, 8 * s))
    p.drawLine(QPointF(5 * s, 8 * s), QPointF(8.5 * s, 4.5 * s))
    p.drawLine(QPointF(11 * s, 6 * s), QPointF(21 * s, 6 * s))

    # Dòng 2 check
    p.drawLine(QPointF(3 * s, 12 * s), QPointF(5 * s, 14 * s))
    p.drawLine(QPointF(5 * s, 14 * s), QPointF(8.5 * s, 10.5 * s))
    p.drawLine(QPointF(11 * s, 12 * s), QPointF(21 * s, 12 * s))

    # Dòng 3 check
    p.drawLine(QPointF(3 * s, 18 * s), QPointF(5 * s, 20 * s))
    p.drawLine(QPointF(5 * s, 20 * s), QPointF(8.5 * s, 16.5 * s))
    p.drawLine(QPointF(11 * s, 18 * s), QPointF(21 * s, 18 * s))

    p.end()
    return QIcon(pixmap)


def make_wizard_icon(size: int = 48) -> QIcon:
    """Modern Lucide Wand-2 / Magic."""
    pixmap, p = _create_pixmap(size)
    s = size / 24.0

    p.setPen(QPen(QColor("#6366F1"), 2.0 * s, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    p.setBrush(Qt.BrushStyle.NoBrush)

    # Cây đũa
    p.drawLine(QPointF(3.5 * s, 20.5 * s), QPointF(15.5 * s, 8.5 * s))

    # Tia sáng 1
    p.drawLine(QPointF(19 * s, 2 * s), QPointF(19 * s, 6 * s))
    p.drawLine(QPointF(17 * s, 4 * s), QPointF(21 * s, 4 * s))

    # Tia sáng 2
    p.drawLine(QPointF(9 * s, 2 * s), QPointF(9 * s, 4 * s))
    p.drawLine(QPointF(8 * s, 3 * s), QPointF(10 * s, 3 * s))

    # Tia sáng 3
    p.drawLine(QPointF(21 * s, 11 * s), QPointF(21 * s, 13 * s))
    p.drawLine(QPointF(20 * s, 12 * s), QPointF(22 * s, 12 * s))

    p.end()
    return QIcon(pixmap)


def make_panel_right_icon(size: int = 48) -> QIcon:
    """Modern Lucide Panel-Right."""
    pixmap, p = _create_pixmap(size)
    s = size / 24.0

    p.setPen(QPen(QColor("#0284C7"), 1.8 * s, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    p.setBrush(QBrush(QColor("#F0F9FF")))
    p.drawRoundedRect(QRectF(3 * s, 3 * s, 18 * s, 18 * s), 3 * s, 3 * s)

    p.setPen(QPen(QColor("#0284C7"), 1.8 * s, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.drawLine(QPointF(15 * s, 3 * s), QPointF(15 * s, 21 * s))

    p.end()
    return QIcon(pixmap)


def make_theme_icon(size: int = 48) -> QIcon:
    """Modern Lucide Sun-Medium / Theme."""
    pixmap, p = _create_pixmap(size)
    s = size / 24.0

    p.setPen(QPen(QColor("#F59E0B"), 2.0 * s, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.setBrush(QBrush(QColor("#FEF3C7")))
    p.drawEllipse(QRectF(7 * s, 7 * s, 10 * s, 10 * s))

    # Tia nắng
    p.drawLine(QPointF(12 * s, 2 * s), QPointF(12 * s, 4 * s))
    p.drawLine(QPointF(12 * s, 20 * s), QPointF(12 * s, 22 * s))
    p.drawLine(QPointF(2 * s, 12 * s), QPointF(4 * s, 12 * s))
    p.drawLine(QPointF(20 * s, 12 * s), QPointF(22 * s, 12 * s))

    p.end()
    return QIcon(pixmap)


def make_settings_icon(size: int = 48) -> QIcon:
    """Modern Lucide Settings / Gear."""
    pixmap, p = _create_pixmap(size)
    s = size / 24.0

    p.setPen(QPen(QColor("#475569"), 1.8 * s, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    p.setBrush(Qt.BrushStyle.NoBrush)

    # Vòng tròn trong
    p.drawEllipse(QRectF(8.5 * s, 8.5 * s, 7 * s, 7 * s))

    # Bánh răng ngoài
    gear = QPainterPath()
    gear.moveTo(10.5 * s, 2.5 * s)
    gear.lineTo(13.5 * s, 2.5 * s)
    gear.lineTo(14 * s, 5 * s)
    gear.lineTo(16 * s, 5.8 * s)
    gear.lineTo(18 * s, 4 * s)
    gear.lineTo(20 * s, 6 * s)
    gear.lineTo(18.2 * s, 8 * s)
    gear.lineTo(19 * s, 10 * s)
    gear.lineTo(21.5 * s, 10.5 * s)
    gear.lineTo(21.5 * s, 13.5 * s)
    gear.lineTo(19 * s, 14 * s)
    gear.lineTo(18.2 * s, 16 * s)
    gear.lineTo(20 * s, 18 * s)
    gear.lineTo(18 * s, 20 * s)
    gear.lineTo(16 * s, 18.2 * s)
    gear.lineTo(14 * s, 19 * s)
    gear.lineTo(13.5 * s, 21.5 * s)
    gear.lineTo(10.5 * s, 21.5 * s)
    gear.lineTo(10 * s, 19 * s)
    gear.lineTo(8 * s, 18.2 * s)
    gear.lineTo(6 * s, 20 * s)
    gear.lineTo(4 * s, 18 * s)
    gear.lineTo(5.8 * s, 16 * s)
    gear.lineTo(5 * s, 14 * s)
    gear.lineTo(2.5 * s, 13.5 * s)
    gear.lineTo(2.5 * s, 10.5 * s)
    gear.lineTo(5 * s, 10 * s)
    gear.lineTo(5.8 * s, 8 * s)
    gear.lineTo(4 * s, 6 * s)
    gear.lineTo(6 * s, 4 * s)
    gear.lineTo(8 * s, 5.8 * s)
    gear.lineTo(10 * s, 5 * s)
    gear.closeSubpath()
    p.drawPath(gear)

    p.end()
    return QIcon(pixmap)


def make_help_icon(size: int = 48) -> QIcon:
    """Modern Lucide Lightbulb / Help."""
    pixmap, p = _create_pixmap(size)
    s = size / 24.0

    p.setPen(QPen(QColor("#D97706"), 1.8 * s, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    p.setBrush(QBrush(QColor("#FEF3C7")))

    bulb = QPainterPath()
    bulb.moveTo(9 * s, 18 * s)
    bulb.lineTo(15 * s, 18 * s)
    bulb.lineTo(15 * s, 16 * s)
    bulb.quadTo(19 * s, 13 * s, 19 * s, 9 * s)
    bulb.quadTo(19 * s, 4 * s, 12 * s, 4 * s)
    bulb.quadTo(5 * s, 4 * s, 5 * s, 9 * s)
    bulb.quadTo(5 * s, 13 * s, 9 * s, 16 * s)
    bulb.closeSubpath()
    p.drawPath(bulb)

    # Đuôi bóng đèn
    p.drawLine(QPointF(10 * s, 21 * s), QPointF(14 * s, 21 * s))

    p.end()
    return QIcon(pixmap)


def make_refresh_icon(size: int = 48) -> QIcon:
    """Modern Lucide Refresh-CW / Update."""
    pixmap, p = _create_pixmap(size)
    s = size / 24.0

    p.setPen(QPen(QColor("#0284C7"), 2.0 * s, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    p.setBrush(Qt.BrushStyle.NoBrush)

    # Cung trên
    arc1 = QPainterPath()
    arc1.arcMoveTo(QRectF(3 * s, 3 * s, 18 * s, 18 * s), 45)
    arc1.arcTo(QRectF(3 * s, 3 * s, 18 * s, 18 * s), 45, 130)
    p.drawPath(arc1)
    p.drawLine(QPointF(20 * s, 4 * s), QPointF(20 * s, 9 * s))
    p.drawLine(QPointF(20 * s, 9 * s), QPointF(15 * s, 9 * s))

    # Cung dưới
    arc2 = QPainterPath()
    arc2.arcMoveTo(QRectF(3 * s, 3 * s, 18 * s, 18 * s), 225)
    arc2.arcTo(QRectF(3 * s, 3 * s, 18 * s, 18 * s), 225, 130)
    p.drawPath(arc2)
    p.drawLine(QPointF(4 * s, 20 * s), QPointF(4 * s, 15 * s))
    p.drawLine(QPointF(4 * s, 15 * s), QPointF(9 * s, 15 * s))

    p.end()
    return QIcon(pixmap)


def make_info_icon(size: int = 48) -> QIcon:
    """Modern Lucide Info / About."""
    pixmap, p = _create_pixmap(size)
    s = size / 24.0

    p.setPen(QPen(QColor("#0284C7"), 1.8 * s, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    p.setBrush(QBrush(QColor("#F0F9FF")))
    p.drawEllipse(QRectF(3 * s, 3 * s, 18 * s, 18 * s))

    p.setPen(QPen(QColor("#0284C7"), 2.2 * s, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.drawLine(QPointF(12 * s, 11 * s), QPointF(12 * s, 16.5 * s))
    p.drawLine(QPointF(12 * s, 7.5 * s), QPointF(12 * s, 8 * s))

    p.end()
    return QIcon(pixmap)


def make_chart_icon(size: int = 48) -> QIcon:
    """Modern Lucide Bar-Chart-3 / Stats."""
    pixmap, p = _create_pixmap(size)
    s = size / 24.0

    p.setPen(QPen(QColor("#0D9488"), 2.0 * s, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.setBrush(Qt.BrushStyle.NoBrush)

    p.drawLine(QPointF(18 * s, 20 * s), QPointF(18 * s, 10 * s))
    p.drawLine(QPointF(12 * s, 20 * s), QPointF(12 * s, 4 * s))
    p.drawLine(QPointF(6 * s, 20 * s), QPointF(6 * s, 14 * s))

    p.end()
    return QIcon(pixmap)


def make_help_menu_icon(size: int = 48) -> QIcon:
    """Modern Help Circle for menu dropdown."""
    pixmap, p = _create_pixmap(size)
    s = size / 24.0

    p.setPen(QPen(QColor("#0284C7"), 1.8 * s, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    p.setBrush(QBrush(QColor("#F0F9FF")))
    p.drawEllipse(QRectF(3 * s, 3 * s, 18 * s, 18 * s))

    p.setPen(QPen(QColor("#0284C7"), 1.8 * s, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    q = QPainterPath()
    q.moveTo(9.5 * s, 9 * s)
    q.quadTo(9.5 * s, 6.5 * s, 12 * s, 6.5 * s)
    q.quadTo(14.5 * s, 6.5 * s, 14.5 * s, 9 * s)
    q.quadTo(14.5 * s, 11 * s, 12 * s, 12 * s)
    q.lineTo(12 * s, 14 * s)
    p.drawPath(q)

    p.setPen(QPen(QColor("#0284C7"), 2.2 * s, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.drawLine(QPointF(12 * s, 17 * s), QPointF(12 * s, 17.5 * s))

    p.end()
    return QIcon(pixmap)


_ICON_REGISTRY = {
    "app": make_app_icon,
    "file-plus": make_file_add_icon,
    "folder": make_folder_add_icon,
    "trash": make_clear_icon,
    "search": make_scan_icon,
    "play": make_apply_icon,
    "stop": make_cancel_icon,
    "rotate-ccw": make_undo_icon,
    "checklist": make_manage_rules_icon,
    "wand": make_wizard_icon,
    "panel-right": make_panel_right_icon,
    "theme": make_theme_icon,
    "gear": make_settings_icon,
    "bulb": make_help_icon,
    "refresh": make_refresh_icon,
    "info": make_info_icon,
    "chart": make_chart_icon,
    "help-menu": make_help_menu_icon,
}


def get_icon(name: str, size: int = 48) -> QIcon:
    factory = _ICON_REGISTRY.get(name)
    if factory:
        return factory(size)
    return make_app_icon(size)


def get_app_icon() -> QIcon:
    ico_path = assets_dir() / "app_icon.ico"
    if ico_path.exists():
        return QIcon(str(ico_path))
    return make_app_icon()

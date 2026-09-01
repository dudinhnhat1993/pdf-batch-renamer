"""Tiện ích dùng chung cho tầng GUI: đổi ảnh PIL sang Qt, màu theo theme, icon chữ."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPixmap
from PySide6.QtWidgets import QStyledItemDelegate

# Màu trạng thái, chọn theo nghĩa chứ không theo thẩm mỹ: xanh = xong, đỏ = cần người xử lý
STATUS_COLORS = {
    "pending": ("#1f6feb", "#8ab4f8"),
    "processing": ("#8250df", "#d2a8ff"),
    "success": ("#1a7f37", "#7ee787"),
    "duplicate": ("#9a6700", "#e3b341"),
    "error": ("#cf222e", "#ff7b72"),
}


def is_dark_theme() -> bool:
    """Windows đang ở dark mode hay không (Qt 6.5+ báo qua colorScheme)."""
    try:
        return QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
    except Exception:
        return False


def status_color(status_value: str) -> QColor:
    dark, light = STATUS_COLORS.get(status_value, ("#57606a", "#8b949e"))
    return QColor(light if is_dark_theme() else dark)


def pil_to_qimage(image) -> QImage:
    """Đổi ảnh PIL (RGB) sang QImage, copy dữ liệu để không phụ thuộc buffer gốc."""
    rgb = image if image.mode == "RGB" else image.convert("RGB")
    data = rgb.tobytes("raw", "RGB")
    qimage = QImage(data, rgb.width, rgb.height, rgb.width * 3, QImage.Format.Format_RGB888)
    return qimage.copy()


def pil_to_qpixmap(image) -> QPixmap:
    return QPixmap.fromImage(pil_to_qimage(image))


def elide(text: str, limit: int = 60) -> str:
    """Rút gọn chuỗi dài để bảng không bị giãn."""
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


class ElideDelegate(QStyledItemDelegate):
    """Cắt chữ theo kiểu riêng cho từng cột.

    QTableView chỉ có 1 kiểu cắt chung, nhưng cột đường dẫn cần cắt ĐẦU (giữ phần đuôi
    ...\\output\2026-08-31) còn cột tên file cần cắt GIỮA (giữ cả ngày lẫn đuôi .pdf).
    """

    def __init__(self, mode: Qt.TextElideMode, parent=None) -> None:
        super().__init__(parent)
        self.mode = mode

    def initStyleOption(self, option, index) -> None:
        super().initStyleOption(option, index)
        option.textElideMode = self.mode


def open_in_explorer(path: Path | str) -> bool:
    """Mo file hoac thu muc trong File Explorer cua he dieu hanh."""
    import os
    import sys

    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QDesktopServices

    p = Path(path)
    if not p.exists():
        if p.parent.exists():
            p = p.parent
        else:
            return False

    try:
        if sys.platform.startswith("win"):
            os.startfile(str(p))
            return True
        else:
            return QDesktopServices.openUrl(QUrl.fromLocalFile(str(p)))
    except Exception:
        return False

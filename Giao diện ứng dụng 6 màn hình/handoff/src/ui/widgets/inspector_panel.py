"""Inspector: extracted fields for the selected queue row.

Double-clicking a value turns it into an editable line-edit; committing a
change raises the learning-loop dialog (Màn hình 6) so the user can promote
the correction into a rule.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QGridLayout, QHBoxLayout, QLabel, QLineEdit, QScrollArea, QVBoxLayout, QWidget,
)

from src.ui.theme import Theme, repolish


class FieldRow(QWidget):
    edited = Signal(str, str, str)   # key, old_value, new_value

    def __init__(self, theme: Theme, key: str, label: str, value: str,
                 regex: str, confidence: int, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("FieldRow")
        self.theme, self.key, self._old = theme, key, value

        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 7, 10, 7)
        lay.setSpacing(10)

        lbl = QLabel(label, self)
        lbl.setFixedWidth(150)
        lbl.setStyleSheet(f"color:{theme.color('text_muted')}")

        self.edit = QLineEdit(value, self)
        self.edit.setObjectName("FieldValueEdit")
        self.edit.setProperty("mono", "true")
        self.edit.setReadOnly(True)
        self.edit.mouseDoubleClickEvent = self._begin_edit
        self.edit.editingFinished.connect(self._commit)

        rgx = QLabel(regex, self)
        rgx.setFixedWidth(132)
        rgx.setStyleSheet(
            f"color:{theme.color('text_faint')};font-family:'JetBrains Mono',Consolas,monospace;font-size:10px")

        conf = QLabel(f"{confidence}%", self)
        conf.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        conf.setFixedWidth(92)
        key_token = "success" if confidence >= 90 else ("duplicate" if confidence >= 70 else "error")
        conf.setStyleSheet(
            f"color:{theme.color(f'status.{key_token}.fg')};"
            f"font-family:'JetBrains Mono',Consolas,monospace;font-size:10px")

        for w in (lbl, self.edit, rgx, conf):
            lay.addWidget(w)
        lay.setStretch(1, 1)

    def _begin_edit(self, _event) -> None:
        self.edit.setReadOnly(False)
        self.edit.selectAll()
        self.edit.setFocus(Qt.MouseFocusReason)

    def _commit(self) -> None:
        self.edit.setReadOnly(True)
        new = self.edit.text().strip()
        if new and new != self._old:
            self.edited.emit(self.key, self._old, new)
            self._old = new
        repolish(self.edit)


class InspectorPanel(QWidget):
    field_edited = Signal(str, str, str)

    def __init__(self, theme: Theme, parent=None) -> None:
        super().__init__(parent)
        self.theme = theme
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 10, 0, 10)
        root.setSpacing(8)

        head = QHBoxLayout()
        head.setContentsMargins(14, 0, 14, 0)
        self.caption = QLabel("INSPECTOR — TRƯỜNG TRÍCH XUẤT", self)
        self.caption.setProperty("role", "caption")
        self.lbl_file = QLabel("— chưa chọn file —", self)
        self.lbl_file.setProperty("role", "path")
        hint = QLabel("Nhấp đúp ô Giá trị để sửa tay", self)
        hint.setStyleSheet(f"color:{theme.color('text_faint')};font-size:11px")
        head.addWidget(self.caption)
        head.addWidget(self.lbl_file)
        head.addStretch(1)
        head.addWidget(hint)
        root.addLayout(head)

        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.NoFrame)
        self.body = QWidget(self.scroll)
        self.grid = QVBoxLayout(self.body)
        self.grid.setContentsMargins(14, 0, 14, 0)
        self.grid.setSpacing(6)
        self.scroll.setWidget(self.body)
        root.addWidget(self.scroll, 1)

        links = QGridLayout()
        links.setContentsMargins(14, 0, 14, 0)
        self.lnk_source = QLabel('Nguồn: <a href="#">—</a>', self)
        self.lnk_target = QLabel('Thư mục đích: <a href="#">—</a>', self)
        for i, w in enumerate((self.lnk_source, self.lnk_target)):
            w.setOpenExternalLinks(False)
            w.setTextInteractionFlags(Qt.TextBrowserInteraction)
            links.addWidget(w, 0, i)
        root.addLayout(links)

    def show_fields(self, file_name: str, fields: list[dict], source: str, target: str) -> None:
        self.lbl_file.setText(file_name)
        while self.grid.count():
            item = self.grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for f in fields:
            row = FieldRow(self.theme, f["key"], f["label"], f["value"],
                           f.get("regex", ""), f.get("confidence", 0), self.body)
            row.edited.connect(self.field_edited)
            self.grid.addWidget(row)
        self.grid.addStretch(1)
        self.lnk_source.setText(f'Nguồn: <a href="file:///{source}">{source}</a>')
        self.lnk_target.setText(f'Thư mục đích: <a href="file:///{target}">{target}</a>')

    def show_row(self, row: int) -> None:
        """Hook the controller to real model data."""
        raise NotImplementedError("controller: map row -> extracted fields, then call show_fields()")

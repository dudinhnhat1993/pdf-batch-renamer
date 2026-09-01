"""Inspector: extracted fields for the selected queue row.

Double-clicking a value turns it into an editable line-edit; committing a
change raises the learning-loop dialog (Màn hình 6) so the user can promote
the correction into a rule.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from src.core.models import FileJob, JobStatus
from src.ui.qt_helpers import open_in_explorer
from src.ui.theme import Theme, repolish


class FieldRow(QWidget):
    edited = Signal(str, str, str)  # key, old_value, new_value

    def __init__(
        self,
        theme: Theme,
        key: str,
        label: str,
        value: str,
        regex: str,
        confidence: int,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("FieldRow")
        self.theme, self.key, self._old = theme, key, value

        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 7, 10, 7)
        lay.setSpacing(10)

        lbl = QLabel(label or key, self)
        lbl.setFixedWidth(150)
        lbl.setStyleSheet(f"color:{theme.color('text_muted')}; font-weight: 500;")

        self.edit = QLineEdit(value, self)
        self.edit.setObjectName("FieldValueEdit")
        self.edit.setProperty("mono", "true")
        self.edit.setReadOnly(True)
        self.edit.mouseDoubleClickEvent = self._begin_edit
        self.edit.editingFinished.connect(self._commit)

        rgx = QLabel(regex, self)
        rgx.setFixedWidth(140)
        rgx.setStyleSheet(
            f"color:{theme.color('text_faint')};font-family:'JetBrains Mono',Consolas,monospace;font-size:10px"
        )
        rgx.setToolTip(f"Nguồn trích xuất: {regex}" if regex else "")

        conf = QLabel(f"{confidence}%", self)
        conf.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        conf.setFixedWidth(50)
        key_token = "success" if confidence >= 90 else ("duplicate" if confidence >= 70 else "error")
        conf.setStyleSheet(
            f"color:{theme.color(f'status.{key_token}.fg')};"
            f"font-family:'JetBrains Mono',Consolas,monospace;font-size:10px;font-weight:bold;"
        )

        for w in (lbl, self.edit, rgx, conf):
            lay.addWidget(w)
        lay.setStretch(1, 1)

    def _begin_edit(self, _event) -> None:
        self.edit.setReadOnly(False)
        self.edit.selectAll()
        self.edit.setFocus(Qt.FocusReason.MouseFocusReason)

    def _commit(self) -> None:
        self.edit.setReadOnly(True)
        new = self.edit.text().strip()
        if new and new != self._old:
            self.edited.emit(self.key, self._old, new)
            self._old = new
        repolish(self.edit)


class InspectorPanel(QWidget):
    field_edited = Signal(str, str, str)  # key, old_value, new_value

    def __init__(self, theme: Theme, parent=None) -> None:
        super().__init__(parent)
        self.theme = theme
        self._current_job: FileJob | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 10, 0, 10)
        root.setSpacing(8)

        head = QHBoxLayout()
        head.setContentsMargins(14, 0, 14, 0)
        self.caption = QLabel("INSPECTOR — TRƯỜNG TRÍCH XUẤT", self)
        self.caption.setProperty("role", "caption")
        self.lbl_file = QLabel("— chưa chọn file —", self)
        self.lbl_file.setProperty("role", "path")
        self.lbl_file.setStyleSheet(f"color:{theme.color('primary_text')}; font-weight: 600;")
        hint = QLabel("Nhấp đúp ô Giá trị để sửa tay", self)
        hint.setStyleSheet(f"color:{theme.color('text_faint')};font-size:11px")
        head.addWidget(self.caption)
        head.addWidget(self.lbl_file)
        head.addStretch(1)
        head.addWidget(hint)
        root.addLayout(head)

        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.body = QWidget(self.scroll)
        self.grid = QVBoxLayout(self.body)
        self.grid.setContentsMargins(14, 0, 14, 0)
        self.grid.setSpacing(6)
        self.scroll.setWidget(self.body)
        root.addWidget(self.scroll, 1)

        links = QGridLayout()
        links.setContentsMargins(14, 0, 14, 0)
        self.lnk_source = QLabel("Nguồn: —", self)
        self.lnk_target = QLabel("Thư mục đích: —", self)
        for i, w in enumerate((self.lnk_source, self.lnk_target)):
            w.setOpenExternalLinks(False)
            w.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
            w.linkActivated.connect(self._on_link_activated)
            links.addWidget(w, 0, i)
        root.addLayout(links)

    def _on_link_activated(self, link: str) -> None:
        if link.startswith("file:///"):
            clean_path = link[8:]
            open_in_explorer(clean_path)

    def set_job(self, job: FileJob | None) -> None:
        self._current_job = job
        while self.grid.count():
            item = self.grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if job is None:
            self.lbl_file.setText("— chưa chọn file —")
            self.lnk_source.setText("Nguồn: —")
            self.lnk_target.setText("Thư mục đích: —")
            empty_lbl = QLabel("Chọn 1 file trong danh sách bên trên để xem các trường dữ liệu.", self.body)
            empty_lbl.setStyleSheet(f"color:{self.theme.color('text_muted')}; padding: 16px 0;")
            self.grid.addWidget(empty_lbl)
            self.grid.addStretch(1)
            return

        file_name = job.source.name if job.source else "—"
        self.lbl_file.setText(file_name)

        if job.fields:
            for key, field in job.fields.items():
                name = getattr(field, "name", key) or key
                val = getattr(field, "value", "") or getattr(field, "raw_value", "") or ""
                rule_id = getattr(field, "rule_id", "") or ""
                layer = getattr(field, "layer", None)
                source_label = f"{layer.label_vi}" if layer and hasattr(layer, "label_vi") else rule_id
                conf = 100
                row = FieldRow(self.theme, key, name, val, source_label, conf, self.body)
                row.edited.connect(self.field_edited)
                self.grid.addWidget(row)
        else:
            if getattr(job, "error_code", "") == "no-profile" or (job.status == JobStatus.ERROR and not job.fields):
                no_fields = QLabel(
                    "Chưa có mẫu nhận diện (Rule) phù hợp cho chứng từ này.\n"
                    "Nhấp nút [Tạo loại mới] trên thanh công cụ (Ctrl+N) để AI hỗ trợ tạo mẫu bóc tách từ file này.",
                    self.body
                )
                no_fields.setStyleSheet(f"color:{self.theme.color('accent_deep')}; padding: 12px 0; font-weight: 600; line-height: 1.4;")
            else:
                no_fields = QLabel("Chưa có trường nào được trích xuất (Bấm 'Xem trước' hoặc 'Áp dụng').", self.body)
                no_fields.setStyleSheet(f"color:{self.theme.color('text_muted')}; padding: 12px 0;")
            self.grid.addWidget(no_fields)

        self.grid.addStretch(1)

        src_str = str(job.source) if job.source else ""
        dest_str = str(job.dest_dir) if job.dest_dir else ""
        if src_str:
            self.lnk_source.setText(f'Nguồn: <a href="file:///{src_str}" style="color:{self.theme.color("primary_text")};">{src_str}</a>')
        else:
            self.lnk_source.setText("Nguồn: —")
        if dest_str:
            self.lnk_target.setText(f'Thư mục đích: <a href="file:///{dest_str}" style="color:{self.theme.color("primary_text")};">{dest_str}</a>')
        else:
            self.lnk_target.setText("Thư mục đích: —")

    def show_fields(self, file_name: str, fields: list[dict], source: str, target: str) -> None:
        self.lbl_file.setText(file_name)
        while self.grid.count():
            item = self.grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for f in fields:
            row = FieldRow(
                self.theme,
                f["key"],
                f["label"],
                f["value"],
                f.get("regex", ""),
                f.get("confidence", 100),
                self.body,
            )
            row.edited.connect(self.field_edited)
            self.grid.addWidget(row)
        self.grid.addStretch(1)
        self.lnk_source.setText(f'Nguồn: <a href="file:///{source}">{source}</a>')
        self.lnk_target.setText(f'Thư mục đích: <a href="file:///{target}">{target}</a>')

    def show_row(self, row: int) -> None:
        pass

    def rebind_theme(self, theme: Theme) -> None:
        self.theme = theme
        self.lbl_file.setStyleSheet(f"color:{theme.color('primary_text')}; font-weight: 600;")
        self.set_job(self._current_job)

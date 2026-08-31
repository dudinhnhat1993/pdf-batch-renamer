"""Model cho bảng Preview và bảng field.

Preview là bước bắt buộc trước khi ghi file: người dùng thấy Tên cũ -> Tên mới -> Thư mục
đích -> Profile match -> Field trích được, và sửa tay được cả tên lẫn field ngay tại chỗ.
Mọi lần sửa tay đều được ghi lại làm tín hiệu cho Learning Loop.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, Signal
from PySide6.QtGui import QColor, QFont

from ..core.models import ExtractedField, FileJob, JobStatus, Layer
from .qt_helpers import elide, status_color

logger = logging.getLogger(__name__)

COLUMNS = ["Trạng thái", "Tên cũ", "Tên mới", "Thư mục đích", "Profile", "Field trích được", "Ghi chú"]
COL_STATUS, COL_OLD, COL_NEW, COL_DEST, COL_PROFILE, COL_FIELDS, COL_NOTE = range(7)


class PreviewModel(QAbstractTableModel):
    """Bảng Preview. Chỉ cột 'Tên mới' sửa được trực tiếp."""

    jobEdited = Signal(int)  # index của job vừa bị sửa

    def __init__(
        self,
        rename_handler: Callable[[FileJob, str], None] | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._jobs: list[FileJob] = []
        self._rename_handler = rename_handler
        # Thư mục output gốc: cột "Thư mục đích" hiển thị đường dẫn TƯƠNG ĐỐI so với nó
        self._output_root: Path | None = None

    def set_output_root(self, root: Path | str | None) -> None:
        self._output_root = Path(root) if root else None

    @staticmethod
    def _norm(path: Path) -> str:
        """Chuẩn hóa để so khớp trên Windows: tuyệt đối hóa, thống nhất hoa/thường và dấu gạch."""
        return os.path.normcase(os.path.abspath(str(path))).rstrip("\\/")

    def dest_display(self, job: FileJob) -> str:
        """Hiển thị phần khác biệt (vd "2026-08-31" hay "_Loi"), không lặp lại output gốc.

        So khớp bằng chuỗi đã chuẩn hóa chứ không dùng relative_to trực tiếp: đường dẫn
        trong config do người dùng gõ tay nên hay lệch hoa/thường, lệch chiều gạch, hoặc
        thừa dấu gạch cuối.
        """
        if job.dest_dir is None:
            return "—"
        if self._output_root is None:
            return str(job.dest_dir)

        root = self._norm(self._output_root)
        dest = self._norm(job.dest_dir)
        if dest == root:
            return "(thư mục gốc)"
        if not dest.startswith(root + os.sep):
            return str(job.dest_dir)  # nằm ngoài thư mục output -> hiện đủ đường dẫn

        # Cắt theo độ dài phần gốc nhưng trả về chuỗi GỐC để giữ nguyên hoa/thường thật
        return str(job.dest_dir)[len(str(self._output_root).rstrip("\\/")) :].lstrip("\\/")

    # ------------------------------------------------------------- dữ liệu

    def set_jobs(self, jobs: list[FileJob]) -> None:
        self.beginResetModel()
        self._jobs = list(jobs)
        self.endResetModel()

    @property
    def jobs(self) -> list[FileJob]:
        return self._jobs

    def job_at(self, row: int) -> FileJob | None:
        return self._jobs[row] if 0 <= row < len(self._jobs) else None

    def refresh_row(self, row: int) -> None:
        if 0 <= row < len(self._jobs):
            self.dataChanged.emit(self.index(row, 0), self.index(row, len(COLUMNS) - 1))

    # --------------------------------------------------------- Qt override

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._jobs)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(COLUMNS)

    def headerData(self, section: int, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return COLUMNS[section]
        return None

    def flags(self, index: QModelIndex):
        base = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        job = self.job_at(index.row())
        # Chỉ cho sửa tên của file thật sự sẽ được ghi ra
        if index.column() == COL_NEW and job and job.status == JobStatus.PENDING:
            return base | Qt.ItemFlag.ItemIsEditable
        return base

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        job = self.job_at(index.row())
        if job is None:
            return None
        col = index.column()

        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            if col == COL_STATUS:
                return job.status.label_vi
            if col == COL_OLD:
                return job.source.name
            if col == COL_NEW:
                if role == Qt.ItemDataRole.EditRole:
                    return job.new_name.rsplit(".", 1)[0] if job.new_name else ""
                return job.new_name or "—"
            if col == COL_DEST:
                return self.dest_display(job)
            if col == COL_PROFILE:
                return job.profile_name or "—"
            if col == COL_FIELDS:
                return elide(self._fields_text(job), 80)
            if col == COL_NOTE:
                return elide(self._note_text(job), 90)

        if role == Qt.ItemDataRole.ForegroundRole and col == COL_STATUS:
            return status_color(job.status.value)

        if role == Qt.ItemDataRole.FontRole and col == COL_STATUS:
            font = QFont()
            font.setBold(True)
            return font

        if role == Qt.ItemDataRole.BackgroundRole and job.warnings:
            # Cảnh báo (vd trùng số chứng từ) phải nổi bật ngay trên bảng
            return QColor(255, 212, 121, 60)

        if role == Qt.ItemDataRole.ToolTipRole:
            return self._tooltip(job, col)

        return None

    # ------------------------------------------------------------ trợ giúp

    @staticmethod
    def _fields_text(job: FileJob) -> str:
        return ", ".join(f"{k}={v.value}" for k, v in sorted(job.fields.items())) or "—"

    @staticmethod
    def _note_text(job: FileJob) -> str:
        return "; ".join(x for x in [job.message, *job.warnings] if x)

    def _tooltip(self, job: FileJob, col: int) -> str:
        """Tooltip theo từng cột: cột nào bị cắt ngắn thì tooltip cho xem đủ."""
        if col == COL_OLD:
            return str(job.source)
        if col == COL_NEW:
            return str(job.dest_path) if job.dest_path else (job.new_name or "—")
        if col == COL_DEST:
            return str(job.dest_dir) if job.dest_dir else "—"
        if col == COL_FIELDS:
            if not job.fields:
                return "Không trích được field nào."
            return "\n".join(
                f"{k} = {v.value}   ({v.layer.label_vi})" for k, v in sorted(job.fields.items())
            )
        if col == COL_NOTE:
            return self._note_text(job) or "Không có ghi chú."

        parts = [str(job.source)]
        if job.message:
            parts.append(job.message)
        parts.extend(job.warnings)
        if job.layers_used:
            parts.append("Tầng đã dùng: " + ", ".join(x.label_vi for x in job.layers_used))
        return "\n".join(parts)

    def setData(self, index: QModelIndex, value, role=Qt.ItemDataRole.EditRole) -> bool:
        if role != Qt.ItemDataRole.EditRole or index.column() != COL_NEW:
            return False
        job = self.job_at(index.row())
        if job is None:
            return False
        new_stem = str(value).strip()
        if not new_stem:
            return False
        if self._rename_handler:
            self._rename_handler(job, new_stem)
        self.refresh_row(index.row())
        self.jobEdited.emit(index.row())
        return True


FIELD_COLUMNS = ["Field", "Giá trị", "Nguồn"]


class FieldsModel(QAbstractTableModel):
    """Bảng field của 1 job. Cột 'Giá trị' sửa tay được — đây là tín hiệu cho Learning Loop."""

    fieldEdited = Signal(str, str, str)  # (tên field, giá trị cũ, giá trị mới)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._job: FileJob | None = None
        self._names: list[str] = []

    def set_job(self, job: FileJob | None) -> None:
        self.beginResetModel()
        self._job = job
        self._names = sorted(job.fields.keys()) if job else []
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._names)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(FIELD_COLUMNS)

    def headerData(self, section: int, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return FIELD_COLUMNS[section]
        return None

    def flags(self, index: QModelIndex):
        base = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        return base | Qt.ItemFlag.ItemIsEditable if index.column() == 1 else base

    def _field(self, row: int) -> ExtractedField | None:
        if self._job is None or row >= len(self._names):
            return None
        return self._job.fields.get(self._names[row])

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        field = self._field(index.row())
        if field is None:
            return None
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            if index.column() == 0:
                return field.name
            if index.column() == 1:
                return field.value
            if index.column() == 2:
                source = f"{field.layer.label_vi}"
                if field.rule_id:
                    source += f" · {field.rule_id}"
                if field.page >= 0:
                    source += f" · trang {field.page + 1}"
                return source
        if role == Qt.ItemDataRole.FontRole and field.edited_by_user:
            font = QFont()
            font.setItalic(True)
            font.setBold(True)
            return font
        if role == Qt.ItemDataRole.ToolTipRole:
            return f"Giá trị gốc trên chứng từ: {field.raw_value or '(không có)'}"
        return None

    def setData(self, index: QModelIndex, value, role=Qt.ItemDataRole.EditRole) -> bool:
        if role != Qt.ItemDataRole.EditRole or index.column() != 1:
            return False
        field = self._field(index.row())
        if field is None:
            return False
        new_value = str(value).strip()
        if new_value == field.value:
            return False

        old_value = field.value
        field.value = new_value
        field.edited_by_user = True
        field.layer = Layer(field.layer)  # giữ nguyên tầng gốc để provenance không mất dấu
        self.dataChanged.emit(index, index)
        self.fieldEdited.emit(field.name, old_value, new_value)
        return True

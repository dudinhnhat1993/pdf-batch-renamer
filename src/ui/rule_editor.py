"""Quản lý rule: bật/tắt, nhân bản, kéo-thả ưu tiên, file mẫu, version + regression + rollback.

Nguyên tắc: mọi thay đổi rule đều phải chạy regression test trên bộ file mẫu của profile
và chỉ được lưu khi người dùng xác nhận nếu có field match kém đi.
"""

from __future__ import annotations

import copy
import logging
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ..core.config import AppConfig
from ..core.errors import MasterDataError
from ..core.learning import LearningStore
from ..core.masterdata import load_table
from ..core.models import FieldSpec, MasterDataLookup, MatchCondition, Profile
from ..core.regression import run_regression
from ..core.rules import ProfileStore
from .icons import get_app_icon

logger = logging.getLogger(__name__)

MAX_SAMPLES = 5
# Khoảng cách giữa các mức ưu tiên khi đánh lại số theo thứ tự kéo-thả
PRIORITY_STEP = 10




class ConditionList(QWidget):
    """Danh sách điều kiện (nhận diện hoặc loại trừ) — thêm bằng cách gõ chữ."""

    def __init__(self, title: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowIcon(get_app_icon())
        self.list = QListWidget()
        self.list.setFixedHeight(115)
        self.input = QLineEdit()
        self.input.setFixedHeight(30)
        self.input.setPlaceholderText("Nhập từ khóa hoặc cú pháp regex...")
        self.input.returnPressed.connect(self._add)
        self.kind = QComboBox()
        self.kind.setFixedHeight(30)
        self.kind.setFixedWidth(95)
        self.kind.addItem("Chứa chữ", "keyword")
        self.kind.addItem("Regex", "regex")

        add = QPushButton("Thêm")
        add.setFixedHeight(30)
        add.setFixedWidth(60)
        add.clicked.connect(self._add)
        remove = QPushButton("Xóa")
        remove.setFixedHeight(30)
        remove.setFixedWidth(50)
        remove.clicked.connect(self._remove)

        box = QGroupBox(title)
        layout = QVBoxLayout(box)
        layout.addWidget(self.list)
        layout.addWidget(self.input)

        row = QHBoxLayout()
        row.setSpacing(6)
        row.setContentsMargins(0, 2, 0, 0)
        row.addWidget(self.kind)
        row.addWidget(add)
        row.addWidget(remove)
        row.addStretch(1)
        layout.addLayout(row)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(box)

    def set_conditions(self, conditions: list[MatchCondition]) -> None:
        self.list.clear()
        for cond in conditions:
            self._append(cond)

    def conditions(self) -> list[MatchCondition]:
        return [
            self.list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.list.count())
        ]

    def _append(self, cond: MatchCondition) -> None:
        prefix = "regex: " if cond.kind == "regex" else ""
        item = QListWidgetItem(f"{prefix}{cond.value}")
        item.setData(Qt.ItemDataRole.UserRole, cond)
        self.list.addItem(item)

    def _add(self) -> None:
        text = self.input.text().strip()
        if not text:
            return
        self._append(MatchCondition(kind=self.kind.currentData(), value=text))
        self.input.clear()

    def _remove(self) -> None:
        for item in self.list.selectedItems():
            self.list.takeItem(self.list.row(item))



class EditFieldSpecDialog(QDialog):
    """Hộp thoại chỉnh sửa chi tiết 1 FieldSpec (tên, nhãn, regex patterns, validate...)."""

    def __init__(self, spec: FieldSpec | None = None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Chỉnh sửa Field" if spec and spec.name else "Thêm Field mới")
        self.resize(600, 520)

        self.spec = copy.deepcopy(spec) if spec else FieldSpec(name="")

        self.name_edit = QLineEdit(self.spec.name)
        self.name_edit.setPlaceholderText("vd: description, doc_date, invoice_no...")
        self.label_edit = QLineEdit(self.spec.label)
        self.label_edit.setPlaceholderText("Tên hiển thị tiếng Việt, vd: Nội dung, Số hóa đơn")

        self.required_check = QCheckBox("Bắt buộc (thiếu field này thì coi như không khớp profile)")
        self.required_check.setChecked(self.spec.required)

        self.validate_combo = QComboBox()
        validates = [
            ("Không kiểm tra (none)", "none"),
            ("Định dạng ngày (date)", "date"),
            ("Mã container ISO (container)", "container"),
            ("Mã số thuế (tax_id)", "tax_id"),
            ("Số nguyên / float (number)", "number"),
            ("Số tiền (amount)", "amount"),
            ("Biểu thức regex riêng (regex)", "regex"),
        ]
        for label, val in validates:
            self.validate_combo.addItem(label, val)
        idx = self.validate_combo.findData(self.spec.validate)
        self.validate_combo.setCurrentIndex(max(0, idx))

        self.validate_regex_edit = QLineEdit(self.spec.validate_regex)
        self.validate_regex_edit.setPlaceholderText("Regex kiểm tra nếu chọn kiểu regex")

        self.from_barcode_check = QCheckBox("Cho phép nhận từ Barcode/QR nếu text không có")
        self.from_barcode_check.setChecked(self.spec.from_barcode)

        self.normalize_check = QCheckBox("Chuẩn hóa theo từ điển tên công ty")
        self.normalize_check.setChecked(self.spec.normalize_company)

        self.patterns_edit = QPlainTextEdit()
        self.patterns_edit.setPlaceholderText(
            "Mỗi dòng 1 biểu thức Regular Expression (Regex).\n"
            "App sẽ thử lần lượt từ trên xuống dưới."
        )
        self.patterns_edit.setPlainText("\n".join(self.spec.patterns))

        form = QFormLayout()
        form.addRow("Tên field ({name}):", self.name_edit)
        form.addRow("Nhãn hiển thị:", self.label_edit)
        form.addRow(self.required_check)
        form.addRow("Kiểm tra dữ liệu:", self.validate_combo)
        form.addRow("Regex kiểm tra:", self.validate_regex_edit)
        form.addRow(self.from_barcode_check)
        form.addRow(self.normalize_check)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(QLabel("<b>Các biểu thức Regex trích xuất (patterns):</b>"))
        layout.addWidget(self.patterns_edit, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Lưu field")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Hủy")
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _accept(self) -> None:
        name = self.name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Thiếu thông tin", "Tên field không được để trống.")
            return
        patterns = [p for p in self.patterns_edit.toPlainText().splitlines() if p.strip()]
        self.spec.name = name
        self.spec.label = self.label_edit.text().strip() or name
        self.spec.required = self.required_check.isChecked()
        self.spec.validate = self.validate_combo.currentData() or "none"
        self.spec.validate_regex = self.validate_regex_edit.text().strip()
        self.spec.from_barcode = self.from_barcode_check.isChecked()
        self.spec.normalize_company = self.normalize_check.isChecked()
        self.spec.patterns = patterns
        self.accept()

    def get_field_spec(self) -> FieldSpec:
        return self.spec

class RuleEditorDialog(QDialog):
    """Cửa sổ quản lý toàn bộ profile."""

    def __init__(
        self,
        config: AppConfig,
        store: ProfileStore,
        learning: LearningStore | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Quản lý loại chứng từ")
        self.resize(1120, 760)
        self.config = config
        self.store = store
        self.learning = learning

        self.profiles: list[Profile] = store.load_all()
        self.current: Profile | None = None
        self._loading = False
        self._loading_md = False
        self._md_cache: dict[str, MasterDataLookup] = {}
        self._md_current = ""

        self._build_ui()
        self._reload_list()

    # ------------------------------------------------------------------ UI

    def _build_ui(self) -> None:
        self.profile_list = QListWidget()
        self.profile_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.profile_list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.profile_list.currentRowChanged.connect(self._on_profile_selected)
        self.profile_list.itemChanged.connect(self._on_item_changed)
        self.profile_list.model().rowsMoved.connect(self._on_rows_moved)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(
            QLabel("<b>Thứ tự ưu tiên</b> — kéo-thả để đổi. Bỏ tick là tắt profile.")
        )
        left_layout.addWidget(self.profile_list, 1)

        duplicate = QPushButton("Nhân bản")
        duplicate.clicked.connect(self._duplicate)
        delete = QPushButton("Xóa")
        delete.clicked.connect(self._delete)
        row = QHBoxLayout()
        row.addWidget(duplicate)
        row.addWidget(delete)
        left_layout.addLayout(row)

        export_pack = QPushButton("Xuất rule pack…")
        export_pack.setToolTip("Đóng gói toàn bộ rule thành 1 file JSON để backup hoặc mang sang máy khác.")
        export_pack.clicked.connect(self._export_pack)
        import_pack = QPushButton("Nhập rule pack…")
        import_pack.clicked.connect(self._import_pack)
        pack_row = QHBoxLayout()
        pack_row.addWidget(export_pack)
        pack_row.addWidget(import_pack)
        left_layout.addLayout(pack_row)

        # Cột chi tiết dày đặc; cửa sổ hẹp là các nhóm chồng đè lên nhau. Bọc trong vùng
        # cuộn để nội dung luôn đủ chỗ, người dùng cuộn xuống thay vì thấy chữ đè chữ.
        self.detail_scroll = QScrollArea()
        self.detail_scroll.setWidgetResizable(True)
        self.detail_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.detail_scroll.setWidget(self._build_detail())
        detail_scroll = self.detail_scroll

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left)
        splitter.addWidget(detail_scroll)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Close
        )
        save_btn = buttons.button(QDialogButtonBox.StandardButton.Save)
        save_btn.setText("Lưu profile này")
        save_btn.setProperty("variant", "primary")
        save_btn.setMinimumWidth(130)
        close_btn = buttons.button(QDialogButtonBox.StandardButton.Close)
        close_btn.setText("Đóng")
        close_btn.setProperty("variant", "secondary")
        close_btn.setMinimumWidth(80)
        buttons.accepted.connect(self._save_current)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(splitter, 1)
        layout.addWidget(buttons)

    def _build_detail(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        self.name = QLineEdit()
        self.name.setFixedHeight(30)
        self.doctype = QLineEdit()
        self.doctype.setFixedHeight(30)
        self.template = QLineEdit()
        self.template.setFixedHeight(30)
        self.output_dir = QLineEdit()
        self.output_dir.setFixedHeight(30)
        self.output_dir.setPlaceholderText("Để trống = dùng Thư mục output chung trong Cài đặt")
        pick_out_btn = QPushButton("Chọn…")
        pick_out_btn.setFixedHeight(30)
        pick_out_btn.setFixedWidth(75)
        pick_out_btn.clicked.connect(self._pick_output_dir)
        out_row = QWidget()
        out_layout = QHBoxLayout(out_row)
        out_layout.setContentsMargins(0, 0, 0, 0)
        out_layout.setSpacing(6)
        out_layout.addWidget(self.output_dir, 1)
        out_layout.addWidget(pick_out_btn)

        self.fill_optional = QCheckBox(
            "Điền đủ field tùy chọn (chạy thêm tầng vùng/barcode/metadata cho field còn trống)"
        )
        self.fill_optional.setToolTip(
            "Tắt để tiết kiệm thời gian với chứng từ nặng: khi đó các tầng sau chỉ chạy "
            "nếu còn thiếu field BẮT BUỘC."
        )
        self.ai_enabled = QCheckBox("Cho phép AI hỗ trợ profile này (vẫn phải bật ở Cài đặt)")
        self.date_formats = QLineEdit()
        self.date_formats.setPlaceholderText("dd/mm/yyyy, dd-mm-yyyy, dd/mm/yy")

        form = QFormLayout()
        form.setVerticalSpacing(4)
        form.setContentsMargins(0, 0, 0, 0)
        form.addRow("Tên:", self.name)
        form.addRow("Mã loại ({doctype}):", self.doctype)
        form.addRow("Mẫu tên file:", self.template)
        form.addRow("Thư mục đích riêng:", out_row)
        form.addRow("Định dạng ngày:", self.date_formats)
        form.addRow(self.fill_optional)
        form.addRow(self.ai_enabled)
        layout.addLayout(form)

        self.conditions = ConditionList("Nhận khi chứng từ CÓ chứa (trúng 1 là đủ)")
        self.excludes = ConditionList("Nhưng LOẠI TRỪ nếu chứng từ chứa")
        cond_row = QHBoxLayout()
        cond_row.setSpacing(12)
        cond_row.addWidget(self.conditions, 1)
        cond_row.addWidget(self.excludes, 1)
        layout.addLayout(cond_row)

        hint_exclude = QLabel(
            "Lưu ý: Điều kiện loại trừ có quyền phủ quyết (ví dụ Invoice loại trừ 'PACKING LIST'), "
            "không phụ thuộc thứ tự ưu tiên."
        )
        hint_exclude.setStyleSheet("color: #64748b; font-size: 11.5px; margin-top: -4px; margin-bottom: 4px;")
        layout.addWidget(hint_exclude)

        self._draft_fields: list[FieldSpec] = []
        self.fields_list = QListWidget()
        self.fields_list.setMinimumHeight(180)
        self.fields_list.setMaximumHeight(320)
        self.fields_list.setAlternatingRowColors(True)
        self.fields_list.itemDoubleClicked.connect(self._on_field_double_clicked)

        add_field_btn = QPushButton("Thêm field…")
        add_field_btn.clicked.connect(self._add_field)
        edit_field_btn = QPushButton("Sửa field…")
        edit_field_btn.clicked.connect(self._edit_field)
        remove_field_btn = QPushButton("Bỏ field")
        remove_field_btn.clicked.connect(self._remove_field)

        fields_btn_row = QHBoxLayout()
        fields_btn_row.addWidget(add_field_btn)
        fields_btn_row.addWidget(edit_field_btn)
        fields_btn_row.addWidget(remove_field_btn)
        fields_btn_row.addStretch(1)

        self.samples = QListWidget()
        self.samples.setMaximumHeight(110)
        add_sample = QPushButton("Thêm file mẫu")
        add_sample.clicked.connect(self._add_sample)
        remove_sample = QPushButton("Bỏ")
        remove_sample.clicked.connect(self._remove_sample)
        sample_box = QGroupBox(f"Thư viện file mẫu (tối đa {MAX_SAMPLES}) — dùng cho regression")
        sample_layout = QVBoxLayout(sample_box)
        sample_layout.addWidget(self.samples)
        sample_row = QHBoxLayout()
        sample_row.addWidget(add_sample)
        sample_row.addWidget(remove_sample)
        sample_layout.addLayout(sample_row)

        self.versions = QListWidget()
        self.versions.setMaximumHeight(110)
        rollback = QPushButton("Quay về version này")
        rollback.clicked.connect(self._rollback)
        version_box = QGroupBox("Lịch sử version")
        version_layout = QVBoxLayout(version_box)
        version_layout.addWidget(self.versions)
        version_layout.addWidget(rollback)
        version_layout.addWidget(
            QLabel("Rollback cũng tạo version mới — lịch sử không bao giờ bị xóa.")
        )

        bottom = QHBoxLayout()
        bottom.addWidget(sample_box)
        bottom.addWidget(version_box)

        self.fields_box = QGroupBox("Field của profile (nhấp đúp hoặc bấm Sửa để chỉnh regex)")
        fields_layout = QVBoxLayout(self.fields_box)
        fields_layout.addWidget(self.fields_list)
        fields_layout.addLayout(fields_btn_row)

        layout.addWidget(self.fields_box)
        layout.addWidget(self._build_masterdata())
        layout.addLayout(bottom)
        return page

    def _build_masterdata(self) -> QWidget:
        """Khai báo tra cứu Excel cho 1 field: lấy giá trị field -> dò cột key -> lấy cột value."""
        box = QGroupBox("Tra cứu master data (Excel)")
        form = QFormLayout(box)

        self.md_field = QComboBox()
        self.md_field.currentIndexChanged.connect(self._on_md_field_changed)

        self.md_source = QLineEdit()
        self.md_source.setPlaceholderText("Để trống = dùng file mặc định trong Cài đặt")
        pick = QPushButton("Chọn…")
        pick.clicked.connect(self._pick_masterdata)
        source_row = QWidget()
        source_layout = QHBoxLayout(source_row)
        source_layout.setContentsMargins(0, 0, 0, 0)
        source_layout.addWidget(self.md_source, 1)
        source_layout.addWidget(pick)

        self.md_sheet = QLineEdit()
        self.md_sheet.setPlaceholderText("Để trống = sheet đầu tiên")
        self.md_key = QLineEdit()
        self.md_key.setPlaceholderText("Tên cột chứa giá trị của field này, vd Ma KH")
        self.md_value = QLineEdit()
        self.md_value.setPlaceholderText("Tên cột muốn lấy ra, vd Ten cong ty")
        self.md_target = QLineEdit()
        self.md_target.setPlaceholderText("Tên field mới để dùng trong template, vd ten_kh")

        self.md_status = QLabel()
        self.md_status.setWordWrap(True)
        # Thông báo có tới 4 dòng (số dòng Excel, ví dụ, giá trị thật, kết quả dò) — không
        # đặt chiều cao tối thiểu thì dòng quan trọng nhất "0 DÒNG KHỚP" bị cắt mất
        self.md_status.setFixedHeight(76)
        self.md_status.setAlignment(Qt.AlignmentFlag.AlignTop)
        test = QPushButton("Kiểm tra tra cứu")
        test.clicked.connect(self._test_masterdata)

        form.addRow("Áp cho field:", self.md_field)
        form.addRow("File Excel:", source_row)
        form.addRow("Sheet:", self.md_sheet)
        form.addRow("Cột dò (key):", self.md_key)
        form.addRow("Cột lấy ra (value):", self.md_value)
        form.addRow("Đặt tên field mới:", self.md_target)
        form.addRow("Chạy thử:", test)
        form.addRow(self.md_status)

        box.setToolTip(
            "Ví dụ: field “ma_kh” bắt được KH001 -> dò cột “Ma KH” -> lấy “Ten cong ty” -> "
            "sinh field mới “ten_kh”, dùng được ngay trong mẫu tên file bằng {ten_kh}."
        )
        return box

    # -------------------------------------------------------------- danh sách

    def _reload_list(self, keep_row: int = 0) -> None:
        self._loading = True
        self.profile_list.clear()
        stats = self._match_stats()
        for profile in self.profiles:
            matched = stats.get(profile.id, 0)
            item = QListWidgetItem(
                f"{profile.name}  ·  v{profile.version}  ·  {matched} file đã xử lý (30 ngày)"
            )
            item.setData(Qt.ItemDataRole.UserRole, profile.id)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked if profile.enabled else Qt.CheckState.Unchecked
            )
            if profile.is_fallback:
                item.setToolTip("Profile dự phòng — chỉ dùng khi không profile nào khác nhận.")
            self.profile_list.addItem(item)
        self._loading = False
        if self.profiles:
            self.profile_list.setCurrentRow(max(0, min(keep_row, len(self.profiles) - 1)))

    def _match_stats(self) -> dict[str, int]:
        if self.learning is None:
            return {}
        try:
            return {s["profile_id"]: s["total"] for s in self.learning.profile_stats(30)}
        except Exception:
            logger.exception("Không đọc được thống kê match")
            return {}

    def _on_profile_selected(self, row: int) -> None:
        if self._loading or row < 0 or row >= len(self.profiles):
            return
        self.current = self.profiles[row]
        self._load_detail(self.current)

    def _on_item_changed(self, item: QListWidgetItem) -> None:
        """Tick/bỏ tick = bật/tắt profile, lưu ngay vì đây là thao tác 1 chạm."""
        if self._loading:
            return
        profile_id = item.data(Qt.ItemDataRole.UserRole)
        profile = next((p for p in self.profiles if p.id == profile_id), None)
        if profile is None:
            return
        enabled = item.checkState() == Qt.CheckState.Checked
        if enabled == profile.enabled:
            return
        profile.enabled = enabled
        self.store.save(profile, bump_version=False)
        logger.info("%s profile %s", "Bật" if enabled else "Tắt", profile.name)

    def _on_rows_moved(self, *_args) -> None:
        """Kéo-thả xong thì đánh lại số ưu tiên theo đúng thứ tự đang hiển thị."""
        if self._loading:
            return
        order = [
            self.profile_list.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self.profile_list.count())
        ]
        by_id = {p.id: p for p in self.profiles}
        reordered = [by_id[pid] for pid in order if pid in by_id]

        for index, profile in enumerate(reordered):
            # Profile dự phòng luôn ở cuối hàng, không cho leo lên trước
            new_priority = 999 if profile.is_fallback else (index + 1) * PRIORITY_STEP
            if profile.priority != new_priority:
                profile.priority = new_priority
                self.store.save(profile, bump_version=False)
        self.profiles = reordered
        logger.info("Đã cập nhật thứ tự ưu tiên cho %s profile", len(reordered))

    # ---------------------------------------------------------------- chi tiết

    def _load_detail(self, profile: Profile) -> None:
        self.name.setText(profile.name)
        self.doctype.setText(profile.doctype)
        self.template.setText(profile.template)
        self.output_dir.setText(getattr(profile, "output_dir", "") or "")
        self.date_formats.setText(", ".join(profile.date_formats))
        self.fill_optional.setChecked(profile.fill_optional_fields)
        self.ai_enabled.setChecked(profile.ai_enabled)
        self.conditions.set_conditions(profile.conditions)
        self.excludes.set_conditions(profile.exclude_conditions)

        self._draft_fields = profile.fields
        self._reload_fields_list()

        self.samples.clear()
        for path in profile.samples:
            item = QListWidgetItem(Path(path).name)
            item.setData(Qt.ItemDataRole.UserRole, path)
            item.setToolTip(path)
            if not Path(path).exists():
                item.setText(item.text() + "  (không tìm thấy file)")
            self.samples.addItem(item)

        self._load_masterdata(profile)

        self.versions.clear()
        for version in reversed(self.store.versions(profile.id)):
            item = QListWidgetItem(
                f"v{version}" + ("  (đang dùng)" if version == profile.version else "")
            )
            item.setData(Qt.ItemDataRole.UserRole, version)
            self.versions.addItem(item)


    # ------------------------------------------------------------- thao tác field

    def _reload_fields_list(self) -> None:
        self.fields_list.clear()
        count = len(self._draft_fields)
        if hasattr(self, "fields_box"):
            self.fields_box.setTitle(
                f"Field của profile ({count} trường trích xuất) — nhấp đúp hoặc bấm Sửa để chỉnh regex"
            )
        for spec in self._draft_fields:
            req_tag = "[BẮT BUỘC]" if spec.required else "[Tùy chọn]"
            bits = [f"{spec.label or spec.name} ({spec.name})", req_tag]
            if spec.zone is not None:
                bits.append(f"vùng trang {spec.zone.page + 1}")
            if spec.patterns:
                bits.append(f"{len(spec.patterns)} mẫu regex")
            if spec.from_barcode:
                bits.append("nhận từ barcode")
            if spec.validate != "none":
                bits.append(f"kiểm tra: {spec.validate}")
            item = QListWidgetItem("   ·   ".join(bits))
            item.setData(Qt.ItemDataRole.UserRole, spec)
            item.setToolTip(
                f"Tên field: {spec.name}\nNhãn hiển thị: {spec.label or spec.name}\n"
                f"Bắt buộc: {'Có' if spec.required else 'Không'}\n"
                f"Kiểm tra: {spec.validate}\n"
                f"Số mẫu Regex: {len(spec.patterns)}"
            )
            self.fields_list.addItem(item)

    def _on_field_double_clicked(self, _item: QListWidgetItem) -> None:
        self._edit_field()

    def _edit_field(self) -> None:
        row = self.fields_list.currentRow()
        if row < 0 or row >= len(self._draft_fields):
            return
        spec = self._draft_fields[row]
        dialog = EditFieldSpecDialog(spec, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._draft_fields[row] = dialog.get_field_spec()
            self._reload_fields_list()
            self.fields_list.setCurrentRow(row)
            self._refresh_masterdata_field_choices()

    def _add_field(self) -> None:
        dialog = EditFieldSpecDialog(None, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            new_spec = dialog.get_field_spec()
            self._draft_fields.append(new_spec)
            self._reload_fields_list()
            self.fields_list.setCurrentRow(len(self._draft_fields) - 1)
            self._refresh_masterdata_field_choices()

    def _remove_field(self) -> None:
        row = self.fields_list.currentRow()
        if row < 0 or row >= len(self._draft_fields):
            return
        spec = self._draft_fields[row]
        ans = QMessageBox.question(
            self,
            "Xóa field",
            f"Bạn có chắc muốn xóa field “{spec.label or spec.name}”?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if ans == QMessageBox.StandardButton.Yes:
            del self._draft_fields[row]
            self._reload_fields_list()
            self._refresh_masterdata_field_choices()

    def _refresh_masterdata_field_choices(self) -> None:
        current_data = self.md_field.currentData() or ""
        self._loading_md = True
        self.md_field.clear()
        for spec in self._draft_fields:
            self.md_field.addItem(spec.label or spec.name, spec.name)
            if spec.name not in self._md_cache:
                self._md_cache[spec.name] = (
                    MasterDataLookup.from_dict(spec.masterdata.to_dict())
                    if spec.masterdata
                    else MasterDataLookup()
                )
        self._loading_md = False
        idx = self.md_field.findData(current_data)
        if idx >= 0:
            self.md_field.setCurrentIndex(idx)
        elif self.md_field.count() > 0:
            self.md_field.setCurrentIndex(0)

    # -------------------------------------------------------- master data

    def _load_masterdata(self, profile: Profile) -> None:
        """Nạp khai báo master data của từng field vào bộ nhớ tạm để sửa qua lại."""
        self._md_cache = {
            spec.name: (
                MasterDataLookup.from_dict(spec.masterdata.to_dict())
                if spec.masterdata
                else MasterDataLookup()
            )
            for spec in profile.fields
        }
        self._loading_md = True
        self.md_field.clear()
        for spec in profile.fields:
            self.md_field.addItem(spec.label or spec.name, spec.name)
        self._loading_md = False
        self.md_status.setText("")
        self._md_current = self.md_field.currentData() or ""
        self._show_masterdata(self._md_current)

    def _show_masterdata(self, field_name: str | None) -> None:
        spec = self._md_cache.get(field_name or "", MasterDataLookup())
        self.md_source.setText(spec.source)
        self.md_sheet.setText(spec.sheet)
        self.md_key.setText(spec.key_column)
        self.md_value.setText(spec.value_column)
        self.md_target.setText(spec.target_field)

    def _capture_masterdata(self, name: str | None = None) -> None:
        """Ghi form hiện tại vào bộ nhớ tạm của field đang sửa."""
        name = name if name is not None else self._md_current
        if not name:
            return
        self._md_cache[name] = MasterDataLookup(
            source=self.md_source.text().strip(),
            sheet=self.md_sheet.text().strip(),
            key_column=self.md_key.text().strip(),
            value_column=self.md_value.text().strip(),
            target_field=self.md_target.text().strip(),
        )

    def _on_md_field_changed(self, _index: int) -> None:
        """Đổi field: phải cất khai báo đang gõ của field CŨ lại trước, kẻo mất."""
        if getattr(self, "_loading_md", False):
            return
        self._capture_masterdata(self._md_current)
        self._md_current = self.md_field.currentData() or ""
        self._show_masterdata(self._md_current)

    def _pick_output_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Chọn thư mục đích riêng cho profile", self.output_dir.text())
        if path:
            self.output_dir.setText(path)

    def _pick_masterdata(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Chọn file Excel", self.md_source.text(), "Excel (*.xlsx *.xlsm)"
        )
        if path:
            self.md_source.setText(path)

    def scroll_to_masterdata(self) -> None:
        """Cuộn tới khung tra cứu master data — dùng sau khi bấm Kiểm tra."""
        self.detail_scroll.ensureWidgetVisible(self.md_status, 0, 40)

    def _sample_field_value(self, field_name: str) -> tuple[str, str]:
        """Lấy giá trị THẬT của field trên file mẫu đầu tiên. Trả (giá trị, lý do nếu trống)."""
        if self.current is None or not field_name:
            return "", "chưa chọn field"

        samples = [
            self.samples.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self.samples.count())
        ]
        samples = [s for s in samples if s and Path(s).exists()]
        if not samples:
            return "", "profile chưa có file mẫu nào (thêm ở khung Thư viện file mẫu)"

        from ..core.extractor import Extractor
        from ..core.ocr import OcrEngine

        draft = self._collect_into(self.current)
        ocr = OcrEngine(
            self.config.ocr.tesseract_path,
            self.config.ocr.languages,
            self.config.ocr.dpi,
            self.config.ocr.tessdata_path,
        )
        try:
            extractor = Extractor(self.config, [draft], ocr=ocr, ai_client=None)
            result = extractor.extract(samples[0], forced_profile=draft.id)
        except Exception as exc:
            logger.warning("Chạy thử master data trên file mẫu thất bại: %s", exc)
            return "", f"không đọc được file mẫu ({exc})"
        return result.value(field_name), f"field này không bắt được gì trên {Path(samples[0]).name}"

    def _test_masterdata(self) -> None:
        """Mở file Excel VÀ chạy thử bằng giá trị thật lấy từ file mẫu.

        Chỉ báo "đọc được N dòng" là chưa đủ: người dùng có thể bind nhầm field số hóa đơn
        vào cột mã khách hàng mà vẫn thấy OK. Phải dò thử giá trị thật mới lộ ra.
        """
        source = self.md_source.text().strip() or self.config.masterdata_source
        if not source:
            self.md_status.setText("Chưa chọn file Excel, và Cài đặt cũng chưa có file mặc định.")
            self.md_status.setStyleSheet("QLabel { color: #9a6700; }")
            return
        try:
            table = load_table(
                source,
                self.md_key.text().strip(),
                self.md_value.text().strip(),
                self.md_sheet.text().strip(),
            )
        except MasterDataError as exc:
            self.md_status.setText(f"Lỗi: {exc}")
            self.md_status.setStyleSheet("QLabel { color: #cf222e; }")
            return

        sample_pair = table.first_pair()
        lines = [f"Đọc được {len(table)} dòng."]
        if sample_pair:
            lines.append(f"Ví dụ trong Excel: {sample_pair[0]} -> {sample_pair[1]}")

        field_name = self.md_field.currentData() or ""
        value, reason = self._sample_field_value(field_name)
        if not value:
            lines.append(f"Chưa chạy thử được: {reason}.")
            self.md_status.setText("\n".join(lines))
            self.md_status.setStyleSheet("QLabel { color: #9a6700; }")
            return

        found = table.lookup(value)
        lines.append(f"Giá trị thật của field trên file mẫu: “{value}”")
        if found:
            lines.append(f"OK — dò ra: “{found}”")
            self.md_status.setStyleSheet("QLabel { color: #1a7f37; }")
        else:
            lines.append(
                f"0 DÒNG KHỚP trong cột “{self.md_key.text().strip()}”. "
                "Nhiều khả năng bind nhầm field hoặc nhầm cột dò."
            )
            self.md_status.setStyleSheet("QLabel { color: #cf222e; }")
        self.md_status.setText("\n".join(lines))

    # ---------------------------------------------------------- rule pack

    def _export_pack(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Xuất rule pack", "rule-pack.json", "JSON (*.json)"
        )
        if not path:
            return
        try:
            written = self.store.export_pack(path)
        except Exception as exc:
            logger.exception("Xuất rule pack thất bại")
            QMessageBox.critical(self, "Lỗi", str(exc))
            return
        QMessageBox.information(
            self, "Đã xuất", f"Đã đóng gói {len(self.profiles)} profile vào:\n{written}"
        )

    def _import_pack(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Nhập rule pack", "", "JSON (*.json)")
        if not path:
            return
        answer = QMessageBox.question(
            self,
            "Nhập rule pack",
            "Profile trùng id sẽ được NHÂN BẢN thành profile mới (không đè rule đang có).\n"
            "Tiếp tục?",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            imported = self.store.import_pack(path, overwrite=False)
        except Exception as exc:
            logger.exception("Nhập rule pack thất bại")
            QMessageBox.critical(self, "Lỗi", str(exc))
            return

        self.profiles = self.store.load_all()
        self._reload_list()
        QMessageBox.information(
            self, "Đã nhập", f"Đã nhập {len(imported)} profile từ rule pack."
        )

    def _collect_into(self, profile: Profile) -> Profile:
        """Gom dữ liệu trên form vào 1 BẢN SAO — chưa đụng gì tới profile đang lưu."""
        draft = Profile.from_dict(profile.to_dict())
        draft.name = self.name.text().strip() or profile.name
        draft.doctype = self.doctype.text().strip() or draft.name
        draft.template = self.template.text().strip() or profile.template
        draft.output_dir = self.output_dir.text().strip()
        formats = [f.strip() for f in self.date_formats.text().split(",") if f.strip()]
        draft.date_formats = formats or profile.date_formats
        draft.fill_optional_fields = self.fill_optional.isChecked()
        draft.ai_enabled = self.ai_enabled.isChecked()
        draft.conditions = self.conditions.conditions()
        draft.exclude_conditions = self.excludes.conditions()
        draft.samples = [
            self.samples.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self.samples.count())
        ]

        # Cập nhật danh sách fields đã chỉnh sửa
        draft.fields = [copy.deepcopy(f) for f in self._draft_fields]

        # Khai báo tra cứu Excel: chỉ giữ khai báo đủ 3 phần, còn lại coi như không dùng
        self._capture_masterdata()
        for spec in draft.fields:
            lookup = self._md_cache.get(spec.name)
            if lookup and lookup.key_column and lookup.value_column and lookup.target_field:
                spec.masterdata = lookup
            else:
                spec.masterdata = None
        return draft

    # ------------------------------------------------------------------ lưu

    def _save_current(self) -> None:
        if self.current is None:
            return
        draft = self._collect_into(self.current)

        if not draft.conditions and not draft.is_fallback:
            QMessageBox.warning(
                self, "Thiếu điều kiện nhận diện",
                "Profile này chưa có điều kiện nào nên sẽ không bao giờ nhận được chứng từ.",
            )
            return

        report = run_regression(self.current, draft, draft.samples, config=self.config)
        if report.sample_count:
            if report.has_regression:
                answer = QMessageBox.warning(
                    self, "Rule mới match kém hơn",
                    report.summary_vi() + "\n\nVẫn lưu?",
                    QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Cancel,
                )
                if answer != QMessageBox.StandardButton.Save:
                    return
            else:
                QMessageBox.information(self, "Kết quả regression", report.summary_vi())

        saved = self.store.save(draft, bump_version=True)
        row = self.profile_list.currentRow()
        self.profiles = [saved if p.id == saved.id else p for p in self.profiles]
        self.current = saved
        self._reload_list(row)
        logger.info("Đã lưu profile %s (v%s)", saved.name, saved.version)

    # ------------------------------------------------------------ thao tác

    def _duplicate(self) -> None:
        if self.current is None:
            return
        clone = Profile.from_dict(self.current.to_dict())
        clone.id = ""
        Profile.__post_init__(clone)
        clone.name = f"{self.current.name} (bản sao)"
        clone.version = 0
        clone.enabled = False  # bản sao tắt sẵn để không tranh match với bản gốc
        saved = self.store.save(clone, bump_version=True)
        self.profiles.append(saved)
        self._reload_list(len(self.profiles) - 1)
        QMessageBox.information(
            self, "Đã nhân bản",
            f"Đã tạo “{saved.name}”, đang TẮT sẵn để không tranh nhận chứng từ với bản gốc. "
            "Sửa xong thì tick vào ô bên trái để bật.",
        )

    def _delete(self) -> None:
        if self.current is None:
            return
        if self.current.is_fallback:
            QMessageBox.warning(
                self, "Không xóa được",
                "Đây là profile dự phòng — xóa đi thì chứng từ lạ sẽ không có chỗ rơi vào.",
            )
            return
        answer = QMessageBox.question(
            self, "Xóa profile",
            f"Xóa “{self.current.name}”?\nLịch sử version vẫn giữ lại trên đĩa.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.store.delete(self.current.id)
        self.profiles = [p for p in self.profiles if p.id != self.current.id]
        self.current = None
        self._reload_list()

    def _add_sample(self) -> None:
        if self.current is None:
            return
        if self.samples.count() >= MAX_SAMPLES:
            QMessageBox.information(
                self, "Đủ file mẫu rồi",
                f"Mỗi profile giữ tối đa {MAX_SAMPLES} file mẫu. Bỏ bớt rồi thêm cái khác.",
            )
            return
        files, _ = QFileDialog.getOpenFileNames(self, "Chọn file mẫu", "", "PDF (*.pdf)")
        existing = {
            self.samples.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self.samples.count())
        }
        for path in files[: MAX_SAMPLES - self.samples.count()]:
            if path in existing:
                continue
            item = QListWidgetItem(Path(path).name)
            item.setData(Qt.ItemDataRole.UserRole, path)
            item.setToolTip(path)
            self.samples.addItem(item)

    def _remove_sample(self) -> None:
        for item in self.samples.selectedItems():
            self.samples.takeItem(self.samples.row(item))

    def _rollback(self) -> None:
        if self.current is None:
            return
        item = self.versions.currentItem()
        if item is None:
            QMessageBox.information(self, "Chưa chọn version", "Chọn 1 version trong danh sách.")
            return
        version = item.data(Qt.ItemDataRole.UserRole)
        answer = QMessageBox.question(
            self, "Quay về version cũ",
            f"Quay profile “{self.current.name}” về nội dung của v{version}?\n"
            "Thao tác này tạo version mới, không xóa lịch sử.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        restored = self.store.rollback(self.current.id, version)
        row = self.profile_list.currentRow()
        self.profiles = [restored if p.id == restored.id else p for p in self.profiles]
        self.current = restored
        self._reload_list(row)
        logger.info("Rollback %s về v%s (thành v%s)", restored.name, version, restored.version)

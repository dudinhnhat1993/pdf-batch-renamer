"""Visual Rule Builder — wizard 4 bước tạo profile mà KHÔNG cần biết regex.

(1) Nạp PDF mẫu  (2) Đặt tên + điều kiện nhận diện bằng cách click vào chữ
(3) Tạo field bằng cách bôi chọn giá trị  (4) Ghép template + xem trước tên file

Mọi regex sinh ra đều kèm giải thích tiếng Việt để người dùng học dần.
Bước 3 có 2 chế độ: bôi chọn chữ (sinh regex) và kéo khung vùng (tầng zonal) — chế độ
vùng dùng cho chứng từ mà giá trị luôn nằm đúng một chỗ nhưng nhãn thì thất thường.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
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
    QPushButton,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
    QWizard,
    QWizardPage,
)

from ..core.config import AppConfig
from ..core.extractor import Extractor
from ..core.models import DocumentText, FieldSpec, MatchCondition, Profile, Zone
from ..core.namer import finalize_filename, render_template, template_tokens
from ..core.ocr import OcrEngine
from ..core.pdfdoc import PdfDocument
from ..core.rule_builder import (
    RegexCandidate,
    condition_from_keyword,
    generate_candidates,
    shape_pattern,
    zone_from_bbox,
)
from ..core.rules import ProfileStore, run_regex_field
from ..core.zonal import (
    apply_zone_filter,
    describe_ambiguity,
    text_in_zone,
    zone_lines,
    zone_looks_ambiguous,
)
from .pdf_view import PdfPreviewWidget

logger = logging.getLogger(__name__)

VALIDATE_CHOICES = [
    ("Không kiểm tra", "none"),
    ("Ngày tháng", "date"),
    ("Số container (ISO 6346)", "container"),
]

# Key chuẩn của field. Đặt đúng key thì token trong template dùng được ngay, không bị
# lệch kiểu "field tên so_container nhưng template lại viết {container}".
STANDARD_FIELD_KEYS = [
    ("number", "Số chứng từ"),
    ("doc_date", "Ngày trên chứng từ"),
    ("company", "Tên công ty"),
    ("container", "Số container"),
]

# Token dựng sẵn KHÔNG cần field tương ứng — app tự sinh giá trị
PROFILE_TOKENS = [
    ("{doctype}", "Mã loại chứng từ"),
    ("{original_name}", "Tên file gốc"),
]

COUNTER_TOKEN = ("{counter}", "Số đếm theo ngày")
COUNTER_WARNING = (
    "Số đếm tăng dần theo từng ngày cho mỗi profile. Dùng token này thì cùng một file "
    "chạy lại 2 lần sẽ ra 2 tên khác nhau — mất tính deterministic. Chỉ nên dùng cho "
    "profile “Chung”."
)


def standard_label(key: str) -> str:
    """Nhãn tiếng Việt gợi ý cho 1 key chuẩn."""
    return dict(STANDARD_FIELD_KEYS).get((key or "").strip(), "")


def field_name_combo(existing: list[str] | None = None) -> QComboBox:
    """Ô chọn tên field: gợi ý key chuẩn + field đã có của profile, vẫn gõ tự do được."""
    combo = QComboBox()
    combo.setEditable(True)
    seen: set[str] = set()
    for key, label in STANDARD_FIELD_KEYS:
        combo.addItem(f"{key}  ({label})", key)
        seen.add(key)
    for name in existing or []:
        if name not in seen:
            combo.addItem(f"{name}  (đã có trong profile)", name)
            seen.add(name)
    combo.setCurrentText("")
    combo.lineEdit().setPlaceholderText("Chọn key chuẩn hoặc tự gõ tên field")
    return combo


def combo_field_name(combo: QComboBox) -> str:
    """Lấy tên field từ ô chọn: ưu tiên key chuẩn gắn sau mục, không thì lấy chữ đã gõ."""
    text = combo.currentText().strip()
    for i in range(combo.count()):
        if combo.itemText(i) == text:
            return str(combo.itemData(i))
    return text.split("  (")[0].strip()


BUILTIN_TOKENS = [
    ("{doc_date}", "Ngày trên chứng từ"),
    ("{number}", "Số chứng từ"),
    ("{company}", "Tên công ty"),
    *PROFILE_TOKENS,
]


class _State:
    """Dữ liệu dùng chung giữa các bước của wizard."""

    def __init__(self) -> None:
        self.sample_path: Path | None = None
        self.document: DocumentText | None = None
        self.doc: PdfDocument | None = None
        self.profile = Profile(name="", template="{doc_date}_{doctype}_{number}")
        self.selected_text: str = ""
        self.selected_zone: Zone | None = None
        self.selected_zone_text: str = ""

    @property
    def text(self) -> str:
        return self.document.text if self.document else ""

    def close(self) -> None:
        if self.doc is not None:
            self.doc.close()
            self.doc = None


# --------------------------------------------------------------------- bước 1


class SamplePage(QWizardPage):
    """Bước 1 — nạp file PDF mẫu, app tự trích text (OCR nếu là bản scan)."""

    def __init__(self, wizard: RuleBuilderWizard) -> None:
        super().__init__()
        self.wiz = wizard
        self.setTitle("Bước 1/4 — Nạp chứng từ mẫu")
        self.setSubTitle(
            "Chọn 1 file PDF tiêu biểu cho loại chứng từ này. App sẽ đọc nội dung bên "
            "trong để bạn click chọn trực tiếp ở các bước sau."
        )

        self.path_label = QLabel("Chưa chọn file nào.")
        self.path_label.setWordWrap(True)
        pick = QPushButton("Chọn file PDF mẫu…")
        pick.clicked.connect(self._pick)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.placeholder = QWidget()
        self.placeholder.setLayout(QVBoxLayout())
        self.placeholder.layout().setContentsMargins(0, 0, 0, 0)

        layout = QVBoxLayout(self)
        row = QHBoxLayout()
        row.addWidget(pick)
        row.addWidget(self.path_label, 1)
        layout.addLayout(row)
        layout.addWidget(self.status)
        layout.addWidget(self.placeholder, 1)

    def _pick(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Chọn PDF mẫu", "", "PDF (*.pdf)")
        if not path:
            return
        self.wiz.load_sample(Path(path))
        state = self.wiz.state
        if state.document is None:
            self.status.setText("Không đọc được file này.")
            return

        self.path_label.setText(str(path))
        pages = len(state.document.pages)
        chars = state.document.char_count
        if state.document.ocr_used:
            self.status.setText(f"Đã OCR bản scan — {pages} trang, đọc được {chars} ký tự.")
        elif chars < 50:
            self.status.setText(
                f"Lưu ý: chỉ đọc được {chars} ký tự. File này nhiều khả năng là bản scan mà "
                "OCR chưa bật hoặc chưa cài Tesseract — hãy kiểm tra trong Cài đặt."
            )
        else:
            self.status.setText(f"Đọc được text sẵn có — {pages} trang, {chars} ký tự.")
        self.completeChanged.emit()

    def isComplete(self) -> bool:
        return self.wiz.state.document is not None


# --------------------------------------------------------------------- bước 2


class IdentifyPage(QWizardPage):
    """Bước 2 — đặt tên profile và tạo điều kiện nhận diện bằng cách click vào chữ."""

    def __init__(self, wizard: RuleBuilderWizard) -> None:
        super().__init__()
        self.wiz = wizard
        self.setTitle("Bước 2/4 — Nhận diện loại chứng từ")
        self.setSubTitle(
            "Click vào chữ đặc trưng trên trang (vd “BILL OF LADING”) rồi bấm Thêm điều kiện."
        )

        self.name = QLineEdit()
        self.name.textChanged.connect(lambda _: self.completeChanged.emit())
        self.doctype = QLineEdit()
        self.doctype.setPlaceholderText("Mã ngắn dùng trong tên file, vd BL, INV, PL")
        self.priority = QSpinBox()
        self.priority.setRange(1, 999)
        self.priority.setValue(50)
        self.priority.setToolTip("Số nhỏ hơn được thử match trước")

        self.conditions = QListWidget()
        self.excludes = QListWidget()

        add_cond = QPushButton("Thêm điều kiện từ chữ đang chọn")
        add_cond.clicked.connect(lambda: self._add(self.conditions))
        del_cond = QPushButton("Bỏ")
        del_cond.clicked.connect(lambda: self._remove(self.conditions))

        add_ex = QPushButton("Thêm loại trừ từ chữ đang chọn")
        add_ex.clicked.connect(lambda: self._add(self.excludes))
        del_ex = QPushButton("Bỏ")
        del_ex.clicked.connect(lambda: self._remove(self.excludes))

        cond_box = QGroupBox("Nhận khi chứng từ CÓ chứa (chỉ cần trúng 1)")
        cond_layout = QVBoxLayout(cond_box)
        cond_layout.addWidget(self.conditions)
        cond_row = QHBoxLayout()
        cond_row.addWidget(add_cond)
        cond_row.addWidget(del_cond)
        cond_layout.addLayout(cond_row)

        ex_box = QGroupBox("Nhưng LOẠI TRỪ nếu chứng từ chứa")
        ex_layout = QVBoxLayout(ex_box)
        ex_layout.addWidget(self.excludes)
        ex_row = QHBoxLayout()
        ex_row.addWidget(add_ex)
        ex_row.addWidget(del_ex)
        ex_layout.addLayout(ex_row)
        hint = QLabel(
            "Dùng khi 2 loại chứng từ chồng lấn — vd Packing List cũng có dòng "
            "“Invoice No.”, nên profile Invoice nên loại trừ “PACKING LIST”."
        )
        hint.setWordWrap(True)
        ex_layout.addWidget(hint)

        self.selection_label = QLabel()
        self.selection_label.setWordWrap(True)
        self.on_selection("")

        form = QFormLayout()
        form.addRow("Tên profile:", self.name)
        form.addRow("Mã loại ({doctype}):", self.doctype)
        form.addRow("Thứ tự ưu tiên:", self.priority)

        right = QVBoxLayout()
        right.addLayout(form)
        right.addWidget(self.selection_label)
        right.addWidget(cond_box, 1)
        right.addWidget(ex_box, 1)

        self.placeholder = QWidget()
        self.placeholder.setLayout(QVBoxLayout())
        self.placeholder.layout().setContentsMargins(0, 0, 0, 0)

        layout = QHBoxLayout(self)
        layout.addWidget(self.placeholder, 3)
        right_widget = QWidget()
        right_widget.setLayout(right)
        layout.addWidget(right_widget, 2)

    def on_selection(self, text: str) -> None:
        """Hint đổi theo ngữ cảnh: chưa chọn thì chỉ cách chọn, chọn rồi thì chỉ bước kế."""
        text = (text or "").strip()
        if text:
            self.selection_label.setText(
                f"Đang chọn: <b>{text}</b> — bấm “Thêm điều kiện…” hoặc “Thêm loại trừ…” bên dưới."
            )
        else:
            self.selection_label.setText(
                "Chưa chọn chữ nào. Click vào một chữ trên trang bên trái, hoặc bôi chọn "
                "cả cụm nếu tiêu đề gồm nhiều từ."
            )

    def _add(self, target: QListWidget) -> None:
        text = self.wiz.state.selected_text.strip()
        if not text:
            QMessageBox.information(
                self, "Chưa chọn chữ nào",
                "Click vào một chữ trên trang bên trái, hoặc bôi chọn một cụm từ.",
            )
            return
        cond = condition_from_keyword(text)
        item = QListWidgetItem(cond.value)
        item.setData(Qt.ItemDataRole.UserRole, cond)
        target.addItem(item)
        self.completeChanged.emit()

    @staticmethod
    def _remove(target: QListWidget) -> None:
        for item in target.selectedItems():
            target.takeItem(target.row(item))

    def _collect(self, widget: QListWidget) -> list[MatchCondition]:
        return [
            widget.item(i).data(Qt.ItemDataRole.UserRole) for i in range(widget.count())
        ]

    def isComplete(self) -> bool:
        return bool(self.name.text().strip() and self.conditions.count())

    def validatePage(self) -> bool:
        profile = self.wiz.state.profile
        profile.name = self.name.text().strip()
        profile.doctype = self.doctype.text().strip() or profile.name
        profile.priority = self.priority.value()
        profile.conditions = self._collect(self.conditions)
        profile.exclude_conditions = self._collect(self.excludes)
        return True


# --------------------------------------------------------------------- bước 3


class FieldDialog(QDialog):
    """Tạo 1 field từ đoạn text người dùng vừa bôi chọn."""

    def __init__(
        self, sample_text: str, selected: str, existing: list[str] | None = None, parent=None
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Tạo field từ giá trị đã chọn")
        self.resize(680, 560)
        self.sample_text = sample_text
        self.selected = selected
        self.candidates: list[RegexCandidate] = []
        self._buttons: list[QRadioButton] = []

        self.name = field_name_combo(existing)
        self.name.currentTextChanged.connect(self._on_name_changed)
        self.label = QLineEdit()
        self.label.setPlaceholderText("Tên hiển thị, vd Số hóa đơn")
        self.required = QCheckBox("Bắt buộc — thiếu field này thì file bị đưa vào thư mục lỗi")
        self.validate = QComboBox()
        for text, value in VALIDATE_CHOICES:
            self.validate.addItem(text, value)
        self.normalize = QCheckBox("Chuẩn hóa theo từ điển tên công ty")
        self.from_barcode = QCheckBox("Cho phép lấy từ barcode/QR nếu không tìm thấy trong text")

        form = QFormLayout()
        form.addRow("Giá trị đã chọn:", QLabel(f"<b>{selected}</b>"))
        form.addRow("Tên field:", self.name)
        form.addRow("Nhãn hiển thị:", self.label)
        form.addRow(self.required)
        form.addRow("Kiểm tra giá trị:", self.validate)
        form.addRow(self.normalize)
        form.addRow(self.from_barcode)

        self.candidate_box = QGroupBox("Cách tìm giá trị này — chọn 1")
        self.candidate_layout = QVBoxLayout(self.candidate_box)

        self.custom = QLineEdit()
        self.custom.setPlaceholderText("Hoặc tự sửa regex ở đây (không bắt buộc)")
        self.custom.textChanged.connect(self._test)
        self.test_result = QLabel()
        self.test_result.setWordWrap(True)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Thêm field")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Hủy")
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.candidate_box, 1)
        layout.addWidget(QLabel("Regex đang dùng:"))
        layout.addWidget(self.custom)
        layout.addWidget(self.test_result)
        layout.addWidget(buttons)

        self._build_candidates()

    def _build_candidates(self) -> None:
        self.candidates = generate_candidates(self.sample_text, self.selected)
        if not self.candidates:
            self.candidate_layout.addWidget(
                QLabel("Không sinh được cách tìm nào. Bạn có thể tự nhập regex bên dưới.")
            )
            return
        for i, cand in enumerate(self.candidates):
            button = QRadioButton(cand.explanation)
            button.setToolTip(cand.pattern)
            button.toggled.connect(lambda checked, idx=i: self._pick(idx) if checked else None)
            self._buttons.append(button)
            self.candidate_layout.addWidget(button)
        self._buttons[0].setChecked(True)

    def _pick(self, index: int) -> None:
        self.custom.setText(self.candidates[index].pattern)

    def _test(self) -> None:
        pattern = self.custom.text().strip()
        if not pattern:
            self.test_result.setText("")
            return
        spec = FieldSpec(name="_test", patterns=[pattern])
        found = run_regex_field(spec, self._as_document())
        if found and found.value == self.selected:
            self._set_result(f"OK — chạy thử trên file mẫu: bắt đúng “{found.value}”", "ok")
        elif found:
            self._set_result(
                f"LỆCH — bắt được “{found.value}”, khác giá trị bạn chọn “{self.selected}”",
                "warn",
            )
        else:
            self._set_result("KHÔNG KHỚP — không bắt được gì trên file mẫu.", "bad")

    def _set_result(self, text: str, kind: str) -> None:
        """Dùng chữ + màu thay cho ký hiệu tick/chéo vì font Windows không phải máy nào cũng có."""
        color = {"ok": "#1a7f37", "warn": "#9a6700", "bad": "#cf222e"}.get(kind, "")
        self.test_result.setText(text)
        self.test_result.setStyleSheet(f"QLabel {{ color: {color}; font-weight: 600; }}")

    def _as_document(self) -> DocumentText:
        from ..core.models import PageText

        return DocumentText(pages=[PageText(index=0, width=0, height=0, text=self.sample_text)])

    def _on_name_changed(self, _text: str) -> None:
        key = combo_field_name(self.name)
        if not self.label.text().strip():
            self.label.setPlaceholderText(standard_label(key) or key)

    def _accept(self) -> None:
        if not combo_field_name(self.name):
            QMessageBox.warning(self, "Thiếu tên field", "Đặt tên cho field trước đã.")
            return
        if not self.custom.text().strip():
            QMessageBox.warning(self, "Chưa có cách tìm", "Chọn 1 cách tìm hoặc tự nhập regex.")
            return
        self.accept()

    def field_spec(self) -> FieldSpec:
        name = combo_field_name(self.name)
        return FieldSpec(
            name=name,
            label=self.label.text().strip() or standard_label(name) or name,
            required=self.required.isChecked(),
            patterns=[self.custom.text().strip()],
            validate=self.validate.currentData(),
            normalize_company=self.normalize.isChecked(),
            from_barcode=self.from_barcode.isChecked(),
        )


class ZoneFieldDialog(QDialog):
    """Tạo field lấy theo VÙNG trên trang (tầng 2), kèm bước tinh lọc bên trong vùng.

    Vùng thường bắt cả cụm nhiều dòng. Không lọc thêm thì field zonal gần như vô dụng
    trên chứng từ thật, nên hộp thoại này bắt buộc cho xem và thử ngay kết quả lọc.
    """

    FILTERS = [
        ("Lấy nguyên text trong vùng", "none"),
        ("Lấy phần sau nhãn…", "label"),
        ("Lấy dòng thứ…", "line"),
        ("Lọc bằng biểu thức…", "regex"),
    ]

    # Chỉ áp dụng cho cách lọc "sau nhãn"
    STOPS = [
        ("Hết phần còn lại", ""),
        ("Tại nhãn kế tiếp", "label"),
        ("Tại 2 khoảng trắng liên tiếp", "gap"),
        ("Theo biểu thức", "regex"),
    ]

    def __init__(self, zone: Zone, preview: str, existing: list[str] | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Tạo field từ vùng đã kéo")
        self.resize(640, 560)
        self.zone = zone
        self.zone_text = preview or ""

        self.name = field_name_combo(existing)
        self.name.currentTextChanged.connect(self._on_name_changed)
        self.label = QLineEdit()
        self.required = QCheckBox("Bắt buộc — thiếu field này thì file bị đưa vào thư mục lỗi")
        self.validate = QComboBox()
        for text, value in VALIDATE_CHOICES:
            self.validate.addItem(text, value)
        self.normalize = QCheckBox("Chuẩn hóa theo từ điển tên công ty")

        self.zone_view = QLabel(self.zone_text or "(không đọc được chữ nào trong vùng)")
        self.zone_view.setWordWrap(True)
        self.zone_view.setStyleSheet("QLabel { background: rgba(127,127,127,25); padding: 6px; }")

        self.ambiguous = QLabel()
        self.ambiguous.setWordWrap(True)

        self.filter_kind = QComboBox()
        for text, value in self.FILTERS:
            self.filter_kind.addItem(text, value)
        self.filter_kind.currentIndexChanged.connect(self._on_filter_changed)
        self.filter_value = QLineEdit()
        self.filter_value.textChanged.connect(self._update_result)

        # Lấy "sau nhãn" mà không có điểm dừng thì vẫn ôm hết phần còn lại của dòng
        self.stop_kind = QComboBox()
        for text, value in self.STOPS:
            self.stop_kind.addItem(text, value)
        self.stop_kind.currentIndexChanged.connect(self._on_stop_changed)
        self.stop_value = QLineEdit()
        self.stop_value.setPlaceholderText(r"Biểu thức dừng, vd  ([A-Z]{4}\d{7})")
        self.stop_value.textChanged.connect(self._update_result)

        self.result = QLabel()
        self.result.setWordWrap(True)

        self.suggest_button = QPushButton("Chuyển sang lọc bằng biểu thức (điền sẵn)")
        self.suggest_button.clicked.connect(self._use_suggested_regex)
        self.suggest_button.setVisible(False)

        form = QFormLayout()
        form.addRow("Trang:", QLabel(str(zone.page + 1)))
        form.addRow(
            "Vị trí vùng:",
            QLabel(
                f"x {zone.x0:.1%}–{zone.x1:.1%} · y {zone.y0:.1%}–{zone.y1:.1%} (tỉ lệ trang)"
            ),
        )
        form.addRow("Đọc được trong vùng:", self.zone_view)
        form.addRow(self.ambiguous)
        form.addRow("Cách lọc:", self.filter_kind)
        form.addRow("Giá trị lọc:", self.filter_value)
        form.addRow("Dừng ở:", self.stop_kind)
        form.addRow("Biểu thức dừng:", self.stop_value)
        form.addRow("Kết quả:", self.result)
        form.addRow(self.suggest_button)
        form.addRow("Tên field:", self.name)
        form.addRow("Nhãn hiển thị:", self.label)
        form.addRow(self.required)
        form.addRow("Kiểm tra giá trị:", self.validate)
        form.addRow(self.normalize)

        note = QLabel(
            "Vùng lưu theo tỉ lệ trang nên đổi khổ giấy hay DPI vẫn trúng chỗ. Tầng vùng "
            "chạy sau tầng regex; trang scan thì app tự OCR đúng vùng này."
        )
        note.setWordWrap(True)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Thêm field")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Hủy")
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(note)
        layout.addStretch(1)
        layout.addWidget(buttons)

        self._suggest_filter()
        self._on_filter_changed()

    # ------------------------------------------------------------- gợi ý

    def _suggest_filter(self) -> None:
        """Vùng nhiều giá trị thì cảnh báo và gợi ý sẵn cách lọc hợp lý nhất."""
        if not zone_looks_ambiguous(self.zone_text):
            self.ambiguous.setText("")
            return

        lines = zone_lines(self.zone_text)
        self.ambiguous.setText(
            f"Lưu ý: vùng này có vẻ chứa nhiều giá trị — {describe_ambiguity(self.zone_text)}. "
            "Chọn cách lọc bên dưới, nếu không tên file sẽ dính cả cụm."
        )
        self.ambiguous.setStyleSheet("QLabel { color: #9a6700; font-weight: 600; }")

        first = lines[0] if lines else ""
        if ":" not in first:
            self.filter_kind.setCurrentIndex(2)  # lấy dòng thứ 1
            self.filter_value.setText("1")
            return

        # Dòng đầu dạng "Nhãn: giá trị" -> lọc theo nhãn; nếu vẫn dính thì thêm điểm dừng
        # ở nhãn kế tiếp. Đây đúng ca hay gặp khi vùng gộp thành một dòng dài.
        self.filter_kind.setCurrentIndex(1)
        self.filter_value.setText(first.split(":", 1)[0].strip() + ":")
        if zone_looks_ambiguous(self.filtered_value()):
            self.stop_kind.setCurrentIndex(1)  # dừng tại nhãn kế tiếp

    def suggested_regex(self) -> str:
        """Regex ứng viên dựng từ token đầu tiên của kết quả đang lọc được."""
        value = self.filtered_value() or self.zone_text
        tokens = [t for t in value.split() if t]
        return f"({shape_pattern(tokens[0])})" if tokens else ""

    def _use_suggested_regex(self) -> None:
        candidate = self.suggested_regex()
        if not candidate:
            return
        self.filter_kind.setCurrentIndex(3)  # lọc bằng biểu thức
        self.filter_value.setText(candidate)

    def _on_stop_changed(self) -> None:
        self.stop_value.setEnabled(self.stop_kind.currentData() == "regex")
        self._update_result()

    def _on_name_changed(self, _text: str) -> None:
        key = combo_field_name(self.name)
        if not self.label.text().strip():
            self.label.setPlaceholderText(standard_label(key) or key)

    def _on_filter_changed(self) -> None:
        kind = self.filter_kind.currentData()
        self.filter_value.setEnabled(kind != "none")
        # Điểm dừng chỉ có nghĩa với cách lọc "sau nhãn"
        self.stop_kind.setEnabled(kind == "label")
        self.stop_value.setEnabled(kind == "label" and self.stop_kind.currentData() == "regex")
        self.filter_value.setPlaceholderText(
            {
                "none": "",
                "label": "Nhãn đứng trước giá trị, vd  B/L No.:",
                "line": "Số thứ tự dòng, đếm từ 1",
                "regex": r"Biểu thức, vd  ([A-Z]{4}\d{7})",
            }[kind]
        )
        self._update_result()

    def _update_result(self) -> None:
        value = self.filtered_value()
        still_many = bool(value) and zone_looks_ambiguous(value)

        if value and not still_many:
            self.result.setText(f"OK — lấy ra: “{value}”")
            self.result.setStyleSheet("QLabel { color: #1a7f37; font-weight: 600; }")
        elif value:
            self.result.setText(f"VẪN NHIỀU GIÁ TRỊ — “{value[:80]}”")
            self.result.setStyleSheet("QLabel { color: #9a6700; font-weight: 600; }")
        else:
            self.result.setText("KHÔNG LẤY ĐƯỢC GÌ với cách lọc này")
            self.result.setStyleSheet("QLabel { color: #cf222e; font-weight: 600; }")

        # Lọc theo nhãn mà vẫn dính nhiều giá trị -> mời chuyển sang biểu thức, điền sẵn
        offer = still_many and self.filter_kind.currentData() != "regex"
        self.suggest_button.setVisible(bool(offer and self.suggested_regex()))
        if offer:
            self.suggest_button.setText(
                f"Chuyển sang lọc bằng biểu thức: {self.suggested_regex()}"
            )

    # ------------------------------------------------------------- kết quả

    def filtered_value(self) -> str:
        return apply_zone_filter(
            self.zone_text,
            self.filter_kind.currentData(),
            self.filter_value.text().strip(),
            self.stop_kind.currentData(),
            self.stop_value.text().strip(),
        )

    def _accept(self) -> None:
        if not combo_field_name(self.name):
            QMessageBox.warning(self, "Thiếu tên field", "Đặt tên cho field trước đã.")
            return
        if not self.filtered_value().strip():
            answer = QMessageBox.question(
                self,
                "Cách lọc chưa ra giá trị",
                "Trên file mẫu, cách lọc này không lấy được gì. Vẫn thêm field?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        self.accept()

    def field_spec(self) -> FieldSpec:
        name = combo_field_name(self.name)
        return FieldSpec(
            name=name,
            label=self.label.text().strip() or standard_label(name) or name,
            required=self.required.isChecked(),
            patterns=[],
            zone=self.zone,
            zone_filter=self.filter_kind.currentData(),
            zone_filter_value=self.filter_value.text().strip(),
            zone_filter_stop=self.stop_kind.currentData(),
            zone_stop_value=self.stop_value.text().strip(),
            validate=self.validate.currentData(),
            normalize_company=self.normalize.isChecked(),
        )


class FieldPage(QWizardPage):
    """Bước 3 — bôi chọn giá trị hoặc kéo khung vùng để tạo field."""

    def __init__(self, wizard: RuleBuilderWizard) -> None:
        super().__init__()
        self.wiz = wizard
        self.setTitle("Bước 3/4 — Dạy app lấy dữ liệu")
        self.setSubTitle(
            "Bôi chọn đúng giá trị cần lấy trên trang (vd số B/L), app sẽ tự đề xuất "
            "cách tìm và cho bạn chạy thử ngay."
        )

        self.fields = QListWidget()

        # Hai cách dạy app lấy dữ liệu — chọn cách nào thì khung xem trang đổi hành vi theo
        self.mode_text = QRadioButton("Bôi chọn chữ (sinh cách tìm theo nhãn)")
        self.mode_zone = QRadioButton("Kéo khung vùng (lấy theo vị trí trên trang)")
        self.mode_text.setChecked(True)
        self.mode_text.toggled.connect(self._on_mode_changed)
        mode_box = QGroupBox("Cách lấy dữ liệu")
        mode_layout = QVBoxLayout(mode_box)
        mode_layout.addWidget(self.mode_text)
        mode_layout.addWidget(self.mode_zone)
        self.mode_hint = QLabel(
            "Bôi chọn chữ hợp với chứng từ có nhãn rõ ràng. Kéo khung vùng hợp với chứng từ "
            "in sẵn theo biểu mẫu — giá trị luôn nằm đúng một chỗ nhưng nhãn thất thường, "
            "hoặc bản scan chữ nhận dạng không chuẩn."
        )
        self.mode_hint.setWordWrap(True)
        mode_layout.addWidget(self.mode_hint)

        self.add_text_button = QPushButton("Tạo field từ đoạn đang chọn")
        self.add_text_button.clicked.connect(self._add_field)
        self.add_zone_button = QPushButton("Tạo field từ khung vừa kéo")
        self.add_zone_button.clicked.connect(self._add_zone_field)
        self.add_zone_button.setEnabled(False)
        remove = QPushButton("Bỏ field")
        remove.clicked.connect(self._remove_field)

        self.selection_label = QLabel("Chưa chọn gì.")
        self.selection_label.setWordWrap(True)

        right = QVBoxLayout()
        right.addWidget(mode_box)
        right.addWidget(QLabel("<b>Đang chọn:</b>"))
        right.addWidget(self.selection_label)
        row = QHBoxLayout()
        row.addWidget(self.add_text_button)
        row.addWidget(self.add_zone_button)
        row.addWidget(remove)
        right.addLayout(row)
        right.addWidget(QLabel("<b>Field của profile:</b>"))
        right.addWidget(self.fields, 1)

        self.placeholder = QWidget()
        self.placeholder.setLayout(QVBoxLayout())
        self.placeholder.layout().setContentsMargins(0, 0, 0, 0)

        layout = QHBoxLayout(self)
        layout.addWidget(self.placeholder, 3)
        right_widget = QWidget()
        right_widget.setLayout(right)
        layout.addWidget(right_widget, 2)

    def on_selection(self, text: str) -> None:
        self.selection_label.setText(text or "Chưa chọn gì.")

    def on_zone(self, zone: Zone, preview: str) -> None:
        """Người dùng vừa kéo xong 1 khung: hiện text đọc được trong vùng đó."""
        self.add_zone_button.setEnabled(True)
        self.selection_label.setText(
            f"Vùng trang {zone.page + 1} — đọc được: "
            + (f"“{preview}”" if preview else "(không có chữ nào trong vùng)")
        )

    def _on_mode_changed(self, _checked: bool = False) -> None:
        mode = "text" if self.mode_text.isChecked() else "zone"
        self.wiz.preview.set_mode(mode)
        self.add_text_button.setEnabled(mode == "text")
        self.add_zone_button.setEnabled(mode == "zone" and self.wiz.state.selected_zone is not None)
        self.selection_label.setText("Chưa chọn gì.")

    def _add_zone_field(self) -> None:
        zone = self.wiz.state.selected_zone
        if zone is None:
            QMessageBox.information(
                self, "Chưa kéo khung nào", "Kéo một khung chữ nhật trên trang bên trái trước."
            )
            return
        existing = [f.name for f in self.wiz.state.profile.fields]
        dialog = ZoneFieldDialog(
            zone, self.wiz.state.selected_zone_text, existing, self
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        spec = dialog.field_spec()
        self.wiz.state.profile.fields = [
            f for f in self.wiz.state.profile.fields if f.name != spec.name
        ] + [spec]
        self._refresh()

    def _add_field(self) -> None:
        selected = self.wiz.state.selected_text.strip()
        if not selected:
            QMessageBox.information(
                self, "Chưa chọn gì", "Bôi chọn giá trị cần lấy trên trang bên trái trước."
            )
            return
        existing = [f.name for f in self.wiz.state.profile.fields]
        dialog = FieldDialog(self.wiz.state.text, selected, existing, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        spec = dialog.field_spec()
        self.wiz.state.profile.fields = [
            f for f in self.wiz.state.profile.fields if f.name != spec.name
        ] + [spec]
        self._refresh()

    def _remove_field(self) -> None:
        for item in self.fields.selectedItems():
            name = item.data(Qt.ItemDataRole.UserRole)
            self.wiz.state.profile.fields = [
                f for f in self.wiz.state.profile.fields if f.name != name
            ]
        self._refresh()

    def _refresh(self) -> None:
        self.fields.clear()
        document = self.wiz.state.document
        for spec in self.wiz.state.profile.fields:
            found = self._probe(spec, document)
            value = found if found else "chưa bắt được trên file mẫu"
            flag = " (bắt buộc)" if spec.required else ""
            source = " [vùng]" if spec.zone is not None else ""
            # Dùng gạch đầu dòng + màu: ký hiệu tick/chéo không phải font Windows nào cũng có
            item = QListWidgetItem(f"-  {spec.label}{flag}{source}  ->  {value}")
            item.setData(Qt.ItemDataRole.UserRole, spec.name)
            item.setForeground(QColor("#1a7f37") if found else QColor("#cf222e"))
            item.setToolTip(
                "\n".join(spec.patterns)
                if spec.patterns
                else (f"Vùng trên trang {spec.zone.page + 1}" if spec.zone else "")
            )
            self.fields.addItem(item)
        self.completeChanged.emit()

    @staticmethod
    def _probe(spec: FieldSpec, document: DocumentText | None) -> str:
        """Thử lấy giá trị trên chính file mẫu: regex trước, không có thì đọc trong vùng."""
        if document is None:
            return ""
        if spec.patterns:
            found = run_regex_field(spec, document)
            if found:
                return found.value
        if spec.zone is not None:
            page = next((p for p in document.pages if p.index == spec.zone.page), None)
            if page is not None:
                return " ".join(text_in_zone(page, spec.zone).split())
        return ""

    def initializePage(self) -> None:
        self._refresh()

    def isComplete(self) -> bool:
        return bool(self.wiz.state.profile.fields)


# --------------------------------------------------------------------- bước 4


class TemplatePage(QWizardPage):
    """Bước 4 — ghép tên file từ token, xem trước ngay trên chính file mẫu."""

    def __init__(self, wizard: RuleBuilderWizard) -> None:
        super().__init__()
        self.wiz = wizard
        self.setTitle("Bước 4/4 — Đặt tên file")
        self.setSubTitle("Bấm vào token để chèn vào mẫu tên. Xem trước cập nhật ngay bên dưới.")

        self.template = QLineEdit()
        self.template.textChanged.connect(self._update_preview)

        self.token_box = QGroupBox("Token — bấm để chèn")
        self.token_layout = QVBoxLayout(self.token_box)

        self.preview = QLabel()
        self.preview.setWordWrap(True)
        self.preview.setStyleSheet("QLabel { padding: 10px; background: rgba(127,127,127,30); }")

        self.warning = QLabel()
        self.warning.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Mẫu tên file:"))
        layout.addWidget(self.template)
        layout.addWidget(self.token_box)
        layout.addWidget(QLabel("<b>Tên file sẽ ra:</b>"))
        layout.addWidget(self.preview)
        layout.addWidget(self.warning)
        layout.addStretch(1)

    def _token_palette(self) -> list[tuple[str, str, str]]:
        """(token, nhãn, trạng thái) — trạng thái: field | auto | missing | counter."""
        available = {f.name: f.label for f in self.wiz.state.profile.fields}

        palette: list[tuple[str, str, str]] = [
            (f"{{{name}}}", label, "field") for name, label in available.items()
        ]
        palette += [(token, label, "auto") for token, label in PROFILE_TOKENS]
        palette += [
            (f"{{{name}}}", label, "missing")
            for name, label in STANDARD_FIELD_KEYS
            if name not in available
        ]
        palette.append((COUNTER_TOKEN[0], COUNTER_TOKEN[1], "counter"))
        return palette

    def missing_tokens(self) -> list[str]:
        """Token trong template mà profile không có field, app cũng không tự sinh được."""
        known = {f.name for f in self.wiz.state.profile.fields}
        known |= {token.strip("{}") for token, _ in PROFILE_TOKENS}
        known.add(COUNTER_TOKEN[0].strip("{}"))
        return [t for t in template_tokens(self.template.text()) if t not in known]

    def initializePage(self) -> None:
        while self.token_layout.count():
            item = self.token_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        row: QHBoxLayout | None = None
        for i, (token, label, state) in enumerate(self._token_palette()):
            if i % 3 == 0:
                row = QHBoxLayout()
                self.token_layout.addLayout(row)

            if state == "missing":
                # Token dựng sẵn nhưng profile chưa có field -> làm mờ + nói rõ lý do
                button = QPushButton(f"{token}\n(chưa có field)")
                button.setStyleSheet("QPushButton { color: rgba(127,127,127,180); }")
                button.setToolTip(
                    f"Profile này chưa có field “{token.strip('{}')}” ({label}). Quay lại "
                    "bước 3 tạo field trước, nếu không token sẽ luôn rỗng."
                )
            elif state == "counter":
                button = QPushButton(f"{token}\n{label}  (lưu ý)")
                button.setToolTip(COUNTER_WARNING)
            else:
                button = QPushButton(f"{token}\n{label}")
                if state == "auto":
                    button.setToolTip("App tự sinh giá trị, không cần tạo field.")
            button.clicked.connect(lambda _=False, t=token: self._insert(t))
            row.addWidget(button)

        if not self.template.text():
            self.template.setText(self.wiz.state.profile.template)
        self._update_preview()

    def _insert(self, token: str) -> None:
        current = self.template.text()
        separator = "_" if current and not current.endswith(("_", "-", " ")) else ""
        self.template.setText(current + separator + token)

    def _update_preview(self) -> None:
        state = self.wiz.state
        profile = state.profile
        values = {}
        for spec in profile.fields:
            found = run_regex_field(spec, state.document) if state.document else None
            values[spec.name] = found.value if found else ""
        values.setdefault("doctype", profile.doctype or profile.name)
        values.setdefault("original_name", state.sample_path.stem if state.sample_path else "file")

        date_fields = {s.name for s in profile.fields if s.validate == "date"} | {"doc_date"}
        try:
            base = render_template(
                self.template.text(), values,
                date_formats=profile.date_formats, date_fields=date_fields,
            )
        except Exception as exc:
            self.preview.setText("—")
            self.warning.setText(f"Lưu ý: {exc}")
            self.completeChanged.emit()
            return

        name = finalize_filename(base, ".pdf", max_length=self.wiz.config.max_name_length,
                                 remove_accents=self.wiz.config.strip_accents)
        self.preview.setText(name)

        messages = []
        missing = self.missing_tokens()
        if missing:
            messages.append(
                "Lưu ý: token KHÔNG có field tương ứng nên sẽ luôn rỗng: "
                + ", ".join(f"{{{m}}}" for m in missing)
                + " — quay lại bước 3 để tạo field."
            )
        empty = [k for k, v in values.items() if not v and f"{{{k}}}" in self.template.text()]
        if empty:
            messages.append("Lưu ý: token chưa lấy được giá trị trên file mẫu: " + ", ".join(empty))
        if "counter" in template_tokens(self.template.text()):
            messages.append("Lưu ý: " + COUNTER_WARNING)
        self.warning.setText("\n".join(messages))
        self.completeChanged.emit()

    def isComplete(self) -> bool:
        return bool(self.template.text().strip())

    def validatePage(self) -> bool:
        self.wiz.state.profile.template = self.template.text().strip()
        return True


# --------------------------------------------------------------------- wizard


class RuleBuilderWizard(QWizard):
    """Gộp 4 bước và giữ 1 khung xem trang dùng chung cho các bước."""

    def __init__(self, config: AppConfig, store: ProfileStore, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Tạo loại chứng từ mới")
        self.resize(1150, 760)
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)
        self.setOption(QWizard.WizardOption.NoBackButtonOnStartPage, True)
        self.setButtonText(QWizard.WizardButton.NextButton, "Tiếp >")
        self.setButtonText(QWizard.WizardButton.BackButton, "< Quay lại")
        self.setButtonText(QWizard.WizardButton.FinishButton, "Lưu profile")
        self.setButtonText(QWizard.WizardButton.CancelButton, "Hủy")

        self.config = config
        self.store = store
        self.state = _State()
        self.saved_profile: Profile | None = None

        # 1 khung xem trang duy nhất, được chuyển qua lại giữa các bước để khỏi render lại
        self.preview = PdfPreviewWidget()
        self.preview.textSelected.connect(self._on_text_selected)
        self.preview.rectDragged.connect(self._on_rect_dragged)

        self.sample_page = SamplePage(self)
        self.identify_page = IdentifyPage(self)
        self.field_page = FieldPage(self)
        self.template_page = TemplatePage(self)
        for page in (self.sample_page, self.identify_page, self.field_page, self.template_page):
            self.addPage(page)

        self.currentIdChanged.connect(self._move_preview)

    # ------------------------------------------------------------- nội bộ

    def _move_preview(self, _page_id: int) -> None:
        page = self.currentPage()
        holder = getattr(page, "placeholder", None)
        if holder is not None and self.preview.parent() is not holder:
            holder.layout().addWidget(self.preview)
            self.preview.setVisible(True)
        # Chỉ bước 3 mới có chế độ kéo vùng; các bước khác luôn về chế độ chọn chữ
        if isinstance(page, FieldPage):
            page._on_mode_changed()
        else:
            self.preview.set_mode("text")

    def _on_text_selected(self, text: str, _words) -> None:
        self.state.selected_text = text
        page = self.currentPage()
        if isinstance(page, FieldPage):
            page.on_selection(text)
        elif isinstance(page, IdentifyPage):
            page.on_selection(text)

    def _on_rect_dragged(self, bbox: tuple) -> None:
        """Người dùng kéo xong 1 khung: quy về Zone theo tỉ lệ trang và đọc thử text trong đó."""
        if self.preview.mode != "zone":
            return
        page = self.preview.current_page()
        if page is None or not page.width or not page.height:
            return

        zone = zone_from_bbox(bbox, page.width, page.height, page.index, padding=0.0)
        self.state.selected_zone = zone
        # KHÔNG gộp xuống dòng: lúc chạy thật app đọc vùng có xuống dòng, bản xem
        # trước phải giống hệt thì cách lọc theo dòng mới đúng.
        self.state.selected_zone_text = text_in_zone(page, zone).strip()
        current = self.currentPage()
        if isinstance(current, FieldPage):
            current.on_zone(zone, self.state.selected_zone_text)

    def load_sample(self, path: Path) -> None:
        """Mở file mẫu, chạy tầng 0 (text/OCR) rồi đưa vào khung xem trang."""
        self.state.close()
        try:
            doc = PdfDocument(path, self.config.passwords)
        except Exception as exc:
            QMessageBox.warning(self, "Không mở được file", str(exc))
            return

        ocr = OcrEngine(
            self.config.ocr.tesseract_path,
            self.config.ocr.languages,
            self.config.ocr.dpi,
            self.config.ocr.tessdata_path,
        )
        extractor = Extractor(self.config, [], ocr=ocr)
        try:
            document = extractor.read_document(doc)
        except Exception as exc:
            logger.exception("Đọc file mẫu thất bại")
            QMessageBox.warning(self, "Không đọc được nội dung", str(exc))
            doc.close()
            return

        self.state.doc = doc
        self.state.sample_path = path
        self.state.document = document
        self.state.profile.samples = [str(path)]
        self.preview.load_document(doc, document.pages, dpi=150)
        self._move_preview(self.currentId())

    # ------------------------------------------------------------- kết thúc

    def accept(self) -> None:
        profile = self.state.profile
        if not profile.fields:
            QMessageBox.warning(self, "Chưa có field", "Profile cần ít nhất 1 field.")
            return
        profile.version = 0
        self.saved_profile = self.store.save(profile, bump_version=True)
        self.state.close()

        required = [f.label for f in profile.fields if f.required]
        QMessageBox.information(
            self,
            "Đã lưu",
            f"Đã tạo profile “{profile.name}” (version {self.saved_profile.version}).\n"
            f"Field bắt buộc: {', '.join(required) or 'không có'}\n"
            f"File mẫu đã lưu để chạy regression test khi bạn sửa rule về sau.",
        )
        super().accept()

    def reject(self) -> None:
        self.state.close()
        super().reject()

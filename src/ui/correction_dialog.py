"""Learning Loop — biến 1 lần sửa tay thành rule, nhưng phải qua duyệt của người dùng.

Luồng: user sửa field trong Preview -> app hỏi "Tạo rule từ chỉnh sửa này?" -> đọc lại
file để lấy text -> đề xuất regex (và cả vùng nếu định vị được giá trị trên trang) ->
người dùng chọn -> chạy regression trên bộ file mẫu -> chỉ khi đó mới ghi vào profile.

App KHÔNG bao giờ tự sửa rule. Mọi đường trong file này đều dừng ở nút bấm của người dùng.
"""

from __future__ import annotations

import logging

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QLabel,
    QLineEdit,
    QMessageBox,
    QRadioButton,
    QVBoxLayout,
)

from ..core.config import AppConfig
from ..core.extractor import Extractor
from ..core.models import DocumentText, FieldSpec, FileJob, Profile, Zone
from ..core.ocr import OcrEngine
from ..core.pdfdoc import PdfDocument
from ..core.regression import run_regression
from ..core.rule_builder import generate_candidates, zone_from_bbox
from ..core.rules import ProfileStore, run_regex_field
from ..core.textloc import find_word_span
from ..core.zonal import text_in_zone

logger = logging.getLogger(__name__)


def read_document(config: AppConfig, path) -> DocumentText | None:
    """Đọc lại tầng 0 của 1 file để có text và vị trí từ — chỉ chạy khi user yêu cầu."""
    try:
        with PdfDocument(path, config.passwords) as doc:
            ocr = OcrEngine(
                config.ocr.tesseract_path,
                config.ocr.languages,
                config.ocr.dpi,
                config.ocr.tessdata_path,
            )
            return Extractor(config, [], ocr=ocr).read_document(doc)
    except Exception as exc:
        logger.warning("Không đọc lại được file để đề xuất rule: %s", exc)
        return None


def propose_zone(document: DocumentText, value: str) -> tuple[Zone, str] | None:
    """Đề xuất vùng bao quanh giá trị, kèm text đọc được trong vùng đó."""
    for page in document.pages:
        words = find_word_span(page, value)
        if not words or not page.width or not page.height:
            continue
        bbox = (
            min(w.x0 for w in words),
            min(w.y0 for w in words),
            max(w.x1 for w in words),
            max(w.y1 for w in words),
        )
        zone = zone_from_bbox(bbox, page.width, page.height, page.index, padding=0.012)
        return zone, " ".join(text_in_zone(page, zone).split())
    return None


class CorrectionRuleDialog(QDialog):
    """Đề xuất rule từ 1 lần sửa tay. Không có đường nào tự lưu — phải bấm Duyệt."""

    def __init__(
        self,
        config: AppConfig,
        store: ProfileStore,
        profile: Profile,
        job: FileJob,
        field_name: str,
        new_value: str,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Tạo rule từ chỉnh sửa này?")
        self.resize(760, 620)
        self.config = config
        self.store = store
        self.profile = profile
        self.job = job
        self.field_name = field_name
        self.new_value = new_value
        self.saved_profile: Profile | None = None

        self.document = read_document(config, job.source)
        self.zone_proposal = (
            propose_zone(self.document, new_value) if self.document else None
        )
        self.candidates = (
            generate_candidates(self.document.text, new_value) if self.document else []
        )

        self._options: list[tuple[QRadioButton, str, object]] = []
        self._build_ui()

    # ------------------------------------------------------------------ UI

    def _build_ui(self) -> None:
        spec = self.profile.field_by_name(self.field_name)
        label = spec.label if spec else self.field_name

        header = QLabel(
            f"Bạn vừa sửa <b>{label}</b> thành <b>{self.new_value}</b> trên "
            f"<i>{self.job.source.name}</i>.<br>"
            "Muốn app tự lấy đúng giá trị này ở những file sau không?"
        )
        header.setWordWrap(True)

        box = QGroupBox("Cách app sẽ tìm giá trị — chọn 1")
        box_layout = QVBoxLayout(box)

        if self.document is None:
            box_layout.addWidget(
                QLabel("Không đọc lại được file gốc nên chưa đề xuất được cách tìm.")
            )
        else:
            for candidate in self.candidates:
                button = QRadioButton(candidate.explanation)
                button.setToolTip(candidate.pattern)
                box_layout.addWidget(button)
                self._options.append((button, "regex", candidate))

            if self.zone_proposal is not None:
                zone, preview = self.zone_proposal
                button = QRadioButton(
                    f"Lấy theo VÙNG trên trang {zone.page + 1} (chỗ giá trị đang nằm) — "
                    f"đọc được: “{preview[:60]}”"
                )
                button.setToolTip(
                    "Dùng khi nhãn hay đổi nhưng vị trí trên biểu mẫu thì cố định."
                )
                box_layout.addWidget(button)
                self._options.append((button, "zone", zone))

            if not self._options:
                box_layout.addWidget(
                    QLabel(
                        "Không sinh được cách tìm nào cho giá trị này — có thể giá trị "
                        "không xuất hiện nguyên văn trong nội dung file."
                    )
                )
            else:
                self._options[0][0].setChecked(True)

        self.keep_old = QCheckBox("Giữ lại các cách tìm cũ làm dự phòng")
        self.keep_old.setChecked(True)
        self.keep_old.setToolTip(
            "Cách mới được đặt lên đầu; cách cũ vẫn chạy nếu cách mới không trúng."
        )

        self.test_result = QLabel()
        self.test_result.setWordWrap(True)

        self.note = QLineEdit()
        self.note.setPlaceholderText("Ghi chú (không bắt buộc)")

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Duyệt và thêm vào rule")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Để sau")
        buttons.accepted.connect(self._approve)
        buttons.rejected.connect(self.reject)
        self.ok_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.ok_button.setEnabled(bool(self._options))

        footer = QLabel(
            "App sẽ chạy regression test trên bộ file mẫu của profile trước khi lưu, và "
            "tạo version mới để bạn rollback được nếu thấy sai."
        )
        footer.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.addWidget(header)
        layout.addWidget(box)
        layout.addWidget(self.keep_old)
        layout.addWidget(self.test_result)
        layout.addWidget(self.note)
        layout.addStretch(1)
        layout.addWidget(footer)
        layout.addWidget(buttons)

        self._update_test()
        for button, _kind, _payload in self._options:
            button.toggled.connect(self._update_test)

    # -------------------------------------------------------------- kiểm thử

    def selected_option(self) -> tuple[str, object] | None:
        for button, kind, payload in self._options:
            if button.isChecked():
                return kind, payload
        return None

    def build_field(self) -> FieldSpec | None:
        """Dựng FieldSpec mới cho field đang sửa, dựa trên lựa chọn hiện tại."""
        option = self.selected_option()
        if option is None:
            return None
        kind, payload = option

        old = self.profile.field_by_name(self.field_name)
        spec = FieldSpec.from_dict(old.to_dict()) if old else FieldSpec(name=self.field_name)

        if kind == "regex":
            patterns = [payload.pattern]
            if self.keep_old.isChecked() and old:
                patterns += [p for p in old.patterns if p != payload.pattern]
            spec.patterns = patterns
        else:
            spec.zone = payload
            spec.zone_filter = "none"
            if not self.keep_old.isChecked():
                spec.patterns = []
        return spec

    def _update_test(self) -> None:
        spec = self.build_field()
        if spec is None or self.document is None:
            self.test_result.setText("")
            return

        found = run_regex_field(spec, self.document) if spec.patterns else None
        value = found.value if found else ""
        if not value and spec.zone is not None:
            page = next(
                (p for p in self.document.pages if p.index == spec.zone.page), None
            )
            value = " ".join(text_in_zone(page, spec.zone).split()) if page else ""

        if value == self.new_value:
            self.test_result.setText(f"OK — chạy thử trên chính file này: ra đúng “{value}”")
            self.test_result.setStyleSheet("QLabel { color: #1a7f37; font-weight: 600; }")
        elif value:
            self.test_result.setText(f"LỆCH — ra “{value}”, không khớp giá trị bạn vừa sửa")
            self.test_result.setStyleSheet("QLabel { color: #9a6700; font-weight: 600; }")
        else:
            self.test_result.setText("KHÔNG KHỚP — cách này không lấy được gì trên file này")
            self.test_result.setStyleSheet("QLabel { color: #cf222e; font-weight: 600; }")

    # ---------------------------------------------------------------- duyệt

    def _approve(self) -> None:
        spec = self.build_field()
        if spec is None:
            return

        draft = Profile.from_dict(self.profile.to_dict())
        draft.fields = [f for f in draft.fields if f.name != spec.name] + [spec]

        report = run_regression(self.profile, draft, draft.samples, config=self.config)
        if report.sample_count and report.has_regression:
            answer = QMessageBox.warning(
                self,
                "Rule mới làm field khác kém đi",
                report.summary_vi() + "\n\nVẫn thêm vào profile?",
                QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Cancel,
            )
            if answer != QMessageBox.StandardButton.Save:
                return

        self.saved_profile = self.store.save(draft, bump_version=True)
        logger.info(
            "Đã thêm rule từ chỉnh sửa tay: %s.%s -> v%s",
            draft.name, spec.name, self.saved_profile.version,
        )
        summary = report.summary_vi() if report.sample_count else "Profile chưa có file mẫu."
        QMessageBox.information(
            self,
            "Đã thêm vào rule",
            f"Profile “{draft.name}” giờ ở version {self.saved_profile.version}.\n\n"
            f"{summary}\n\nMuốn quay lại thì vào Quản lý rule > Lịch sử version.",
        )
        self.accept()

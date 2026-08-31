"""Test tầng GUI ở chế độ offscreen — không mở cửa sổ thật, không hộp thoại modal."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt  # noqa: E402
from src.core.bootstrap import build_context  # noqa: E402
from src.core.models import ExtractedField, FileJob, JobStatus, Layer, PageText, Word  # noqa: E402
from src.core.pipeline import Pipeline  # noqa: E402
from src.ui.pdf_view import PdfPageView  # noqa: E402
from src.ui.preview_model import COL_NEW, COL_STATUS, FieldsModel, PreviewModel  # noqa: E402
from src.ui.rule_builder_wizard import FieldDialog, RuleBuilderWizard  # noqa: E402
from src.ui.settings_dialog import SettingsDialog  # noqa: E402


def make_job(tmp_path: Path, **kw) -> FileJob:
    source = tmp_path / "goc.pdf"
    source.write_bytes(b"%PDF-1.4")
    job = FileJob(source=source, profile_id="inv", profile_name="Invoice")
    job.status = JobStatus.PENDING
    job.new_name = "2026-03-15_INV_A1.pdf"
    job.dest_dir = tmp_path / "out"
    job.fields = {
        "number": ExtractedField(
            name="number", value="A1", raw_value="Invoice No.: A1",
            layer=Layer.REGEX, rule_id="pattern[0]", page=0,
        )
    }
    for k, v in kw.items():
        setattr(job, k, v)
    return job


class TestPreviewModel:
    def test_hien_du_cot(self, qapp, tmp_path):
        model = PreviewModel()
        model.set_jobs([make_job(tmp_path)])
        assert model.rowCount() == 1
        assert model.columnCount() == 7
        assert model.data(model.index(0, COL_STATUS)) == "Chờ"
        assert model.data(model.index(0, 1)) == "goc.pdf"
        assert model.data(model.index(0, COL_NEW)) == "2026-03-15_INV_A1.pdf"

    def test_chi_cot_ten_moi_sua_duoc(self, qapp, tmp_path):
        model = PreviewModel()
        model.set_jobs([make_job(tmp_path)])
        editable = Qt.ItemFlag.ItemIsEditable
        assert model.flags(model.index(0, COL_NEW)) & editable
        assert not model.flags(model.index(0, 1)) & editable

    def test_khong_cho_sua_ten_cua_file_loi(self, qapp, tmp_path):
        model = PreviewModel()
        model.set_jobs([make_job(tmp_path, status=JobStatus.ERROR)])
        assert not model.flags(model.index(0, COL_NEW)) & Qt.ItemFlag.ItemIsEditable

    def test_sua_ten_goi_handler(self, qapp, tmp_path):
        seen = {}
        model = PreviewModel(rename_handler=lambda job, stem: seen.update(stem=stem))
        model.set_jobs([make_job(tmp_path)])
        assert model.setData(model.index(0, COL_NEW), "TEN-MOI", Qt.ItemDataRole.EditRole)
        assert seen["stem"] == "TEN-MOI"

    def test_bo_qua_ten_rong(self, qapp, tmp_path):
        model = PreviewModel(rename_handler=lambda job, stem: None)
        model.set_jobs([make_job(tmp_path)])
        assert not model.setData(model.index(0, COL_NEW), "   ", Qt.ItemDataRole.EditRole)

    def test_canh_bao_duoc_to_mau_nen(self, qapp, tmp_path):
        model = PreviewModel()
        model.set_jobs([make_job(tmp_path, warnings=["Trùng số chứng từ"])])
        assert model.data(model.index(0, 0), Qt.ItemDataRole.BackgroundRole) is not None

    def test_tooltip_co_tang_pipeline(self, qapp, tmp_path):
        model = PreviewModel()
        model.set_jobs([make_job(tmp_path, layers_used=[Layer.TEXT, Layer.BARCODE])])
        tip = model.data(model.index(0, 0), Qt.ItemDataRole.ToolTipRole)
        assert "Barcode/QR" in tip


class TestFieldsModel:
    def test_hien_nguon_cua_field(self, qapp, tmp_path):
        model = FieldsModel()
        model.set_job(make_job(tmp_path))
        assert model.data(model.index(0, 0)) == "number"
        assert model.data(model.index(0, 1)) == "A1"
        source = model.data(model.index(0, 2))
        assert "Regex" in source and "pattern[0]" in source and "trang 1" in source

    def test_sua_gia_tri_phat_tin_hieu(self, qapp, tmp_path):
        model = FieldsModel()
        job = make_job(tmp_path)
        model.set_job(job)

        seen = []
        model.fieldEdited.connect(lambda *args: seen.append(args))
        assert model.setData(model.index(0, 1), "A2", Qt.ItemDataRole.EditRole)

        assert seen == [("number", "A1", "A2")]
        assert job.fields["number"].value == "A2"
        assert job.fields["number"].edited_by_user is True

    def test_gia_tri_khong_doi_thi_khong_ghi_nhan(self, qapp, tmp_path):
        model = FieldsModel()
        model.set_job(make_job(tmp_path))
        assert not model.setData(model.index(0, 1), "A1", Qt.ItemDataRole.EditRole)

    def test_giu_nguyen_tang_goc_sau_khi_sua(self, qapp, tmp_path):
        model = FieldsModel()
        job = make_job(tmp_path)
        model.set_job(job)
        model.setData(model.index(0, 1), "A2", Qt.ItemDataRole.EditRole)
        assert job.fields["number"].layer == Layer.REGEX  # provenance không mất dấu

    def test_job_rong(self, qapp):
        model = FieldsModel()
        model.set_job(None)
        assert model.rowCount() == 0


class TestPdfPageView:
    def _view(self, qapp) -> PdfPageView:
        from PySide6.QtGui import QPixmap

        view = PdfPageView()
        page = PageText(
            index=0, width=595, height=842,
            words=[
                Word("BILL", 100, 100, 140, 112),
                Word("OF", 145, 100, 165, 112),
                Word("LADING", 170, 100, 230, 112),
                Word("HLCU123", 100, 200, 180, 212),
            ],
        )
        view.load_page(QPixmap(1240, 1754), page, dpi=150)
        return view

    def test_nap_trang_va_co_tu(self, qapp):
        assert self._view(qapp).has_words

    def test_tim_tu_theo_toa_do(self, qapp):
        from PySide6.QtCore import QPointF

        view = self._view(qapp)
        scale = 150 / 72
        word = view._word_at(QPointF(120 * scale, 106 * scale))
        assert word is not None and word.text == "BILL"

    def test_boi_chon_lay_dung_thu_tu_doc(self, qapp):
        from PySide6.QtCore import QRectF

        view = self._view(qapp)
        s = 150 / 72
        rect = QRectF(90 * s, 95 * s, 160 * s, 25 * s)
        words = view._words_in_rect(rect)
        assert [w.text for w in words] == ["BILL", "OF", "LADING"]

    def test_khong_chon_gi_ngoai_vung(self, qapp):
        from PySide6.QtCore import QRectF

        view = self._view(qapp)
        assert view._words_in_rect(QRectF(0, 0, 10, 10)) == []


class TestFieldDialog:
    SAMPLE = "BILL OF LADING\nB/L No.: HLCUSGN2412345\nDate of Issue: 02/04/2026"

    def test_sinh_ung_vien_va_chon_san_cai_dau(self, qapp):
        dialog = FieldDialog(self.SAMPLE, "HLCUSGN2412345")
        assert dialog.candidates
        assert dialog.custom.text() == dialog.candidates[0].pattern
        assert dialog.test_result.text().startswith("OK —")

    def test_moi_ung_vien_deu_co_giai_thich(self, qapp):
        dialog = FieldDialog(self.SAMPLE, "HLCUSGN2412345")
        for button in dialog._buttons:
            assert len(button.text()) > 20

    def test_bao_khi_regex_tu_nhap_khong_trung(self, qapp):
        dialog = FieldDialog(self.SAMPLE, "HLCUSGN2412345")
        dialog.custom.setText(r"KHONG-BAO-GIO-TRUNG (\w+)")
        assert dialog.test_result.text().startswith("KHÔNG KHỚP")

    def test_bao_khi_bat_nham_gia_tri_khac(self, qapp):
        dialog = FieldDialog(self.SAMPLE, "HLCUSGN2412345")
        dialog.custom.setText(r"Date of Issue: (\S+)")
        assert dialog.test_result.text().startswith("LỆCH")

    def test_tao_field_spec_dung(self, qapp):
        dialog = FieldDialog(self.SAMPLE, "HLCUSGN2412345")
        dialog.name.setCurrentText("number")
        dialog.label.setText("Số B/L")
        dialog.required.setChecked(True)
        spec = dialog.field_spec()
        assert spec.name == "number" and spec.required and spec.patterns


class TestRuleBuilderWizard:
    def test_nap_file_mau_va_di_het_4_buoc(self, qapp, isolated_home, pdfs, tmp_path):
        ctx = build_context()
        wizard = RuleBuilderWizard(ctx.config, ctx.store)
        try:
            assert not wizard.sample_page.isComplete()

            wizard.load_sample(pdfs["bill_of_lading"])
            assert wizard.state.document is not None
            assert wizard.sample_page.isComplete()
            assert "BILL OF LADING" in wizard.state.text

            # Bước 2 — điều kiện nhận diện tạo từ chữ đang chọn
            wizard.state.selected_text = "BILL OF LADING"
            wizard.identify_page.name.setText("BL thử")
            wizard.identify_page.doctype.setText("BL")
            wizard.identify_page._add(wizard.identify_page.conditions)
            wizard.state.selected_text = "PACKING LIST"
            wizard.identify_page._add(wizard.identify_page.excludes)
            assert wizard.identify_page.isComplete()
            assert wizard.identify_page.validatePage()
            assert wizard.state.profile.conditions[0].value == "BILL OF LADING"
            assert wizard.state.profile.exclude_conditions[0].value == "PACKING LIST"

            # Bước 3 — thêm field
            from src.core.models import FieldSpec

            wizard.state.profile.fields = [
                FieldSpec(
                    name="number", label="Số B/L", required=True,
                    patterns=[r"B/L\s*No\.[\s:.\-#]*([A-Z0-9]+)"],
                )
            ]
            wizard.field_page._refresh()
            assert wizard.field_page.isComplete()
            assert "HLCUSGN2412345" in wizard.field_page.fields.item(0).text()

            # Bước 4 — template + xem trước
            wizard.template_page.initializePage()
            wizard.template_page.template.setText("{doctype}_{number}")
            assert wizard.template_page.preview.text() == "BL_HLCUSGN2412345.pdf"
            assert wizard.template_page.validatePage()
        finally:
            wizard.state.close()
            ctx.close()

    def test_luu_profile_va_ghi_lai_file_mau(self, qapp, isolated_home, pdfs, monkeypatch):
        from PySide6.QtWidgets import QMessageBox

        monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
        ctx = build_context()
        wizard = RuleBuilderWizard(ctx.config, ctx.store)
        try:
            wizard.load_sample(pdfs["bill_of_lading"])
            from src.core.models import FieldSpec, MatchCondition

            wizard.state.profile.name = "BL thử"
            wizard.state.profile.doctype = "BL"
            wizard.state.profile.conditions = [MatchCondition(value="BILL OF LADING")]
            wizard.state.profile.fields = [
                FieldSpec(name="number", patterns=[r"B/L\s*No\.[\s:.\-#]*([A-Z0-9]+)"])
            ]
            wizard.accept()

            saved = wizard.saved_profile
            assert saved is not None and saved.version == 1
            assert saved.samples == [str(pdfs["bill_of_lading"])]
            assert ctx.store.get(saved.id).name == "BL thử"
        finally:
            ctx.close()

    def test_khong_cho_luu_profile_khong_co_field(self, qapp, isolated_home, pdfs, monkeypatch):
        from PySide6.QtWidgets import QMessageBox

        warned = []
        monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warned.append(a))
        ctx = build_context()
        wizard = RuleBuilderWizard(ctx.config, ctx.store)
        try:
            wizard.load_sample(pdfs["invoice"])
            wizard.state.profile.name = "Thiếu field"
            wizard.accept()
            assert warned
            assert wizard.saved_profile is None
        finally:
            ctx.close()


class TestSettingsDialog:
    def test_nap_cau_hinh_vao_form(self, qapp, config, bundled_profiles):
        config.strip_accents = True
        config.workers = 7
        dialog = SettingsDialog(config, bundled_profiles)
        assert dialog.strip_accents.isChecked()
        assert dialog.workers.value() == 7
        assert dialog.ai_enabled.isChecked() is False  # AI luôn mặc định tắt

    def test_luu_ghi_nguoc_vao_config(self, qapp, config, bundled_profiles, monkeypatch):
        monkeypatch.setattr("src.ui.settings_dialog.save_config", lambda c: None)
        monkeypatch.setattr("src.ui.settings_dialog.set_api_key", lambda *a, **k: True)

        dialog = SettingsDialog(config, bundled_profiles)
        dialog.workers.setValue(9)
        dialog.strip_accents.setChecked(True)
        dialog.mode.setCurrentIndex(1)
        dialog._save()

        assert config.workers == 9
        assert config.strip_accents is True
        assert config.mode == "move"

    def test_khong_luu_khi_thieu_output(self, qapp, config, bundled_profiles, monkeypatch):
        from PySide6.QtWidgets import QMessageBox

        warned = []
        monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warned.append(a))
        dialog = SettingsDialog(config, bundled_profiles)
        dialog.output_root.setText("")
        dialog._save()
        assert warned

    def test_preset_ai_dien_base_url(self, qapp, config, bundled_profiles):
        dialog = SettingsDialog(config, bundled_profiles)
        dialog.ai_preset.setCurrentText("Ollama (chạy trên máy)")
        assert dialog.ai_base_url.text() == "http://localhost:11434/v1"

    def test_canh_bao_gui_du_lieu_ra_ngoai(self, qapp, config, bundled_profiles):
        from src.ui.settings_dialog import AI_WARNING

        assert "gửi" in AI_WARNING and "Ollama" in AI_WARNING


class TestMainWindow:
    def _window(self, ctx):
        from src.ui.main_window import MainWindow

        return MainWindow(ctx)

    def test_mo_cua_so_khong_loi(self, qapp, isolated_home, output_root):
        ctx = build_context()
        ctx.config.output_root = str(output_root)
        window = self._window(ctx)
        try:
            assert window.acceptDrops()
            assert window.counts.text() == "Chưa có file nào."
            assert not window.act_apply.isEnabled()  # chưa có job thì không cho áp dụng
        finally:
            window.close()
            ctx.close()

    def test_nap_duong_dan_va_dem_file(self, qapp, isolated_home, output_root, pdfs, tmp_path):
        import shutil

        folder = tmp_path / "in"
        folder.mkdir()
        shutil.copy2(pdfs["invoice"], folder / "a.pdf")
        shutil.copy2(pdfs["bill_of_lading"], folder / "b.pdf")

        ctx = build_context()
        ctx.config.output_root = str(output_root)
        window = self._window(ctx)
        try:
            window._add_paths([folder])
            assert "2 file PDF" in window.counts.text()
        finally:
            window.close()
            ctx.close()

    def test_sua_field_dung_lai_ten_va_ghi_correction(
        self, qapp, isolated_home, output_root, pdfs, tmp_path, monkeypatch
    ):
        import shutil

        from PySide6.QtWidgets import QMessageBox

        # Sau khi sửa field, app hỏi "Tạo rule từ chỉnh sửa này?" — ở đây trả lời Không
        monkeypatch.setattr(
            QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No
        )

        folder = tmp_path / "in"
        folder.mkdir()
        shutil.copy2(pdfs["invoice"], folder / "a.pdf")

        ctx = build_context()
        ctx.config.output_root = str(output_root)
        ctx.config.ocr.enabled = False
        window = self._window(ctx)
        try:
            pipeline = Pipeline(ctx.config, ctx.profiles, ctx.db)
            window.pipeline = pipeline
            jobs = pipeline.plan([folder])
            window.preview_model.set_jobs(jobs)
            window.table.selectRow(0)

            job = jobs[0]
            old_name = job.new_name
            window.fields_model.setData(
                window.fields_model.index(
                    sorted(job.fields).index("number"), 1
                ),
                "INV-SUA-TAY",
                Qt.ItemDataRole.EditRole,
            )

            assert job.new_name != old_name
            assert "INV-SUA-TAY" in job.new_name
            corrections = pipeline.learning.corrections(profile_id=job.profile_id)
            assert corrections and corrections[0]["new_value"] == "INV-SUA-TAY"
            assert corrections[0]["status"] == "new"  # phải chờ người dùng duyệt
        finally:
            window.close()
            ctx.close()

    def test_dem_trang_thai_tren_thanh_trang_thai(self, qapp, isolated_home, output_root, tmp_path):
        ctx = build_context()
        ctx.config.output_root = str(output_root)
        window = self._window(ctx)
        try:
            window.preview_model.set_jobs(
                [make_job(tmp_path), make_job(tmp_path, status=JobStatus.ERROR)]
            )
            window._update_counts()
            text = window.counts.text()
            assert "Chờ: 1" in text and "Lỗi: 1" in text and "tổng 2" in text
        finally:
            window.close()
            ctx.close()

    def test_log_panel_nhan_duoc_log(self, qapp, isolated_home, output_root):
        import logging

        ctx = build_context()
        ctx.config.output_root = str(output_root)
        window = self._window(ctx)
        try:
            logging.getLogger("src.core.test").warning("thông điệp thử")
            assert "thông điệp thử" in window.log_view.toPlainText()
        finally:
            window.close()
            ctx.close()

"""Test tầng GUI ở chế độ offscreen — không mở cửa sổ thật, không hộp thoại modal."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox, QTextBrowser  # noqa: E402
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
            assert "tổng 2" in window.counts.text() or "2 file PDF" in window.counts.text()
            assert window.preview_model.rowCount() == 2
        finally:
            window.close()
            ctx.close()

    def test_sua_field_dung_lai_ten_va_ghi_correction(
        self, qapp, isolated_home, output_root, pdfs, tmp_path, monkeypatch
    ):
        import shutil


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

    def test_settings_dialog_presets(self, qapp, monkeypatch):
        import src.ui.settings_dialog as sd
        monkeypatch.setattr(sd.QMessageBox, "information", lambda *a, **k: None)

        from src.core.config import AppConfig
        dlg = SettingsDialog(AppConfig(), [])

        # Áp dụng preset Siêu tốc
        dlg._apply_quick_preset("fast")
        assert dlg.ocr_enabled.isChecked() is False
        assert dlg.barcode_enabled.isChecked() is False
        assert dlg.workers.value() == 6

        # Áp dụng preset Quét sâu
        dlg._apply_quick_preset("deep")
        assert dlg.ocr_enabled.isChecked() is True
        assert dlg.ocr_max_pages.value() == 5
        assert dlg.barcode_enabled.isChecked() is True

        # Áp dụng preset Mặc định chuẩn
        dlg._apply_quick_preset("default")
        assert dlg.ocr_enabled.isChecked() is True
        assert dlg.ocr_max_pages.value() == 3
        assert dlg.subfolder_enabled.isChecked() is True
        dlg.close()

    def test_quick_guide_dialog(self, qapp, isolated_home, output_root):
        from src.ui.main_window import QuickGuideDialog
        from PySide6.QtWidgets import QLabel
        ctx = build_context()
        ctx.config.output_root = str(output_root)
        window = self._window(ctx)
        try:
            guide = QuickGuideDialog(window)
            assert "PDF Batch Renamer" in guide.windowTitle()
            labels = guide.findChildren(QLabel)
            all_text = " ".join(l.text() for l in labels if l.text())
            assert "BƯỚC 1" in all_text or "BUOC 1" in all_text
            assert "BƯỚC 2" in all_text or "BUOC 2" in all_text
            assert "BƯỚC 3" in all_text or "BUOC 3" in all_text
        finally:
            window.close()
            ctx.close()

    def test_open_in_explorer_and_links(self, qapp, isolated_home, output_root, tmp_path, monkeypatch):
        from src.ui.qt_helpers import open_in_explorer
        opened = []
        monkeypatch.setattr("os.startfile", lambda p: opened.append(str(p)))

        test_dir = tmp_path / "test_dir"
        test_dir.mkdir()
        test_file = test_dir / "sample.pdf"
        test_file.write_bytes(b"%PDF-1.4")

        assert open_in_explorer(test_file) is True
        assert opened and opened[-1] == str(test_file)

        assert open_in_explorer(test_dir) is True
        assert opened and opened[-1] == str(test_dir)

        # File không tồn tại nhưng thư mục cha tồn tại
        non_exist = test_dir / "not_exist.pdf"
        assert open_in_explorer(non_exist) is True
        assert opened and opened[-1] == str(test_dir)

        # Cả thư mục lẫn file đều không tồn tại
        assert open_in_explorer(tmp_path / "fake" / "fake.pdf") is False

    def test_main_window_double_click_and_detail_links(self, qapp, isolated_home, output_root, tmp_path, monkeypatch):
        opened = []
        monkeypatch.setattr("os.startfile", lambda p: opened.append(str(p)))

        ctx = build_context()
        ctx.config.output_root = str(output_root)
        window = self._window(ctx)
        try:
            job = make_job(tmp_path)
            dest_dir = tmp_path / "out"
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest_file = dest_dir / job.new_name
            dest_file.write_bytes(b"%PDF-1.4")
            job.dest_dir = dest_dir

            window.preview_model.set_jobs([job])
            window.table.selectRow(0)

            # Double click cột Thư mục đích (COL_DEST = 3)
            idx_dest = window.preview_model.index(0, 3)
            window._on_table_double_clicked(idx_dest)
            assert str(dest_dir) in opened

            # Double click cột Tên mới (COL_NEW = 2)
            idx_new = window.preview_model.index(0, 2)
            window._on_table_double_clicked(idx_new)
            assert str(dest_file) in opened

            # Double click cột Tên cũ (COL_OLD = 1)
            idx_old = window.preview_model.index(0, 1)
            window._on_table_double_clicked(idx_old)
            assert str(job.source) in opened

            # Click link trong detail panel
            window._on_detail_link_clicked("dest_file")
            assert str(dest_file) in opened

            window._on_detail_link_clicked("source")
            assert str(job.source) in opened

            window._on_detail_link_clicked("dest_dir")
            assert str(dest_dir) in opened

            # Xóa job khỏi bảng
            window._remove_job_at(0)
            assert len(window.preview_model.jobs) == 0
        finally:
            window.close()
            ctx.close()

    def test_menubar_structure_and_toolbar(self, qapp, isolated_home, output_root):
        ctx = build_context()
        ctx.config.output_root = str(output_root)
        window = self._window(ctx)
        try:
            # Menu bar ẩn để tránh thừa hàng
            assert window.menuBar().isVisible() is False

            # Kiểm tra các action chính có icon và gắn đúng phím tắt
            assert not window.act_files.icon().isNull()
            assert not window.act_scan.icon().isNull()
            assert not window.act_apply.icon().isNull()
            assert not window.act_settings.icon().isNull()
            assert not window.act_guide.icon().isNull()

            assert window.act_files.shortcut().toString() == "Ctrl+O"
            assert window.act_scan.shortcut().toString() == "F5"
            assert window.act_apply.shortcut().toString() == "Ctrl+Return"
            assert window.act_undo.shortcut().toString() == "Ctrl+Z"
            assert window.act_settings.shortcut().toString() == "F10"
            assert window.act_guide.shortcut().toString() == "F1"

            # Window icon đã được thiết lập
            assert not window.windowIcon().isNull()
        finally:
            window.close()
            ctx.close()

    def test_pdf_viewer_widget_and_preview_dock(self, qapp, isolated_home, output_root, tmp_path, pdfs):
        from src.ui.pdf_view import PdfViewerWidget

        viewer = PdfViewerWidget()
        try:
            # Khi chưa nạp file
            assert viewer.file_name_label.text() == "Chưa chọn file"
            assert viewer.page_label.text() == "0 / 0"

            # Nạp file PDF mẫu
            viewer.load_file(pdfs["invoice"])
            assert viewer._total_pages > 0
            assert viewer.page_label.text().startswith("1 /")

            # Chuyển trang và zoom
            viewer._next_page()
            viewer._prev_page()
            viewer.view.zoom(1.2)
            viewer.view.fit_width()

            # Clear
            viewer.clear()
            assert viewer.file_name_label.text() == "Chưa chọn file"
        finally:
            viewer.close_document()
            viewer.close()

    def test_main_window_pdf_preview_integration(self, qapp, isolated_home, output_root, tmp_path, pdfs):
        ctx = build_context()
        ctx.config.output_root = str(output_root)
        window = self._window(ctx)
        try:
            window.show()
            assert window.preview_dock is not None
            assert window.pdf_viewer is not None
            assert not window.act_toggle_preview.icon().isNull()

            # Toggle dock
            window.act_toggle_preview.setChecked(False)
            assert window.preview_dock.isHidden()
            window.act_toggle_preview.setChecked(True)
            assert not window.preview_dock.isHidden()

            # Chọn dòng có file PDF
            job = make_job(tmp_path)
            job.source = pdfs["invoice"]
            window.preview_model.set_jobs([job])
            window.table.selectRow(0)

            assert window.pdf_viewer._current_path == pdfs["invoice"]
            assert window.pdf_viewer._total_pages > 0
        finally:
            window.close()
            ctx.close()

    def test_pdf_page_view_ctrl_multi_selection(self, qapp, isolated_home, output_root, tmp_path, pdfs):
        from src.core.models import PageText, Word
        from src.ui.pdf_view import PdfPageView

        view = PdfPageView()
        # Giả lập 2 dòng từ
        words = [
            Word("HAI", 10.0, 20.0, 30.0, 30.0),
            Word("ANH", 35.0, 20.0, 55.0, 30.0),
            Word("BK/0687", 10.0, 40.0, 50.0, 50.0),
            Word("T07.26", 55.0, 40.0, 85.0, 50.0),
        ]
        page = PageText(index=0, width=200.0, height=200.0, words=words)
        from PySide6.QtGui import QPixmap
        pix = QPixmap(400, 400)
        view.load_page(pix, page, dpi=200)

        # Chọn dòng 1
        view._selection = [words[0], words[1]]
        assert view.selected_text() == "HAI ANH"

        # Giữ Ctrl và chọn thêm dòng 2
        combined = view._sort_words(view._selection + [words[2], words[3]])
        view._selection = combined
        assert view.selected_text() == "HAI ANH BK/0687 T07.26"

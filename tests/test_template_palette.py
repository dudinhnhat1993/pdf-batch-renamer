"""Test palette token ở bước 4 và cách cắt chữ theo từng cột ở bảng chính."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt  # noqa: E402
from src.core.bootstrap import build_context  # noqa: E402
from src.core.models import FieldSpec  # noqa: E402
from src.ui.main_window import MainWindow  # noqa: E402
from src.ui.preview_model import COL_DEST, COL_NEW, COL_OLD  # noqa: E402
from src.ui.rule_builder_wizard import RuleBuilderWizard  # noqa: E402


@pytest.fixture
def wizard(qapp, isolated_home, pdfs):
    ctx = build_context()
    wiz = RuleBuilderWizard(ctx.config, ctx.store)
    wiz.load_sample(pdfs["bill_of_lading"])
    wiz.state.profile.name = "BL thử"
    wiz.state.profile.doctype = "BL"
    yield wiz
    wiz.state.close()
    ctx.close()


def palette_state(page, token: str) -> str:
    for tok, _label, state in page._token_palette():
        if tok == token:
            return state
    return ""


class TestTokenPalette:
    def test_field_cua_profile_hien_binh_thuong(self, wizard):
        wizard.state.profile.fields = [FieldSpec(name="number", label="Số B/L")]
        page = wizard.template_page
        assert palette_state(page, "{number}") == "field"

    def test_token_chua_co_field_bi_danh_dau(self, wizard):
        wizard.state.profile.fields = [FieldSpec(name="number", label="Số B/L")]
        page = wizard.template_page
        # Chưa tạo field ngày -> {doc_date} phải bị đánh dấu là thiếu
        assert palette_state(page, "{doc_date}") == "missing"
        assert palette_state(page, "{company}") == "missing"

    def test_token_app_tu_sinh_khong_can_field(self, wizard):
        page = wizard.template_page
        assert palette_state(page, "{doctype}") == "auto"
        assert palette_state(page, "{original_name}") == "auto"

    def test_counter_luon_co_trong_palette(self, wizard):
        assert palette_state(wizard.template_page, "{counter}") == "counter"

    def test_tao_field_thi_token_het_bi_danh_dau(self, wizard):
        page = wizard.template_page
        assert palette_state(page, "{doc_date}") == "missing"
        wizard.state.profile.fields = [FieldSpec(name="doc_date", label="Ngày")]
        assert palette_state(page, "{doc_date}") == "field"

    def test_nut_token_thieu_field_co_nhan_rieng(self, wizard):
        page = wizard.template_page
        wizard.state.profile.fields = [FieldSpec(name="number", label="Số B/L")]
        page.initializePage()

        texts = []
        for i in range(page.token_layout.count()):
            row = page.token_layout.itemAt(i).layout()
            if row is None:
                continue
            for j in range(row.count()):
                widget = row.itemAt(j).widget()
                if widget is not None:
                    texts.append(widget.text())
        assert any("{doc_date}" in t and "chưa có field" in t for t in texts)


class TestTemplateWarning:
    def test_canh_bao_token_khong_co_field(self, wizard):
        page = wizard.template_page
        wizard.state.profile.fields = [FieldSpec(name="number", label="Số B/L")]
        page.initializePage()
        page.template.setText("{doc_date}_{number}")

        assert page.missing_tokens() == ["doc_date"]
        assert "KHÔNG có field tương ứng" in page.warning.text()

    def test_khong_canh_bao_khi_du_field(self, wizard):
        page = wizard.template_page
        wizard.state.profile.fields = [
            FieldSpec(name="number", label="Số B/L", patterns=[r"B/L No\.[\s:.\-#]*([A-Z0-9]+)"])
        ]
        page.initializePage()
        page.template.setText("{doctype}_{number}")

        assert page.missing_tokens() == []
        assert "KHÔNG có field" not in page.warning.text()

    def test_token_app_tu_sinh_khong_bi_bao_thieu(self, wizard):
        page = wizard.template_page
        page.initializePage()
        page.template.setText("{original_name}")
        assert page.missing_tokens() == []

    def test_counter_canh_bao_pha_deterministic(self, wizard):
        page = wizard.template_page
        page.initializePage()
        page.template.setText("{doctype}_{counter}")

        assert page.missing_tokens() == []  # counter không phải field thiếu
        assert "deterministic" in page.warning.text()

    def test_xem_truoc_van_chay_khi_thieu_token(self, wizard):
        page = wizard.template_page
        wizard.state.profile.fields = [
            FieldSpec(name="number", label="Số B/L", patterns=[r"B/L No\.[\s:.\-#]*([A-Z0-9]+)"])
        ]
        page.initializePage()
        page.template.setText("{doc_date}_{number}")
        assert "HLCUSGN2412345" in page.preview.text()


class TestColumnElide:
    def test_cot_duong_dan_cat_dau_cot_ten_file_cat_giua(self, qapp, isolated_home, output_root):
        ctx = build_context()
        ctx.config.output_root = str(output_root)
        window = MainWindow(ctx)
        try:
            # Bảng cắt giữa theo mặc định -> áp cho cột tên file mới
            assert window.table.textElideMode() == Qt.TextElideMode.ElideMiddle
            assert window.table.itemDelegateForColumn(COL_NEW) is None

            # Cột đường dẫn dùng delegate cắt ĐẦU để giữ phần đuôi
            for column in (COL_DEST, COL_OLD):
                delegate = window.table.itemDelegateForColumn(column)
                assert delegate is not None
                assert delegate.mode == Qt.TextElideMode.ElideLeft
        finally:
            window.close()
            ctx.close()

    def test_co_cot_theo_noi_dung_nhung_co_tran(self, qapp, isolated_home, output_root, tmp_path):
        from tests.test_ui import make_job

        ctx = build_context()
        ctx.config.output_root = str(output_root)
        window = MainWindow(ctx)
        try:
            job = make_job(tmp_path)
            job.dest_dir = tmp_path / ("thu-muc-rat-dai-" * 20)
            window.preview_model.set_jobs([job])
            window._fit_columns()

            for column, limit in enumerate(window.COLUMN_MAX_WIDTH):
                assert window.table.columnWidth(column) <= limit
        finally:
            window.close()
            ctx.close()

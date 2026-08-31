"""Test phần GUI bổ sung: kéo khung vùng, dock panel field, binding lựa chọn, tooltip cột."""

from __future__ import annotations

import os
import shutil

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtGui import QPixmap  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from src.core.bootstrap import build_context  # noqa: E402
from src.core.models import Layer, MatchCondition, PageText, Profile, Word, Zone  # noqa: E402
from src.core.pipeline import BatchSummary, Pipeline  # noqa: E402
from src.ui.main_window import MainWindow  # noqa: E402
from src.ui.pdf_view import PdfPageView  # noqa: E402
from src.ui.preview_model import (  # noqa: E402
    COL_DEST,
    COL_FIELDS,
    COL_NEW,
    COL_NOTE,
    COL_OLD,
    PreviewModel,
)
from src.ui.rule_builder_wizard import ZoneFieldDialog  # noqa: E402

from tests.test_ui import make_job  # noqa: E402


def make_window(ctx):
    return MainWindow(ctx)


# ------------------------------------------------------------------- vùng


class TestZoneMode:
    def _view(self) -> PdfPageView:
        view = PdfPageView()
        page = PageText(
            index=0,
            width=595,
            height=842,
            words=[Word("BILL", 100, 100, 140, 112), Word("HLCU123", 100, 200, 180, 212)],
        )
        view.load_page(QPixmap(1240, 1754), page, dpi=150)
        view.resize(600, 800)
        return view

    def test_mac_dinh_la_che_do_chon_chu(self, qapp):
        assert self._view().mode == "text"

    def test_doi_sang_che_do_vung_xoa_lua_chon_cu(self, qapp):
        view = self._view()
        view._selection = list(view._page.words)
        view.set_mode("zone")
        assert view.mode == "zone"
        assert view.selected_words() == []

    def test_che_do_la_bi_bo_qua(self, qapp):
        view = self._view()
        view.set_mode("khong-ton-tai")
        assert view.mode == "text"

    def test_keo_khung_o_che_do_vung_khong_boi_chon_chu(self, qapp):
        view = self._view()
        view.set_mode("zone")
        seen = []
        view.rectDragged.connect(seen.append)

        QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(20, 20))
        QTest.mouseMove(view.viewport(), QPoint(200, 220))
        QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(200, 220))

        assert seen, "phải phát tín hiệu vùng đã kéo"
        assert view.selected_words() == []  # chế độ vùng không đụng tới lựa chọn chữ

    def test_keo_o_che_do_chu_thi_van_boi_chon(self, qapp):
        view = self._view()
        seen = []
        view.textSelected.connect(lambda text, words: seen.append(text))

        QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(5, 5))
        QTest.mouseMove(view.viewport(), QPoint(400, 400))
        QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(400, 400))

        assert seen and "BILL" in seen[0]

    def test_khung_da_luu_ve_lai_duoc(self, qapp):
        view = self._view()
        view.set_mode("zone")
        view.set_zone_rect((100, 100, 200, 150))
        assert view._drag_rect is not None
        view.set_zone_rect(None)
        assert view._drag_rect is None

    def test_zone_from_bbox_quy_ve_ti_le_trang(self, qapp):
        from src.core.rule_builder import zone_from_bbox

        zone = zone_from_bbox((59.5, 84.2, 119.0, 168.4), 595, 842, page=2, padding=0.0)
        assert zone.page == 2
        assert round(zone.x0, 2) == 0.1 and round(zone.y0, 2) == 0.1
        assert round(zone.x1, 2) == 0.2 and round(zone.y1, 2) == 0.2


class TestZoneFieldDialog:
    def test_tao_field_vung_dung_thong_tin(self, qapp):
        zone = Zone(page=0, x0=0.1, y0=0.2, x1=0.5, y1=0.3)
        dialog = ZoneFieldDialog(zone, "INV-2026-00871")
        dialog.name.setCurrentText("number")
        dialog.label.setText("Số hóa đơn")
        dialog.required.setChecked(True)

        spec = dialog.field_spec()
        assert spec.name == "number" and spec.required
        assert spec.patterns == []  # field vùng không dùng regex
        assert spec.zone is zone

    def test_field_vung_chay_that_qua_pipeline(self, qapp, config, pdfs):
        """Field tạo bằng kéo khung phải thật sự lấy được giá trị khi chạy pipeline."""
        from src.core.extractor import Extractor

        dialog = ZoneFieldDialog(Zone(page=0, x0=0.0, y0=0.0, x1=1.0, y1=1.0), "xem trước")
        dialog.name.setCurrentText("noi_dung")
        dialog.required.setChecked(True)

        profile = Profile(
            id="zone-test",
            name="Zone test",
            doctype="Z",
            conditions=[MatchCondition(value="COMMERCIAL INVOICE")],
            fields=[dialog.field_spec()],
            template="{noi_dung}",
        )
        result = Extractor(config, [profile]).extract(pdfs["invoice"])
        assert "INV-2026-00871" in result.value("noi_dung")
        assert result.fields["noi_dung"].layer == Layer.ZONAL


# -------------------------------------------------------------------- dock


class TestFieldPanelDock:
    def test_mac_dinh_neo_o_duoi(self, qapp, isolated_home, output_root):
        ctx = build_context()
        ctx.config.output_root = str(output_root)
        window = make_window(ctx)
        try:
            area = window.dockWidgetArea(window.field_dock)
            assert area == Qt.DockWidgetArea.BottomDockWidgetArea
        finally:
            window.close()
            ctx.close()

    def test_neo_ben_phai_khi_config_yeu_cau(self, qapp, isolated_home, output_root):
        ctx = build_context()
        ctx.config.output_root = str(output_root)
        ctx.config.field_panel_area = "right"
        window = make_window(ctx)
        try:
            area = window.dockWidgetArea(window.field_dock)
            assert area == Qt.DockWidgetArea.RightDockWidgetArea
        finally:
            window.close()
            ctx.close()

    def test_chi_cho_neo_phai_hoac_duoi(self, qapp, isolated_home, output_root):
        ctx = build_context()
        ctx.config.output_root = str(output_root)
        window = make_window(ctx)
        try:
            allowed = window.field_dock.allowedAreas()
            assert allowed & Qt.DockWidgetArea.RightDockWidgetArea
            assert allowed & Qt.DockWidgetArea.BottomDockWidgetArea
            assert not (allowed & Qt.DockWidgetArea.LeftDockWidgetArea)
            assert not (allowed & Qt.DockWidgetArea.TopDockWidgetArea)
        finally:
            window.close()
            ctx.close()

    def test_doi_cho_thi_nho_vao_config(self, qapp, isolated_home, output_root):
        from src.core.config import load_config

        ctx = build_context()
        ctx.config.output_root = str(output_root)
        window = make_window(ctx)
        try:
            window.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, window.field_dock)
            window._on_dock_moved(Qt.DockWidgetArea.RightDockWidgetArea)
            assert ctx.config.field_panel_area == "right"
            assert load_config().field_panel_area == "right"  # đã ghi xuống đĩa
        finally:
            window.close()
            ctx.close()


# --------------------------------------------------------- binding lựa chọn


class TestSelectionBinding:
    def _prepared(self, ctx, tmp_path, pdfs, key="invoice", name="inv.pdf"):
        folder = tmp_path / "in"
        folder.mkdir(exist_ok=True)
        shutil.copy2(pdfs[key], folder / name)

        window = make_window(ctx)
        pipeline = Pipeline(ctx.config, ctx.profiles, ctx.db)
        window.pipeline = pipeline
        window._on_plan_done(pipeline.plan([folder]))
        return window

    def test_panel_bam_theo_dong_dang_chon(self, qapp, isolated_home, output_root, tmp_path, pdfs):
        ctx = build_context()
        ctx.config.output_root = str(output_root)
        window = self._prepared(ctx, tmp_path, pdfs)
        try:
            assert window.fields_model.rowCount() > 0
            assert "Chọn 1 dòng" not in window.detail_label.text()
            assert "inv.pdf" in window.detail_label.text()
        finally:
            window.close()
            ctx.close()

    def test_giu_lua_chon_sau_khi_ap_dung(
        self, qapp, isolated_home, output_root, tmp_path, pdfs, monkeypatch
    ):
        from PySide6.QtWidgets import QMessageBox

        # _on_apply_done mở hộp thoại tổng kết — chặn lại kẻo test treo ở modal
        monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)

        ctx = build_context()
        ctx.config.output_root = str(output_root)
        window = self._prepared(ctx, tmp_path, pdfs)
        try:
            window._on_apply_done(BatchSummary(total=1, success=1))
            assert window.table.selectionModel().selectedRows()
            assert "Chọn 1 dòng" not in window.detail_label.text()
        finally:
            window.close()
            ctx.close()

    def test_profile_chung_bao_ro_la_giu_ten_goc(
        self, qapp, isolated_home, output_root, tmp_path, pdfs
    ):
        ctx = build_context()
        ctx.config.output_root = str(output_root)
        window = self._prepared(ctx, tmp_path, pdfs, key="unknown", name="memo.pdf")
        try:
            assert window.fields_model.rowCount() == 0
            assert "giữ nguyên tên gốc" in window.detail_label.text()
            assert "Chung" in window.detail_label.text()
        finally:
            window.close()
            ctx.close()

    def test_xoa_danh_sach_thi_panel_ve_trang_thai_rong(
        self, qapp, isolated_home, output_root, tmp_path, pdfs
    ):
        ctx = build_context()
        ctx.config.output_root = str(output_root)
        window = self._prepared(ctx, tmp_path, pdfs)
        try:
            window._clear()
            assert window.fields_model.rowCount() == 0
            assert "Chưa có file nào" in window.detail_label.text()
        finally:
            window.close()
            ctx.close()


# ------------------------------------------------------------------ tooltip


class TestColumnTooltips:
    def test_moi_cot_dai_deu_co_tooltip_day_du(self, qapp, tmp_path):
        model = PreviewModel()
        job = make_job(tmp_path, warnings=["Trùng số chứng từ"])
        model.set_jobs([job])

        assert str(job.source) in model.data(model.index(0, COL_OLD), Qt.ItemDataRole.ToolTipRole)
        assert model.data(model.index(0, COL_NEW), Qt.ItemDataRole.ToolTipRole).endswith(
            "2026-03-15_INV_A1.pdf"
        )
        assert str(job.dest_dir) == model.data(
            model.index(0, COL_DEST), Qt.ItemDataRole.ToolTipRole
        )
        assert "number = A1" in model.data(model.index(0, COL_FIELDS), Qt.ItemDataRole.ToolTipRole)
        assert "Trùng số chứng từ" in model.data(
            model.index(0, COL_NOTE), Qt.ItemDataRole.ToolTipRole
        )

    def test_khong_co_field_thi_tooltip_noi_ro(self, qapp, tmp_path):
        model = PreviewModel()
        job = make_job(tmp_path)
        job.fields = {}
        model.set_jobs([job])
        tip = model.data(model.index(0, COL_FIELDS), Qt.ItemDataRole.ToolTipRole)
        assert "Không trích được field nào" in tip

    def test_bang_chinh_cat_chu_o_giua(self, qapp, isolated_home, output_root):
        ctx = build_context()
        ctx.config.output_root = str(output_root)
        window = make_window(ctx)
        try:
            assert window.table.textElideMode() == Qt.TextElideMode.ElideMiddle
        finally:
            window.close()
            ctx.close()

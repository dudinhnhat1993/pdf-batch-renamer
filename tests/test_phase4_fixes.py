"""Test 6 điểm sửa đầu Phase 4: đường dẫn tương đối, điểm dừng zonal, glyph, master data."""

from __future__ import annotations

import os
import unicodedata
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.core.models import FieldSpec, MatchCondition, Profile, Zone  # noqa: E402
from src.core.zonal import (  # noqa: E402
    LABEL_RE,
    apply_zone_filter,
    apply_zone_stop,
    count_labels,
    zone_looks_ambiguous,
)

ONE_LINE = "B/L No.: HLCUSGN2412345 Date of Issue: 02/04/2026 Carrier: HAPAG-LLOYD AG"


# ------------------------------------------------ 2 + 6: điểm dừng và heuristic


class TestNhanDienNhan:
    def test_dem_nhan_tren_mot_dong(self):
        assert count_labels(ONE_LINE) == 3

    def test_khong_dem_nham_giua_gia_tri(self):
        # "HLCUSGN2412345" không được coi là nhãn
        assert count_labels("HLCUSGN2412345") == 0

    def test_nhan_phai_dung_dau_dong_hoac_sau_khoang_trang(self):
        assert LABEL_RE.search("xxHLCU Date:") is not None  # "Date:" sau khoảng trắng
        assert LABEL_RE.search("HLCUSGN2412345") is None

    def test_nhan_khong_chua_chu_so(self):
        # nếu cho phép chữ số, regex sẽ ăn lẹm vào giá trị rồi cắt nhầm
        assert LABEL_RE.search("ABC123:") is None


class TestHeuristicNhapNhang:
    def test_phat_hien_qua_so_nhan_du_chi_1_dong(self):
        assert zone_looks_ambiguous(ONE_LINE)

    def test_mot_nhan_mot_gia_tri_van_bi_coi_la_nhap_nhang_vi_nhieu_tu(self):
        assert zone_looks_ambiguous("Carrier: HAPAG LLOYD AG Hamburg")

    def test_gia_tri_don_thi_khong(self):
        assert not zone_looks_ambiguous("HLCUSGN2412345")
        assert not zone_looks_ambiguous("02/04/2026")

    def test_nhieu_dong_van_bi_bat(self):
        assert zone_looks_ambiguous("HLCUSGN2412345\nMSKU2482484")


class TestDiemDung:
    def test_khong_dung_thi_om_het_phan_con_lai(self):
        value = apply_zone_filter(ONE_LINE, "label", "B/L No.")
        assert value.startswith("HLCUSGN2412345")
        assert "Date of Issue" in value  # đúng cái bẫy cần chặn

    def test_dung_tai_nhan_ke_tiep(self):
        assert (
            apply_zone_filter(ONE_LINE, "label", "B/L No.", stop="label") == "HLCUSGN2412345"
        )

    def test_dung_tai_nhan_ke_tiep_cho_nhan_giua_dong(self):
        assert (
            apply_zone_filter(ONE_LINE, "label", "Date of Issue", stop="label") == "02/04/2026"
        )

    def test_dung_tai_hai_khoang_trang(self):
        text = "B/L No.:  HLCUSGN2412345   Date: 02/04/2026"
        assert apply_zone_filter(text, "label", "B/L No.", stop="gap") == "HLCUSGN2412345"

    def test_dung_theo_bieu_thuc(self):
        value = apply_zone_filter(
            ONE_LINE, "label", "B/L No.", stop="regex", stop_value=r"([A-Z]{7}\d{7})"
        )
        assert value == "HLCUSGN2412345"

    def test_bieu_thuc_dung_khong_trung_thi_rong(self):
        assert (
            apply_zone_filter(
                ONE_LINE, "label", "B/L No.", stop="regex", stop_value=r"(KHONG-TRUNG)"
            )
            == ""
        )

    def test_bieu_thuc_hong_khong_lam_chet(self):
        value = apply_zone_filter(
            ONE_LINE, "label", "B/L No.", stop="regex", stop_value="[unclosed"
        )
        assert value.startswith("HLCUSGN2412345")

    def test_khong_co_nhan_ke_tiep_thi_giu_nguyen(self):
        assert apply_zone_stop("25.400 USD", "label") == "25.400 USD"

    def test_diem_dung_chi_ap_dung_cho_loc_theo_nhan(self):
        # lọc theo dòng thì điểm dừng không đụng tới kết quả
        text = "HLCUSGN2412345 Date: x\nMSKU2482484"
        assert apply_zone_filter(text, "line", "2", stop="label") == "MSKU2482484"


class TestDiemDungQuaPipeline:
    def test_chay_that_voi_diem_dung(self, config, pdfs):
        from src.core.extractor import Extractor

        profile = Profile(
            id="stop-test",
            name="Stop test",
            doctype="Z",
            conditions=[MatchCondition(value="COMMERCIAL INVOICE")],
            fields=[
                FieldSpec(
                    name="number",
                    required=True,
                    patterns=[],
                    zone=Zone(page=0, x0=0.0, y0=0.0, x1=1.0, y1=1.0),
                    zone_filter="label",
                    zone_filter_value="Invoice No.:",
                    zone_filter_stop="label",
                )
            ],
            template="{number}",
        )
        result = Extractor(config, [profile]).extract(pdfs["invoice"])
        assert result.value("number") == "INV-2026-00871"

    def test_diem_dung_duoc_luu_va_doc_lai(self, tmp_path):
        from src.core.rules import ProfileStore

        store = ProfileStore(tmp_path / "profiles")
        profile = Profile(
            id="p1",
            name="P1",
            fields=[
                FieldSpec(
                    name="number",
                    zone=Zone(),
                    zone_filter="label",
                    zone_filter_value="B/L No.:",
                    zone_filter_stop="regex",
                    zone_stop_value=r"([A-Z]{7}\d{7})",
                )
            ],
        )
        store.save(profile)
        spec = store.get("p1").fields[0]
        assert spec.zone_filter_stop == "regex"
        assert spec.zone_stop_value == r"([A-Z]{7}\d{7})"


# --------------------------------------------------------- 3: không còn glyph lạ


class TestKhongConKyHieuLa:
    """Ký hiệu như ✔ ✘ ⚠ → không phải font Windows nào cũng có — đã lộ trên ảnh chụp."""

    ALLOWED = set("–—‘’“”…·×")

    def test_khong_con_ky_hieu_unicode_dac_biet_trong_src(self):
        offenders: list[str] = []
        root = Path(__file__).resolve().parents[1] / "src"
        for path in sorted(root.rglob("*.py")):
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                for char in line:
                    if ord(char) < 128 or char in self.ALLOWED:
                        continue
                    category = unicodedata.category(char)
                    if category.startswith("L") or category == "Mn":
                        continue  # chữ cái có dấu tiếng Việt
                    offenders.append(
                        f"{path.name}:{number} {char!r} "
                        f"({unicodedata.name(char, '?')})"
                    )
        assert not offenders, "Còn ký hiệu lạ:\n" + "\n".join(offenders[:20])


# ------------------------------------------------- 1: đường dẫn đích tương đối


pytest.importorskip("PySide6")

from src.ui.preview_model import COL_DEST, PreviewModel  # noqa: E402
from src.ui.rule_builder_wizard import ZoneFieldDialog  # noqa: E402

from tests.test_ui import make_job  # noqa: E402


class TestDuongDanDich:
    def _model(self, tmp_path, dest_name: str = "2026-08-31"):
        model = PreviewModel()
        job = make_job(tmp_path)
        job.dest_dir = tmp_path / "output" / dest_name
        model.set_output_root(tmp_path / "output")
        model.set_jobs([job])
        return model, job

    def test_hien_duong_dan_tuong_doi(self, qapp, tmp_path):
        model, _ = self._model(tmp_path)
        assert model.data(model.index(0, COL_DEST)) == "2026-08-31"

    def test_thu_muc_cach_ly(self, qapp, tmp_path):
        model, _ = self._model(tmp_path, "_Loi")
        assert model.data(model.index(0, COL_DEST)) == "_Loi"

    def test_tooltip_van_la_duong_dan_day_du(self, qapp, tmp_path):
        from PySide6.QtCore import Qt

        model, job = self._model(tmp_path)
        tip = model.data(model.index(0, COL_DEST), Qt.ItemDataRole.ToolTipRole)
        assert tip == str(job.dest_dir)
        assert str(tmp_path) in tip

    def test_ngoai_thu_muc_output_thi_hien_day_du(self, qapp, tmp_path):
        model = PreviewModel()
        job = make_job(tmp_path)
        job.dest_dir = tmp_path / "cho-khac"
        model.set_output_root(tmp_path / "output")
        model.set_jobs([job])
        assert model.data(model.index(0, COL_DEST)) == str(job.dest_dir)

    def test_chua_biet_output_thi_hien_day_du(self, qapp, tmp_path):
        model = PreviewModel()
        job = make_job(tmp_path)
        job.dest_dir = tmp_path / "output" / "2026-08-31"
        model.set_jobs([job])
        assert model.data(model.index(0, COL_DEST)) == str(job.dest_dir)

    def test_cot_co_be_rong_toi_thieu(self, qapp, isolated_home, output_root):
        from src.core.bootstrap import build_context
        from src.ui.main_window import MainWindow

        ctx = build_context()
        ctx.config.output_root = str(output_root)
        window = MainWindow(ctx)
        try:
            window.preview_model.set_jobs([])
            window._fit_columns()
            for column, floor in enumerate(window.COLUMN_MIN_WIDTH):
                assert window.table.columnWidth(column) >= floor
        finally:
            window.close()
            ctx.close()


class TestZoneDialogDiemDung:
    def test_tu_bat_diem_dung_khi_van_dinh_nhieu_gia_tri(self, qapp):
        dialog = ZoneFieldDialog(Zone(), ONE_LINE)
        assert dialog.filter_kind.currentData() == "label"
        assert dialog.stop_kind.currentData() == "label"
        assert dialog.filtered_value() == "HLCUSGN2412345"
        assert dialog.result.text().startswith("OK —")

    def test_field_spec_mang_theo_diem_dung(self, qapp):
        dialog = ZoneFieldDialog(Zone(), ONE_LINE)
        dialog.name.setCurrentText("number")
        spec = dialog.field_spec()
        assert spec.zone_filter == "label"
        assert spec.zone_filter_stop == "label"

    def test_o_diem_dung_chi_bat_khi_loc_theo_nhan(self, qapp):
        dialog = ZoneFieldDialog(Zone(), ONE_LINE)
        dialog.filter_kind.setCurrentIndex(2)  # lấy dòng thứ N
        assert not dialog.stop_kind.isEnabled()

    def test_goi_y_regex_khi_van_nhieu_gia_tri(self, qapp):
        dialog = ZoneFieldDialog(Zone(), ONE_LINE)
        dialog.stop_kind.setCurrentIndex(0)  # bỏ điểm dừng -> dính cả cụm
        assert dialog.result.text().startswith("VẪN NHIỀU GIÁ TRỊ")
        assert not dialog.suggest_button.isHidden()
        assert dialog.suggested_regex() == r"([A-Z]{7}\d{7})"

    def test_bam_goi_y_thi_chuyen_sang_regex_va_ra_dung(self, qapp):
        dialog = ZoneFieldDialog(Zone(), ONE_LINE)
        dialog.stop_kind.setCurrentIndex(0)
        dialog._use_suggested_regex()
        assert dialog.filter_kind.currentData() == "regex"
        assert dialog.filtered_value() == "HLCUSGN2412345"

    def test_vung_mot_gia_tri_thi_khong_moi_goi_y(self, qapp):
        dialog = ZoneFieldDialog(Zone(), "HLCUSGN2412345")
        assert dialog.suggest_button.isHidden()

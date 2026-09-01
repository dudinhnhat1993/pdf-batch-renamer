"""Test tinh lọc giá trị bên trong vùng zonal — core + hộp thoại tạo field."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.core.extractor import Extractor  # noqa: E402
from src.core.models import FieldSpec, MatchCondition, Profile, Zone  # noqa: E402
from src.core.zonal import (  # noqa: E402
    apply_zone_filter,
    zone_lines,
    zone_looks_ambiguous,
)

ZONE_TEXT = (
    "B/L No.: HLCUSGN2412345\n"
    "Date of Issue: 02/04/2026\n"
    "Carrier: HAPAG-LLOYD AG"
)


class TestApplyZoneFilter:
    def test_khong_loc_thi_giu_nguyen(self):
        assert apply_zone_filter(ZONE_TEXT, "none") == ZONE_TEXT

    def test_loc_theo_nhan(self):
        assert apply_zone_filter(ZONE_TEXT, "label", "B/L No.") == "HLCUSGN2412345"
        assert apply_zone_filter(ZONE_TEXT, "label", "Carrier") == "HAPAG-LLOYD AG"

    def test_loc_theo_nhan_khong_phan_biet_hoa_thuong(self):
        assert apply_zone_filter(ZONE_TEXT, "label", "b/l no.") == "HLCUSGN2412345"

    def test_nhan_khong_co_thi_tra_rong(self):
        assert apply_zone_filter(ZONE_TEXT, "label", "KHONG CO NHAN NAY") == ""

    def test_loc_theo_dong(self):
        assert apply_zone_filter(ZONE_TEXT, "line", "1") == "B/L No.: HLCUSGN2412345"
        assert apply_zone_filter(ZONE_TEXT, "line", "3") == "Carrier: HAPAG-LLOYD AG"

    def test_dong_vuot_qua_so_dong(self):
        assert apply_zone_filter(ZONE_TEXT, "line", "99") == ""

    def test_so_dong_khong_hop_le_thi_giu_nguyen(self):
        assert apply_zone_filter(ZONE_TEXT, "line", "abc") == ZONE_TEXT

    def test_loc_bang_regex(self):
        assert apply_zone_filter(ZONE_TEXT, "regex", r"([A-Z]{7}\d{7})") == "HLCUSGN2412345"

    def test_regex_khong_trung(self):
        assert apply_zone_filter(ZONE_TEXT, "regex", r"(KHONG-BAO-GIO-TRUNG)") == ""

    def test_regex_hong_thi_giu_nguyen_khong_lam_chet(self):
        assert apply_zone_filter(ZONE_TEXT, "regex", "[unclosed") == ZONE_TEXT

    def test_vung_rong(self):
        assert apply_zone_filter("", "label", "X") == ""


class TestZoneAmbiguity:
    def test_nhieu_dong_la_nhap_nhang(self):
        assert zone_looks_ambiguous(ZONE_TEXT)

    def test_mot_gia_tri_thi_khong(self):
        assert not zone_looks_ambiguous("HLCUSGN2412345")

    def test_mot_dong_nhieu_chu_cung_la_nhap_nhang(self):
        assert zone_looks_ambiguous("Carrier HAPAG LLOYD AG Hamburg")

    def test_dem_dong_bo_qua_dong_trong(self):
        assert zone_lines("a\n\n  \nb") == ["a", "b"]


class TestZoneFilterQuaPipeline:
    """Field vùng có bộ lọc phải chạy đúng qua tầng 2 của pipeline thật."""

    def _profile(self, **field_kw) -> Profile:
        spec = FieldSpec(
            name="number",
            label="Số hóa đơn",
            required=True,
            patterns=[],
            zone=Zone(page=0, x0=0.0, y0=0.0, x1=1.0, y1=1.0),
            **field_kw,
        )
        return Profile(
            id="zone-filter",
            name="Zone filter",
            doctype="Z",
            conditions=[MatchCondition(value="COMMERCIAL INVOICE")],
            fields=[spec],
            template="{number}",
        )

    def test_khong_loc_thi_bat_ca_cum(self, config, pdfs):
        result = Extractor(config, [self._profile()]).extract(pdfs["invoice"])
        # Không lọc: vùng cả trang nên dính rất nhiều chữ
        assert len(result.value("number")) > 50

    def test_loc_theo_nhan_ra_dung_gia_tri(self, config, pdfs):
        profile = self._profile(zone_filter="label", zone_filter_value="Invoice No.:")
        result = Extractor(config, [profile]).extract(pdfs["invoice"])
        assert result.value("number") == "INV-2026-00871"

    def test_loc_bang_regex_trong_vung(self, config, pdfs):
        profile = self._profile(zone_filter="regex", zone_filter_value=r"(INV-\d{4}-\d+)")
        result = Extractor(config, [profile]).extract(pdfs["invoice"])
        assert result.value("number") == "INV-2026-00871"

    def test_loc_khong_ra_gi_thi_field_coi_nhu_thieu(self, config, pdfs):
        profile = self._profile(zone_filter="label", zone_filter_value="NHAN KHONG TON TAI")
        result = Extractor(config, [profile]).extract(pdfs["invoice"])
        assert result.missing_required == ["number"]

    def test_raw_value_van_giu_nguyen_ca_vung(self, config, pdfs):
        profile = self._profile(zone_filter="label", zone_filter_value="Invoice No.:")
        result = Extractor(config, [profile]).extract(pdfs["invoice"])
        field = result.fields["number"]
        assert field.value == "INV-2026-00871"
        assert len(field.raw_value) > len(field.value)  # provenance giữ nguyên vùng gốc

    def test_bo_loc_duoc_luu_va_doc_lai(self, tmp_path):
        from src.core.rules import ProfileStore

        store = ProfileStore(tmp_path / "profiles")
        profile = self._profile(zone_filter="line", zone_filter_value="2")
        store.save(profile)

        loaded = store.get(profile.id)
        assert loaded.fields[0].zone_filter == "line"
        assert loaded.fields[0].zone_filter_value == "2"


# --------------------------------------------------------------- hộp thoại


pytest.importorskip("PySide6")

from src.ui.rule_builder_wizard import (  # noqa: E402
    COUNTER_TOKEN,
    ZoneFieldDialog,
    combo_field_name,
    field_name_combo,
)


class TestZoneFieldDialogLoc:
    def test_canh_bao_khi_vung_nhieu_gia_tri(self, qapp):
        dialog = ZoneFieldDialog(Zone(), ZONE_TEXT)
        assert "nhiều giá trị" in dialog.ambiguous.text()

    def test_khong_canh_bao_khi_vung_1_gia_tri(self, qapp):
        dialog = ZoneFieldDialog(Zone(), "HLCUSGN2412345")
        assert dialog.ambiguous.text() == ""

    def test_tu_goi_y_loc_theo_nhan_khi_dong_dau_co_dau_hai_cham(self, qapp):
        dialog = ZoneFieldDialog(Zone(), ZONE_TEXT)
        assert dialog.filter_kind.currentData() == "label"
        assert dialog.filter_value.text() == "B/L No.:"
        assert dialog.filtered_value() == "HLCUSGN2412345"

    def test_goi_y_loc_theo_dong_khi_khong_co_nhan(self, qapp):
        dialog = ZoneFieldDialog(Zone(), "HLCUSGN2412345\nMSKU2482484")
        assert dialog.filter_kind.currentData() == "line"
        assert dialog.filtered_value() == "HLCUSGN2412345"

    def test_ket_qua_cap_nhat_theo_bo_loc(self, qapp):
        dialog = ZoneFieldDialog(Zone(), ZONE_TEXT)
        dialog.filter_kind.setCurrentIndex(3)  # regex
        dialog.filter_value.setText(r"(\d{2}/\d{2}/\d{4})")
        assert dialog.filtered_value() == "02/04/2026"
        assert dialog.result.text().startswith("OK —")

    def test_bao_khi_van_con_nhieu_gia_tri(self, qapp):
        dialog = ZoneFieldDialog(Zone(), ZONE_TEXT)
        dialog.filter_kind.setCurrentIndex(0)  # không lọc
        assert dialog.result.text().startswith("VẪN NHIỀU GIÁ TRỊ")

    def test_bao_khi_loc_khong_ra_gi(self, qapp):
        dialog = ZoneFieldDialog(Zone(), ZONE_TEXT)
        dialog.filter_kind.setCurrentIndex(1)
        dialog.filter_value.setText("NHAN KHONG TON TAI")
        assert dialog.result.text().startswith("KHÔNG LẤY ĐƯỢC GÌ")

    def test_field_spec_mang_theo_bo_loc(self, qapp):
        dialog = ZoneFieldDialog(Zone(page=1), ZONE_TEXT)
        dialog.name.setCurrentText("number")
        spec = dialog.field_spec()
        assert spec.zone_filter == "label"
        assert spec.zone_filter_value == "B/L No.:"
        assert spec.zone.page == 1


class TestTenFieldChuan:
    """Tên field phải gắn với key chuẩn để token trong template dùng được ngay."""

    def test_combo_goi_y_key_chuan(self, qapp):
        combo = field_name_combo()
        keys = [combo.itemData(i) for i in range(combo.count())]
        assert "number" in keys and "doc_date" in keys and "container" in keys

    def test_combo_them_field_da_co_cua_profile(self, qapp):
        combo = field_name_combo(["so_seal"])
        keys = [combo.itemData(i) for i in range(combo.count())]
        assert "so_seal" in keys

    def test_chon_muc_goi_y_thi_lay_dung_key(self, qapp):
        combo = field_name_combo()
        combo.setCurrentIndex([combo.itemData(i) for i in range(combo.count())].index("container"))
        assert combo_field_name(combo) == "container"

    def test_van_go_tu_do_duoc(self, qapp):
        combo = field_name_combo()
        combo.setCurrentText("so_seal")
        assert combo_field_name(combo) == "so_seal"

    def test_nhan_tu_dong_theo_key_chuan(self, qapp):
        dialog = ZoneFieldDialog(Zone(), "MSKU2482484")
        dialog.name.setCurrentIndex(
            [dialog.name.itemData(i) for i in range(dialog.name.count())].index("container")
        )
        assert dialog.field_spec().label == "Số container"

    def test_field_vung_ra_token_render_duoc(self, qapp, config, pdfs):
        """Tạo field từ vùng với key chuẩn -> token cùng tên render ra giá trị, không rỗng."""
        from src.core.namer import render_template

        dialog = ZoneFieldDialog(
            Zone(page=0, x0=0.0, y0=0.0, x1=1.0, y1=1.0), "Invoice No.: INV-2026-00871"
        )
        dialog.name.setCurrentIndex(
            [dialog.name.itemData(i) for i in range(dialog.name.count())].index("number")
        )
        dialog.filter_kind.setCurrentIndex(1)
        dialog.filter_value.setText("Invoice No.:")
        spec = dialog.field_spec()
        assert spec.name == "number"

        profile = Profile(
            id="token-test", name="Token test", doctype="INV",
            conditions=[MatchCondition(value="COMMERCIAL INVOICE")],
            fields=[spec], template="{doctype}_{number}",
        )
        result = Extractor(config, [profile]).extract(pdfs["invoice"])
        rendered = render_template(
            profile.template,
            {**{k: v.value for k, v in result.fields.items()}, "doctype": profile.doctype},
        )
        assert rendered == "INV_INV-2026-00871"
        assert COUNTER_TOKEN[0] == "{counter}"

"""Test từ điển chuẩn hóa tên công ty."""

from __future__ import annotations

import json

from src.core.normalize import CompanyDictionary, match_key

ALIASES = {
    "HLAG": "Hapag-Lloyd",
    "HAPAG-LLOYD AG": "Hapag-Lloyd",
    "MAERSK LINE": "Maersk",
}


class TestMatchKey:
    def test_bo_dau_cau_va_viet_hoa(self):
        assert match_key("Hapag-Lloyd A.G.") == "HAPAG LLOYD A G"

    def test_bo_dau_tieng_viet(self):
        assert match_key("Công ty Đại Dương") == "CONG TY DAI DUONG"


class TestNormalize:
    def test_alias_ve_ten_chuan(self):
        d = CompanyDictionary(ALIASES)
        assert d.normalize("HLAG") == "Hapag-Lloyd"
        assert d.normalize("hapag-lloyd ag") == "Hapag-Lloyd"

    def test_bo_duoi_phap_ly_khi_so_khop(self):
        d = CompanyDictionary(ALIASES)
        assert d.normalize("MAERSK LINE CO., LTD") == "Maersk"

    def test_ten_chuan_tu_khop_voi_chinh_no(self):
        d = CompanyDictionary(ALIASES)
        assert d.normalize("Hapag-Lloyd") == "Hapag-Lloyd"

    def test_khong_khop_thi_giu_nguyen_chi_don_khoang_trang(self):
        d = CompanyDictionary(ALIASES)
        assert d.normalize("  CONG TY   ABC  ") == "CONG TY ABC"

    def test_chuoi_rong(self):
        assert CompanyDictionary(ALIASES).normalize("") == ""

    def test_them_va_xoa_alias(self):
        d = CompanyDictionary()
        d.add("ONE", "Ocean Network Express")
        assert d.normalize("one") == "Ocean Network Express"
        d.remove("ONE")
        assert d.normalize("ONE") == "ONE"

    def test_deterministic(self):
        d = CompanyDictionary(ALIASES)
        assert d.normalize("HLAG") == d.normalize("HLAG")


class TestLoadSave:
    def test_ghi_roi_doc_lai(self, tmp_path):
        path = tmp_path / "companies.json"
        CompanyDictionary(ALIASES).save(path)
        loaded = CompanyDictionary.load(path)
        assert loaded.normalize("HLAG") == "Hapag-Lloyd"

    def test_file_thieu_tra_tu_dien_rong(self, tmp_path):
        d = CompanyDictionary.load(tmp_path / "khong-co.json")
        assert d.aliases == {}

    def test_file_hong_khong_lam_chet_app(self, tmp_path):
        path = tmp_path / "hong.json"
        path.write_text("{ khong phai json", encoding="utf-8")
        assert CompanyDictionary.load(path).aliases == {}

    def test_chap_nhan_ca_dang_dict_phang(self, tmp_path):
        path = tmp_path / "phang.json"
        path.write_text(json.dumps({"HLAG": "Hapag-Lloyd"}), encoding="utf-8")
        assert CompanyDictionary.load(path).normalize("HLAG") == "Hapag-Lloyd"

    def test_tu_dien_mau_di_kem_app_load_duoc(self):
        from pathlib import Path

        asset = Path(__file__).resolve().parents[1] / "assets" / "dictionaries" / "companies.json"
        d = CompanyDictionary.load(asset)
        assert d.normalize("HLAG") == "Hapag-Lloyd"
        assert d.normalize("MSC MEDITERRANEAN SHIPPING COMPANY") == "MSC"

"""Test tra cứu master data từ Excel."""

from __future__ import annotations

import pytest
from src.core.errors import MasterDataError
from src.core.masterdata import MasterDataStore, load_table
from src.core.models import MasterDataLookup


def lookup_spec(path, **kw) -> MasterDataLookup:
    base = dict(
        source=str(path), key_column="Ma KH", value_column="Ten cong ty",
        target_field="ten_kh",
    )
    base.update(kw)
    return MasterDataLookup(**base)


class TestLoadTable:
    def test_doc_theo_ten_cot(self, pdfs):
        table = load_table(pdfs["masterdata"], "Ma KH", "Ten cong ty")
        assert len(table) == 3
        assert table.lookup("KH001") == "Cong ty TNHH Acme Logistics"

    def test_doc_theo_chu_cai_cot(self, pdfs):
        table = load_table(pdfs["masterdata"], "A", "C")
        assert table.lookup("KH002") == "0398765432"

    def test_tra_cuu_khong_phan_biet_hoa_thuong_va_khoang_trang(self, pdfs):
        table = load_table(pdfs["masterdata"], "Ma KH", "Ten cong ty")
        assert table.lookup("  kh003 ") == "Hapag-Lloyd Vietnam"

    def test_key_khong_ton_tai_tra_rong(self, pdfs):
        table = load_table(pdfs["masterdata"], "Ma KH", "Ten cong ty")
        assert table.lookup("KH999") == ""

    def test_chon_sheet_theo_ten(self, pdfs):
        table = load_table(pdfs["masterdata"], "Ma KH", "Ten cong ty", sheet="KhachHang")
        assert len(table) == 3

    def test_sheet_khong_ton_tai(self, pdfs):
        with pytest.raises(MasterDataError):
            load_table(pdfs["masterdata"], "Ma KH", "Ten cong ty", sheet="KhongCo")

    def test_ten_cot_sai(self, pdfs):
        with pytest.raises(MasterDataError):
            load_table(pdfs["masterdata"], "Cot Khong Co", "Ten cong ty")

    def test_file_khong_ton_tai(self, tmp_path):
        with pytest.raises(MasterDataError):
            load_table(tmp_path / "khong-co.xlsx", "A", "B")

    def test_file_khong_phai_excel(self, tmp_path):
        fake = tmp_path / "gia.xlsx"
        fake.write_text("day khong phai excel", encoding="utf-8")
        with pytest.raises(MasterDataError):
            load_table(fake, "A", "B")


class TestStore:
    def test_cache_theo_mtime(self, pdfs):
        store = MasterDataStore()
        spec = lookup_spec(pdfs["masterdata"])
        first = store.get_table(spec)
        second = store.get_table(spec)
        assert first is second  # lần 2 lấy từ cache, không mở lại file

    def test_nap_lai_khi_file_doi(self, pdfs, tmp_path):
        import shutil

        from openpyxl import Workbook

        target = tmp_path / "md.xlsx"
        shutil.copy2(pdfs["masterdata"], target)

        store = MasterDataStore()
        spec = lookup_spec(target)
        assert store.lookup(spec, "KH001") == "Cong ty TNHH Acme Logistics"

        wb = Workbook()
        ws = wb.active
        ws.append(["Ma KH", "Ten cong ty"])
        ws.append(["KH001", "Ten moi sau khi sua"])
        wb.save(str(target))
        import os
        import time

        os.utime(target, (time.time() + 10, time.time() + 10))

        assert store.lookup(spec, "KH001") == "Ten moi sau khi sua"

    def test_dung_nguon_mac_dinh_khi_profile_khong_khai_bao(self, pdfs):
        store = MasterDataStore(default_source=str(pdfs["masterdata"]))
        spec = MasterDataLookup(key_column="Ma KH", value_column="Ten cong ty", target_field="x")
        assert store.lookup(spec, "KH002") == "Vietnam Import Export JSC"

    def test_khong_co_nguon_nao_thi_bao_loi(self):
        store = MasterDataStore()
        spec = MasterDataLookup(key_column="A", value_column="B", target_field="x")
        with pytest.raises(MasterDataError):
            store.lookup(spec, "KH001")

    def test_key_rong_tra_ve_rong_khong_mo_file(self):
        assert MasterDataStore().lookup(MasterDataLookup(), "") == ""

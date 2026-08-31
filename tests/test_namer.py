"""Test render template đặt tên, làm sạch tên file, chống trùng tên, thư mục theo ngày."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from src.core.errors import TemplateError
from src.core.namer import (
    finalize_filename,
    render_subfolder,
    render_template,
    sanitize,
    strip_accents,
    truncate,
    unique_name,
)


class TestSanitize:
    @pytest.mark.parametrize("ch", list('\\/:*?"<>|'))
    def test_bo_ky_tu_cam_cua_windows(self, ch):
        assert ch not in sanitize(f"INV{ch}2026")

    def test_bo_ky_tu_dieu_khien_va_gom_khoang_trang(self):
        assert sanitize("INV\x00 \t 2026") == "INV 2026"

    def test_khong_ket_thuc_bang_dau_cham_hoac_khoang_trang(self):
        assert sanitize("bao cao. ") == "bao cao"

    def test_bo_dau_tieng_viet(self):
        assert strip_accents("Hóa đơn tháng Tư") == "Hoa don thang Tu"
        assert sanitize("Hóa đơn", remove_accents=True) == "Hoa don"

    def test_ten_thiet_bi_windows_duoc_doi_ten(self):
        assert finalize_filename("CON") == "_CON.pdf"
        assert finalize_filename("nul") == "_nul.pdf"


class TestTruncate:
    def test_gioi_han_120_ky_tu_ke_ca_duoi_file(self):
        name = finalize_filename("A" * 300, ".pdf", max_length=120)
        assert len(name) == 120
        assert name.endswith(".pdf")

    def test_giu_phan_duoi_phan_biet(self):
        stem = "PREFIX" + "X" * 100 + "SO-CHUNG-TU-999"
        cut = truncate(stem, 40)
        assert len(cut) == 40
        assert cut.startswith("PREFIX")
        assert cut.endswith("999")  # phần đuôi phân biệt vẫn còn

    def test_ten_ngan_khong_bi_dong_vao(self):
        assert truncate("INV-001", 100) == "INV-001"


class TestRenderTemplate:
    def test_token_co_ban(self):
        out = render_template(
            "{doc_date}_{doctype}_{number}",
            {"doc_date": "15/03/2026", "doctype": "INV", "number": "INV-2026-00871"},
            date_formats=["dd/mm/yyyy"],
        )
        assert out == "2026-03-15_INV_INV-2026-00871"

    def test_doc_date_mac_dinh_la_yyyy_mm_dd(self):
        out = render_template("{doc_date}", {"doc_date": "02/04/2026"}, date_formats=["dd/mm/yyyy"])
        assert out == "2026-04-02"

    def test_doc_date_co_the_override_dinh_dang(self):
        out = render_template(
            "{doc_date:ddMMyyyy}", {"doc_date": "02/04/2026"}, date_formats=["dd/mm/yyyy"]
        )
        assert out == "02042026"

    def test_ngay_khong_parse_duoc_thi_giu_nguyen(self):
        out = render_template("{doc_date}", {"doc_date": "ngay 2 thang 4"}, date_formats=["dd/mm/yyyy"])
        assert out == "ngay 2 thang 4"

    def test_counter_mac_dinh_3_chu_so(self):
        assert render_template("{counter}", {"counter": "7"}) == "007"
        assert render_template("{counter:05}", {"counter": "7"}) == "00007"

    def test_field_rong_khong_de_lai_dau_phan_cach_thua(self):
        out = render_template(
            "{doc_date}_{doctype}_{number}_{company}",
            {"doc_date": "15/03/2026", "doctype": "INV", "number": "A1", "company": ""},
            date_formats=["dd/mm/yyyy"],
        )
        assert out == "2026-03-15_INV_A1"

    def test_token_la_bi_bo_qua_o_che_do_thuong(self):
        assert render_template("{number}_{khong_ton_tai}", {"number": "A1"}) == "A1"

    def test_token_la_bao_loi_o_che_do_strict(self):
        with pytest.raises(TemplateError):
            render_template("{number}_{khong_ton_tai}", {"number": "A1"}, strict=True)

    def test_template_rong_bao_loi(self):
        with pytest.raises(TemplateError):
            render_template("", {})

    def test_ky_tu_cam_trong_gia_tri_field_bi_loai(self):
        out = render_template("{number}", {"number": "INV/2026:001"})
        assert out == "INV2026001"

    def test_deterministic_cung_dau_vao_cung_ket_qua(self):
        values = {"doc_date": "15/03/2026", "number": "A/B*C", "doctype": "INV"}
        first = render_template("{doc_date}_{doctype}_{number}", values, date_formats=["dd/mm/yyyy"])
        second = render_template("{doc_date}_{doctype}_{number}", values, date_formats=["dd/mm/yyyy"])
        assert first == second


class TestSubfolder:
    def test_mau_mac_dinh_theo_ngay_xu_ly(self):
        assert render_subfolder("{YYYY}-{MM}-{DD}", date(2026, 8, 31)) == Path("2026-08-31")

    def test_mau_long_nhau(self):
        assert render_subfolder("{YYYY}/{MM}", date(2026, 8, 31)) == Path("2026") / "08"

    def test_mau_rong_tra_ve_duong_dan_rong(self):
        assert render_subfolder("", date(2026, 8, 31)) == Path()


class TestUniqueName:
    def test_them_hau_to_khi_trung(self, tmp_path):
        (tmp_path / "INV-001.pdf").write_bytes(b"x")
        assert unique_name(tmp_path, "INV-001.pdf") == "INV-001_01.pdf"

    def test_tang_dan_hau_to(self, tmp_path):
        (tmp_path / "INV-001.pdf").write_bytes(b"x")
        (tmp_path / "INV-001_01.pdf").write_bytes(b"x")
        assert unique_name(tmp_path, "INV-001.pdf") == "INV-001_02.pdf"

    def test_ton_trong_ten_da_dat_cho_trong_cung_batch(self, tmp_path):
        reserved = {"inv-001.pdf"}
        assert unique_name(tmp_path, "INV-001.pdf", reserved=reserved) == "INV-001_01.pdf"

    def test_khong_trung_thi_giu_nguyen(self, tmp_path):
        assert unique_name(tmp_path, "INV-002.pdf") == "INV-002.pdf"

    def test_hau_to_khong_lam_vuot_gioi_han_do_dai(self, tmp_path):
        long_name = "B" * 116 + ".pdf"
        (tmp_path / long_name).write_bytes(b"x")
        result = unique_name(tmp_path, long_name, max_length=120)
        assert len(result) <= 120 and result != long_name

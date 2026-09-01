"""Test validate số container ISO 6346 và ngày tháng."""

from __future__ import annotations

from datetime import date

import pytest
from src.core.validators import (
    container_check_digit,
    format_date,
    is_valid_container,
    normalize_container,
    parse_date,
    to_strptime,
    validate_field_value,
)


class TestContainerISO6346:
    def test_vi_du_chuan_cua_iso(self):
        # CSQU3054383 là ví dụ chính thức trong tiêu chuẩn ISO 6346
        assert is_valid_container("CSQU3054383")
        assert container_check_digit("CSQU305438") == 3

    @pytest.mark.parametrize(
        "value,expected",
        [("MSKU248248", 4), ("HLCU123456", 8), ("TGHU765432", 0)],
    )
    def test_check_digit(self, value, expected):
        assert container_check_digit(value) == expected

    def test_sai_check_digit_bi_tu_choi(self):
        assert not is_valid_container("CSQU3054384")
        assert not is_valid_container("MSKU2482483")

    def test_chuan_hoa_khoang_trang_va_gach_noi(self):
        assert normalize_container("csqu 305438 3") == "CSQU3054383"
        assert is_valid_container("CSQU 305438 3")
        assert is_valid_container("csqu-305438-3")

    @pytest.mark.parametrize(
        "value",
        ["CSQ3054383", "CSQUX054383", "CSQU30543831", "", "1234567890A", "CSQA3054383"],
    )
    def test_sai_dinh_dang(self, value):
        assert not is_valid_container(value)

    def test_ky_tu_loai_phai_la_u_j_hoac_z(self):
        assert is_valid_container("CSQU3054383")
        # ký tự thứ 4 là 'A' -> không phải loại container hợp lệ
        assert not is_valid_container("CSQA3054383")

    def test_check_digit_dau_vao_sai_tra_none(self):
        assert container_check_digit("ABC") is None
        assert container_check_digit("ABCD12345X") is None


class TestDate:
    def test_doi_format_sang_strptime(self):
        assert to_strptime("dd/mm/yyyy") == "%d/%m/%Y"
        assert to_strptime("dd-MMM-yyyy") == "%d-%b-%Y"
        assert to_strptime("yyyy-MM-dd") == "%Y-%m-%d"

    def test_parse_theo_format_profile(self):
        assert parse_date("15/03/2026", ["dd/mm/yyyy"]) == date(2026, 3, 15)
        assert parse_date("2026-03-15", ["yyyy-MM-dd"]) == date(2026, 3, 15)
        assert parse_date("15-MAR-2026", ["dd-MMM-yyyy"]) == date(2026, 3, 15)

    def test_thu_lan_luot_nhieu_format(self):
        formats = ["dd/mm/yyyy", "dd-mm-yyyy", "yyyy-MM-dd"]
        assert parse_date("02-04-2026", formats) == date(2026, 4, 2)

    def test_ngay_khong_hop_le_bi_tu_choi(self):
        assert parse_date("31/02/2026", ["dd/mm/yyyy"]) is None
        assert parse_date("15/13/2026", ["dd/mm/yyyy"]) is None
        assert parse_date("khong phai ngay", ["dd/mm/yyyy"]) is None
        assert parse_date("", ["dd/mm/yyyy"]) is None

    def test_khong_doan_bua_format_khac(self):
        # profile khai dd/mm/yyyy thì 03/15/2026 (kiểu Mỹ) phải bị từ chối
        assert parse_date("03/15/2026", ["dd/mm/yyyy"]) is None

    def test_format_ra_ten_file(self):
        d = date(2026, 3, 15)
        assert format_date(d) == "2026-03-15"
        assert format_date(d, "ddMMyyyy") == "15032026"
        assert format_date(d, "dd.mm.yyyy") == "15.03.2026"


class TestValidateFieldValue:
    def test_container_tra_ve_gia_tri_da_chuan_hoa(self):
        ok, value = validate_field_value("csqu 305438 3", "container")
        assert ok and value == "CSQU3054383"

    def test_container_sai_bi_loai(self):
        ok, value = validate_field_value("CSQU3054384", "container")
        assert not ok and value == ""

    def test_date_giu_nguyen_chuoi_goc(self):
        ok, value = validate_field_value("15/03/2026", "date", date_formats=["dd/mm/yyyy"])
        assert ok and value == "15/03/2026"

    def test_regex(self):
        ok, _ = validate_field_value("INV-001", "regex", regex=r"^INV-\d+$")
        assert ok
        ok, _ = validate_field_value("XYZ", "regex", regex=r"^INV-\d+$")
        assert not ok

    def test_regex_hong_thi_khong_chan_gia_tri(self):
        ok, value = validate_field_value("INV-001", "regex", regex=r"[unclosed")
        assert ok and value == "INV-001"

    def test_gia_tri_rong_luon_khong_hop_le(self):
        assert validate_field_value("   ", "none") == (False, "")


class TestTwoDigitYear:
    """Chứng từ thật hay ghi năm 2 chữ số: 17/7/26."""

    def test_parse_nam_2_chu_so(self):
        assert parse_date("17/7/26", ["dd/mm/yy"]) == date(2026, 7, 17)
        assert parse_date("17/07/26", ["dd/mm/yy"]) == date(2026, 7, 17)

    def test_thu_format_4_chu_so_truoc_roi_moi_den_2_chu_so(self):
        formats = ["dd/mm/yyyy", "dd/mm/yy"]
        assert parse_date("15/03/2026", formats) == date(2026, 3, 15)
        assert parse_date("17/7/26", formats) == date(2026, 7, 17)

    @pytest.mark.parametrize(
        "value,expected",
        [
            ("01/01/00", date(2000, 1, 1)),
            ("01/01/26", date(2026, 1, 1)),
            ("01/01/49", date(2049, 1, 1)),  # mốc: <= 49 là thế kỷ 21
            ("01/01/50", date(1950, 1, 1)),  # > 49 là thế kỷ 20
            ("01/01/68", date(1968, 1, 1)),  # Python mặc định cho 2068 — phải bị chỉnh lại
            ("01/01/99", date(1999, 1, 1)),
        ],
    )
    def test_moc_the_ky(self, value, expected):
        assert parse_date(value, ["dd/mm/yy"]) == expected

    def test_nam_4_chu_so_khong_bi_dung_toi_moc(self):
        assert parse_date("01/01/1950", ["dd/mm/yyyy"]) == date(1950, 1, 1)
        assert parse_date("01/01/2060", ["dd/mm/yyyy"]) == date(2060, 1, 1)

    def test_ngay_sai_van_bi_tu_choi(self):
        assert parse_date("31/02/26", ["dd/mm/yy"]) is None

    def test_profile_mau_di_kem_doc_duoc_nam_2_chu_so(self):
        import json
        from pathlib import Path

        from src.core.models import Profile

        path = Path(__file__).resolve().parents[1] / "assets" / "profiles" / "invoice.json"
        profile = Profile.from_dict(json.loads(path.read_text(encoding="utf-8")))
        assert parse_date("17/7/26", profile.date_formats) == date(2026, 7, 17)

"""Test sinh regex từ đoạn text người dùng bôi chọn (nền của Visual Rule Builder)."""

from __future__ import annotations

from src.core.models import PageText, Word
from src.core.rule_builder import (
    condition_from_keyword,
    describe_shape,
    explain_pattern,
    generate_candidates,
    guess_label,
    shape_pattern,
    zone_around_words,
    zone_from_bbox,
)

SAMPLE = """HAPAG-LLOYD AG
BILL OF LADING
B/L No.: HLCUSGN2412345
Date of Issue: 02/04/2026
Container No.: MSKU2482484
"""


class TestShape:
    def test_mo_ta_hinh_dang_so_bl(self):
        assert shape_pattern("HLCUSGN2412345") == r"[A-Z]{7}\d{7}"

    def test_mo_ta_hinh_dang_ngay(self):
        assert shape_pattern("02/04/2026") == r"\d{2}/\d{2}/\d{4}"

    def test_giai_thich_tieng_viet(self):
        assert describe_shape("HLCU1234567") == "4 chữ in hoa, rồi 7 chữ số"
        assert "chữ số" in describe_shape("02/04/2026")


class TestGuessLabel:
    def test_doan_nhan_dung_truoc_gia_tri(self):
        assert guess_label(SAMPLE, "HLCUSGN2412345") == "B/L No."

    def test_nhan_nhieu_tu(self):
        assert guess_label(SAMPLE, "02/04/2026") == "Date of Issue"

    def test_khong_co_nhan_thi_tra_rong(self):
        assert guess_label("HLCUSGN2412345", "HLCUSGN2412345") == ""


class TestGenerateCandidates:
    def test_sinh_it_nhat_2_ung_vien_va_deu_bat_dung_gia_tri(self):
        candidates = generate_candidates(SAMPLE, "HLCUSGN2412345")
        assert len(candidates) >= 2
        for c in candidates:
            assert c.test(SAMPLE) == "HLCUSGN2412345"

    def test_ung_vien_theo_nhan_duoc_uu_tien_dau_tien(self):
        candidates = generate_candidates(SAMPLE, "HLCUSGN2412345")
        assert candidates[0].kind == "label"
        assert candidates[0].label == "B/L No."

    def test_moi_ung_vien_deu_co_giai_thich_tieng_viet(self):
        for c in generate_candidates(SAMPLE, "HLCUSGN2412345"):
            assert c.explanation and len(c.explanation) > 20

    def test_co_ung_vien_khong_phu_thuoc_nhan(self):
        kinds = {c.kind for c in generate_candidates(SAMPLE, "HLCUSGN2412345")}
        assert "shape" in kinds

    def test_bat_duoc_ngay(self):
        candidates = generate_candidates(SAMPLE, "02/04/2026")
        assert candidates and candidates[0].test(SAMPLE) == "02/04/2026"

    def test_bat_duoc_so_container(self):
        candidates = generate_candidates(SAMPLE, "MSKU2482484")
        assert candidates and candidates[0].test(SAMPLE) == "MSKU2482484"

    def test_nhan_do_nguoi_dung_chi_dinh_duoc_uu_tien(self):
        candidates = generate_candidates(SAMPLE, "HLCUSGN2412345", label_hint="B/L No")
        assert candidates[0].label == "B/L No"

    def test_gia_tri_rong_khong_sinh_gi(self):
        assert generate_candidates(SAMPLE, "  ") == []

    def test_khong_tra_ve_regex_trung_lap(self):
        patterns = [c.pattern for c in generate_candidates(SAMPLE, "HLCUSGN2412345")]
        assert len(patterns) == len(set(patterns))

    def test_deterministic(self):
        first = [c.pattern for c in generate_candidates(SAMPLE, "HLCUSGN2412345")]
        second = [c.pattern for c in generate_candidates(SAMPLE, "HLCUSGN2412345")]
        assert first == second

    def test_gioi_han_so_ung_vien(self):
        assert len(generate_candidates(SAMPLE, "HLCUSGN2412345", limit=2)) == 2


class TestExplainPattern:
    def test_dich_regex_sang_tieng_viet(self):
        text = explain_pattern(r"B/L\s*No\.\s*[:\-#]?\s*([A-Z]{4}\d{7})")
        assert "4 chữ in hoa" in text and "7 chữ số" in text


class TestConditionAndZone:
    def test_tao_dieu_kien_tu_keyword_click(self):
        cond = condition_from_keyword("  BILL OF   LADING ")
        assert cond.kind == "keyword"
        assert cond.value == "BILL OF LADING"
        assert cond.case_sensitive is False

    def test_zone_tu_khung_keo(self):
        zone = zone_from_bbox((100, 200, 300, 250), 1000, 1000, page=1, padding=0.0)
        assert zone.page == 1
        assert (zone.x0, zone.y0, zone.x1, zone.y1) == (0.1, 0.2, 0.3, 0.25)

    def test_zone_tu_khung_keo_nguoc_chieu(self):
        zone = zone_from_bbox((300, 250, 100, 200), 1000, 1000, padding=0.0)
        assert zone.x0 == 0.1 and zone.x1 == 0.3

    def test_zone_khong_vuot_khoi_trang(self):
        zone = zone_from_bbox((0, 0, 1000, 1000), 1000, 1000, padding=0.05)
        assert zone.x0 == 0.0 and zone.x1 == 1.0

    def test_zone_bao_quanh_tu_da_boi_chon(self):
        page = PageText(
            index=0, width=1000, height=1000,
            words=[Word("HLCU", 100, 200, 150, 220), Word("123", 155, 200, 190, 220)],
        )
        zone = zone_around_words(page, page.words, padding=0.0)
        assert zone.x0 == 0.1 and zone.x1 == 0.19

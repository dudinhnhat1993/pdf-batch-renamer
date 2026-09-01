"""Test engine rule: nhận diện profile, regex tầng 1, versioning, rule pack."""

from __future__ import annotations

import pytest
from src.core.errors import ProfileError
from src.core.models import DocumentText, FieldSpec, MatchCondition, PageText, Profile
from src.core.rules import (
    ProfileStore,
    condition_matches,
    profile_matches,
    run_regex_field,
    select_profile,
)

BL_TEXT = "HAPAG-LLOYD AG\nBILL OF LADING\nB/L No.: HLCUSGN2412345\nDate of Issue: 02/04/2026"


def doc(text: str) -> DocumentText:
    pages = [
        PageText(index=i, width=595, height=842, text=chunk)
        for i, chunk in enumerate(text.split("\f"))
    ]
    return DocumentText(pages=pages)


@pytest.fixture
def store(tmp_path) -> ProfileStore:
    return ProfileStore(tmp_path / "profiles", tmp_path / "profiles" / "_versions")


class TestConditions:
    def test_keyword_khong_phan_biet_hoa_thuong(self):
        cond = MatchCondition(kind="keyword", value="bill of lading")
        assert condition_matches(cond, BL_TEXT)

    def test_keyword_phan_biet_hoa_thuong_khi_bat(self):
        cond = MatchCondition(kind="keyword", value="bill of lading", case_sensitive=True)
        assert not condition_matches(cond, BL_TEXT)

    def test_regex(self):
        assert condition_matches(MatchCondition(kind="regex", value=r"B/L\s*No"), BL_TEXT)

    def test_regex_hong_khong_lam_chet_app(self):
        assert not condition_matches(MatchCondition(kind="regex", value="[unclosed"), BL_TEXT)

    def test_mode_all_phai_trung_het(self):
        p = Profile(
            name="X",
            condition_mode="all",
            conditions=[
                MatchCondition(value="BILL OF LADING"),
                MatchCondition(value="KHONG CO TRONG VAN BAN"),
            ],
        )
        assert not profile_matches(p, BL_TEXT)

    def test_profile_tat_thi_khong_match(self):
        p = Profile(name="X", enabled=False, conditions=[MatchCondition(value="BILL OF LADING")])
        assert not profile_matches(p, BL_TEXT)


class TestSelectProfile:
    def test_chon_theo_thu_tu_uu_tien(self, profiles):
        chosen = select_profile(profiles, BL_TEXT)
        assert chosen.name == "Bill of Lading"

    def test_packing_list_uu_tien_hon_invoice(self, profiles):
        # Packing list thường có nhắc "Invoice No." bên trong -> phải match Packing List
        text = "PACKING LIST\nPacking List No.: PL-1\nInvoice No.: INV-1"
        assert select_profile(profiles, text).name == "Packing List"

    def test_khong_match_thi_dung_profile_chung(self, profiles):
        assert select_profile(profiles, "van ban vo thuong vo phat").is_fallback

    def test_forced_profile_bo_qua_dieu_kien_nhan_dien(self, profiles):
        chosen = select_profile(profiles, "van ban khong lien quan", forced_id="invoice")
        assert chosen.id == "invoice"

    def test_forced_profile_theo_ten(self, profiles):
        assert select_profile(profiles, "", forced_id="Bill of Lading").id == "bill-of-lading"

    def test_forced_profile_khong_ton_tai_bao_loi(self, profiles):
        with pytest.raises(ProfileError):
            select_profile(profiles, BL_TEXT, forced_id="khong-co")

    def test_khong_co_profile_nao_tra_none(self):
        assert select_profile([], BL_TEXT) is None


class TestRunRegexField:
    def test_bat_gia_tri_theo_nhan(self):
        spec = FieldSpec(name="number", patterns=[r"B/L\s*No\.?\s*:?\s*([A-Z0-9]+)"])
        found = run_regex_field(spec, doc(BL_TEXT))
        assert found.value == "HLCUSGN2412345"
        assert found.rule_id == "pattern[0]"
        assert found.page == 0

    def test_regex_du_phong_chay_khi_cai_dau_truot(self):
        spec = FieldSpec(
            name="number",
            patterns=[r"KHONG-CO\s*([A-Z0-9]+)", r"B/L\s*No\.?\s*:?\s*([A-Z0-9]+)"],
        )
        found = run_regex_field(spec, doc(BL_TEXT))
        assert found.value == "HLCUSGN2412345"
        assert found.rule_id == "pattern[1]"

    def test_uu_tien_theo_thu_tu_regex_khong_phai_thu_tu_trang(self):
        # pattern[0] chỉ trúng ở trang 2; vẫn phải thắng pattern[1] trúng ở trang 1
        text = "Ref: AAA\fB/L No.: BBB"
        spec = FieldSpec(name="number", patterns=[r"B/L No\.: (\w+)", r"Ref: (\w+)"])
        assert run_regex_field(spec, doc(text)).value == "BBB"

    def test_khong_co_capture_group_thi_lay_ca_match(self):
        spec = FieldSpec(name="x", patterns=[r"HLCUSGN\d+"])
        assert run_regex_field(spec, doc(BL_TEXT)).value == "HLCUSGN2412345"

    def test_regex_hong_bi_bo_qua_khong_lam_chet(self):
        spec = FieldSpec(name="x", patterns=["[unclosed", r"B/L No\.: (\w+)"])
        assert run_regex_field(spec, doc(BL_TEXT)).value == "HLCUSGN2412345"

    def test_khong_trung_tra_none(self):
        spec = FieldSpec(name="x", patterns=[r"KHONG-BAO-GIO-TRUNG (\w+)"])
        assert run_regex_field(spec, doc(BL_TEXT)) is None


class TestProfileStoreVersioning:
    def test_luu_lan_dau_tao_version_1(self, store):
        p = store.save(Profile(id="p1", name="Test"))
        assert p.version == 1
        assert store.versions("p1") == [1]

    def test_moi_lan_luu_tao_version_moi(self, store):
        store.save(Profile(id="p1", name="Test"))
        p = store.get("p1")
        p.template = "{number}"
        store.save(p)
        assert store.versions("p1") == [1, 2]
        assert store.get("p1").version == 2

    def test_rollback_giu_lich_su_va_tao_version_moi(self, store):
        store.save(Profile(id="p1", name="Test", template="{original_name}"))
        p = store.get("p1")
        p.template = "{number}"
        store.save(p)

        rolled = store.rollback("p1", 1)
        assert rolled.template == "{original_name}"
        assert rolled.version == 3  # rollback cũng là 1 thay đổi, không xoá lịch sử
        assert store.versions("p1") == [1, 2, 3]

    def test_rollback_version_khong_ton_tai(self, store):
        store.save(Profile(id="p1", name="Test"))
        with pytest.raises(ProfileError):
            store.rollback("p1", 99)

    def test_load_all_sap_xep_theo_uu_tien(self, store):
        store.save(Profile(id="b", name="B", priority=50))
        store.save(Profile(id="a", name="A", priority=10))
        assert [p.id for p in store.load_all()] == ["a", "b"]

    def test_profile_hong_bi_bo_qua_khong_lam_chet(self, store):
        store.save(Profile(id="ok", name="OK"))
        (store.directory / "hong.json").write_text("{ khong phai json", encoding="utf-8")
        assert [p.id for p in store.load_all()] == ["ok"]

    def test_xoa_profile(self, store):
        store.save(Profile(id="p1", name="Test"))
        store.delete("p1")
        assert store.get("p1") is None


class TestRulePack:
    def test_export_roi_import_sang_may_khac(self, store, tmp_path):
        store.save(Profile(id="p1", name="Invoice", template="{number}"))
        pack = store.export_pack(tmp_path / "pack.json")

        other = ProfileStore(tmp_path / "other", tmp_path / "other" / "_versions")
        imported = other.import_pack(pack)
        assert len(imported) == 1
        assert other.get("p1").template == "{number}"

    def test_import_trung_id_thi_nhan_ban_thay_vi_de(self, store, tmp_path):
        store.save(Profile(id="p1", name="Invoice"))
        pack = store.export_pack(tmp_path / "pack.json")
        store.import_pack(pack)

        ids = [p.id for p in store.load_all()]
        assert "p1" in ids and len(ids) == 2
        assert any(p.name.endswith("(nhập)") for p in store.load_all())

    def test_import_ghi_de_khi_duoc_yeu_cau(self, store, tmp_path):
        store.save(Profile(id="p1", name="Invoice", template="{number}"))
        pack = store.export_pack(tmp_path / "pack.json")
        store.save(Profile(id="p1", name="Invoice", template="{original_name}"))

        store.import_pack(pack, overwrite=True)
        assert store.get("p1").template == "{number}"
        assert len(store.load_all()) == 1

    def test_file_khong_phai_rule_pack_bi_tu_choi(self, store, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text('{"format": "cai gi do"}', encoding="utf-8")
        with pytest.raises(ProfileError):
            store.import_pack(bad)


class TestExcludeConditions:
    """Điều kiện loại trừ: xử lý chứng từ chồng lấn mà không phải chỉnh thứ tự ưu tiên."""

    def test_dieu_kien_loai_tru_phu_quyet_dieu_kien_nhan_dien(self):
        p = Profile(
            name="Invoice",
            conditions=[MatchCondition(value="INVOICE")],
            exclude_conditions=[MatchCondition(value="PACKING LIST")],
        )
        assert profile_matches(p, "COMMERCIAL INVOICE\nInvoice No.: INV-1")
        assert not profile_matches(p, "PACKING LIST\nInvoice No.: INV-1")

    def test_loai_tru_bang_regex(self):
        p = Profile(
            name="Invoice",
            conditions=[MatchCondition(value="INVOICE")],
            exclude_conditions=[MatchCondition(kind="regex", value=r"\bPROFORMA\b")],
        )
        assert not profile_matches(p, "PROFORMA INVOICE No 1")

    def test_khong_khai_bao_loai_tru_thi_khong_doi_hanh_vi(self):
        p = Profile(name="Invoice", conditions=[MatchCondition(value="INVOICE")])
        assert profile_matches(p, "COMMERCIAL INVOICE")

    def test_loai_tru_thang_ca_khi_condition_mode_all(self):
        p = Profile(
            name="X",
            condition_mode="all",
            conditions=[MatchCondition(value="INVOICE"), MatchCondition(value="No")],
            exclude_conditions=[MatchCondition(value="PACKING LIST")],
        )
        assert not profile_matches(p, "PACKING LIST INVOICE No 1")

    def test_chung_tu_chong_lan_dung_ngay_ca_khi_uu_tien_dao_nguoc(self, profiles):
        # Ép Invoice lên ưu tiên cao nhất; exclude_conditions vẫn phải giữ đúng kết quả
        for p in profiles:
            if p.id == "invoice":
                p.priority = 1
        text = "PACKING LIST\nPacking List No.: PL-2026-0442\nInvoice No.: INV-2026-00871"
        assert select_profile(profiles, text).name == "Packing List"

    def test_hoa_don_thuan_van_vao_invoice(self, profiles):
        for p in profiles:
            if p.id == "invoice":
                p.priority = 1
        text = "COMMERCIAL INVOICE\nInvoice No.: INV-2026-00871"
        assert select_profile(profiles, text).name == "Invoice"

    def test_forced_profile_van_bo_qua_ca_dieu_kien_loai_tru(self, profiles):
        # --profile là mệnh lệnh trực tiếp của người dùng, không bị rule chặn
        chosen = select_profile(profiles, "PACKING LIST", forced_id="invoice")
        assert chosen.id == "invoice"

    def test_loai_tru_duoc_luu_va_doc_lai(self, store):
        p = Profile(
            id="p1", name="Invoice",
            conditions=[MatchCondition(value="INVOICE")],
            exclude_conditions=[MatchCondition(value="PACKING LIST")],
        )
        store.save(p)
        loaded = store.get("p1")
        assert [c.value for c in loaded.exclude_conditions] == ["PACKING LIST"]

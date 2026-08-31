"""Test hash SHA-256 và registry chống trùng."""

from __future__ import annotations

from src.core.dedup import DedupRegistry, sha256_file


class TestHash:
    def test_cung_noi_dung_cung_hash(self, tmp_path):
        a, b = tmp_path / "a.pdf", tmp_path / "b.pdf"
        a.write_bytes(b"noi dung giong nhau")
        b.write_bytes(b"noi dung giong nhau")
        assert sha256_file(a) == sha256_file(b)

    def test_khac_noi_dung_khac_hash(self, tmp_path):
        a, b = tmp_path / "a.pdf", tmp_path / "b.pdf"
        a.write_bytes(b"noi dung 1")
        b.write_bytes(b"noi dung 2")
        assert sha256_file(a) != sha256_file(b)

    def test_file_lon_hon_chunk_van_hash_dung(self, tmp_path):
        big = tmp_path / "big.pdf"
        big.write_bytes(b"x" * (2 * 1024 * 1024 + 17))
        assert len(sha256_file(big)) == 64

    def test_file_rong(self, tmp_path):
        empty = tmp_path / "empty.pdf"
        empty.write_bytes(b"")
        # hash SHA-256 của chuỗi rỗng
        assert sha256_file(empty).startswith("e3b0c442")


class TestRegistry:
    def test_file_moi_chua_co_trong_registry(self, db):
        assert DedupRegistry(db).lookup("abc123") is None

    def test_ghi_nhan_va_tra_cuu(self, db):
        reg = DedupRegistry(db)
        reg.record("abc123", source_name="goc.pdf", dest_path="D:/out/moi.pdf", profile_id="inv")
        row = reg.lookup("abc123")
        assert row["source_name"] == "goc.pdf"
        assert row["dest_path"] == "D:/out/moi.pdf"
        assert row["first_seen"] and row["last_seen"]

    def test_xu_ly_lai_cap_nhat_dich_moi_khong_tao_dong_trung(self, db):
        reg = DedupRegistry(db)
        reg.record("abc123", dest_path="D:/out/1.pdf")
        reg.record("abc123", dest_path="D:/out/2.pdf")
        assert reg.count() == 1
        assert reg.lookup("abc123")["dest_path"] == "D:/out/2.pdf"

    def test_quen_file_de_xu_ly_lai_nhu_moi(self, db):
        reg = DedupRegistry(db)
        reg.record("abc123")
        reg.forget("abc123")
        assert reg.lookup("abc123") is None

    def test_trung_mem_theo_so_chung_tu(self, db):
        reg = DedupRegistry(db)
        reg.record("hash-1", profile_id="inv", doc_number="INV-001", dest_path="D:/out/a.pdf")
        others = reg.find_by_number("inv", "INV-001", exclude_hash="hash-2")
        assert len(others) == 1 and others[0]["file_hash"] == "hash-1"

    def test_trung_mem_bo_qua_chinh_no(self, db):
        reg = DedupRegistry(db)
        reg.record("hash-1", profile_id="inv", doc_number="INV-001")
        assert reg.find_by_number("inv", "INV-001", exclude_hash="hash-1") == []

    def test_trung_mem_khac_profile_thi_khong_tinh(self, db):
        reg = DedupRegistry(db)
        reg.record("hash-1", profile_id="inv", doc_number="INV-001")
        assert reg.find_by_number("bl", "INV-001") == []

    def test_so_chung_tu_rong_khong_bao_trung(self, db):
        reg = DedupRegistry(db)
        reg.record("hash-1", profile_id="inv", doc_number="")
        assert reg.find_by_number("inv", "") == []

"""Test Learning Loop: provenance, correction, dataset, counter, thống kê."""

from __future__ import annotations

import json
from datetime import date

from src.core.learning import LearningStore
from src.core.models import ExtractedField, FileJob, Layer


def sample_field(**kw) -> ExtractedField:
    base = dict(
        name="number", value="INV-001", raw_value="Invoice No.: INV-001",
        layer=Layer.REGEX, rule_id="pattern[0]", page=0, bbox=(10.0, 20.0, 90.0, 32.0),
    )
    base.update(kw)
    return ExtractedField(**base)


class TestProvenance:
    def test_ghi_du_metadata_cua_1_field(self, db):
        store = LearningStore(db)
        store.log_field(
            sample_field(), session_id="s1", file_hash="h1", file_name="a.pdf",
            profile_id="inv", rule_version=3,
        )
        rows = store.provenance_for("h1")
        assert len(rows) == 1
        row = rows[0]
        assert row["field_name"] == "number"
        assert row["value"] == "INV-001"
        assert row["raw_value"] == "Invoice No.: INV-001"
        assert row["layer"] == int(Layer.REGEX)
        assert row["rule_id"] == "pattern[0]"
        assert row["page"] == 0
        assert json.loads(row["bbox"]) == [10.0, 20.0, 90.0, 32.0]
        assert row["profile_id"] == "inv"
        assert row["rule_version"] == 3
        assert row["session_id"] == "s1"

    def test_ghi_ca_job(self, db, tmp_path):
        store = LearningStore(db)
        job = FileJob(source=tmp_path / "a.pdf", file_hash="h1", profile_id="inv")
        job.fields = {
            "number": sample_field(),
            "doc_date": sample_field(name="doc_date", value="15/03/2026"),
        }
        store.log_job(job, session_id="s1", rule_version=2)
        assert len(store.provenance_for("h1")) == 2

    def test_danh_dau_field_do_user_sua(self, db):
        store = LearningStore(db)
        store.log_field(sample_field(edited_by_user=True), file_hash="h1")
        assert store.provenance_for("h1")[0]["edited"] == 1


class TestCorrections:
    def test_ghi_nhan_chinh_sua_o_trang_thai_moi(self, db):
        store = LearningStore(db)
        cid = store.record_correction(
            field_name="number", old_value="INV-OO1", new_value="INV-001",
            profile_id="inv", file_name="a.pdf", context="Invoice No.: INV-001",
        )
        rows = store.corrections(profile_id="inv")
        assert len(rows) == 1 and rows[0]["id"] == cid
        assert rows[0]["status"] == "new"
        assert rows[0]["new_value"] == "INV-001"

    def test_duyet_correction(self, db):
        store = LearningStore(db)
        cid = store.record_correction(
            field_name="number", old_value="", new_value="X", profile_id="inv"
        )
        store.set_correction_status(cid, "approved")
        assert store.corrections(profile_id="inv", status="approved")
        assert not store.corrections(profile_id="inv", status="new")

    def test_app_khong_tu_sua_rule(self, db):
        # Correction chỉ là dữ liệu; không có API nào trong LearningStore ghi vào profile
        store = LearningStore(db)
        assert not hasattr(store, "apply_to_profile")
        assert not hasattr(store, "update_profile")


class TestDataset:
    def test_luu_va_export_jsonl(self, db, tmp_path):
        store = LearningStore(db)
        store.save_dataset_row(
            text="COMMERCIAL INVOICE ...", fields={"number": "INV-001"},
            profile_id="inv", file_hash="h1", rule_version=2, corrected=True,
        )
        out = tmp_path / "dataset.jsonl"
        assert store.export_jsonl(out) == 1

        row = json.loads(out.read_text(encoding="utf-8").strip())
        assert row["fields"] == {"number": "INV-001"}
        assert row["corrected"] is True
        assert row["rule_version"] == 2

    def test_export_loc_theo_profile(self, db, tmp_path):
        store = LearningStore(db)
        store.save_dataset_row(text="a", fields={"x": "1"}, profile_id="inv")
        store.save_dataset_row(text="b", fields={"x": "2"}, profile_id="bl")
        assert store.export_jsonl(tmp_path / "inv.jsonl", profile_id="inv") == 1

    def test_few_shot_uu_tien_ban_ghi_da_sua(self, db):
        store = LearningStore(db)
        store.save_dataset_row(text="chua sua", fields={"number": "A"}, profile_id="inv")
        store.save_dataset_row(
            text="da sua", fields={"number": "B"}, profile_id="inv", corrected=True
        )
        examples = store.few_shot_examples("inv", limit=2)
        assert examples[0].text == "da sua"

    def test_few_shot_bo_qua_ban_ghi_thieu_text(self, db):
        store = LearningStore(db)
        store.save_dataset_row(text="", fields={"number": "A"}, profile_id="inv")
        assert store.few_shot_examples("inv") == []


class TestCounter:
    def test_dem_theo_profile_theo_ngay(self, db):
        store = LearningStore(db)
        day = date(2026, 8, 31)
        assert store.next_counter("inv", day) == 1
        assert store.next_counter("inv", day) == 2
        assert store.next_counter("bl", day) == 1  # profile khác đếm riêng

    def test_sang_ngay_moi_dem_lai_tu_dau(self, db):
        store = LearningStore(db)
        store.next_counter("inv", date(2026, 8, 31))
        assert store.next_counter("inv", date(2026, 9, 1)) == 1

    def test_peek_khong_lam_tang_so(self, db):
        store = LearningStore(db)
        day = date(2026, 8, 31)
        assert store.peek_counter("inv", day) == 1
        assert store.peek_counter("inv", day) == 1
        assert store.next_counter("inv", day) == 1


class TestStats:
    def test_ti_le_thanh_cong_theo_profile(self, db):
        store = LearningStore(db)
        for _ in range(3):
            store.record_match("inv", "success", "a.pdf")
        store.record_match("inv", "error", "b.pdf", missing=["number"])
        store.record_match("bl", "success", "c.pdf")

        stats = {s["profile_id"]: s for s in store.profile_stats(30)}
        assert stats["inv"]["total"] == 4
        assert stats["inv"]["success"] == 3
        assert stats["inv"]["errors"] == 1
        assert stats["inv"]["success_rate"] == 75.0
        assert stats["bl"]["success_rate"] == 100.0

    def test_khong_co_du_lieu_tra_danh_sach_rong(self, db):
        assert LearningStore(db).profile_stats(30) == []

"""Test end-to-end: quét file -> plan (Preview) -> apply, kèm dedup, cách ly, hủy batch."""

from __future__ import annotations

import shutil
from datetime import date
from pathlib import Path

import pytest
from src.core.models import JobStatus
from src.core.pipeline import Pipeline, scan_pdfs

TODAY = date(2026, 8, 31)


@pytest.fixture
def inbox(tmp_path, pdfs):
    """Thư mục đầu vào chứa 3 chứng từ hợp lệ + 1 file có mật khẩu."""
    folder = tmp_path / "inbox"
    folder.mkdir()
    for key in ("invoice", "bill_of_lading", "packing_list", "encrypted"):
        shutil.copy2(pdfs[key], folder / pdfs[key].name)
    return folder


@pytest.fixture
def pipeline(config, profiles, db):
    return Pipeline(config, profiles, db)


class TestScan:
    def test_quet_de_quy_chi_lay_pdf(self, tmp_path, pdfs):
        nested = tmp_path / "a" / "b"
        nested.mkdir(parents=True)
        shutil.copy2(pdfs["invoice"], nested / "inv.pdf")
        shutil.copy2(pdfs["masterdata"], tmp_path / "a" / "bang.xlsx")

        found = scan_pdfs([tmp_path])
        assert [p.name for p in found] == ["inv.pdf"]

    def test_khong_lay_trung_file_khi_truyen_ca_file_va_thu_muc(self, tmp_path, pdfs):
        shutil.copy2(pdfs["invoice"], tmp_path / "inv.pdf")
        assert len(scan_pdfs([tmp_path, tmp_path / "inv.pdf"])) == 1

    def test_duong_dan_khong_ton_tai_bi_bo_qua(self, tmp_path):
        assert scan_pdfs([tmp_path / "khong-co"]) == []


class TestPlan:
    def test_dung_ten_moi_theo_template(self, pipeline, inbox):
        jobs = {j.source.name: j for j in pipeline.plan([inbox], when=TODAY)}
        assert jobs["invoice_text.pdf"].new_name == "2026-03-15_INV_INV-2026-00871_Hapag-Lloyd.pdf"
        assert (
            jobs["bl_text.pdf"].new_name
            == "2026-04-02_BL_HLCUSGN2412345_MSKU2482484_Hapag-Lloyd.pdf"
        )

    def test_thu_muc_dich_theo_ngay_xu_ly(self, pipeline, inbox, output_root):
        job = pipeline.plan([inbox / "invoice_text.pdf"], when=TODAY)[0]
        assert job.dest_dir == output_root / "2026-08-31"

    def test_file_co_mat_khau_thanh_loi_khong_lam_chet_batch(self, pipeline, inbox):
        jobs = {j.source.name: j for j in pipeline.plan([inbox], when=TODAY)}
        bad = jobs["invoice_encrypted.pdf"]
        assert bad.status == JobStatus.ERROR
        assert bad.error_code == "password-protected"
        # các file khác vẫn xử lý bình thường
        assert jobs["invoice_text.pdf"].status == JobStatus.PENDING

    def test_thieu_field_bat_buoc_thanh_loi_co_ly_do_ro_rang(self, config, profiles, db, inbox):
        for p in profiles:
            if p.id == "invoice":
                p.fields[0].patterns = [r"KHONG-BAO-GIO-TRUNG (\w+)"]
        jobs = {j.source.name: j for j in Pipeline(config, profiles, db).plan([inbox], when=TODAY)}
        job = jobs["invoice_text.pdf"]
        assert job.status == JobStatus.ERROR
        assert job.error_code == "missing-required-field"
        assert "Số hóa đơn" in job.message

    def test_plan_khong_ghi_gi_ra_dia(self, pipeline, inbox, output_root):
        pipeline.plan([inbox], when=TODAY)
        assert list(output_root.rglob("*.pdf")) == []

    def test_khong_file_nao_bi_bo_sot(self, pipeline, inbox):
        jobs = pipeline.plan([inbox], when=TODAY)
        assert len(jobs) == 4
        assert all(j.status != JobStatus.PROCESSING for j in jobs)

    def test_deterministic_chay_2_lan_cung_ten_co_so(self, config, profiles, db, inbox):
        first = Pipeline(config, profiles, db).plan([inbox], when=TODAY)
        second = Pipeline(config, profiles, db).plan([inbox], when=TODAY)
        assert [j.base_name for j in first] == [j.base_name for j in second]

    def test_hai_file_giong_ten_dich_duoc_them_hau_to(self, config, profiles, db, tmp_path, pdfs):
        folder = tmp_path / "hai-ban-sao"
        folder.mkdir()
        shutil.copy2(pdfs["invoice"], folder / "ban-1.pdf")
        # đổi 1 byte để hash khác nhau nhưng nội dung trích vẫn giống hệt
        data = pdfs["invoice"].read_bytes()
        (folder / "ban-2.pdf").write_bytes(data + b"\n% khac hash")

        jobs = Pipeline(config, profiles, db).plan([folder], when=TODAY)
        names = sorted(j.new_name for j in jobs)
        assert names[1].endswith("_01.pdf")


class TestApply:
    def test_ghi_file_ra_dung_thu_muc(self, pipeline, inbox, output_root):
        jobs = pipeline.plan([inbox], when=TODAY)
        summary = pipeline.apply(jobs)

        assert summary.success == 3
        assert summary.errors == 1
        written = sorted(p.name for p in (output_root / "2026-08-31").glob("*.pdf"))
        assert len(written) == 3

    def test_file_loi_vao_thu_muc_cach_ly_kem_ly_do(self, pipeline, inbox, output_root):
        pipeline.apply(pipeline.plan([inbox], when=TODAY))
        quarantine = output_root / "_Loi"
        assert (quarantine / "invoice_encrypted.pdf").exists()
        note = quarantine / "invoice_encrypted.pdf.txt"
        assert "password-protected" in note.read_text(encoding="utf-8")

    def test_che_do_copy_giu_file_goc(self, pipeline, inbox):
        pipeline.apply(pipeline.plan([inbox], when=TODAY))
        assert (inbox / "invoice_text.pdf").exists()

    def test_che_do_move_don_sach_thu_muc_vao(self, config, profiles, db, inbox):
        config.mode = "move"
        p = Pipeline(config, profiles, db)
        p.apply(p.plan([inbox], when=TODAY))
        assert not (inbox / "invoice_text.pdf").exists()
        assert list(p.mover.backup_dir().glob("*.pdf"))

    def test_ghi_operation_log_cho_undo(self, pipeline, inbox):
        summary = pipeline.apply(pipeline.plan([inbox], when=TODAY))
        assert summary.log_path and summary.log_path.exists()

    def test_ghi_registry_de_lan_sau_biet_trung(self, pipeline, inbox):
        pipeline.apply(pipeline.plan([inbox], when=TODAY))
        assert pipeline.dedup.count() == 3

    def test_ghi_provenance_cho_tung_field(self, pipeline, inbox):
        jobs = pipeline.plan([inbox], when=TODAY)
        pipeline.apply(jobs)
        job = next(j for j in jobs if j.source.name == "invoice_text.pdf")
        rows = pipeline.learning.provenance_for(job.file_hash)
        assert {r["field_name"] for r in rows} >= {"number", "doc_date"}
        assert all(r["rule_version"] >= 1 for r in rows)


class TestDeduplication:
    def test_chay_lan_2_bao_trung(self, config, profiles, db, inbox):
        first = Pipeline(config, profiles, db)
        first.apply(first.plan([inbox], when=TODAY))

        second = Pipeline(config, profiles, db)
        jobs = second.plan([inbox], when=TODAY)
        duplicates = [j for j in jobs if j.status == JobStatus.DUPLICATE]
        assert len(duplicates) == 3
        assert "Đã xử lý ngày" in duplicates[0].message
        assert duplicates[0].previous["dest_path"]

    def test_ignore_dedup_de_xu_ly_lai(self, config, profiles, db, inbox):
        first = Pipeline(config, profiles, db)
        first.apply(first.plan([inbox], when=TODAY))

        second = Pipeline(config, profiles, db)
        job = second.plan_one(inbox / "invoice_text.pdf", ignore_dedup=True, when=TODAY)
        assert job.status == JobStatus.PENDING and job.new_name

    def test_tat_dedup_trong_config(self, config, profiles, db, inbox):
        first = Pipeline(config, profiles, db)
        first.apply(first.plan([inbox], when=TODAY))

        config.dedup_enabled = False
        second = Pipeline(config, profiles, db)
        jobs = second.plan([inbox], when=TODAY)
        assert not any(j.status == JobStatus.DUPLICATE for j in jobs)

    def test_canh_bao_trung_mem_theo_so_chung_tu(self, config, profiles, db, inbox, tmp_path, pdfs):
        first = Pipeline(config, profiles, db)
        first.apply(first.plan([inbox], when=TODAY))

        # cùng số hóa đơn, khác nội dung file -> chỉ cảnh báo, không chặn
        folder = tmp_path / "lan-2"
        folder.mkdir()
        (folder / "ban-sao.pdf").write_bytes(pdfs["invoice"].read_bytes() + b"\n% doi hash")

        second = Pipeline(config, profiles, db)
        job = second.plan([folder], when=TODAY)[0]
        assert job.status == JobStatus.PENDING
        assert any("Trùng số chứng từ" in w for w in job.warnings)


class TestCounter:
    def test_counter_chi_dung_cho_profile_chung(self, config, profiles, db, tmp_path, pdfs):
        folder = tmp_path / "chung"
        folder.mkdir()
        shutil.copy2(pdfs["unknown"], folder / "memo.pdf")

        for p in profiles:
            if p.is_fallback:
                p.template = "{doctype}_{counter}"

        job = Pipeline(config, profiles, db).plan([folder], when=TODAY)[0]
        assert job.new_name == "DOC_001.pdf"

    def test_dry_run_khong_dot_so_dem(self, config, profiles, db, tmp_path, pdfs):
        folder = tmp_path / "chung"
        folder.mkdir()
        shutil.copy2(pdfs["unknown"], folder / "memo.pdf")
        for p in profiles:
            if p.is_fallback:
                p.template = "{doctype}_{counter}"

        Pipeline(config, profiles, db).plan([folder], dry_run=True, when=TODAY)
        job = Pipeline(config, profiles, db).plan([folder], dry_run=True, when=TODAY)[0]
        assert job.new_name == "DOC_001.pdf"


class TestManualEdit:
    def test_user_sua_tay_ten_file(self, pipeline, inbox):
        job = pipeline.plan([inbox / "invoice_text.pdf"], when=TODAY)[0]
        pipeline.rename_manually(job, "TEN-DO-USER-DAT")
        assert job.new_name == "TEN-DO-USER-DAT.pdf"

    def test_ten_user_dat_van_duoc_lam_sach(self, pipeline, inbox):
        job = pipeline.plan([inbox / "invoice_text.pdf"], when=TODAY)[0]
        pipeline.rename_manually(job, 'TEN/CO:KY*TU?CAM')
        assert job.new_name == "TENCOKYTUCAM.pdf"


class TestCancel:
    def test_huy_batch(self, pipeline, inbox):
        pipeline.cancel()
        jobs = pipeline.plan([inbox], when=TODAY)
        assert all(j.error_code == "cancelled" for j in jobs)


class TestBarcodeInFilename:
    """Field tùy chọn lấy từ barcode phải xuất hiện được trong tên file."""

    def test_ten_file_bl_co_so_container_tu_barcode(self, config, profiles, db, tmp_path, pdfs):
        from src.core.barcode import AVAILABLE

        if not AVAILABLE:
            pytest.skip("pyzbar không dùng được trên máy này")

        folder = tmp_path / "bc"
        folder.mkdir()
        shutil.copy2(pdfs["barcode"], folder / "bl_barcode.pdf")

        job = Pipeline(config, profiles, db).plan([folder], when=TODAY)[0]
        assert "MSKU2482484" in job.new_name
        assert job.new_name == "2026-04-05_BL_ONEYSGNF1234567_MSKU2482484.pdf"


class TestStripAccents:
    """Toggle bỏ dấu tiếng Việt trong tên file (spec mục 4)."""

    @pytest.fixture
    def vietnamese_file(self, tmp_path, pdfs):
        folder = tmp_path / "co-dau"
        folder.mkdir()
        target = folder / "Hóa đơn tháng Tư.pdf"
        shutil.copy2(pdfs["invoice"], target)
        return target

    def test_mac_dinh_giu_nguyen_dau(self, config, profiles, db, vietnamese_file):
        job = Pipeline(config, profiles, db).plan_one(
            vietnamese_file, forced_profile="chung", when=TODAY
        )
        assert job.new_name == "Hóa đơn tháng Tư.pdf"

    def test_bat_toggle_thi_bo_dau(self, config, profiles, db, vietnamese_file):
        config.strip_accents = True
        job = Pipeline(config, profiles, db).plan_one(
            vietnamese_file, forced_profile="chung", when=TODAY
        )
        assert job.new_name == "Hoa don thang Tu.pdf"

    def test_bo_dau_ca_khi_user_sua_tay(self, config, profiles, db, vietnamese_file):
        config.strip_accents = True
        pipeline = Pipeline(config, profiles, db)
        job = pipeline.plan_one(vietnamese_file, forced_profile="chung", when=TODAY)
        pipeline.rename_manually(job, "Chứng từ đã duyệt")
        assert job.new_name == "Chung tu da duyet.pdf"

    def test_bo_dau_ap_dung_cho_gia_tri_field(self, config, profiles, db, vietnamese_file):
        config.strip_accents = True
        for p in profiles:
            if p.is_fallback:
                p.template = "{doctype}_{original_name}"
        job = Pipeline(config, profiles, db).plan_one(
            vietnamese_file, forced_profile="chung", when=TODAY
        )
        assert job.new_name == "DOC_Hoa don thang Tu.pdf"


class TestTimeoutDiscardsLateResult:
    """File quá timeout: kết quả về muộn phải bị HỦY hoàn toàn, không rò rỉ vào DB."""

    class SlowExtractor:
        """Bọc extractor thật, cố tình làm chậm đúng 1 file."""

        def __init__(self, inner, slow_name: str, delay: float) -> None:
            self.inner = inner
            self.slow_name = slow_name
            self.delay = delay

        def extract(self, path, forced_profile: str = ""):
            import time as _time

            if Path(path).name == self.slow_name:
                _time.sleep(self.delay)
            return self.inner.extract(path, forced_profile)

    @pytest.fixture
    def slow_pipeline(self, config, profiles, db, tmp_path, pdfs):
        folder = tmp_path / "cham"
        folder.mkdir()
        shutil.copy2(pdfs["invoice"], folder / "cham.pdf")
        shutil.copy2(pdfs["bill_of_lading"], folder / "nhanh.pdf")

        config.timeout_seconds = 1
        config.workers = 2
        base = Pipeline(config, profiles, db)
        base.extractor = self.SlowExtractor(base.extractor, "cham.pdf", 2.5)
        return base, folder

    def test_file_qua_han_bi_danh_timeout(self, slow_pipeline):
        pipeline, folder = slow_pipeline
        jobs = {j.source.name: j for j in pipeline.plan([folder], when=TODAY)}

        assert jobs["cham.pdf"].status == JobStatus.ERROR
        assert jobs["cham.pdf"].error_code == "timeout"
        # file nhanh trong cùng batch không bị ảnh hưởng
        assert jobs["nhanh.pdf"].status == JobStatus.PENDING

    def test_ket_qua_muon_bi_huy(self, slow_pipeline):
        pipeline, folder = slow_pipeline
        pipeline.plan([folder], when=TODAY)
        # plan() chỉ trả về sau khi pool đóng, nên luồng muộn đã chạy xong và bị hủy
        assert pipeline.late_results_discarded == 1

    def test_khong_ghi_dedup_khong_ghi_provenance(self, slow_pipeline):
        pipeline, folder = slow_pipeline
        jobs = pipeline.plan([folder], when=TODAY)
        slow = next(j for j in jobs if j.source.name == "cham.pdf")

        assert pipeline.dedup.lookup(slow.file_hash) is None
        assert pipeline.learning.provenance_for(slow.file_hash) == []

    def test_xu_ly_lai_file_timeout_khong_bi_bao_trung(self, slow_pipeline, config, profiles, db):
        pipeline, folder = slow_pipeline
        jobs = pipeline.plan([folder], when=TODAY)
        pipeline.apply(jobs)  # file timeout đi vào thư mục cách ly

        # Lần sau xử lý lại (không còn chậm) -> phải là file mới, KHÔNG phải Trùng
        config.timeout_seconds = 120
        again = Pipeline(config, profiles, db)
        job = again.plan_one(folder / "cham.pdf", when=TODAY)
        assert job.status == JobStatus.PENDING
        assert job.new_name == "2026-03-15_INV_INV-2026-00871_Hapag-Lloyd.pdf"

    def test_file_timeout_van_duoc_cach_ly_khong_bo_sot(self, slow_pipeline, output_root):
        pipeline, folder = slow_pipeline
        summary = pipeline.apply(pipeline.plan([folder], when=TODAY))

        assert summary.errors == 1
        note = output_root / "_Loi" / "cham.pdf.txt"
        assert note.exists()
        assert "timeout" in note.read_text(encoding="utf-8")

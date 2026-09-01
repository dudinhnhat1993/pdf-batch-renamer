"""Test ghi file ra output: copy/move, thư mục theo ngày, cách ly, backup, Undo."""

from __future__ import annotations

from datetime import date

import pytest
from src.core.errors import PdfRenamerError
from src.core.models import ExtractedField, FileJob, JobStatus
from src.core.mover import Mover, list_sessions, undo_session


@pytest.fixture
def source_file(tmp_path):
    src = tmp_path / "goc" / "chung-tu-goc.pdf"
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_bytes(b"%PDF-1.4 noi dung gia")
    return src


def make_job(source, mover, name="2026-03-15_INV_A1.pdf") -> FileJob:
    job = FileJob(source=source, profile_id="inv", profile_name="Invoice")
    job.dest_dir = mover.destination_dir(date(2026, 8, 31))
    job.new_name = mover.reserve(job.dest_dir, name)
    return job


class TestDestination:
    def test_thu_muc_con_theo_ngay_xu_ly(self, config, source_file):
        mover = Mover(config)
        assert mover.destination_dir(date(2026, 8, 31)).name == "2026-08-31"

    def test_mau_thu_muc_long_nhau(self, config):
        config.subfolder_pattern = "{YYYY}/{MM}"
        dest = Mover(config).destination_dir(date(2026, 8, 31))
        assert dest.parent.name == "2026" and dest.name == "08"

    def test_tat_thu_muc_con(self, config, output_root):
        config.subfolder_enabled = False
        assert Mover(config).destination_dir(date(2026, 8, 31)) == output_root

    def test_chua_cau_hinh_output_thi_bao_loi(self, config):
        config.output_root = ""
        with pytest.raises(PdfRenamerError):
            Mover(config)


class TestReserve:
    def test_hai_file_cung_batch_khong_duoc_trung_duong_dan(self, config, source_file):
        mover = Mover(config)
        d = mover.destination_dir()
        assert mover.reserve(d, "A.pdf") == "A.pdf"
        assert mover.reserve(d, "A.pdf") == "A_01.pdf"

    def test_nha_cho_khi_user_sua_ten(self, config):
        mover = Mover(config)
        d = mover.destination_dir()
        mover.reserve(d, "A.pdf")
        mover.release(d, "A.pdf")
        assert mover.reserve(d, "A.pdf") == "A.pdf"


class TestCopyMove:
    def test_copy_giu_nguyen_file_goc(self, config, source_file):
        mover = Mover(config)
        job = make_job(source_file, mover)
        dest = mover.apply(job)
        assert dest.exists() and source_file.exists()
        assert dest.read_bytes() == b"%PDF-1.4 noi dung gia"

    def test_move_xoa_file_goc_va_tao_backup(self, config, source_file):
        config.mode = "move"
        mover = Mover(config)
        job = make_job(source_file, mover)
        dest = mover.apply(job)

        assert dest.exists() and not source_file.exists()
        backups = list(mover.backup_dir().glob("*.pdf"))
        assert len(backups) == 1 and backups[0].read_bytes() == b"%PDF-1.4 noi dung gia"

    def test_ghi_de_duoc_chan_bang_hau_to(self, config, source_file):
        mover = Mover(config)
        job = make_job(source_file, mover)
        first = mover.apply(job)

        job2 = FileJob(source=source_file)
        job2.dest_dir = job.dest_dir
        job2.new_name = first.name  # cố tình đặt trùng tên
        second = mover.apply(job2)
        assert second != first and first.exists() and second.exists()

    def test_thieu_dich_thi_bao_loi(self, config, source_file):
        with pytest.raises(PdfRenamerError):
            Mover(config).apply(FileJob(source=source_file))


class TestQuarantine:
    def test_file_loi_vao_thu_muc_loi_kem_ly_do(self, config, source_file):
        mover = Mover(config)
        job = FileJob(
            source=source_file, status=JobStatus.ERROR, profile_name="Invoice",
            error_code="missing-required-field",
        )
        job.fields["number"] = ExtractedField(name="number", value="INV-1")

        dest = mover.quarantine(job, "Thiếu field bắt buộc: Ngày hóa đơn")
        assert dest.parent.name == "_Loi"
        assert dest.exists()

        note = dest.with_suffix(dest.suffix + ".txt")
        content = note.read_text(encoding="utf-8")
        assert "Thiếu field bắt buộc" in content
        assert "missing-required-field" in content
        assert "number: INV-1" in content

    def test_cach_ly_khong_bo_sot_khi_khong_co_field_nao(self, config, source_file):
        mover = Mover(config)
        job = FileJob(source=source_file, status=JobStatus.ERROR)
        dest = mover.quarantine(job, "PDF hỏng", code="pdf-open-failed")
        note = dest.with_suffix(dest.suffix + ".txt")
        assert "(không có)" in note.read_text(encoding="utf-8")


class TestOperationLogAndUndo:
    def test_log_ghi_lai_moi_thao_tac(self, config, source_file):
        mover = Mover(config)
        mover.apply(make_job(source_file, mover))
        log = mover.save_log()
        assert log is not None and log.exists()
        assert list_sessions(log.parent)[0] == log

    def test_khong_thao_tac_thi_khong_tao_log_rac(self, config):
        assert Mover(config).save_log() is None

    def test_undo_che_do_copy_xoa_file_da_ghi(self, config, source_file):
        mover = Mover(config)
        dest = mover.apply(make_job(source_file, mover))
        log = mover.save_log()

        undone, errors = undo_session(log)
        assert undone == 1 and not errors
        assert not dest.exists() and source_file.exists()

    def test_undo_che_do_move_tra_file_ve_cho_cu(self, config, source_file):
        config.mode = "move"
        mover = Mover(config)
        dest = mover.apply(make_job(source_file, mover))
        log = mover.save_log()

        undone, errors = undo_session(log)
        assert undone == 1 and not errors
        assert source_file.exists() and not dest.exists()

    def test_undo_khoi_phuc_ca_file_da_cach_ly(self, config, source_file):
        config.mode = "move"
        mover = Mover(config)
        job = FileJob(source=source_file, status=JobStatus.ERROR)
        dest = mover.quarantine(job, "loi gi do")
        log = mover.save_log()

        undo_session(log)
        assert source_file.exists()
        assert not dest.exists()
        assert not dest.with_suffix(dest.suffix + ".txt").exists()

    def test_log_duoc_danh_dau_da_hoan_tac(self, config, source_file):
        mover = Mover(config)
        mover.apply(make_job(source_file, mover))
        log = mover.save_log()
        undo_session(log)
        assert not log.exists()
        assert log.with_suffix(".json.undone").exists()


class TestBackupCleanup:
    def test_xoa_backup_qua_han(self, config, source_file):
        import os
        import time

        config.mode = "move"
        mover = Mover(config)
        mover.apply(make_job(source_file, mover))

        old = mover.backup_dir()
        stale = time.time() - 40 * 86400
        os.utime(old, (stale, stale))

        assert mover.cleanup_backups(30) == 1
        assert not old.exists()

    def test_giu_backup_con_han(self, config, source_file):
        config.mode = "move"
        mover = Mover(config)
        mover.apply(make_job(source_file, mover))
        assert mover.cleanup_backups(30) == 0
        assert mover.backup_dir().exists()

    def test_retention_0_nghia_la_khong_bao_gio_xoa(self, config, source_file):
        config.mode = "move"
        mover = Mover(config)
        mover.apply(make_job(source_file, mover))
        assert mover.cleanup_backups(0) == 0

"""Test watch folder: chỉ nhặt file khi kích thước đã đứng yên (tránh file copy dở)."""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from src.core.watcher import StableFileWatcher


@pytest.fixture
def watch_dir(tmp_path):
    d = tmp_path / "watch"
    d.mkdir()
    return d


def make_watcher(folder, seen: list, **kw) -> StableFileWatcher:
    return StableFileWatcher(folder, seen.append, poll_interval=0.05, **kw)


class TestStability:
    def test_file_dang_copy_do_chua_duoc_nhat(self, watch_dir):
        seen: list[Path] = []
        w = make_watcher(watch_dir, seen, stable_seconds=5)
        f = watch_dir / "dang-copy.pdf"
        f.write_bytes(b"mot phan")

        w.enqueue(f)
        assert w.check_once() == []  # chưa đủ thời gian ổn định
        assert seen == []

    def test_file_da_ghi_xong_thi_duoc_nhat(self, watch_dir):
        seen: list[Path] = []
        w = make_watcher(watch_dir, seen, stable_seconds=0)
        f = watch_dir / "xong.pdf"
        f.write_bytes(b"day du")

        w.enqueue(f)
        assert w.check_once() == [f]
        assert seen == [f]

    def test_kich_thuoc_doi_thi_dat_lai_dong_ho(self, watch_dir):
        seen: list[Path] = []
        w = make_watcher(watch_dir, seen, stable_seconds=0.2)
        f = watch_dir / "dang-lon-dan.pdf"

        f.write_bytes(b"phan 1")
        w.enqueue(f)
        time.sleep(0.25)

        f.write_bytes(b"phan 1 + phan 2")  # file lớn thêm -> phải chờ lại từ đầu
        assert w.check_once() == []

        time.sleep(0.25)
        assert w.check_once() == [f]

    def test_khong_xu_ly_lai_file_da_nhat(self, watch_dir):
        seen: list[Path] = []
        w = make_watcher(watch_dir, seen, stable_seconds=0)
        f = watch_dir / "a.pdf"
        f.write_bytes(b"x")

        w.enqueue(f)
        w.check_once()
        w.enqueue(f)
        assert w.check_once() == []
        assert len(seen) == 1

    def test_bo_qua_file_khong_phai_pdf(self, watch_dir):
        seen: list[Path] = []
        w = make_watcher(watch_dir, seen, stable_seconds=0)
        f = watch_dir / "bang.xlsx"
        f.write_bytes(b"x")

        w.enqueue(f)
        assert w.check_once() == []

    def test_file_bien_mat_giua_chung_khong_lam_chet(self, watch_dir):
        seen: list[Path] = []
        w = make_watcher(watch_dir, seen, stable_seconds=0)
        f = watch_dir / "bay-hoi.pdf"
        f.write_bytes(b"x")
        w.enqueue(f)
        f.unlink()

        assert w.check_once() == []
        assert seen == []

    def test_loi_khi_xu_ly_1_file_khong_lam_chet_watcher(self, watch_dir):
        def boom(path):
            raise RuntimeError("loi xu ly")

        w = StableFileWatcher(watch_dir, boom, stable_seconds=0, poll_interval=0.05)
        f = watch_dir / "a.pdf"
        f.write_bytes(b"x")
        w.enqueue(f)
        assert w.check_once() == [f]  # nuốt lỗi, ghi log, không ném ra ngoài


class TestLifecycle:
    def test_thu_muc_khong_ton_tai_bao_loi_ro_rang(self, tmp_path):
        w = StableFileWatcher(tmp_path / "khong-co", lambda p: None)
        with pytest.raises(FileNotFoundError):
            w.start()

    def test_start_stop_va_nhat_file_moi(self, watch_dir):
        seen: list[Path] = []
        w = make_watcher(watch_dir, seen, stable_seconds=0)
        with w:
            (watch_dir / "moi.pdf").write_bytes(b"noi dung")
            for _ in range(40):  # chờ tối đa ~2s
                if seen:
                    break
                time.sleep(0.05)
        assert [p.name for p in seen] == ["moi.pdf"]

    def test_process_existing_nhat_ca_file_co_san(self, watch_dir):
        (watch_dir / "co-san.pdf").write_bytes(b"x")
        seen: list[Path] = []
        w = make_watcher(watch_dir, seen, stable_seconds=0, process_existing=True)
        with w:
            for _ in range(40):
                if seen:
                    break
                time.sleep(0.05)
        assert [p.name for p in seen] == ["co-san.pdf"]

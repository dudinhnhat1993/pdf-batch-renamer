"""Test CLI và exit code chuẩn cho n8n/script ngoài: 0 = ok, 1 = có lỗi, 2 = sai cấu hình."""

from __future__ import annotations

import shutil

import pytest
from src.cli import EXIT_CONFIG, EXIT_HAS_ERRORS, EXIT_OK, run


@pytest.fixture
def good_inbox(tmp_path, pdfs):
    folder = tmp_path / "in-ok"
    folder.mkdir()
    for key in ("invoice", "bill_of_lading", "packing_list"):
        shutil.copy2(pdfs[key], folder / pdfs[key].name)
    return folder


@pytest.fixture
def bad_inbox(tmp_path, pdfs):
    folder = tmp_path / "in-loi"
    folder.mkdir()
    shutil.copy2(pdfs["encrypted"], folder / "co-mat-khau.pdf")
    return folder


class TestExitCodes:
    def test_tat_ca_thanh_cong_tra_0(self, good_inbox, output_root, capsys):
        code = run(["--input", str(good_inbox), "--output", str(output_root)])
        assert code == EXIT_OK
        assert len(list((output_root).rglob("*.pdf"))) == 3

    def test_co_file_loi_tra_1(self, bad_inbox, output_root):
        code = run(["--input", str(bad_inbox), "--output", str(output_root)])
        assert code == EXIT_HAS_ERRORS
        assert (output_root / "_Loi" / "co-mat-khau.pdf").exists()

    def test_thieu_output_tra_2(self, good_inbox):
        assert run(["--input", str(good_inbox)]) == EXIT_CONFIG

    def test_input_khong_ton_tai_tra_2(self, tmp_path, output_root):
        code = run(["--input", str(tmp_path / "khong-co"), "--output", str(output_root)])
        assert code == EXIT_CONFIG

    def test_profile_khong_ton_tai_tra_2(self, good_inbox, output_root):
        code = run(
            ["--input", str(good_inbox), "--output", str(output_root), "--profile", "khong-co"]
        )
        assert code == EXIT_CONFIG

    def test_thu_muc_rong_tra_0(self, tmp_path, output_root):
        empty = tmp_path / "rong"
        empty.mkdir()
        assert run(["--input", str(empty), "--output", str(output_root)]) == EXIT_OK


class TestDryRun:
    def test_khong_ghi_file_nao(self, good_inbox, output_root, capsys):
        code = run(["--input", str(good_inbox), "--output", str(output_root), "--dry-run"])
        assert code == EXIT_OK
        assert list(output_root.rglob("*.pdf")) == []
        assert "DRY-RUN" in capsys.readouterr().out

    def test_in_bang_ten_cu_ten_moi(self, good_inbox, output_root, capsys):
        run(["--input", str(good_inbox), "--output", str(output_root), "--dry-run"])
        out = capsys.readouterr().out
        assert "TÊN CŨ" in out and "TÊN MỚI" in out
        assert "invoice_text.pdf" in out
        assert "2026-03-15_INV_INV-2026-00871" in out


class TestOptions:
    def test_ep_profile_bo_qua_dieu_kien_nhan_dien(self, good_inbox, output_root, capsys):
        run(
            [
                "--input", str(good_inbox), "--output", str(output_root),
                "--profile", "Packing List", "--dry-run",
            ]
        )
        out = capsys.readouterr().out
        # cả 3 file đều bị ép sang profile Packing List
        assert out.count("Packing List") >= 3

    def test_no_dedup_van_xu_ly_file_da_chay(self, good_inbox, output_root):
        run(["--input", str(good_inbox), "--output", str(output_root)])
        code = run(["--input", str(good_inbox), "--output", str(output_root), "--no-dedup"])
        assert code == EXIT_OK

    def test_lan_2_khong_no_dedup_thi_bao_trung(self, good_inbox, output_root, capsys):
        run(["--input", str(good_inbox), "--output", str(output_root)])
        run(["--input", str(good_inbox), "--output", str(output_root)])
        assert "Trùng" in capsys.readouterr().out

    def test_watch_khong_co_thu_muc_tra_2(self, good_inbox, output_root):
        code = run(
            [
                "--input", str(good_inbox / "invoice_text.pdf"),
                "--output", str(output_root), "--watch",
            ]
        )
        assert code == EXIT_CONFIG

"""Test dò Tesseract, thư mục tessdata riêng của app, và cài gói ngôn ngữ (mock mạng)."""

from __future__ import annotations

from pathlib import Path

import pytest
from src.core.bootstrap import RepeatFilter, quiet_noisy_libraries
from src.core.config import tessdata_dir
from src.core.ocr import bundled_tessdata_of, find_tessdata, install_language_pack

FAKE_PACK = b"x" * 20000  # đủ lớn để qua kiểm tra kích thước tối thiểu


class TestFindTessdata:
    def test_uu_tien_duong_dan_cau_hinh_tay(self, tmp_path):
        custom = tmp_path / "tessdata-rieng"
        custom.mkdir()
        (custom / "eng.traineddata").write_bytes(FAKE_PACK)
        assert find_tessdata(str(custom)) == str(custom)

    def test_dung_tessdata_cua_app_khi_de_trong(self, isolated_home):
        target = tessdata_dir()
        target.mkdir(parents=True, exist_ok=True)
        (target / "vie.traineddata").write_bytes(FAKE_PACK)
        assert find_tessdata("") == str(target)

    def test_thu_muc_rong_van_dung_thu_muc_cua_app(self, isolated_home):
        """Không bao giờ âm thầm rơi về tessdata mặc định của Tesseract."""
        tessdata_dir().mkdir(parents=True, exist_ok=True)
        assert find_tessdata("") == str(tessdata_dir())

    def test_duong_dan_cau_hinh_sai_thi_quay_ve_thu_muc_app(self, isolated_home, tmp_path):
        assert find_tessdata(str(tmp_path / "khong-ton-tai")) == str(tessdata_dir())

    def test_tu_tao_thu_muc_neu_chua_co(self, isolated_home):
        target = tessdata_dir()
        assert not target.exists()
        assert find_tessdata("") == str(target)
        assert target.is_dir()

    def test_moi_san_goi_co_ban_tu_ban_tesseract_da_cai(self, isolated_home, tmp_path):
        """Thư mục của app được mồi eng/osd để nó không bao giờ rỗng."""
        from src.core.ocr import ensure_app_tessdata

        exe_dir = tmp_path / "Tesseract-OCR"
        (exe_dir / "tessdata").mkdir(parents=True)
        for name in ("eng.traineddata", "osd.traineddata"):
            (exe_dir / "tessdata" / name).write_bytes(FAKE_PACK)
        exe = exe_dir / "tesseract.exe"
        exe.write_bytes(b"MZ")

        target = ensure_app_tessdata(str(exe))
        assert {p.name for p in target.glob("*.traineddata")} == {
            "eng.traineddata",
            "osd.traineddata",
        }

    def test_khong_moi_de_len_goi_da_co(self, isolated_home, tmp_path):
        from src.core.ocr import ensure_app_tessdata

        target = tessdata_dir()
        target.mkdir(parents=True, exist_ok=True)
        (target / "vie.traineddata").write_bytes(b"da co san")

        exe_dir = tmp_path / "Tesseract-OCR"
        (exe_dir / "tessdata").mkdir(parents=True)
        (exe_dir / "tessdata" / "eng.traineddata").write_bytes(FAKE_PACK)
        exe = exe_dir / "tesseract.exe"
        exe.write_bytes(b"MZ")

        ensure_app_tessdata(str(exe))
        assert (target / "vie.traineddata").read_bytes() == b"da co san"
        assert not (target / "eng.traineddata").exists()

    def test_tim_tessdata_di_kem_ban_cai(self, tmp_path):
        exe_dir = tmp_path / "Tesseract-OCR"
        (exe_dir / "tessdata").mkdir(parents=True)
        exe = exe_dir / "tesseract.exe"
        exe.write_bytes(b"MZ")
        assert bundled_tessdata_of(str(exe)) == exe_dir / "tessdata"

    def test_khong_co_exe_thi_tra_none(self):
        assert bundled_tessdata_of("") is None


class TestInstallLanguagePack:
    def test_chep_tu_ban_tesseract_da_cai(self, isolated_home, tmp_path):
        exe_dir = tmp_path / "Tesseract-OCR"
        (exe_dir / "tessdata").mkdir(parents=True)
        (exe_dir / "tessdata" / "vie.traineddata").write_bytes(FAKE_PACK)
        exe = exe_dir / "tesseract.exe"
        exe.write_bytes(b"MZ")

        ok, message = install_language_pack("vie", exe=str(exe))
        assert ok and "chép" in message.lower()
        assert (tessdata_dir() / "vie.traineddata").read_bytes() == FAKE_PACK

    def test_tai_ve_khi_may_khong_co_san(self, isolated_home, tmp_path):
        called = {}

        def fake_download(url, timeout=120):
            called["url"] = url
            return FAKE_PACK

        ok, message = install_language_pack("vie", exe="", downloader=fake_download)
        assert ok and "tải" in message.lower()
        assert called["url"].endswith("/vie.traineddata")
        assert (tessdata_dir() / "vie.traineddata").exists()

    def test_da_co_thi_khong_tai_lai(self, isolated_home):
        target = tessdata_dir()
        target.mkdir(parents=True, exist_ok=True)
        (target / "vie.traineddata").write_bytes(FAKE_PACK)

        def boom(url, timeout=120):
            raise AssertionError("không được tải lại khi đã có sẵn")

        ok, message = install_language_pack("vie", downloader=boom)
        assert ok and "đã có sẵn" in message

    def test_loi_mang_bao_ro_va_chi_cach_tai_tay(self, isolated_home):
        def broken(url, timeout=120):
            raise ConnectionError("mất mạng")

        ok, message = install_language_pack("vie", exe="", downloader=broken)
        assert not ok
        assert "tải tay" in message and "vie.traineddata" in message

    def test_file_tai_ve_qua_nho_bi_tu_choi(self, isolated_home):
        ok, message = install_language_pack("vie", exe="", downloader=lambda u, timeout=120: b"404")
        assert not ok and "không hợp lệ" in message
        assert not (tessdata_dir() / "vie.traineddata").exists()

    def test_ma_ngon_ngu_rong(self, isolated_home):
        ok, _ = install_language_pack("")
        assert not ok

    def test_ghi_vao_thu_muc_chi_dinh(self, isolated_home, tmp_path):
        target = tmp_path / "noi-khac"
        ok, _ = install_language_pack(
            "vie", target_dir=target, exe="", downloader=lambda u, timeout=120: FAKE_PACK
        )
        assert ok and (target / "vie.traineddata").exists()


class TestLogNoise:
    def test_thu_vien_on_ao_bi_ha_xuong_error(self):
        import logging

        quiet_noisy_libraries()
        assert logging.getLogger("pdfminer").level == logging.ERROR
        assert logging.getLogger("pdfminer.pdffont").level == logging.ERROR
        assert logging.getLogger("pdfplumber").level == logging.ERROR

    def _record(self, message: str, level: int = 30) -> object:
        import logging

        return logging.LogRecord("x", level, __file__, 1, message, None, None)

    def test_gom_dong_lap_lai(self):
        f = RepeatFilter(max_repeats=1)
        assert f.filter(self._record("Could not get FontBBox"))  # lần đầu: cho qua
        second = self._record("Could not get FontBBox")
        assert f.filter(second)  # lần hai: cho qua kèm ghi chú đã gom
        assert "gom lại" in second.getMessage()
        for _ in range(10):
            assert not f.filter(self._record("Could not get FontBBox"))

    def test_dong_khac_nhau_khong_bi_gom(self):
        f = RepeatFilter(max_repeats=1)
        assert f.filter(self._record("cảnh báo A"))
        assert f.filter(self._record("cảnh báo B"))

    def test_khong_bao_gio_gom_loi_that(self):
        import logging

        f = RepeatFilter(max_repeats=1)
        for _ in range(5):
            assert f.filter(self._record("lỗi nghiêm trọng", logging.ERROR))

    def test_reset_khi_bat_dau_batch_moi(self):
        f = RepeatFilter(max_repeats=1)
        f.filter(self._record("trùng"))
        f.filter(self._record("trùng"))
        assert not f.filter(self._record("trùng"))
        f.reset()
        assert f.filter(self._record("trùng"))


@pytest.mark.integration
def test_tessdata_that_cua_may_co_du_goi():
    """Trên máy dev: gói vie phải nằm trong tessdata riêng của app."""
    import os

    base = os.environ.get("APPDATA")
    if not base:
        pytest.skip("Không có %APPDATA%")
    path = Path(base) / "PDFBatchRenamer" / "tessdata"
    if not path.is_dir():
        pytest.skip("Chưa dựng thư mục tessdata riêng của app")
    names = {p.stem for p in path.glob("*.traineddata")}
    assert "vie" in names and "eng" in names

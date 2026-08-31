"""Test config, keyring, và khởi tạo môi trường (seed profile mẫu)."""

from __future__ import annotations

import json
from datetime import UTC

from src.core import config as config_module
from src.core.bootstrap import build_context, seed_defaults
from src.core.config import AppConfig, load_config, save_config
from src.core.rules import ProfileStore


class TestAppConfig:
    def test_mac_dinh_an_toan(self):
        cfg = AppConfig()
        assert cfg.ai.enabled is False  # AI phải tắt mặc định
        assert cfg.mode == "copy"  # copy an toàn hơn move
        assert cfg.backup_retention_days == 30
        assert cfg.max_name_length == 120
        assert cfg.subfolder_pattern == "{YYYY}-{MM}-{DD}"
        assert cfg.ocr.min_chars == 50 and cfg.ocr.max_pages == 3
        assert cfg.timeout_seconds == 120 and cfg.workers == 4

    def test_ghi_roi_doc_lai_giu_nguyen_gia_tri(self, tmp_path):
        cfg = AppConfig(output_root="D:/out", workers=8, strip_accents=True)
        cfg.ai.base_url = "http://localhost:11434/v1"
        path = save_config(cfg, tmp_path / "config.json")

        loaded = load_config(path)
        assert loaded.output_root == "D:/out"
        assert loaded.workers == 8
        assert loaded.strip_accents is True
        assert loaded.ai.base_url == "http://localhost:11434/v1"

    def test_api_key_khong_bao_gio_nam_trong_config(self, tmp_path):
        cfg = AppConfig()
        path = save_config(cfg, tmp_path / "config.json")
        assert "api_key" not in path.read_text(encoding="utf-8")

    def test_config_hong_khong_lam_chet_app(self, tmp_path):
        path = tmp_path / "config.json"
        path.write_text("{ khong phai json", encoding="utf-8")
        assert load_config(path).mode == "copy"

    def test_config_thieu_thi_dung_mac_dinh(self, tmp_path):
        assert load_config(tmp_path / "khong-co.json").workers == 4

    def test_khoa_la_trong_config_cu_bi_bo_qua(self, tmp_path):
        path = tmp_path / "config.json"
        path.write_text(
            json.dumps({"output_root": "D:/x", "khoa_da_bo": 1}), encoding="utf-8"
        )
        assert load_config(path).output_root == "D:/x"


class TestPaths:
    def test_moi_duong_dan_nam_trong_thu_muc_du_lieu(self, isolated_home):
        assert config_module.app_dir() == isolated_home
        assert config_module.db_path().parent == isolated_home
        assert config_module.profiles_dir().parent == isolated_home

    def test_tu_dien_mac_dinh_lay_ban_di_kem_khi_chua_seed(self, isolated_home):
        path = config_module.default_company_dictionary()
        assert path is not None and path.exists()


class TestKeyring:
    def test_loi_keyring_khong_lam_chet_app(self, monkeypatch):
        class Broken:
            def get_password(self, *a):
                raise RuntimeError("khong co backend")

            def set_password(self, *a):
                raise RuntimeError("khong co backend")

        monkeypatch.setattr(config_module, "_keyring", lambda: Broken())
        assert config_module.get_api_key() == ""
        assert config_module.set_api_key("x") is False


class TestSeed:
    def test_nap_profile_mau_lan_dau(self, tmp_path):
        store = ProfileStore(tmp_path / "profiles")
        assert seed_defaults(store) == 4
        names = {p.name for p in store.load_all()}
        assert names == {"Invoice", "Bill of Lading", "Packing List", "Chung"}

    def test_khong_de_rule_nguoi_dung_da_co(self, tmp_path):
        from src.core.models import Profile

        store = ProfileStore(tmp_path / "profiles")
        store.save(Profile(id="cua-toi", name="Của tôi"))
        assert seed_defaults(store) == 0
        assert [p.id for p in store.load_all()] == ["cua-toi"]

    def test_build_context_tao_du_thu_muc_va_profile(self, isolated_home):
        ctx = build_context()
        assert len(ctx.profiles) == 4
        assert (isolated_home / "profiles").exists()
        assert (isolated_home / "sessions").exists()
        assert (isolated_home / "logs").exists()
        assert (isolated_home / "dictionaries" / "companies.json").exists()
        ctx.close()


class TestTimeUtil:
    """Hiển thị luôn theo giờ máy, dù DB lưu UTC."""

    def test_ngay_hien_thi_theo_gio_may(self):
        from datetime import datetime

        from src.core.timeutil import local_date_str, to_local, utc_now_iso

        # 17:46 UTC ngày 30 = 00:46 ngày 31 ở GMT+7 -> phải hiện đúng ngày địa phương
        iso = "2026-08-30T17:46:00+00:00"
        expected = datetime(2026, 8, 30, 17, 46, tzinfo=UTC).astimezone().strftime("%Y-%m-%d")
        assert local_date_str(iso) == expected

        assert local_date_str("") == ""
        assert local_date_str("khong phai ngay") == ""
        assert to_local(utc_now_iso()) is not None

    def test_chuoi_khong_co_mui_gio_duoc_coi_la_utc(self):
        from src.core.timeutil import to_local

        assert to_local("2026-08-30T17:46:00").utcoffset() is not None

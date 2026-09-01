"""Kiểm thử tự động cho Engine Tự Động Cập Nhật (Auto-Update Engine) & UpdateDialog."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from PySide6.QtWidgets import QApplication

from src.core.version import parse_version, is_newer_version, __version__
from src.core.updater import (
    UpdateManifest,
    UpdateAsset,
    check_for_updates,
    verify_file_sha256,
)
from src.ui.update_dialog import UpdateDialog


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if not app:
        app = QApplication([])
    return app


def test_version_parsing_and_comparison():
    assert parse_version("1.0.0") == (1, 0, 0, 0)
    assert parse_version("v1.2.3") == (1, 2, 3, 0)
    assert parse_version("2.1") == (2, 1, 0, 0)
    assert parse_version("1.10.2-beta") == (1, 10, 2, 0)

    assert is_newer_version("1.0.1", "1.0.0") is True
    assert is_newer_version("1.1.0", "1.0.9") is True
    assert is_newer_version("2.0.0", "1.9.9") is True
    assert is_newer_version("1.0.0", "1.0.0") is False
    assert is_newer_version("0.9.9", "1.0.0") is False


def test_update_manifest_serialization():
    data = {
        "version": "1.2.0",
        "release_date": "2026-09-01",
        "title": "Bản cập nhật lớn",
        "changelog": ["Nâng cấp AI", "Sửa lỗi giao diện"],
        "installer": {
            "url": "https://example.com/setup.exe",
            "sha256": "abc123hash",
            "size_bytes": 1024,
        },
        "portable": {
            "url": "https://example.com/portable.zip",
            "sha256": "def456hash",
            "size_bytes": 2048,
        },
        "mandatory": True,
    }
    manifest = UpdateManifest.from_dict(data)
    assert manifest.version == "1.2.0"
    assert manifest.title == "Bản cập nhật lớn"
    assert len(manifest.changelog) == 2
    assert manifest.installer is not None
    assert manifest.installer.url == "https://example.com/setup.exe"
    assert manifest.mandatory is True

    exported = manifest.to_dict()
    assert exported["version"] == "1.2.0"
    assert exported["installer"]["sha256"] == "abc123hash"


def test_verify_file_sha256(tmp_path: Path):
    test_file = tmp_path / "test.txt"
    test_file.write_text("hello update", encoding="utf-8")
    import hashlib
    correct_hash = hashlib.sha256(b"hello update").hexdigest()

    assert verify_file_sha256(test_file, correct_hash) is True
    assert verify_file_sha256(test_file, "wronghash123") is False
    assert verify_file_sha256(test_file, "") is True


@patch("urllib.request.urlopen")
def test_check_for_updates_mock(mock_urlopen):
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_data = {
        "version": "9.9.9",
        "release_date": "2026-09-01",
        "changelog": ["Super update"],
    }
    mock_resp.read.return_value = json.dumps(mock_data).encode("utf-8")
    mock_urlopen.return_value.__enter__.return_value = mock_resp

    manifest = check_for_updates("https://fake-url/version.json")
    assert manifest is not None
    assert manifest.version == "9.9.9"
    assert manifest.changelog == ["Super update"]


def test_update_dialog_ui_render(qapp):
    manifest = UpdateManifest(
        version="1.1.0",
        release_date="2026-09-01",
        title="Bản cập nhật v1.1.0",
        changelog=["Tính năng A", "Giao diện mới B"],
        installer=UpdateAsset(url="https://example.com/setup.exe", sha256="abc", size_bytes=1000),
    )
    dlg = UpdateDialog(manifest)
    assert dlg.windowTitle() == "Đã có bản cập nhật mới"
    assert "v1.1.0" in dlg.browser.toPlainText() or "Tính năng A" in dlg.browser.toPlainText()
    assert dlg.btn_update.text() == "Cập nhật ngay"
    dlg.close()

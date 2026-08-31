"""Fixture dùng chung. Không test nào được đụng vào %APPDATA% thật hay mạng thật."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core import db as db_module  # noqa: E402
from src.core.config import AppConfig  # noqa: E402
from src.core.db import Database  # noqa: E402
from src.core.models import PageText, Profile, Word  # noqa: E402
from tools.make_fixtures import generate_all  # noqa: E402


@pytest.fixture(scope="session")
def pdfs(tmp_path_factory) -> dict[str, Path]:
    """Bộ file mẫu sinh 1 lần cho cả phiên test (PDF text/scan/barcode/password + Excel)."""
    return generate_all(tmp_path_factory.mktemp("fixtures"))


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """Ép mọi test dùng thư mục dữ liệu riêng, không chạm %APPDATA% của máy thật."""
    home = tmp_path / "apphome"
    home.mkdir()
    monkeypatch.setenv("PDFRENAMER_HOME", str(home))
    db_module.reset_default_db()
    yield home
    db_module.reset_default_db()


@pytest.fixture
def db(tmp_path) -> Database:
    database = Database(tmp_path / "test.db")
    yield database
    database.close()


@pytest.fixture
def output_root(tmp_path) -> Path:
    root = tmp_path / "output"
    root.mkdir()
    return root


@pytest.fixture
def config(output_root) -> AppConfig:
    cfg = AppConfig(output_root=str(output_root), workers=2, timeout_seconds=60)
    cfg.ocr.enabled = False  # mặc định tắt OCR trong test; test nào cần thì bật riêng
    return cfg


@pytest.fixture(scope="session")
def bundled_profiles() -> list[Profile]:
    """4 profile mẫu đi kèm app (Invoice, B/L, Packing List, Chung)."""
    return [
        Profile.from_dict(json.loads(p.read_text(encoding="utf-8")))
        for p in sorted((ROOT / "assets" / "profiles").glob("*.json"))
    ]


@pytest.fixture
def profiles(bundled_profiles) -> list[Profile]:
    """Bản sao để test sửa thoải mái không ảnh hưởng test khác."""
    return [Profile.from_dict(p.to_dict()) for p in bundled_profiles]


# ------------------------------------------------------------------ mock OCR


class FakeOcr:
    """OCR giả: trả về text định sẵn, không cần Tesseract."""

    def __init__(self, text: str = "", available: bool = True) -> None:
        self.text = text
        self.available = available
        self.calls = 0

    def image_to_page(self, image, page_index: int, scale: float = 1.0) -> PageText:
        self.calls += 1
        words = []
        y = 10.0
        for line in self.text.splitlines():
            x = 10.0
            for token in line.split():
                words.append(Word(text=token, x0=x, y0=y, x1=x + len(token) * 6, y1=y + 12))
                x += len(token) * 6 + 5
            y += 16
        return PageText(
            index=page_index, width=595.0, height=842.0, text=self.text,
            words=words, from_ocr=True,
        )

    def image_to_text(self, image) -> str:
        self.calls += 1
        return self.text


@pytest.fixture
def fake_ocr():
    return FakeOcr


# ------------------------------------------------------------------- Qt

# Test GUI chạy offscreen: không mở cửa sổ thật, không cần màn hình.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="session")
def qapp():
    """QApplication dùng chung cho cả phiên — Qt chỉ cho phép tạo đúng 1 cái."""
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])

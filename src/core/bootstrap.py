"""Khởi tạo môi trường chạy: thư mục dữ liệu, profile mẫu, từ điển, database.

Dùng chung cho cả GUI lẫn CLI để hai đường vào luôn thấy cùng một trạng thái.
"""

from __future__ import annotations

import json
import logging
import shutil
import sys
from pathlib import Path

from .config import (
    AppConfig,
    app_dir,
    assets_dir,
    dictionaries_dir,
    ensure_dirs,
    load_config,
    logs_dir,
    profiles_dir,
    versions_dir,
)
from .db import Database, get_db
from .rules import ProfileStore

logger = logging.getLogger(__name__)


def seed_defaults(store: ProfileStore) -> int:
    """Chép profile mẫu + từ điển vào thư mục người dùng nếu họ chưa có gì.

    Chỉ chạy khi thư mục profile đang rỗng — không bao giờ đè rule người dùng đã sửa.
    """
    if store.load_all():
        return 0

    source = assets_dir() / "profiles"
    if not source.exists():
        logger.warning("Không tìm thấy profile mẫu ở %s", source)
        return 0

    count = 0
    for path in sorted(source.glob("*.json")):
        try:
            from .models import Profile

            profile = Profile.from_dict(json.loads(path.read_text(encoding="utf-8")))
            profile.version = 0
            store.save(profile, bump_version=True)
            count += 1
        except Exception as exc:
            logger.error("Không nạp được profile mẫu %s: %s", path.name, exc)

    dict_source = assets_dir() / "dictionaries" / "companies.json"
    dict_target = dictionaries_dir() / "companies.json"
    if dict_source.exists() and not dict_target.exists():
        dict_target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(dict_source, dict_target)

    return count


def force_utf8_streams() -> None:
    """Console Windows mặc định không phải UTF-8 — không ép thì log tiếng Việt ra rác."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


# Thư viện đọc PDF cảnh báo rất nhiều thứ vô hại ("Could not get FontBBox...") — mỗi file
# có thể ra hàng chục dòng. Người dùng cuối không làm gì được với chúng, nên hạ xuống ERROR.
NOISY_LOGGERS = (
    "pdfminer",
    "pdfminer.pdffont",
    "pdfminer.pdfinterp",
    "pdfminer.pdfpage",
    "pdfminer.converter",
    "pdfplumber",
    "PIL",
    "fontTools",
)


class RepeatFilter(logging.Filter):
    """Gom các dòng log giống hệt nhau: cho qua lần đầu, lần thứ hai báo gom, sau đó im.

    Chặn kiểu spam "1 file đẻ ra 30 dòng cảnh báo giống nhau" trong panel log.
    """

    def __init__(self, max_repeats: int = 1) -> None:
        super().__init__()
        self.max_repeats = max_repeats
        self._seen: dict[str, int] = {}

    def reset(self) -> None:
        self._seen.clear()

    def filter(self, record: logging.LogRecord) -> bool:
        if record.levelno >= logging.ERROR:
            return True  # lỗi thật thì không gom, mất dấu vết là hỏng
        try:
            key = f"{record.name}|{record.getMessage()}"
        except Exception:
            return True
        count = self._seen.get(key, 0) + 1
        self._seen[key] = count
        if count <= self.max_repeats:
            return True
        if count == self.max_repeats + 1:
            record.msg = f"{record.getMessage()}  — các dòng giống hệt sau đó đã được gom lại"
            record.args = ()
            return True
        return False


def quiet_noisy_libraries() -> None:
    for name in NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.ERROR)


def setup_logging(verbose: bool = False) -> None:
    """Log ra console + file xoay vòng trong %APPDATA%/PDFBatchRenamer/logs."""
    from logging.handlers import RotatingFileHandler

    force_utf8_streams()
    quiet_noisy_libraries()
    ensure_dirs()
    root = logging.getLogger()
    if root.handlers:
        return
    root.setLevel(logging.DEBUG if verbose else logging.INFO)

    console = logging.StreamHandler()
    console.setLevel(logging.DEBUG if verbose else logging.INFO)
    console.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    root.addHandler(console)

    try:
        handler = RotatingFileHandler(
            logs_dir() / "app.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8"
        )
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
        )
        root.addHandler(handler)
    except OSError as exc:  # pragma: no cover - ổ đĩa chỉ đọc
        logger.warning("Không ghi được log file: %s", exc)


class AppContext:
    """Gói config + profile store + database lại một chỗ."""

    def __init__(self, config: AppConfig, store: ProfileStore, db: Database) -> None:
        self.config = config
        self.store = store
        self.db = db

    @property
    def profiles(self):
        return self.store.load_all()

    def close(self) -> None:
        self.db.close()


def build_context(config_path: Path | None = None, seed: bool = True) -> AppContext:
    """Dựng ngữ cảnh app: tạo thư mục, load config, nạp profile mẫu lần đầu, mở DB."""
    ensure_dirs()
    config = load_config(config_path)
    store = ProfileStore(profiles_dir(), versions_dir())
    if seed:
        added = seed_defaults(store)
        if added:
            logger.info("Đã nạp %s profile mẫu vào %s", added, profiles_dir())
    return AppContext(config, store, get_db())


def data_dir_hint() -> str:
    return str(app_dir())

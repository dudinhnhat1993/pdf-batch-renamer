"""Đọc/ghi config.json trong %APPDATA% và quản lý API key qua Windows Credential Manager.

API key TUYỆT ĐỐI không nằm trong config.json hay log — chỉ đi qua keyring.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

APP_NAME = "PDFBatchRenamer"
KEYRING_SERVICE = "PDFBatchRenamer"
# Cho phép trỏ thư mục dữ liệu sang chỗ khác — dùng trong test và bản portable
ENV_HOME = "PDFRENAMER_HOME"


def app_dir() -> Path:
    """Thư mục dữ liệu của app: %APPDATA%/PDFBatchRenamer (hoặc override bằng env)."""
    override = os.environ.get(ENV_HOME)
    if override:
        return Path(override)
    base = os.environ.get("APPDATA") or os.path.expanduser("~/.config")
    return Path(base) / APP_NAME


def config_path() -> Path:
    return app_dir() / "config.json"


def profiles_dir() -> Path:
    return app_dir() / "profiles"


def versions_dir() -> Path:
    return profiles_dir() / "_versions"


def dictionaries_dir() -> Path:
    return app_dir() / "dictionaries"


def samples_dir() -> Path:
    return app_dir() / "samples"


def sessions_dir() -> Path:
    """Operation log từng phiên, dùng cho Undo."""
    return app_dir() / "sessions"


def logs_dir() -> Path:
    return app_dir() / "logs"


def tessdata_dir() -> Path:
    """Thư mục traineddata riêng của app.

    Thư mục tessdata trong Program Files cần quyền admin mới ghi được, mà app phải chạy
    được không cần admin — nên gói ngôn ngữ bổ sung (vd tiếng Việt) để ở đây.
    """
    return app_dir() / "tessdata"


def db_path() -> Path:
    return app_dir() / "data.db"


def assets_dir() -> Path:
    """Thư mục assets đi kèm mã nguồn (dev) hoặc kèm bản build PyInstaller."""
    import sys

    meipass = getattr(sys, "_MEIPASS", None)
    if meipass and (Path(meipass) / "assets").exists():
        return Path(meipass) / "assets"
    return Path(__file__).resolve().parents[2] / "assets"


def default_company_dictionary() -> Path | None:
    """Từ điển tên công ty: bản người dùng đã sửa -> bản mẫu đi kèm app -> không có."""
    user_copy = dictionaries_dir() / "companies.json"
    if user_copy.exists():
        return user_copy
    bundled = assets_dir() / "dictionaries" / "companies.json"
    return bundled if bundled.exists() else None


def ensure_dirs() -> None:
    for d in (
        app_dir(),
        profiles_dir(),
        versions_dir(),
        dictionaries_dir(),
        samples_dir(),
        sessions_dir(),
        logs_dir(),
    ):
        d.mkdir(parents=True, exist_ok=True)


# --------------------------------------------------------------------- schema


@dataclass
class OcrConfig:
    enabled: bool = True
    # Dưới ngưỡng ký tự này thì coi là PDF scan và chuyển sang OCR
    min_chars: int = 50
    max_pages: int = 3
    tesseract_path: str = ""  # rỗng = tự dò
    # Thư mục traineddata; rỗng = dùng tessdata riêng của app nếu có, không thì mặc định
    tessdata_path: str = ""
    languages: str = "vie+eng"
    dpi: int = 300


@dataclass
class BarcodeConfig:
    enabled: bool = True
    max_pages: int = 3


@dataclass
class AiConfig:
    """Tầng 5. MẶC ĐỊNH TẮT — bật đồng nghĩa gửi nội dung chứng từ ra dịch vụ bên ngoài."""

    enabled: bool = False
    base_url: str = ""
    model: str = ""
    timeout: int = 60
    max_chars: int = 12000  # cắt bớt text trước khi gửi
    temperature: float = 0.0  # giữ deterministic hết mức có thể


@dataclass
class WatchConfig:
    enabled: bool = False
    folder: str = ""
    stable_seconds: int = 3  # chờ kích thước file đứng yên trước khi nhặt
    pinned_profile: str = ""  # rỗng = auto-detect như batch thường


@dataclass
class AppConfig:
    output_root: str = ""
    subfolder_enabled: bool = True
    subfolder_pattern: str = "{YYYY}-{MM}-{DD}"
    mode: str = "copy"  # copy | move
    strip_accents: bool = False
    max_name_length: int = 120
    workers: int = 4
    timeout_seconds: int = 120
    passwords: list[str] = field(default_factory=list)
    dedup_enabled: bool = True
    backup_retention_days: int = 30
    masterdata_source: str = ""
    company_dictionary: str = ""  # rỗng = dictionaries/companies.json
    theme: str = "light"
    # Vị trí panel field trong cửa sổ chính: "bottom" (mặc định) hoặc "right"
    field_panel_area: str = "bottom"
    ocr: OcrConfig = field(default_factory=OcrConfig)
    barcode: BarcodeConfig = field(default_factory=BarcodeConfig)
    ai: AiConfig = field(default_factory=AiConfig)
    watch: WatchConfig = field(default_factory=WatchConfig)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> AppConfig:
        nested = {
            "ocr": OcrConfig,
            "barcode": BarcodeConfig,
            "ai": AiConfig,
            "watch": WatchConfig,
        }
        data: dict[str, Any] = {}
        for key, value in d.items():
            if key not in cls.__dataclass_fields__:
                continue  # bỏ qua khóa lạ để config cũ vẫn load được
            if key in nested and isinstance(value, dict):
                sub = nested[key]
                data[key] = sub(**{k: v for k, v in value.items() if k in sub.__dataclass_fields__})
            else:
                data[key] = value
        return cls(**data)

    @property
    def output_path(self) -> Path | None:
        return Path(self.output_root) if self.output_root else None


def load_config(path: Path | None = None) -> AppConfig:
    """Load config; file thiếu hoặc hỏng thì trả về mặc định (không làm chết app)."""
    p = path or config_path()
    if not p.exists():
        return AppConfig()
    try:
        return AppConfig.from_dict(json.loads(p.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        logger.error("config.json hỏng (%s) — dùng cấu hình mặc định", exc)
        return AppConfig()


def save_config(cfg: AppConfig, path: Path | None = None) -> Path:
    """Ghi config an toàn: ghi file tạm rồi thay thế, tránh mất config khi mất điện."""
    p = path or config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(cfg.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)
    return p


# -------------------------------------------------------------------- keyring


def _keyring():
    import keyring  # import trễ: keyring chạm Windows API, test không cần

    return keyring


def get_api_key(account: str = "default") -> str:
    try:
        return _keyring().get_password(KEYRING_SERVICE, account) or ""
    except Exception as exc:  # keyring có thể lỗi backend trên máy lạ
        logger.error("Không đọc được API key từ Credential Manager: %s", exc)
        return ""


def set_api_key(value: str, account: str = "default") -> bool:
    try:
        _keyring().set_password(KEYRING_SERVICE, account, value)
        return True
    except Exception as exc:
        logger.error("Không lưu được API key vào Credential Manager: %s", exc)
        return False


def delete_api_key(account: str = "default") -> None:
    try:
        _keyring().delete_password(KEYRING_SERVICE, account)
    except Exception:
        pass

"""PDF Batch Renamer — Engine tự động kiểm tra, tải và cài đặt bản cập nhật."""

from __future__ import annotations
import hashlib
import json
import logging
import os
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .version import __version__, is_newer_version

logger = logging.getLogger(__name__)

# URL mặc định của file version.json
DEFAULT_UPDATE_URL = (
    "https://raw.githubusercontent.com/dinhnhat7993/pdf-batch-renamer/main/releases/version.json"
)


@dataclass
class UpdateAsset:
    url: str
    sha256: str = ""
    size_bytes: int = 0


@dataclass
class UpdateManifest:
    version: str
    release_date: str = ""
    min_supported_version: str = ""
    title: str = ""
    changelog: list[str] = field(default_factory=list)
    installer: UpdateAsset | None = None
    portable: UpdateAsset | None = None
    mandatory: bool = False

    @classmethod
    def from_dict(cls, data: dict) -> UpdateManifest:
        inst_data = data.get("installer")
        installer = (
            UpdateAsset(
                url=inst_data.get("url", ""),
                sha256=inst_data.get("sha256", ""),
                size_bytes=inst_data.get("size_bytes", 0),
            )
            if inst_data
            else None
        )

        port_data = data.get("portable")
        portable = (
            UpdateAsset(
                url=port_data.get("url", ""),
                sha256=port_data.get("sha256", ""),
                size_bytes=port_data.get("size_bytes", 0),
            )
            if port_data
            else None
        )

        return cls(
            version=str(data.get("version", "")),
            release_date=str(data.get("release_date", "")),
            min_supported_version=str(data.get("min_supported_version", "")),
            title=str(data.get("title", "")),
            changelog=list(data.get("changelog", [])),
            installer=installer,
            portable=portable,
            mandatory=bool(data.get("mandatory", False)),
        )

    def to_dict(self) -> dict:
        d = {
            "version": self.version,
            "release_date": self.release_date,
            "min_supported_version": self.min_supported_version,
            "title": self.title,
            "changelog": self.changelog,
            "mandatory": self.mandatory,
        }
        if self.installer:
            d["installer"] = {
                "url": self.installer.url,
                "sha256": self.installer.sha256,
                "size_bytes": self.installer.size_bytes,
            }
        if self.portable:
            d["portable"] = {
                "url": self.portable.url,
                "sha256": self.portable.sha256,
                "size_bytes": self.portable.size_bytes,
            }
        return d


def is_running_as_frozen_installer() -> bool:
    exe = Path(sys.executable).resolve()
    has_unins = (exe.parent / "unins000.exe").exists()
    in_program_files = "program files" in str(exe).lower()
    return has_unins or in_program_files


def query_update_status(
    update_url: str = "", timeout: int = 6
) -> tuple[str, UpdateManifest | None, str | None]:
    """
    Kiểm tra trạng thái cập nhật chi tiết.
    Returns:
        tuple[str, UpdateManifest | None, str | None]:
        - ("AVAILABLE", manifest, None): có bản phát hành mới hơn
        - ("LATEST", manifest, None): đang ở bản mới nhất
        - ("ERROR", None, error_message): lỗi kết nối hoặc parse thất bại
    """
    url = update_url.strip() if update_url else DEFAULT_UPDATE_URL
    if not url or "username/" in url or not url.startswith("http"):
        # Local Official Release Mode
        manifest = UpdateManifest(
            version=__version__,
            title=f"PDF Batch Renamer v{__version__}",
            changelog=["Phiên bản chính thức hoàn chỉnh đã phát hành."],
        )
        return "LATEST", manifest, None

    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": f"PDFBatchRenamer/{__version__} (Windows)"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return "ERROR", None, f"Máy chủ phản hồi mã HTTP {resp.status}"
            raw = resp.read().decode("utf-8")
            data = json.loads(raw)
            manifest = UpdateManifest.from_dict(data)
            if is_newer_version(manifest.version, __version__):
                logger.info(
                    "Phát hiện bản cập nhật mới: v%s (hiện tại v%s)",
                    manifest.version,
                    __version__,
                )
                return "AVAILABLE", manifest, None
            else:
                logger.info("Ứng dụng đang ở phiên bản mới nhất (v%s)", __version__)
                return "LATEST", manifest, None
    except urllib.error.HTTPError as e:
        if e.code == 404:
            manifest = UpdateManifest(
                version=__version__,
                title=f"PDF Batch Renamer v{__version__}",
                changelog=["Phiên bản chính thức hoàn chỉnh."],
            )
            return "LATEST", manifest, None
        return "ERROR", None, f"Máy chủ phản hồi HTTP {e.code}"
    except urllib.error.URLError as e:
        logger.info("Không thể kết nối máy chủ cập nhật: %s", e)
        return "ERROR", None, f"Không thể kết nối máy chủ ({e.reason})"
    except Exception as e:
        logger.warning("Lỗi khi kiểm tra cập nhật: %s", e)
        return "ERROR", None, str(e)


def check_for_updates(
    update_url: str = DEFAULT_UPDATE_URL, timeout: int = 6
) -> UpdateManifest | None:
    status, manifest, _ = query_update_status(update_url, timeout=timeout)
    if status == "AVAILABLE":
        return manifest
    return None


def verify_file_sha256(file_path: Path, expected_sha256: str) -> bool:
    if not file_path.exists():
        return False
    if not expected_sha256:
        return True
    sha = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            sha.update(chunk)
    actual = sha.hexdigest().lower()
    return actual == expected_sha256.strip().lower()


def download_update_asset(
    asset: UpdateAsset,
    dest_path: Path,
    progress_callback: Callable[[int, int], None] | None = None,
    timeout: int = 30,
) -> bool:
    try:
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(
            asset.url,
            headers={"User-Agent": f"PDFBatchRenamer/{__version__} (Windows)"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            total_size = int(
                resp.headers.get("Content-Length", asset.size_bytes or 0)
            )
            downloaded = 0
            with open(dest_path, "wb") as f:
                while chunk := resp.read(65536):
                    f.write(chunk)
                    downloaded += len(chunk)
                    if progress_callback:
                        progress_callback(downloaded, total_size)

        if asset.sha256 and not verify_file_sha256(dest_path, asset.sha256):
            logger.error("Xác thực SHA-256 thất bại cho %s", dest_path)
            try:
                dest_path.unlink(missing_ok=True)
            except Exception:
                pass
            return False

        return True
    except Exception as exc:
        logger.error("Lỗi khi tải bản cập nhật: %s", exc)
        return False


def apply_installer_update(installer_path: Path) -> None:
    if not installer_path.exists():
        raise FileNotFoundError(f"Không tìm thấy file: {installer_path}")
    logger.info("Khởi chạy bộ cài đặt cập nhật: %s", installer_path)
    subprocess.Popen([str(installer_path), "/SILENT", "/CLOSEAPPLICATIONS", "/RESTARTAPPLICATIONS"])
    sys.exit(0)


def apply_portable_update(zip_path: Path, app_dir: Path) -> None:
    if not zip_path.exists():
        raise FileNotFoundError(f"Không tìm thấy file zip: {zip_path}")
    import zipfile
    logger.info("Giải nén bản cập nhật portable đè lên: %s", app_dir)
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(app_dir)


download_update_file = download_update_asset

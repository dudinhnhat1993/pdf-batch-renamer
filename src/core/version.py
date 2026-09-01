"""PDF Batch Renamer — Phiên bản và so sánh phiên bản (Semantic Versioning)."""

from __future__ import annotations
import re

__version__ = "1.0.3"
APP_NAME = "PDF Batch Renamer"


def parse_version(v: str) -> tuple[int, ...]:
    """Chuyển chuỗi version (vd '1.0.0', 'v1.2.3-beta', '2.0') thành tuple số nguyên để so sánh."""
    clean = re.sub(r"^[^\d]*", "", str(v).strip())
    match = re.match(r"^(\d+)(?:\.(\d+))?(?:\.(\d+))?(?:\.(\d+))?", clean)
    if not match:
        return (0, 0, 0, 0)
    parts = match.groups()
    return tuple(int(p) if p is not None else 0 for p in parts)


def is_newer_version(remote_version: str, current_version: str = __version__) -> bool:
    """Trả về True nếu remote_version lớn hơn current_version."""
    remote_tuple = parse_version(remote_version)
    current_tuple = parse_version(current_version)
    return remote_tuple > current_tuple

"""Tầng 4 — đọc metadata tài liệu (Title/Author/Subject...) và AcroForm bằng pypdf."""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def read_metadata(path: Path | str, password: str = "") -> dict[str, str]:
    """Trả dict phẳng gồm metadata + form field. Khóa metadata đã bỏ dấu '/' đầu.

    Lỗi đọc không được ném ra ngoài: tầng 4 chỉ là nguồn bổ sung, thiếu thì bỏ qua.
    """
    values: dict[str, str] = {}
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        if reader.is_encrypted:
            reader.decrypt(password or "")

        meta = reader.metadata or {}
        for key, value in meta.items():
            name = str(key).lstrip("/")
            text = str(value).strip() if value is not None else ""
            if text:
                values[name] = text

        try:
            fields = reader.get_fields() or {}
        except Exception:
            fields = {}
        for name, obj in fields.items():
            raw = obj.get("/V") if hasattr(obj, "get") else None
            text = str(raw).strip() if raw is not None else ""
            if text:
                values[str(name)] = text

    except Exception as exc:
        logger.warning("Không đọc được metadata của %s: %s", path, exc)

    return values


def lookup(values: dict[str, str], key: str) -> str:
    """Tra khóa metadata, chấp nhận lệch hoa/thường và dấu '/' đầu như trong file gốc."""
    if not key:
        return ""
    if key in values:
        return values[key]
    target = key.lstrip("/").lower()
    for name, value in values.items():
        if name.lstrip("/").lower() == target:
            return value
    return ""

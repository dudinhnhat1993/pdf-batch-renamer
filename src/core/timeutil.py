"""Thời gian dùng chung.

Trong DB luôn lưu UTC (so sánh và sắp xếp không bao giờ nhập nhằng), nhưng mọi thứ
HIỂN THỊ cho người dùng đều quy về giờ máy — người dùng ở VN không nên thấy ngày lùi
1 hôm chỉ vì lệch múi giờ.
"""

from __future__ import annotations

from datetime import UTC, datetime


def utc_now_iso() -> str:
    """Mốc thời gian chuẩn để ghi vào SQLite và operation log."""
    return datetime.now(UTC).isoformat(timespec="seconds")


def to_local(iso_text: str) -> datetime | None:
    """Đổi chuỗi ISO (thường là UTC) sang datetime theo giờ máy."""
    if not iso_text:
        return None
    try:
        parsed = datetime.fromisoformat(iso_text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone()


def local_date_str(iso_text: str) -> str:
    """Ngày theo giờ máy, dạng yyyy-MM-dd, để hiện trong Preview và thông báo."""
    local = to_local(iso_text)
    return local.strftime("%Y-%m-%d") if local else ""


def local_datetime_str(iso_text: str) -> str:
    local = to_local(iso_text)
    return local.strftime("%Y-%m-%d %H:%M:%S") if local else ""

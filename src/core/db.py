"""Lớp truy cập SQLite: registry chống trùng, provenance, correction, dataset, thống kê.

Dùng 1 connection dùng chung + lock vì pipeline chạy đa luồng.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- Chống trùng cứng: 1 dòng cho mỗi nội dung file đã xử lý
CREATE TABLE IF NOT EXISTS processed_files (
    file_hash   TEXT PRIMARY KEY,
    first_seen  TEXT NOT NULL,
    last_seen   TEXT NOT NULL,
    source_name TEXT NOT NULL DEFAULT '',
    dest_path   TEXT NOT NULL DEFAULT '',
    profile_id  TEXT NOT NULL DEFAULT '',
    doc_number  TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_processed_number
    ON processed_files (profile_id, doc_number);

-- Provenance: mỗi field trích được ghi 1 dòng, nền dữ liệu cho Learning Loop
CREATE TABLE IF NOT EXISTS provenance (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ts           TEXT NOT NULL,
    session_id   TEXT NOT NULL DEFAULT '',
    file_hash    TEXT NOT NULL DEFAULT '',
    file_name    TEXT NOT NULL DEFAULT '',
    profile_id   TEXT NOT NULL DEFAULT '',
    rule_version INTEGER NOT NULL DEFAULT 0,
    field_name   TEXT NOT NULL,
    value        TEXT NOT NULL DEFAULT '',
    raw_value    TEXT NOT NULL DEFAULT '',
    layer        INTEGER NOT NULL DEFAULT -1,
    rule_id      TEXT NOT NULL DEFAULT '',
    page         INTEGER NOT NULL DEFAULT -1,
    bbox         TEXT NOT NULL DEFAULT '',
    edited       INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_prov_profile ON provenance (profile_id, ts);

-- Người dùng sửa tay trong Preview -> tín hiệu để đề xuất rule mới (phải duyệt)
CREATE TABLE IF NOT EXISTS corrections (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ts           TEXT NOT NULL,
    file_hash    TEXT NOT NULL DEFAULT '',
    file_name    TEXT NOT NULL DEFAULT '',
    profile_id   TEXT NOT NULL DEFAULT '',
    rule_version INTEGER NOT NULL DEFAULT 0,
    field_name   TEXT NOT NULL,
    old_value    TEXT NOT NULL DEFAULT '',
    new_value    TEXT NOT NULL DEFAULT '',
    context      TEXT NOT NULL DEFAULT '',
    status       TEXT NOT NULL DEFAULT 'new'
);
CREATE INDEX IF NOT EXISTS idx_corr_profile ON corrections (profile_id, status);

-- Dataset nội bộ: (text trích, field chuẩn sau chỉnh sửa) để export JSONL
CREATE TABLE IF NOT EXISTS dataset (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ts           TEXT NOT NULL,
    file_hash    TEXT NOT NULL DEFAULT '',
    profile_id   TEXT NOT NULL DEFAULT '',
    rule_version INTEGER NOT NULL DEFAULT 0,
    text         TEXT NOT NULL DEFAULT '',
    fields_json  TEXT NOT NULL DEFAULT '{}',
    corrected    INTEGER NOT NULL DEFAULT 0
);

-- {counter} đếm theo từng profile theo từng ngày
CREATE TABLE IF NOT EXISTS counters (
    profile_id TEXT NOT NULL,
    day        TEXT NOT NULL,
    value      INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (profile_id, day)
);

-- Thống kê tỉ lệ match theo profile (dashboard 30 ngày)
CREATE TABLE IF NOT EXISTS match_events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ts         TEXT NOT NULL,
    profile_id TEXT NOT NULL DEFAULT '',
    status     TEXT NOT NULL DEFAULT '',
    file_name  TEXT NOT NULL DEFAULT '',
    missing    TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_match_ts ON match_events (ts);
"""


class Database:
    """Bọc sqlite3 cho an toàn đa luồng. Mọi truy vấn đi qua lock."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._migrate()

    def _migrate(self) -> None:
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.execute(
                "INSERT INTO meta (key, value) VALUES ('schema_version', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(SCHEMA_VERSION),),
            )
            self._conn.commit()

    # ------------------------------------------------------------- primitive

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self._conn.execute(sql, params)
            self._conn.commit()
            return cur

    def query(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    def query_one(self, sql: str, params: tuple = ()) -> sqlite3.Row | None:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def __enter__(self) -> Database:
        return self

    def __exit__(self, *exc) -> None:
        self.close()


_default: Database | None = None
_default_lock = threading.Lock()


def get_db(path: Path | str | None = None) -> Database:
    """Database mặc định của app (singleton). Test truyền path riêng để cô lập."""
    global _default
    if path is not None:
        return Database(path)
    with _default_lock:
        if _default is None:
            from .config import db_path

            _default = Database(db_path())
        return _default


def reset_default_db() -> None:
    """Đóng singleton — dùng trong test và khi đổi thư mục dữ liệu."""
    global _default
    with _default_lock:
        if _default is not None:
            _default.close()
        _default = None

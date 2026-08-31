"""Chống trùng: hash SHA-256 nội dung file + registry SQLite.

- Trùng cứng: cùng nội dung file (cùng hash) đã xử lý trước đó.
- Trùng mềm: cùng profile + cùng số chứng từ nhưng nội dung file khác -> chỉ cảnh báo.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Any

from .db import Database
from .timeutil import utc_now_iso

logger = logging.getLogger(__name__)

CHUNK_SIZE = 1024 * 1024


def sha256_file(path: Path | str) -> str:
    """Hash nội dung file. Đọc theo chunk để không nạp cả file PDF lớn vào RAM."""
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        while chunk := fh.read(CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


class DedupRegistry:
    """Sổ đăng ký file đã xử lý."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def lookup(self, file_hash: str) -> dict[str, Any] | None:
        """File này đã xử lý lần nào chưa. Trả thông tin lần xử lý gần nhất."""
        row = self.db.query_one(
            "SELECT * FROM processed_files WHERE file_hash = ?", (file_hash,)
        )
        return dict(row) if row else None

    def record(
        self,
        file_hash: str,
        *,
        source_name: str = "",
        dest_path: str = "",
        profile_id: str = "",
        doc_number: str = "",
    ) -> None:
        """Ghi nhận đã xử lý. Chạy lại cùng file thì cập nhật last_seen và đích mới."""
        now = utc_now_iso()
        self.db.execute(
            """
            INSERT INTO processed_files
                (file_hash, first_seen, last_seen, source_name, dest_path, profile_id, doc_number)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(file_hash) DO UPDATE SET
                last_seen = excluded.last_seen,
                source_name = excluded.source_name,
                dest_path = excluded.dest_path,
                profile_id = excluded.profile_id,
                doc_number = excluded.doc_number
            """,
            (file_hash, now, now, source_name, dest_path, profile_id, doc_number),
        )

    def find_by_number(
        self, profile_id: str, doc_number: str, exclude_hash: str = ""
    ) -> list[dict[str, Any]]:
        """Trùng mềm: cùng profile + cùng số chứng từ nhưng file khác nội dung."""
        if not doc_number:
            return []
        rows = self.db.query(
            "SELECT * FROM processed_files WHERE profile_id = ? AND doc_number = ?",
            (profile_id, doc_number),
        )
        return [dict(r) for r in rows if r["file_hash"] != exclude_hash]

    def forget(self, file_hash: str) -> None:
        """Xoá khỏi registry để buộc xử lý lại như file mới."""
        self.db.execute("DELETE FROM processed_files WHERE file_hash = ?", (file_hash,))

    def count(self) -> int:
        row = self.db.query_one("SELECT COUNT(*) AS n FROM processed_files")
        return int(row["n"]) if row else 0

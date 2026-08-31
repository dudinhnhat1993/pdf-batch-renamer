"""Learning Loop: provenance, correction của người dùng, dataset nội bộ, counter, thống kê.

Nguyên tắc bất biến: app CHỈ ghi nhận và đề xuất. Không có đường nào ở đây tự sửa rule.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from .ai_client import FewShotExample
from .db import Database
from .models import ExtractedField, FileJob
from .timeutil import utc_now_iso

logger = logging.getLogger(__name__)


class LearningStore:
    """Toàn bộ ghi/đọc dữ liệu học nằm ở đây để dễ kiểm soát và test."""

    def __init__(self, db: Database) -> None:
        self.db = db

    # ------------------------------------------------------------ provenance

    def log_field(
        self,
        field: ExtractedField,
        *,
        session_id: str = "",
        file_hash: str = "",
        file_name: str = "",
        profile_id: str = "",
        rule_version: int = 0,
    ) -> None:
        """Ghi 1 field kèm đủ metadata: tầng nào, rule nào, trang nào, version rule nào."""
        self.db.execute(
            """
            INSERT INTO provenance
                (ts, session_id, file_hash, file_name, profile_id, rule_version,
                 field_name, value, raw_value, layer, rule_id, page, bbox, edited)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                utc_now_iso(),
                session_id,
                file_hash,
                file_name,
                profile_id,
                rule_version,
                field.name,
                field.value,
                field.raw_value,
                int(field.layer),
                field.rule_id,
                field.page,
                json.dumps(list(field.bbox)) if field.bbox else "",
                1 if field.edited_by_user else 0,
            ),
        )

    def log_job(self, job: FileJob, *, session_id: str = "", rule_version: int = 0) -> None:
        for f in job.fields.values():
            self.log_field(
                f,
                session_id=session_id,
                file_hash=job.file_hash,
                file_name=job.source.name,
                profile_id=job.profile_id,
                rule_version=rule_version,
            )

    def provenance_for(self, file_hash: str) -> list[dict[str, Any]]:
        return [dict(r) for r in self.db.query(
            "SELECT * FROM provenance WHERE file_hash = ? ORDER BY id", (file_hash,)
        )]

    # ----------------------------------------------------------- correction

    def record_correction(
        self,
        *,
        field_name: str,
        old_value: str,
        new_value: str,
        profile_id: str = "",
        file_hash: str = "",
        file_name: str = "",
        rule_version: int = 0,
        context: str = "",
    ) -> int:
        """Ghi lại 1 lần user sửa tay trong Preview. status='new' cho tới khi được duyệt."""
        cur = self.db.execute(
            """
            INSERT INTO corrections
                (ts, file_hash, file_name, profile_id, rule_version, field_name,
                 old_value, new_value, context, status)
            VALUES (?,?,?,?,?,?,?,?,?,'new')
            """,
            (
                utc_now_iso(),
                file_hash,
                file_name,
                profile_id,
                rule_version,
                field_name,
                old_value,
                new_value,
                context[:4000],
            ),
        )
        return int(cur.lastrowid or 0)

    def set_correction_status(self, correction_id: int, status: str) -> None:
        """status: new | approved | rejected."""
        self.db.execute(
            "UPDATE corrections SET status = ? WHERE id = ?", (status, correction_id)
        )

    def correction(self, correction_id: int) -> dict[str, Any] | None:
        row = self.db.query_one("SELECT * FROM corrections WHERE id = ?", (correction_id,))
        return dict(row) if row else None

    def approve_correction(
        self,
        correction_id: int,
        *,
        text: str = "",
        fields: dict[str, str] | None = None,
        profile_id: str = "",
        file_hash: str = "",
        rule_version: int = 0,
    ) -> None:
        """Duyệt 1 correction và ghi luôn vào dataset để tầng 5 học lại về sau.

        Chỉ dòng dataset có TEXT mới dùng được làm few-shot, nên duyệt correction là
        thời điểm duy nhất chắc chắn có cả text lẫn giá trị chuẩn do người dùng xác nhận.
        """
        self.set_correction_status(correction_id, "approved")
        if text and fields:
            self.save_dataset_row(
                text=text,
                fields=fields,
                profile_id=profile_id,
                file_hash=file_hash,
                rule_version=rule_version,
                corrected=True,
            )

    def corrections(self, profile_id: str = "", status: str = "") -> list[dict[str, Any]]:
        sql = "SELECT * FROM corrections WHERE 1=1"
        params: list[Any] = []
        if profile_id:
            sql += " AND profile_id = ?"
            params.append(profile_id)
        if status:
            sql += " AND status = ?"
            params.append(status)
        sql += " ORDER BY id DESC"
        return [dict(r) for r in self.db.query(sql, tuple(params))]

    # -------------------------------------------------------------- dataset

    def save_dataset_row(
        self,
        *,
        text: str,
        fields: dict[str, str],
        profile_id: str = "",
        file_hash: str = "",
        rule_version: int = 0,
        corrected: bool = False,
    ) -> None:
        """Lưu bộ (text, field chuẩn) để few-shot hoặc fine-tune sau này."""
        self.db.execute(
            """
            INSERT INTO dataset (ts, file_hash, profile_id, rule_version, text, fields_json, corrected)
            VALUES (?,?,?,?,?,?,?)
            """,
            (
                utc_now_iso(),
                file_hash,
                profile_id,
                rule_version,
                text[:20000],
                json.dumps(fields, ensure_ascii=False),
                1 if corrected else 0,
            ),
        )

    def export_jsonl(self, path: Path | str, profile_id: str = "") -> int:
        """Xuất dataset ra JSONL. Trả số dòng đã ghi."""
        sql = "SELECT * FROM dataset"
        params: tuple = ()
        if profile_id:
            sql += " WHERE profile_id = ?"
            params = (profile_id,)
        sql += " ORDER BY id"

        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        count = 0
        with p.open("w", encoding="utf-8") as fh:
            for row in self.db.query(sql, params):
                fh.write(
                    json.dumps(
                        {
                            "profile_id": row["profile_id"],
                            "rule_version": row["rule_version"],
                            "text": row["text"],
                            "fields": json.loads(row["fields_json"] or "{}"),
                            "corrected": bool(row["corrected"]),
                            "ts": row["ts"],
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
                count += 1
        return count

    def few_shot_examples(self, profile_id: str, limit: int = 5) -> list[FewShotExample]:
        """Ví dụ cho tầng 5: ưu tiên các bản ghi đã qua chỉnh sửa của người dùng."""
        rows = self.db.query(
            "SELECT text, fields_json FROM dataset WHERE profile_id = ? "
            "ORDER BY corrected DESC, id DESC LIMIT ?",
            (profile_id, limit),
        )
        out: list[FewShotExample] = []
        for row in rows:
            try:
                fields = json.loads(row["fields_json"] or "{}")
            except json.JSONDecodeError:
                continue
            if row["text"] and fields:
                out.append(FewShotExample(text=row["text"], fields=fields))
        return out

    # -------------------------------------------------------------- counter

    def next_counter(self, profile_id: str, day: date | None = None) -> int:
        """{counter} đếm theo từng profile theo từng ngày, tăng dần và bền qua các phiên."""
        key = (day or date.today()).isoformat()
        self.db.execute(
            "INSERT INTO counters (profile_id, day, value) VALUES (?,?,1) "
            "ON CONFLICT(profile_id, day) DO UPDATE SET value = value + 1",
            (profile_id, key),
        )
        row = self.db.query_one(
            "SELECT value FROM counters WHERE profile_id = ? AND day = ?", (profile_id, key)
        )
        return int(row["value"]) if row else 1

    def peek_counter(self, profile_id: str, day: date | None = None) -> int:
        """Xem giá trị counter kế tiếp mà KHÔNG tăng — dùng cho Preview."""
        key = (day or date.today()).isoformat()
        row = self.db.query_one(
            "SELECT value FROM counters WHERE profile_id = ? AND day = ?", (profile_id, key)
        )
        return (int(row["value"]) if row else 0) + 1

    # ------------------------------------------------------------ thống kê

    def record_match(
        self, profile_id: str, status: str, file_name: str = "", missing: list[str] | None = None
    ) -> None:
        self.db.execute(
            "INSERT INTO match_events (ts, profile_id, status, file_name, missing) VALUES (?,?,?,?,?)",
            (utc_now_iso(), profile_id, status, file_name, ",".join(missing or [])),
        )

    def profile_stats(self, days: int = 30) -> list[dict[str, Any]]:
        """Tỉ lệ thành công theo profile trong N ngày gần nhất -> biết rule nào cần chỉnh."""
        since = (datetime.now(UTC) - timedelta(days=days)).isoformat(timespec="seconds")
        rows = self.db.query(
            """
            SELECT profile_id,
                   COUNT(*) AS total,
                   SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) AS success,
                   SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) AS errors
            FROM match_events WHERE ts >= ? GROUP BY profile_id
            """,
            (since,),
        )
        stats = []
        for r in rows:
            total = int(r["total"]) or 1
            stats.append(
                {
                    "profile_id": r["profile_id"],
                    "total": int(r["total"]),
                    "success": int(r["success"] or 0),
                    "errors": int(r["errors"] or 0),
                    "success_rate": round(int(r["success"] or 0) * 100.0 / total, 1),
                }
            )
        return sorted(stats, key=lambda s: -s["total"])

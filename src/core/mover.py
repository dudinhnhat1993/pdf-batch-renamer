"""Ghi file ra output: copy/move, thư mục con theo ngày, cách ly file lỗi, backup + Undo.

Mọi thao tác ghi đều được ghi vào operation log JSON của phiên -> hoàn tác được.
Mode Move luôn backup bản gốc trước khi di chuyển; backup KHÔNG tự xoá (quyết định #6).
"""

from __future__ import annotations

import json
import logging
import shutil
import time
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Any

from .config import AppConfig, sessions_dir
from .errors import PdfRenamerError
from .models import FileJob
from .namer import render_subfolder, unique_name
from .timeutil import utc_now_iso

logger = logging.getLogger(__name__)

QUARANTINE_DIRNAME = "_Loi"
BACKUP_DIRNAME = "_backup"


class Mover:
    """Thực thi ghi file cho 1 phiên làm việc và giữ operation log của phiên đó."""

    def __init__(
        self,
        config: AppConfig,
        output_root: Path | str | None = None,
        session_id: str = "",
    ) -> None:
        root = output_root or config.output_root
        if not root:
            raise PdfRenamerError("Chưa cấu hình thư mục output trong Settings")
        self.config = config
        self.output_root = Path(root)
        self.session_id = session_id or datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
        self.operations: list[dict[str, Any]] = []
        # Giữ chỗ tên file trong phiên: 2 file cùng batch không được cùng đường dẫn đích
        self._reserved: dict[str, set[str]] = {}

    # ------------------------------------------------------------- thư mục

    def destination_dir(self, when: date | None = None) -> Path:
        """Thư mục đích theo NGÀY XỬ LÝ hiện tại (không phải ngày trên chứng từ)."""
        if not self.config.subfolder_enabled:
            return self.output_root
        return self.output_root / render_subfolder(self.config.subfolder_pattern, when)

    def quarantine_dir(self) -> Path:
        return self.output_root / QUARANTINE_DIRNAME

    def backup_dir(self) -> Path:
        return self.output_root / BACKUP_DIRNAME / self.session_id

    # -------------------------------------------------------- đặt chỗ tên

    def reserve(self, directory: Path, filename: str) -> str:
        """Chốt tên duy nhất trong thư mục đích và giữ chỗ cho tới hết phiên."""
        key = str(directory).casefold()
        taken = self._reserved.setdefault(key, set())
        final = unique_name(
            directory, filename, reserved=taken, max_length=self.config.max_name_length
        )
        taken.add(final.casefold())
        return final

    def release(self, directory: Path, filename: str) -> None:
        """Nhả chỗ khi user sửa tay tên file trong Preview."""
        key = str(directory).casefold()
        self._reserved.get(key, set()).discard(filename.casefold())

    # ---------------------------------------------------------------- ghi

    def apply(self, job: FileJob) -> Path:
        """Copy/move 1 file sang đích. Trả đường dẫn cuối cùng đã ghi."""
        if not job.dest_dir or not job.new_name:
            raise PdfRenamerError(f"Chưa xác định đích cho {job.source.name}")

        job.dest_dir.mkdir(parents=True, exist_ok=True)
        # Kiểm tra lại lúc ghi: file có thể vừa xuất hiện sau khi Preview đã dựng xong
        if (job.dest_dir / job.new_name).exists():
            job.new_name = self.reserve(job.dest_dir, job.new_name)
        dest = job.dest_dir / job.new_name

        backup: Path | None = None
        if self.config.mode == "move":
            backup = self._backup(job.source)

        try:
            if self.config.mode == "move":
                shutil.move(str(job.source), str(dest))
            else:
                shutil.copy2(str(job.source), str(dest))
        except OSError as exc:
            raise PdfRenamerError(f"Không ghi được file đích {dest.name}: {exc}") from exc

        self._log(self.config.mode, job.source, dest, backup)
        return dest

    def _backup(self, source: Path) -> Path:
        """Copy bản gốc vào _backup/<session_id>/ trước khi Move."""
        target_dir = self.backup_dir()
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / unique_name(target_dir, source.name)
        shutil.copy2(str(source), str(target))
        return target

    def quarantine(self, job: FileJob, reason: str, code: str = "") -> Path:
        """Đưa file lỗi vào output/_Loi/ kèm .txt ghi lý do. Không file nào bị bỏ sót."""
        target_dir = self.quarantine_dir()
        target_dir.mkdir(parents=True, exist_ok=True)
        name = self.reserve(target_dir, job.source.name)
        dest = target_dir / name

        backup: Path | None = None
        try:
            if self.config.mode == "move":
                backup = self._backup(job.source)
                shutil.move(str(job.source), str(dest))
            else:
                shutil.copy2(str(job.source), str(dest))
        except OSError as exc:
            logger.error("Không cách ly được %s: %s", job.source.name, exc)
            raise PdfRenamerError(f"Không cách ly được {job.source.name}: {exc}") from exc

        field_lines = [f"  - {k}: {v.value}" for k, v in sorted(job.fields.items())]
        note = dest.with_suffix(dest.suffix + ".txt")
        note.write_text(
            "\n".join(
                [
                    f"File gốc   : {job.source}",
                    f"Thời điểm  : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                    f"Mã lỗi     : {code or job.error_code or 'unknown'}",
                    f"Profile    : {job.profile_name or '(không match)'}",
                    f"Lý do      : {reason}",
                    "",
                    "Field đã trích được:",
                    *(field_lines or ["  (không có)"]),
                ]
            ),
            encoding="utf-8",
        )

        self._log("quarantine", job.source, dest, backup, extra={"note": str(note)})
        return dest

    # --------------------------------------------------------------- log

    def _log(
        self,
        action: str,
        source: Path,
        dest: Path,
        backup: Path | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        entry = {
            "action": action,
            "source": str(source),
            "dest": str(dest),
            "backup": str(backup) if backup else "",
            "ts": utc_now_iso(),
        }
        if extra:
            entry.update(extra)
        self.operations.append(entry)

    def save_log(self, directory: Path | None = None) -> Path | None:
        """Ghi operation log của phiên. Không có thao tác nào thì không tạo file rác."""
        if not self.operations:
            return None
        target_dir = directory or sessions_dir()
        target_dir.mkdir(parents=True, exist_ok=True)
        path = target_dir / f"{self.session_id}.json"
        payload = {
            "session_id": self.session_id,
            "created_at": utc_now_iso(),
            "output_root": str(self.output_root),
            "mode": self.config.mode,
            "operations": self.operations,
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    # -------------------------------------------------------------- backup

    def cleanup_backups(self, retention_days: int | None = None) -> int:
        """Xoá thư mục backup cũ hơn N ngày. Trả số thư mục đã xoá."""
        days = self.config.backup_retention_days if retention_days is None else retention_days
        root = self.output_root / BACKUP_DIRNAME
        if days <= 0 or not root.exists():
            return 0
        cutoff = time.time() - days * 86400
        removed = 0
        for child in root.iterdir():
            if not child.is_dir():
                continue
            try:
                if child.stat().st_mtime < cutoff:
                    shutil.rmtree(child)
                    removed += 1
            except OSError as exc:
                logger.warning("Không xoá được backup %s: %s", child, exc)
        return removed


# ------------------------------------------------------------------- undo


def list_sessions(directory: Path | None = None) -> list[Path]:
    """Danh sách operation log, mới nhất trước."""
    target_dir = directory or sessions_dir()
    if not target_dir.exists():
        return []
    return sorted(target_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)


def undo_session(log_path: Path | str) -> tuple[int, list[str]]:
    """Hoàn tác 1 phiên: đưa file về chỗ cũ, xoá file đã ghi ra output.

    Trả (số thao tác hoàn tác được, danh sách lỗi). Hoàn tác theo thứ tự ngược.
    """
    path = Path(log_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    errors: list[str] = []
    undone = 0

    for entry in reversed(data.get("operations", [])):
        action = entry.get("action", "")
        source = Path(entry.get("source", ""))
        dest = Path(entry.get("dest", ""))
        backup = Path(entry["backup"]) if entry.get("backup") else None
        note = Path(entry["note"]) if entry.get("note") else None

        try:
            if action in ("move", "quarantine") and not source.exists():
                # Trả file về chỗ cũ, ưu tiên chính file đích, không có thì lấy bản backup
                origin = dest if dest.exists() else (backup if backup and backup.exists() else None)
                if origin is None:
                    errors.append(f"Không tìm thấy file để khôi phục: {dest.name}")
                    continue
                source.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(origin), str(source))
            elif dest.exists():
                # Mode copy: bản gốc còn nguyên, chỉ cần xoá bản đã ghi ra output
                dest.unlink()

            if note and note.exists():
                note.unlink()
            undone += 1
        except OSError as exc:
            errors.append(f"{dest.name}: {exc}")

    if not errors:
        path.replace(path.with_suffix(".json.undone"))
    return undone, errors

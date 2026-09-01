"""Điều phối batch: quét file, chạy pipeline đa luồng, dựng Preview, rồi áp dụng.

Tách rõ 2 giai đoạn:
- plan(): KHÔNG ghi gì ra đĩa, chỉ tính tên mới -> đây là dữ liệu cho màn hình Preview.
- apply(): thực thi copy/move + cách ly file lỗi + ghi registry/provenance.

Lỗi của 1 file không bao giờ được làm chết cả batch.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Iterable
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from .ai_client import AiClient, AiSettings
from .config import AppConfig, default_company_dictionary, get_api_key
from .db import Database
from .dedup import DedupRegistry, sha256_file
from .errors import PdfRenamerError
from .extractor import Extractor
from .learning import LearningStore
from .masterdata import MasterDataStore
from .models import FileJob, JobStatus, Profile
from .mover import Mover
from .namer import finalize_filename, render_template, template_tokens
from .normalize import CompanyDictionary
from .ocr import OcrEngine
from .timeutil import local_date_str

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[FileJob, int, int], None]


def scan_pdfs(paths: Iterable[Path | str], recursive: bool = True) -> list[Path]:
    """Gom danh sách .pdf từ file lẻ và thư mục (quét đệ quy). Kết quả sắp xếp ổn định."""
    found: list[Path] = []
    seen: set[str] = set()
    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            pattern = "**/*" if recursive else "*"
            candidates = sorted(x for x in p.glob(pattern) if x.is_file())
        elif p.is_file():
            candidates = [p]
        else:
            logger.warning("Bỏ qua đường dẫn không tồn tại: %s", p)
            continue
        for c in candidates:
            if c.suffix.lower() != ".pdf":
                continue
            key = str(c.resolve()).casefold()
            if key not in seen:
                seen.add(key)
                found.append(c)
    return found


@dataclass
class _WorkSlot:
    """Trạng thái 1 file đang chạy trong pool, dùng để phát hiện timeout và bỏ rơi luồng."""

    index: int
    path: Path
    started: float | None = None
    abandoned: bool = False


@dataclass
class BatchSummary:
    total: int = 0
    success: int = 0
    duplicate: int = 0
    errors: int = 0
    session_id: str = ""
    log_path: Path | None = None
    warnings: list[str] = field(default_factory=list)
    jobs: list[FileJob] = field(default_factory=list)


class Pipeline:
    """Vòng đời 1 batch. Tạo mới cho mỗi lần chạy để session_id và counter không lẫn nhau."""

    def __init__(
        self,
        config: AppConfig,
        profiles: list[Profile],
        db: Database,
        *,
        extractor: Extractor | None = None,
        mover: Mover | None = None,
        dictionary: CompanyDictionary | None = None,
    ) -> None:
        self.config = config
        self.profiles = profiles
        self.db = db
        self.dedup = DedupRegistry(db)
        self.learning = LearningStore(db)
        self.cancel_event = threading.Event()
        # Số kết quả về muộn sau khi file đã bị đánh timeout và đã bị hủy bỏ
        self.late_results_discarded = 0
        self._counter_offsets: dict[str, int] = {}
        self._lock = threading.Lock()

        self.extractor = extractor or self._build_extractor(dictionary)
        if mover:
            self.mover = mover
        else:
            out_root = (
                config.output_root
                or str(Path.home() / "Documents" / "PDF_Renamed")
            )
            self.mover = Mover(config, output_root=out_root)

    # -------------------------------------------------------------- setup

    def _build_extractor(self, dictionary: CompanyDictionary | None) -> Extractor:
        ocr = OcrEngine(
            self.config.ocr.tesseract_path,
            self.config.ocr.languages,
            self.config.ocr.dpi,
            self.config.ocr.tessdata_path,
        )
        ai_client = None
        if self.config.ai.enabled:
            ai_client = AiClient(
                AiSettings(
                    base_url=self.config.ai.base_url,
                    model=self.config.ai.model,
                    api_key=get_api_key(),
                    timeout=self.config.ai.timeout,
                    max_chars=self.config.ai.max_chars,
                    temperature=self.config.ai.temperature,
                )
            )
        return Extractor(
            self.config,
            self.profiles,
            ocr=ocr,
            ai_client=ai_client,
            masterdata=MasterDataStore(self.config.masterdata_source),
            dictionary=dictionary
            or CompanyDictionary.load(
                self.config.company_dictionary or default_company_dictionary()
            ),
            examples_provider=self.learning.few_shot_examples,
        )

    def profile_by_id(self, profile_id: str) -> Profile | None:
        return next((p for p in self.profiles if p.id == profile_id), None)

    def cancel(self) -> None:
        """Hủy batch — các file chưa bắt đầu sẽ không chạy nữa."""
        self.cancel_event.set()

    # --------------------------------------------------------------- plan

    def _counter_for(self, profile_id: str, dry_run: bool) -> int:
        """Cấp số cho {counter}. Dry-run chỉ xem trước, không đốt số trong DB."""
        with self._lock:
            if dry_run:
                self._counter_offsets[profile_id] = self._counter_offsets.get(profile_id, 0) + 1
                return self.learning.peek_counter(profile_id) + self._counter_offsets[profile_id] - 1
            return self.learning.next_counter(profile_id)

    def plan_one(
        self, path: Path | str, *, dry_run: bool = False, ignore_dedup: bool = False,
        forced_profile: str = "", when: date | None = None,
        abandon_check: Callable[[], bool] | None = None,
    ) -> FileJob:
        """Tính tên mới cho 1 file mà KHÔNG ghi gì ra đĩa.

        abandon_check: hàm cho biết file này đã bị đánh timeout hay chưa. Nếu rồi thì
        dừng sớm, không cấp số {counter} và không đụng vào DB.
        """
        source = Path(path)
        job = FileJob(source=source)
        started = time.monotonic()
        try:
            job.size = source.stat().st_size
        except OSError:
            job.size = 0

        try:
            job.file_hash = sha256_file(source)
        except OSError as exc:
            job.status = JobStatus.ERROR
            job.error_code = "read-failed"
            job.message = f"Không đọc được file: {exc}"
            return job

        # Chống trùng cứng: cùng nội dung file đã xử lý trước đó
        if self.config.dedup_enabled and not ignore_dedup:
            previous = self.dedup.lookup(job.file_hash)
            if previous:
                job.status = JobStatus.DUPLICATE
                job.previous = previous
                job.message = (
                    f"Đã xử lý ngày {local_date_str(previous.get('last_seen', ''))} "
                    f"-> {Path(previous.get('dest_path', '')).name or '(không rõ)'}"
                )
                return job

        try:
            result = self.extractor.extract(source, forced_profile)
        except PdfRenamerError as exc:
            job.status = JobStatus.ERROR
            job.error_code = getattr(exc, "code", "unknown")
            job.message = str(exc)
            return job
        except Exception as exc:  # lỗi ngoài dự kiến vẫn phải cô lập theo từng file
            logger.exception("Lỗi không lường trước khi xử lý %s", source.name)
            job.status = JobStatus.ERROR
            job.error_code = "unexpected"
            job.message = f"Lỗi không lường trước: {type(exc).__name__}: {exc}"
            return job

        job.profile_id = result.profile_id
        job.profile_name = result.profile_name
        job.fields = result.fields
        job.layers_used = list(result.layers_used)
        job.warnings = list(result.warnings)

        profile = self.profile_by_id(result.profile_id)
        if profile is None:
            job.status = JobStatus.ERROR
            job.error_code = "no-profile"
            job.message = "Không profile nào nhận diện được chứng từ này"
            return job

        if result.missing_required:
            labels = [
                (profile.field_by_name(n).label if profile.field_by_name(n) else n)
                for n in result.missing_required
            ]
            job.status = JobStatus.ERROR
            job.error_code = "missing-required-field"
            job.message = "Thiếu field bắt buộc sau cả 5 tầng: " + ", ".join(labels)
            return job

        if abandon_check is not None and abandon_check():
            job.status = JobStatus.ERROR
            job.error_code = "timeout"
            job.message = "Đã bị đánh timeout, kết quả bị hủy"
            return job

        self.build_name(job, profile, dry_run=dry_run, when=when)
        self._check_soft_duplicate(job, profile)
        job.duration_ms = int((time.monotonic() - started) * 1000)
        return job

    def build_name(
        self, job: FileJob, profile: Profile, *, dry_run: bool = False, when: date | None = None
    ) -> FileJob:
        """Render template -> base_name -> tên file cuối + thư mục đích (đã chống trùng tên)."""
        values: dict[str, str] = job.field_values()
        values.setdefault("doctype", profile.doctype or profile.name)
        values.setdefault("original_name", job.source.stem)
        if "counter" in template_tokens(profile.template):
            values["counter"] = str(self._counter_for(profile.id, dry_run))

        date_fields = {
            spec.name for spec in profile.fields if spec.validate == "date"
        } | {"doc_date"}

        try:
            job.base_name = render_template(
                profile.template,
                values,
                date_formats=profile.date_formats,
                date_fields=date_fields,
            )
        except PdfRenamerError as exc:
            job.status = JobStatus.ERROR
            job.error_code = "template-invalid"
            job.message = str(exc)
            return job

        if not job.base_name:
            job.base_name = job.source.stem
            job.warnings.append("Template cho ra tên rỗng — tạm dùng tên gốc")

        filename = finalize_filename(
            job.base_name,
            job.source.suffix or ".pdf",
            max_length=self.config.max_name_length,
            remove_accents=self.config.strip_accents,
        )
        profile_root = profile.output_dir.strip() if (profile and profile.output_dir and profile.output_dir.strip()) else None
        job.dest_dir = self.mover.destination_dir(when, root=profile_root)
        job.new_name = self.mover.reserve(job.dest_dir, filename)
        return job

    def rename_manually(self, job: FileJob, new_stem: str) -> FileJob:
        """User sửa tay tên file trong Preview: nhả chỗ cũ, chốt tên mới."""
        if job.dest_dir and job.new_name:
            self.mover.release(job.dest_dir, job.new_name)
        job.base_name = new_stem
        filename = finalize_filename(
            new_stem,
            job.source.suffix or ".pdf",
            max_length=self.config.max_name_length,
            remove_accents=self.config.strip_accents,
        )
        job.new_name = self.mover.reserve(job.dest_dir or self.mover.destination_dir(), filename)
        return job

    def _check_soft_duplicate(self, job: FileJob, profile: Profile) -> None:
        """Trùng mềm: cùng profile + cùng số chứng từ -> cảnh báo nổi bật, không chặn."""
        number = job.fields.get("number")
        if not number or not number.value:
            return
        others = self.dedup.find_by_number(profile.id, number.value, job.file_hash)
        if others:
            names = ", ".join(Path(o.get("dest_path", "")).name for o in others[:3] if o.get("dest_path"))
            job.warnings.append(
                f"Trùng số chứng từ '{number.value}' với file đã xử lý trước đó"
                + (f": {names}" if names else "")
            )

    # ---------------------------------------------------------- chạy batch

    def plan(
        self,
        paths: Iterable[Path | str],
        *,
        dry_run: bool = False,
        forced_profile: str = "",
        progress: ProgressCallback | None = None,
        when: date | None = None,
    ) -> list[FileJob]:
        """Chạy plan_one cho nhiều file bằng ThreadPoolExecutor, giữ nguyên thứ tự đầu vào."""
        files = scan_pdfs(paths)
        total = len(files)
        jobs: list[FileJob | None] = [None] * total
        if not total:
            return []
        if total == 1:
            job = self.plan_one(
                files[0],
                dry_run=dry_run,
                forced_profile=forced_profile,
                when=when,
            )
            if progress:
                progress(job, 1, 1)
            return [job]

        index_of: dict[Future, int] = {}
        slots: dict[Future, _WorkSlot] = {}
        timeout = max(1, self.config.timeout_seconds)

        def work(slot: _WorkSlot) -> FileJob | None:
            slot.started = time.monotonic()
            job = self.plan_one(
                slot.path,
                dry_run=dry_run,
                forced_profile=forced_profile,
                when=when,
                abandon_check=lambda: slot.abandoned,
            )
            # Luồng đã bị đánh timeout vẫn chạy nốt (Python không kill được thread).
            # Kết quả muộn của nó phải bị HỦY: không dedup, không provenance, không ghi file.
            if slot.abandoned:
                self.late_results_discarded += 1
                logger.warning("late result discarded: %s", slot.path.name)
                return None
            return job

        done_count = 0
        with ThreadPoolExecutor(max_workers=max(1, self.config.workers)) as pool:
            pending: set[Future] = set()
            for i, path in enumerate(files):
                if self.cancel_event.is_set():
                    jobs[i] = FileJob(
                        source=path, status=JobStatus.ERROR, error_code="cancelled",
                        message="Đã hủy batch",
                    )
                    continue
                slot = _WorkSlot(index=i, path=path)
                fut = pool.submit(work, slot)
                slots[fut] = slot
                index_of[fut] = i
                pending.add(fut)

            while pending:
                finished, pending = wait(pending, timeout=1.0, return_when=FIRST_COMPLETED)
                for fut in finished:
                    i = index_of[fut]
                    try:
                        result = fut.result()
                    except Exception as exc:  # bọc lần cuối, không để batch chết
                        logger.exception("Worker lỗi ở %s", files[i].name)
                        result = FileJob(
                            source=files[i], status=JobStatus.ERROR, error_code="unexpected",
                            message=str(exc),
                        )
                    if result is None:  # kết quả muộn đã bị hủy, giữ nguyên job timeout
                        continue
                    jobs[i] = result
                    done_count += 1
                    if progress:
                        progress(jobs[i], done_count, total)

                # Timeout từng file: đánh dấu lỗi, bỏ chờ, và đánh dấu luồng là "bỏ rơi"
                now = time.monotonic()
                for fut in list(pending):
                    slot = slots[fut]
                    if fut.done() or slot.started is None:
                        continue  # vừa xong ngay trước lúc quét -> để vòng sau nhận kết quả
                    if now - slot.started > timeout:
                        slot.abandoned = True
                        i = index_of[fut]
                        jobs[i] = FileJob(
                            source=files[i], status=JobStatus.ERROR, error_code="timeout",
                            message=f"Quá {timeout}s chưa xử lý xong",
                        )
                        pending.discard(fut)
                        done_count += 1
                        if progress:
                            progress(jobs[i], done_count, total)

                if self.cancel_event.is_set():
                    for fut in list(pending):
                        if fut.cancel():
                            i = index_of[fut]
                            jobs[i] = FileJob(
                                source=files[i], status=JobStatus.ERROR,
                                error_code="cancelled", message="Đã hủy batch",
                            )
                            pending.discard(fut)

        return [
            j or FileJob(source=files[i], status=JobStatus.ERROR, error_code="cancelled",
                         message="Đã hủy batch")
            for i, j in enumerate(jobs)
        ]

    # -------------------------------------------------------------- apply

    def apply(
        self,
        jobs: list[FileJob],
        *,
        progress: ProgressCallback | None = None,
        save_dataset: bool = True,
    ) -> BatchSummary:
        """Thực thi: file ổn -> output, file lỗi -> _Loi/. Ghi registry, provenance, thống kê."""
        summary = BatchSummary(total=len(jobs), session_id=self.mover.session_id, jobs=jobs)
        for index, job in enumerate(jobs, start=1):
            try:
                if job.status == JobStatus.DUPLICATE:
                    summary.duplicate += 1
                    self.learning.record_match(job.profile_id, "duplicate", job.source.name)
                elif job.status == JobStatus.ERROR:
                    self.mover.quarantine(job, job.message or "Không rõ lý do", job.error_code)
                    summary.errors += 1
                    self.learning.record_match(job.profile_id, "error", job.source.name)
                else:
                    dest = self.mover.apply(job)
                    job.status = JobStatus.SUCCESS
                    job.message = str(dest)
                    summary.success += 1
                    self._record_success(job, dest, save_dataset)
            except PdfRenamerError as exc:
                job.status = JobStatus.ERROR
                job.error_code = getattr(exc, "code", "unknown")
                job.message = str(exc)
                summary.errors += 1
                summary.warnings.append(f"{job.source.name}: {exc}")
            except Exception as exc:
                logger.exception("Áp dụng thất bại cho %s", job.source.name)
                job.status = JobStatus.ERROR
                job.error_code = "unexpected"
                job.message = str(exc)
                summary.errors += 1
            if progress:
                progress(job, index, len(jobs))

        summary.log_path = self.mover.save_log()
        return summary

    def _record_success(self, job: FileJob, dest: Path, save_dataset: bool) -> None:
        """Ghi registry chống trùng + provenance + dataset cho 1 file đã xuất thành công."""
        profile = self.profile_by_id(job.profile_id)
        version = profile.version if profile else 0
        number = job.fields.get("number")
        self.dedup.record(
            job.file_hash,
            source_name=job.source.name,
            dest_path=str(dest),
            profile_id=job.profile_id,
            doc_number=number.value if number else "",
        )
        self.learning.log_job(job, session_id=self.mover.session_id, rule_version=version)
        self.learning.record_match(job.profile_id, "success", job.source.name)
        if save_dataset:
            self.learning.save_dataset_row(
                text="",  # text đầy đủ chỉ lưu khi có correction, tránh phình DB
                fields=job.field_values(),
                profile_id=job.profile_id,
                file_hash=job.file_hash,
                rule_version=version,
                corrected=any(f.edited_by_user for f in job.fields.values()),
            )

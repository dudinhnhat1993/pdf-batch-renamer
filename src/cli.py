"""Chế độ dòng lệnh — dùng cho n8n hoặc script ngoài điều phối.

Exit code:
    0 = tất cả file thành công
    1 = có file lỗi (đã được cách ly vào output/_Loi)
    2 = lỗi cấu hình (thiếu output, sai profile, thư mục không tồn tại)
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

if __package__ in (None, ""):  # chạy trực tiếp: python src/cli.py
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from src.core import bootstrap  # type: ignore  # noqa: F401

from src.core.bootstrap import build_context, force_utf8_streams, setup_logging
from src.core.errors import ConfigError, PdfRenamerError, ProfileError
from src.core.models import FileJob, JobStatus
from src.core.pipeline import Pipeline
from src.core.rules import resolve_profile
from src.core.watcher import StableFileWatcher

logger = logging.getLogger(__name__)

EXIT_OK = 0
EXIT_HAS_ERRORS = 1
EXIT_CONFIG = 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pdf-renamer",
        description="Đổi tên hàng loạt PDF chứng từ theo nội dung bên trong file.",
    )
    parser.add_argument(
        "--input", "-i", action="append", metavar="ĐƯỜNG_DẪN",
        help="File hoặc thư mục PDF (lặp lại được, thư mục quét đệ quy)",
    )
    parser.add_argument(
        "--check", action="store_true",
        help="In tình trạng môi trường (Tesseract, tessdata, barcode, thư mục dữ liệu) rồi thoát",
    )
    parser.add_argument("--output", "-o", metavar="THƯ_MỤC", help="Ghi đè thư mục output")
    parser.add_argument(
        "--profile", "-p", metavar="TÊN",
        help="Ép dùng profile này (bỏ qua điều kiện nhận diện). Không truyền = tự nhận diện",
    )
    parser.add_argument("--dry-run", action="store_true", help="Chỉ xem trước, không ghi file")
    parser.add_argument(
        "--watch", action="store_true",
        help="Theo dõi thư mục input và xử lý PDF mới xuất hiện (Ctrl+C để dừng)",
    )
    parser.add_argument("--no-dedup", action="store_true", help="Bỏ qua kiểm tra file đã xử lý")
    parser.add_argument("--workers", type=int, metavar="N", help="Số luồng xử lý song song")
    parser.add_argument("--verbose", "-v", action="store_true", help="Log chi tiết")
    return parser


def _print_jobs(jobs: list[FileJob], dry_run: bool) -> None:
    print()
    print(f"{'TRẠNG THÁI':<12} {'PROFILE':<18} {'TÊN CŨ':<38} TÊN MỚI")
    print("-" * 110)
    for job in jobs:
        target = job.new_name or "-"
        if job.status in (JobStatus.ERROR, JobStatus.DUPLICATE):
            target = job.message or "-"
        print(
            f"{job.status.label_vi:<12} {(job.profile_name or '-')[:18]:<18} "
            f"{job.source.name[:38]:<38} {target}"
        )
    if dry_run:
        print("\n[DRY-RUN] Không có file nào được ghi.")


def _summarize(jobs: list[FileJob]) -> tuple[int, int, int]:
    ok = sum(1 for j in jobs if j.status in (JobStatus.SUCCESS, JobStatus.PENDING))
    dup = sum(1 for j in jobs if j.status == JobStatus.DUPLICATE)
    err = sum(1 for j in jobs if j.status == JobStatus.ERROR)
    return ok, dup, err


def print_environment() -> int:
    """Chẩn đoán môi trường — dùng khi hỗ trợ người dùng và khi kiểm chứng bản build."""
    from src.core.barcode import AVAILABLE, UNAVAILABLE_REASON
    from src.core.config import app_dir, tessdata_dir
    from src.core.ocr import OcrEngine, find_tesseract

    ctx = build_context()
    engine = OcrEngine(
        ctx.config.ocr.tesseract_path,
        ctx.config.ocr.languages,
        ctx.config.ocr.dpi,
        ctx.config.ocr.tessdata_path,
    )
    frozen = getattr(sys, "frozen", False)

    print("PDF Batch Renamer — tình trạng môi trường")
    print(f"  Bản chạy         : {'exe đã đóng gói' if frozen else 'mã nguồn (dev)'}")
    print(f"  Thư mục dữ liệu  : {app_dir()}")
    print(f"  Thư mục output   : {ctx.config.output_root or '(chưa cấu hình)'}")
    print(f"  Số profile       : {len(ctx.profiles)}")
    print(f"  tesseract.exe    : {find_tesseract(ctx.config.ocr.tesseract_path) or '(không tìm thấy)'}")
    print(f"  tessdata dùng    : {engine.tessdata or '(không có)'}")
    print(f"  tessdata của app : {tessdata_dir()}")
    print(f"  Ngôn ngữ có sẵn  : {', '.join(engine.available_languages()) or '(không đọc được)'}")
    print(f"  Ngôn ngữ cấu hình: {ctx.config.ocr.languages}")
    print(f"  Barcode/QR       : {'sẵn sàng' if AVAILABLE else UNAVAILABLE_REASON}")
    print(f"  AI tầng 5        : {'BẬT' if ctx.config.ai.enabled else 'tắt'}")
    ctx.close()
    return EXIT_OK


def run(argv: list[str] | None = None) -> int:
    force_utf8_streams()
    args = build_parser().parse_args(argv)
    setup_logging(args.verbose)

    if args.check:
        return print_environment()

    if not args.input:
        print("LỖI CẤU HÌNH: thiếu --input (hoặc dùng --check để xem tình trạng).",
              file=sys.stderr)
        return EXIT_CONFIG

    ctx = build_context()
    config = ctx.config
    if args.output:
        config.output_root = args.output
    if args.workers:
        config.workers = args.workers
    if args.no_dedup:
        config.dedup_enabled = False

    if not config.output_root:
        print("LỖI CẤU HÌNH: chưa đặt thư mục output (dùng --output hoặc cấu hình trong app).",
              file=sys.stderr)
        return EXIT_CONFIG

    inputs = [Path(p) for p in args.input]
    missing = [str(p) for p in inputs if not p.exists()]
    if missing:
        print("LỖI CẤU HÌNH: không tìm thấy " + ", ".join(missing), file=sys.stderr)
        return EXIT_CONFIG

    profiles = ctx.profiles
    if not profiles:
        print("LỖI CẤU HÌNH: chưa có profile nào. Tạo rule trong app trước.", file=sys.stderr)
        return EXIT_CONFIG

    # --profile sai là lỗi cấu hình (exit 2), không phải lỗi của từng file (exit 1)
    if args.profile and resolve_profile(profiles, args.profile) is None:
        available = ", ".join(p.name for p in profiles)
        print(
            f"LỖI CẤU HÌNH: không tìm thấy profile '{args.profile}'. Hiện có: {available}",
            file=sys.stderr,
        )
        return EXIT_CONFIG

    try:
        pipeline = Pipeline(config, profiles, ctx.db)
    except PdfRenamerError as exc:
        print(f"LỖI CẤU HÌNH: {exc}", file=sys.stderr)
        return EXIT_CONFIG

    if args.watch:
        return _run_watch(pipeline, inputs, args)

    try:
        jobs = pipeline.plan(inputs, dry_run=args.dry_run, forced_profile=args.profile or "")
    except (ProfileError, ConfigError) as exc:
        print(f"LỖI CẤU HÌNH: {exc}", file=sys.stderr)
        return EXIT_CONFIG

    if not jobs:
        print("Không tìm thấy file PDF nào trong đường dẫn đã cho.")
        return EXIT_OK

    if not args.dry_run:
        summary = pipeline.apply(jobs)
        _print_jobs(jobs, dry_run=False)
        print(
            f"\nTổng {summary.total} | Thành công {summary.success} | "
            f"Trùng {summary.duplicate} | Lỗi {summary.errors}"
        )
        if summary.log_path:
            print(f"Operation log: {summary.log_path}")
        return EXIT_HAS_ERRORS if summary.errors else EXIT_OK

    _print_jobs(jobs, dry_run=True)
    ok, dup, err = _summarize(jobs)
    print(f"\nTổng {len(jobs)} | Sẽ đổi tên {ok} | Trùng {dup} | Lỗi {err}")
    return EXIT_HAS_ERRORS if err else EXIT_OK


def _run_watch(pipeline: Pipeline, inputs: list[Path], args) -> int:
    """Theo dõi thư mục: file mới -> xử lý ngay, không qua preview."""
    folders = [p for p in inputs if p.is_dir()]
    if not folders:
        print("LỖI CẤU HÌNH: --watch cần ít nhất 1 thư mục ở --input.", file=sys.stderr)
        return EXIT_CONFIG

    had_error = False

    def handle(path: Path) -> None:
        nonlocal had_error
        job = pipeline.plan_one(path, dry_run=args.dry_run, forced_profile=args.profile or "")
        if not args.dry_run:
            pipeline.apply([job])
        status = job.status.label_vi
        print(f"[{status}] {path.name} -> {job.new_name or job.message}")
        if job.status == JobStatus.ERROR:
            had_error = True

    watchers = [
        StableFileWatcher(
            folder,
            handle,
            stable_seconds=pipeline.config.watch.stable_seconds,
            process_existing=True,
        )
        for folder in folders
    ]
    for w in watchers:
        w.start()
    print(f"Đang theo dõi: {', '.join(str(f) for f in folders)} — Ctrl+C để dừng.")
    try:
        import time

        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nĐã dừng theo dõi.")
    finally:
        for w in watchers:
            w.stop()
    return EXIT_HAS_ERRORS if had_error else EXIT_OK


def main() -> None:
    try:
        sys.exit(run())
    except KeyboardInterrupt:
        print("\nĐã hủy.", file=sys.stderr)
        sys.exit(EXIT_HAS_ERRORS)


if __name__ == "__main__":
    main()

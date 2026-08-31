"""Dựng bản phát hành: lite (không kèm Tesseract) và full (kèm Tesseract portable).

    python tools/build.py            # dựng cả 2 bản
    python tools/build.py lite       # chỉ bản lite
    python tools/build.py full       # chỉ bản full

Bản full lấy Tesseract từ máy đang cài, chỉ chép đúng phần cần chạy (exe + DLL +
tessdata eng/osd/vie) — bỏ tài liệu và bộ công cụ huấn luyện cho nhẹ.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.core.ocr import find_tesseract  # noqa: E402

STAGE = ROOT / "build" / "tesseract-portable"
DIST = ROOT / "dist"
# Gói ngôn ngữ đi kèm bản full: tiếng Anh, nhận diện hướng trang, tiếng Việt
# osd (nhận diện hướng trang) nặng 10 MB mà app không dùng -> không bundle
BUNDLED_LANGUAGES = ("eng", "vie")


def human(size: int) -> str:
    return f"{size / 1024 / 1024:.1f} MB"


def dir_size(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def stage_tesseract() -> Path:
    """Chép Tesseract portable vào build/tesseract-portable."""
    exe = find_tesseract()
    if not exe:
        raise SystemExit(
            "Không tìm thấy Tesseract trên máy này — không dựng được bản full.\n"
            "Cài bằng:  winget install UB-Mannheim.TesseractOCR"
        )
    source = Path(exe).resolve().parent
    if STAGE.exists():
        shutil.rmtree(STAGE)
    (STAGE / "tessdata").mkdir(parents=True)

    shutil.copy2(source / "tesseract.exe", STAGE / "tesseract.exe")
    dll_count = 0
    for dll in source.glob("*.dll"):
        shutil.copy2(dll, STAGE / dll.name)
        dll_count += 1

    # tessdata: ưu tiên bản trong %APPDATA% của app (đã có vie), thiếu thì lấy của bản cài
    app_tessdata = Path(os.environ.get("APPDATA", "")) / "PDFBatchRenamer" / "tessdata"
    copied: list[str] = []
    for code in BUNDLED_LANGUAGES:
        name = f"{code}.traineddata"
        for candidate in (app_tessdata / name, source / "tessdata" / name):
            if candidate.exists():
                shutil.copy2(candidate, STAGE / "tessdata" / name)
                copied.append(code)
                break

    missing = [c for c in BUNDLED_LANGUAGES if c not in copied]
    if missing:
        print(f"  CANH BAO: thieu goi ngon ngu {missing} — ban full se khong OCR duoc thu tieng do")
    print(f"  tesseract.exe + {dll_count} DLL, tessdata: {', '.join(copied)}")
    print(f"  kich thuoc staging: {human(dir_size(STAGE))}")
    return STAGE


def build(variant: str) -> Path:
    env = dict(os.environ, PDFBR_VARIANT=variant, PDFBR_ROOT=str(ROOT))
    target = DIST / f"PDFBatchRenamer-{variant}"
    if target.exists():
        shutil.rmtree(target)

    print(f"\n=== Dung ban {variant} ===")
    started = time.monotonic()
    result = subprocess.run(
        [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", str(ROOT / "build.spec")],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        print(result.stdout[-4000:])
        print(result.stderr[-4000:])
        raise SystemExit(f"PyInstaller that bai cho ban {variant}")

    elapsed = time.monotonic() - started

    # Chép Tesseract portable vào CẠNH exe (không qua datas, xem chú thích trong build.spec)
    if variant == "full":
        shutil.copytree(STAGE, target / "tesseract")
        print(f"  da chep Tesseract portable -> {target / 'tesseract'}")

    print(f"  xong sau {elapsed:.0f}s -> {target}")
    print(f"  kich thuoc: {human(dir_size(target))}")
    for exe in ("PDFBatchRenamer.exe", "pdf-renamer.exe"):
        path = target / exe
        status = human(path.stat().st_size) if path.exists() else "THIEU"
        print(f"    {exe:24} {status}")
    return target


def main(variants: list[str]) -> None:
    if "full" in variants:
        print("=== Dung Tesseract portable ===")
        stage_tesseract()
    for variant in variants:
        build(variant)


if __name__ == "__main__":
    wanted = sys.argv[1:] or ["lite", "full"]
    invalid = [v for v in wanted if v not in ("lite", "full")]
    if invalid:
        raise SystemExit(f"Ban build khong hop le: {invalid}. Chi co 'lite' hoac 'full'.")
    main(wanted)

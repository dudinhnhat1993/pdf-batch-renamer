"""Tu dong bien dich bo cai dat Inno Setup va tao file zip Portable."""

import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core.version import __version__

DIST = ROOT / "dist"
FULL_DIR = DIST / "PDFBatchRenamer-full"
INSTALLER_DIR = DIST / "installer"
ISCC_PATH = Path(r"C:\Users\Admin\AppData\Local\Programs\Inno Setup 6\ISCC.exe")


def build_installer() -> None:
    if not FULL_DIR.exists():
        raise SystemExit(f"Chua co ban build full tai: {FULL_DIR}. Hay chay python tools/build.py full truoc.")

    INSTALLER_DIR.mkdir(parents=True, exist_ok=True)

    # Chep app_icon.ico vao thu muc full de co icon o moi noi
    icon_src = ROOT / "assets" / "app_icon.ico"
    if icon_src.exists():
        shutil.copy2(icon_src, FULL_DIR / "app_icon.ico")

    if not ISCC_PATH.exists():
        print(f"[WARN] Khong tim thay ISCC.exe tai {ISCC_PATH}")
        return

    iss_file = ROOT / "installer.iss"
    if not iss_file.exists():
        print(f"[WARN] Khong tim thay {iss_file}")
        return

    print(f"=== Dang bien dich Bo Cai Dat Inno Setup ===")
    cmd = [str(ISCC_PATH), str(iss_file)]
    res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if res.returncode != 0:
        print("[LOI ISCC]:", res.stderr or res.stdout)
        raise SystemExit("Loi khi tao bo cai dat Inno Setup.")
    
    out_exe = INSTALLER_DIR / f"PDFBatchRenamer-Setup-v{__version__}.exe"
    if out_exe.exists():
        mb = out_exe.stat().st_size / (1024 * 1024)
        print(f"[THANH CONG] Da tao bo cai dat: {out_exe} ({mb:.1f} MB)")


def build_portable_zip() -> None:
    if not FULL_DIR.exists():
        return

    # Tao file Huong Dan va file chay trong folder truoc khi zip
    readme_text = f"""========================================================================
     HUONG DAN SU DUNG BAN PORTABLE - PDF BATCH RENAMER v{__version__}
========================================================================

QUAN TRONG (BAT BUOC):
1. Khong chay truc tiep file .exe ben trong file nen .zip!
2. Ban hay giai nen toan bo file zip ra 1 thu muc bat ky:
   - Click chuot phai vao file PDFBatchRenamer-v{__version__}-Portable.zip
   - Chon "Extract All..." (Giai nen tat ca) -> Bam "Extract"
3. Mo thu muc vua giai nen ra va chay file "PDFBatchRenamer.exe"

Loi khuyen: Neu ban muon co bieu tuong Shortcut ngoai Desktop va khong
can giai nen thu cong, hay dung file cai dat "PDFBatchRenamer-Setup-v{__version__}.exe"!
========================================================================
"""
    (FULL_DIR / "HUONG-DAN-SU-DUNG.txt").write_text(readme_text, encoding="utf-8")

    zip_path = DIST / f"PDFBatchRenamer-v{__version__}-Portable.zip"
    print(f"=== Dang nen ban Portable: {zip_path} ===")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for file in FULL_DIR.rglob("*"):
            if file.is_file():
                rel = file.relative_to(FULL_DIR)
                arcname = Path("PDFBatchRenamer-Portable") / rel
                zf.write(file, str(arcname))

    mb = zip_path.stat().st_size / (1024 * 1024)
    print(f"[THANH CONG] Da tao goi Portable: {zip_path} ({mb:.1f} MB)")


if __name__ == "__main__":
    build_installer()
    build_portable_zip()

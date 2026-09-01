"""
Script tự động đóng gói và phát hành phiên bản mới (Release Automation Tool).
Chạy: python tools/publish_release.py --version 1.0.0 --notes "Tinh nang moi A" "Tinh nang moi B"
"""

from __future__ import annotations
import argparse
import hashlib
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"


def compute_sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def update_version_files(new_version: str) -> None:
    v_file = ROOT / "src" / "core" / "version.py"
    if v_file.exists():
        txt = v_file.read_text(encoding="utf-8")
        import re
        txt = re.sub(r'__version__\s*=\s*"[^"]+"', f'__version__ = "{new_version}"', txt)
        v_file.write_text(txt, encoding="utf-8")
        print(f"[OK] Updated version in {v_file}")

    iss_file = ROOT / "installer.iss"
    if iss_file.exists():
        txt = iss_file.read_text(encoding="utf-8")
        import re
        txt = re.sub(r'#define MyAppVersion "[^"]+"', f'#define MyAppVersion "{new_version}"', txt)
        txt = re.sub(r'OutputBaseFilename=PDFBatchRenamer-Setup-v[^\s]+', f'OutputBaseFilename=PDFBatchRenamer-Setup-v{new_version}', txt)
        iss_file.write_text(txt, encoding="utf-8")
        print(f"[OK] Updated version in {iss_file}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Phat hanh phien ban moi cho PDF Batch Renamer")
    parser.add_argument("--version", required=True, help="So phien ban moi (VD: 1.0.0)")
    parser.add_argument("--notes", nargs="+", help="Danh sach ghi chu cap nhat / Changelog")
    parser.add_argument("--url-base", default="https://github.com/dudinhnhat1993/pdf-batch-renamer/releases/download", help="Base URL tai file")
    args = parser.parse_args()

    new_ver = args.version.lstrip("v")
    changelog = args.notes or ["Cap nhat tinh nang va sua loi he thong."]

    print(f"=== Bat dau phat hanh phien ban v{new_ver} ===")
    update_version_files(new_ver)

    print("\n[1/3] Bien dich Full PyInstaller bundle...")
    subprocess.run([sys.executable, str(ROOT / "tools" / "build.py"), "full"], check=True)

    print("\n[2/3] Bien dich Inno Setup Installer & Portable Zip...")
    subprocess.run([sys.executable, str(ROOT / "tools" / "build_installer.py")], check=True)

    installer_file = DIST / "installer" / f"PDFBatchRenamer-Setup-v{new_ver}.exe"
    portable_file = DIST / f"PDFBatchRenamer-v{new_ver}-Portable.zip"

    if not installer_file.exists():
        cand = list((DIST / "installer").glob("*.exe"))
        if cand:
            installer_file = cand[0]
    if not portable_file.exists():
        cand = list(DIST.glob("*-Portable.zip"))
        if cand:
            portable_file = cand[0]

    inst_hash = compute_sha256(installer_file) if installer_file.exists() else ""
    port_hash = compute_sha256(portable_file) if portable_file.exists() else ""

    manifest = {
        "version": new_ver,
        "release_date": str(date.today()),
        "min_supported_version": "1.0.0",
        "title": f"Ban phat hanh PDF Batch Renamer v{new_ver}",
        "changelog": changelog,
        "installer": {
            "url": f"{args.url_base}/v{new_ver}/{installer_file.name}",
            "sha256": inst_hash,
            "size_bytes": installer_file.stat().st_size if installer_file.exists() else 0,
        },
        "portable": {
            "url": f"{args.url_base}/v{new_ver}/{portable_file.name}",
            "sha256": port_hash,
            "size_bytes": portable_file.stat().st_size if portable_file.exists() else 0,
        },
        "mandatory": False,
    }

    manifest_out = DIST / "version.json"
    manifest_out.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n[3/3] [THANH CONG] Da tao manifest: {manifest_out}")
    print(f"  - Installer SHA256: {inst_hash}")
    print(f"  - Portable  SHA256: {port_hash}")
    print("\n=== HOAN TAT PHAT HANH BAN CAP NHAT ===")


if __name__ == "__main__":
    main()

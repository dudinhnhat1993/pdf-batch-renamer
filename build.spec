# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec — 2 exe trong CÙNG 1 thư mục onedir.

    PDFBatchRenamer.exe   GUI, windowed (không hiện cửa sổ console)
    pdf-renamer.exe       CLI, console

Bản build chọn bằng biến môi trường:
    PDFBR_VARIANT=lite  (mặc định) — không kèm Tesseract
    PDFBR_VARIANT=full             — kèm Tesseract portable + tessdata eng/osd/vie

Chạy qua tools/build.py, đừng gọi thẳng pyinstaller (script đó lo phần dựng
Tesseract portable trước).
"""

import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

VARIANT = os.environ.get("PDFBR_VARIANT", "lite")
ROOT = Path(os.environ.get("PDFBR_ROOT", os.getcwd()))
TESSERACT_STAGE = ROOT / "build" / "tesseract-portable"

datas = [(str(ROOT / "assets"), "assets")]
binaries = []
hiddenimports = [
    # keyring nạp backend bằng entry point -> PyInstaller không tự thấy
    "keyring.backends.Windows",
    "keyring.backends.chainer",
    "keyring.backends.fail",
]

for package in ("pdfminer", "pdfplumber", "pypdf", "openpyxl", "pytesseract", "pyzbar"):
    pkg_datas, pkg_binaries, pkg_hidden = collect_all(package)
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hidden

hiddenimports += collect_submodules("PIL")

# Bản full KHÔNG nhét Tesseract qua datas: PyInstaller tự xếp lại mọi file .dll trong
# datas thành binary ở thư mục gốc, làm bộ DLL bị nhân đôi (thừa ~180 MB). tools/build.py
# chép nguyên thư mục portable vào cạnh exe sau khi build xong.
if VARIANT == "full" and not (TESSERACT_STAGE / "tesseract.exe").exists():
    raise SystemExit(f"Chưa dựng Tesseract portable ở {TESSERACT_STAGE}. Chạy tools/build.py.")

excludes = ["tkinter", "matplotlib", "numpy.testing", "pytest", "reportlab"]

gui = Analysis(
    [str(ROOT / "src" / "app.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=excludes,
    noarchive=False,
)

cli = Analysis(
    [str(ROOT / "src" / "cli.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=excludes + ["PySide6", "shiboken6"],
    noarchive=False,
)

gui_pyz = PYZ(gui.pure)
cli_pyz = PYZ(cli.pure)

gui_exe = EXE(
    gui_pyz,
    gui.scripts,
    [],
    exclude_binaries=True,
    name="PDFBatchRenamer",
    console=False,  # GUI: không kèm cửa sổ đen
    icon=None,
)

cli_exe = EXE(
    cli_pyz,
    cli.scripts,
    [],
    exclude_binaries=True,
    name="pdf-renamer",
    console=True,  # CLI: cần console để n8n đọc output và exit code
    icon=None,
)

COLLECT(
    gui_exe,
    gui.binaries,
    gui.datas,
    cli_exe,
    cli.binaries,
    cli.datas,
    strip=False,
    upx=False,
    name=f"PDFBatchRenamer-{VARIANT}",
)

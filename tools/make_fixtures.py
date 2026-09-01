"""Sinh file fixture cho test: PDF text layer, PDF scan, PDF barcode, PDF có password, Excel.

Chạy trực tiếp:  python tools/make_fixtures.py [thư_mục_đích]
Test gọi generate_all() qua conftest nên không cần commit file nhị phân vào repo.
"""

from __future__ import annotations

import sys
from pathlib import Path

# --------------------------------------------------------------- nội dung mẫu

INVOICE_LINES = [
    "ACME LOGISTICS CO., LTD",
    "123 Nguyen Van Linh, District 7, Ho Chi Minh City",
    "",
    "COMMERCIAL INVOICE",
    "",
    "Invoice No.: INV-2026-00871",
    "Invoice Date: 15/03/2026",
    "Seller: HAPAG-LLOYD AG",
    "Buyer: VIETNAM IMPORT EXPORT JSC",
    "",
    "Description                Qty      Unit Price      Amount",
    "Steel coils                 20        1,250.00     25,000.00",
    "Packing materials            5           80.00        400.00",
    "",
    "Total Amount: USD 25,400.00",
]

BL_LINES = [
    "HAPAG-LLOYD AG",
    "",
    "BILL OF LADING",
    "",
    "B/L No.: HLCUSGN2412345",
    "Date of Issue: 02/04/2026",
    "Carrier: HAPAG-LLOYD AG",
    "Shipper: ACME LOGISTICS CO., LTD",
    "Consignee: TO ORDER",
    "",
    "Container No.: MSKU2482484",
    "Seal No.: SL8827311",
    "Port of Loading: HO CHI MINH CITY",
    "Port of Discharge: HAMBURG",
]

PACKING_LIST_LINES = [
    "ACME LOGISTICS CO., LTD",
    "",
    "PACKING LIST",
    "",
    "Packing List No.: PL-2026-0442",
    "Date: 16/03/2026",
    "Shipper: ACME LOGISTICS CO., LTD",
    "Invoice No.: INV-2026-00871",
    "",
    "Carton   Description          Net Weight   Gross Weight",
    "1-10     Steel coils            18,000 kg     18,400 kg",
]

SCANNED_LINES = [
    "GLOBAL FREIGHT SERVICES",
    "",
    "COMMERCIAL INVOICE",
    "",
    "Invoice No.: INV-2026-SCAN01",
    "Invoice Date: 20/03/2026",
    "Seller: MAERSK LINE",
]

# Chứng từ tiếng Việt có dấu — dùng kiểm chứng gói ngôn ngữ 'vie' của Tesseract
# Bản scan CÓ DẤU — dùng để chứng minh gói ngôn ngữ 'vie' thực sự cần thiết:
# với 'eng' thì "Số hóa đơn" bị đọc thành rác.
SCANNED_VI_ACCENT_LINES = [
    "CÔNG TY TNHH GIAO NHẬN ĐẠI DƯƠNG",
    "",
    "HÓA ĐƠN THƯƠNG MẠI",
    "",
    "Số hóa đơn: HD-2026-0155",
    "Ngày lập: 17/7/26",
    "Người bán: Hãng tàu Hapag-Lloyd",
]

SCANNED_VI_LINES = [
    "CONG TY TNHH GIAO NHAN DAI DUONG",
    "",
    "HOA DON THUONG MAI",
    "",
    "So hoa don: HD-2026-0155",
    "Ngay lap: 15/03/2026",
    "Nguoi ban: Hang tau Hapag-Lloyd",
]

BARCODE_LINES = [
    "OCEAN NETWORK EXPRESS",
    "",
    "BILL OF LADING",
    "",
    "B/L No.: ONEYSGNF1234567",
    "Date of Issue: 05/04/2026",
]

# Số container hợp lệ theo ISO 6346 (check digit đúng) — dùng cho test barcode
BARCODE_CONTAINER = "MSKU2482484"

BANK_TRANSFER_LINES = [
    "10:21 17/7/26 VietinBank iPay",
    "1900 558 868",
    "contact@vietinbank.vn",
    "Chi tiet giao dich",
    "So tham chieu: 946C60716DK7PDT7",
    "Tai khoan nguon 106884718912 - TRAN THI THANH - Tai khoan thanh toan",
    "So tien -786,500 VND Bay tram tam muoi sau nghin nam tram dong",
    "Tai khoan dich 7229707 TRUONG TRAN TRAN",
    "Ngan hang TMCP A Chau",
    "Noi dung 946C60716DK7PDT7 6197ICBVC2A4YP8C TAM CK PKT",
    "YE2607006 T04.26",
    "Trang thai Thanh cong",
    "Kenh giao dich 78 - Retail Internet Banking",
    "Thoi gian 16-07-2026 22:23:43",
]


# ------------------------------------------------------------------ PDF text


def _text_pdf(path: Path, lines: list[str], title: str = "") -> Path:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    path.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(path), pagesize=A4)
    if title:
        c.setTitle(title)
    width, height = A4
    y = height - 60
    for line in lines:
        c.setFont("Helvetica-Bold" if line.isupper() and line.strip() else "Helvetica", 11)
        c.drawString(50, y, line)
        y -= 18
    c.showPage()
    c.save()
    return path


def make_invoice_pdf(path: Path) -> Path:
    return _text_pdf(path, INVOICE_LINES, title="Commercial Invoice INV-2026-00871")


def make_bill_of_lading_pdf(path: Path) -> Path:
    return _text_pdf(path, BL_LINES, title="Bill of Lading HLCUSGN2412345")


def make_packing_list_pdf(path: Path) -> Path:
    return _text_pdf(path, PACKING_LIST_LINES, title="Packing List PL-2026-0442")


def make_unknown_pdf(path: Path) -> Path:
    """Chứng từ không khớp profile nào -> rơi vào profile Chung."""
    return _text_pdf(path, ["MEMO", "", "Noi dung khong phai chung tu logistics."], title="Memo")


def make_bank_transfer_pdf(path: Path) -> Path:
    """Tạo hoặc sao chép fixture test-2.pdf (chứng từ chuyển khoản VietinBank iPay)."""
    import shutil
    fixture_real = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "test-2.pdf"
    if fixture_real.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(fixture_real, path)
        return path
    return _text_pdf(path, BANK_TRANSFER_LINES, title="VietinBank iPay test-2")



# ---------------------------------------------------------------- PDF scan


def make_scanned_pdf(path: Path, lines: list[str] | None = None) -> Path:
    """PDF chỉ chứa ảnh, KHÔNG có text layer — mô phỏng bản scan để test nhánh OCR."""
    from PIL import Image, ImageDraw, ImageFont

    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (1240, 1754), "white")  # A4 @ 150 dpi
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 34)
    except OSError:
        font = ImageFont.load_default()

    y = 90
    for line in lines or SCANNED_LINES:
        draw.text((90, y), line, fill="black", font=font)
        y += 52

    image.save(str(path), "PDF", resolution=150.0)
    return path


# -------------------------------------------------------------- PDF barcode


def make_barcode_pdf(path: Path, value: str = BARCODE_CONTAINER) -> Path:
    """PDF có text layer + 1 mã Code128 chứa số container."""
    from reportlab.graphics.barcode import code128
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    path.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(path), pagesize=A4)
    c.setTitle("Bill of Lading with barcode")
    width, height = A4
    y = height - 60
    for line in BARCODE_LINES:
        c.setFont("Helvetica", 11)
        c.drawString(50, y, line)
        y -= 18

    barcode = code128.Code128(value, barHeight=48, barWidth=1.1)
    barcode.drawOn(c, 50, y - 90)
    c.showPage()
    c.save()
    return path


# ------------------------------------------------------------- PDF password


def make_encrypted_pdf(path: Path, password: str = "logistics2026") -> Path:
    """PDF mã hóa bằng mật khẩu user — test nhánh thử danh sách password."""
    from pypdf import PdfReader, PdfWriter

    plain = path.with_name(path.stem + "_plain.pdf")
    _text_pdf(plain, INVOICE_LINES, title="Encrypted invoice")

    writer = PdfWriter()
    for page in PdfReader(str(plain)).pages:
        writer.add_page(page)
    writer.encrypt(password)
    with open(path, "wb") as fh:
        writer.write(fh)
    plain.unlink(missing_ok=True)
    return path


# ------------------------------------------------------------------- Excel


def make_masterdata_xlsx(path: Path) -> Path:
    """File tra cứu mẫu: mã khách hàng -> tên công ty đầy đủ."""
    from openpyxl import Workbook

    path.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.title = "KhachHang"
    ws.append(["Ma KH", "Ten cong ty", "MST"])
    ws.append(["KH001", "Cong ty TNHH Acme Logistics", "0312345678"])
    ws.append(["KH002", "Vietnam Import Export JSC", "0398765432"])
    ws.append(["KH003", "Hapag-Lloyd Vietnam", "0301122334"])
    wb.save(str(path))
    return path


# --------------------------------------------------------------------- all


def generate_all(directory: Path | str) -> dict[str, Path]:
    """Sinh toàn bộ fixture vào 1 thư mục. Trả dict tên -> đường dẫn."""
    d = Path(directory)
    d.mkdir(parents=True, exist_ok=True)
    return {
        "invoice": make_invoice_pdf(d / "invoice_text.pdf"),
        "bill_of_lading": make_bill_of_lading_pdf(d / "bl_text.pdf"),
        "packing_list": make_packing_list_pdf(d / "packing_list_text.pdf"),
        "unknown": make_unknown_pdf(d / "memo_unknown.pdf"),
        "scanned": make_scanned_pdf(d / "invoice_scanned.pdf"),
        "scanned_vi": make_scanned_pdf(d / "hoa_don_scan_vi.pdf", SCANNED_VI_LINES),
        "scanned_vi_accent": make_scanned_pdf(
            d / "hoa_don_scan_co_dau.pdf", SCANNED_VI_ACCENT_LINES
        ),
        "barcode": make_barcode_pdf(d / "bl_barcode.pdf"),
        "encrypted": make_encrypted_pdf(d / "invoice_encrypted.pdf"),
        "masterdata": make_masterdata_xlsx(d / "masterdata.xlsx"),
        "bank_transfer": make_bank_transfer_pdf(d / "test-2.pdf"),
    }


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("tests/fixtures/generated")
    created = generate_all(target)
    for name, p in created.items():
        print(f"{name:16} {p}")

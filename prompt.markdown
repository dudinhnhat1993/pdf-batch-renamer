# DỰ ÁN: PDF BATCH RENAMER (PROFESSIONAL DESKTOP UTILITY)
> **Tài liệu Bàn giao & Master Prompt Chuyển giao Ngữ cảnh cho Antigravity 2.0**  
> *Phiên bản hiện tại: v1.0.3 · Ngày cập nhật: 23/09/2026 · Tác giả / Publisher: Đình Nhất*  
> *Repository*: `https://github.com/dudinhnhat1993/pdf-batch-renamer`  
> *Thư mục dự án cục bộ*: `C:\Users\Admin\Claude\Projects\PDF Batch Renamer`

---

## 1. TỔNG QUAN DỰ ÁN & MỤC TIÊU
**PDF Batch Renamer** là phần mềm desktop chuyên nghiệp (Windows x64) dùng để đổi tên hàng loạt file PDF tự động dựa trên nội dung văn bản bóc tách từ tài liệu, kết hợp OCR tiếng Việt có dấu và bộ quy tắc Regex linh hoạt. 

Phần mềm được tối ưu cho các doanh nghiệp, kế toán, logistics, ngân hàng xử lý hàng nghìn chứng từ (hóa đơn VAT, sao kê ngân hàng Vietcombank/MBBank/Techcombank, ủy nhiệm chi, vận đơn B/L, hợp đồng) mỗi ngày với tốc độ cao, độ an toàn tuyệt đối và khả năng hoàn tác (Undo/Rollback) 100%.

### Các tính năng cốt lõi đã hoàn thiện (v1.0.3):
1. **Bóc tách văn bản kép (Hybrid Extraction)**:
   - Trích xuất văn bản vector cực nhanh bằng `PyMuPDF` (`fitz`).
   - Tích hợp động cơ `Tesseract OCR` portable (hỗ trợ tiếng Việt `vie` + tiếng Anh `eng`) cho các file scan / ảnh chụp.
2. **Quy tắc đổi tên động (Smart Rule & Regex Engine)**:
   - Trích xuất trường thông tin linh hoạt: `Số hóa đơn`, `Mã số thuế`, `Ngày lập`, `Số tiền`, `Tên đối tác / Công ty`, `Nội dung chuyển khoản`.
   - Mẫu đổi tên tùy biến: `{date}_{doc_type}_{invoice_no}_{company}`.
   - Hỗ trợ chuẩn hóa ngày tháng đa định dạng (`DD/MM/YYYY`, `YYYY-MM-DD`), chuẩn hóa số tiền (`1.250.000 đ`).
   - Khung quản lý Field mở rộng (min-height 180px, max-height 320px, zebra striping, badge phân loại `[BẮT BUỘC]` / `[Tùy chọn]`).
3. **Giao diện Modern Qt6 (PySide6)**:
   - Hỗ trợ đa chủ đề: **Chế độ Sáng (Light Mode - Mặc định)** và **Chế độ Tối (Dark Mode)** chuyển đổi tức thì.
   - Trình xem trước tài liệu tích hợp (PDF Viewer 2 trang, xoay trang, zoom, highlight từ khóa).
   - Live Preview bảng hàng đợi hiển thị tên cũ, tên mới đề xuất, trạng thái khớp rule (`Khớp`, `Không khớp`, `Bỏ qua`, `Lỗi`).
4. **An toàn dữ liệu & Hoàn tác (Transaction & Rollback Safety)**:
   - Tự động sao lưu lịch sử đổi tên vào CSDL SQLite.
   - Tính năng **Hoàn tác (Undo)** 1-click đưa toàn bộ file về tên gốc chính xác.
   - Chống ghi đè file (Auto Rename Collision: `_1`, `_2`), chống Path Traversal và ký tự cấm của Windows (`\ / : * ? " < > |`).
5. **Hướng dẫn tương tác đồ họa HD (Built-in Rich Guide)**:
   - Đồ họa minh họa HD 100% tiếng Việt có dấu nhúng Base64 trực tiếp vào bộ nhớ (`src/ui/guide_assets.py`).
   - Cửa sổ phóng to ảnh chi tiết `ImageZoomDialog` (1376×768).
6. **Hệ thống Tự động cập nhật (GitHub Releases Auto-Update Engine)**:
   - Tự động kiểm tra bản cập nhật mới từ `dudinhnhat1993/pdf-batch-renamer`.
   - Tải về và chạy cập nhật nền thông minh, xác thực tính toàn vẹn qua mã băm SHA-256.

---

## 2. KIẾN TRÚC HỆ THỐNG & CÔNG NGHỆ (TECH STACK)

```
+-------------------------------------------------------------------------------+
|                            PDF BATCH RENAMER v1.0.3                           |
+-------------------------------------------------------------------------------+
|  [GUI Layer]        PySide6 (Qt6) · QSS Theme Engine · Fluent/Manifest Style   |
|         |           - MainWindow, RuleEditorDialog, GuideDialog, PdfViewer    |
|         v                                                                     |
|  [Core Processing]  PDF Engine (PyMuPDF) + OCR Engine (Tesseract Portable)   |
|         |           - Extractor, RuleMatcher, Renamer, History SQLite DB     |
|         v                                                                     |
|  [Distribution]     PyInstaller (Full Bundle) + Inno Setup 6 (Installer)      |
|         |           - Auto-Updater (GitHub Releases API + SHA256 Verification)|
|         v                                                                     |
|  [Security Guard]   Zero Real-Data DLP · Pre-commit Hook · Regex Path Sanitizer|
+-------------------------------------------------------------------------------+
```

- **Ngôn ngữ**: Python 3.11+
- **GUI Framework**: `PySide6` (Qt 6.7+)
- **Xử lý PDF**: `PyMuPDF` (`fitz` >= 1.24.0)
- **OCR Engine**: `pytesseract` + `Tesseract-OCR` Portable (đính kèm trong bundle)
- **Lưu trữ CSDL Cục bộ**: SQLite (`~/.pdf_renamer/history.db` & `rules.db`)
- **Kiểm thử (Test Suite)**: `pytest`, `pytest-qt` (100% pass với 99 test cases)
- **Đóng gói (Packaging)**: `PyInstaller 6.x` (`build.spec`), `Inno Setup 6` (`installer.iss`)
- **CI/CD**: GitHub Actions workflow `.github/workflows/release.yml`

---

## 3. CẤU TRÚC THƯ MỤC DỰ ÁN

```
PDF Batch Renamer/
├── .github/
│   └── workflows/
│       └── release.yml          # CI/CD tự động build & release trên GitHub Actions
├── assets/
│   ├── icon.ico                 # App Icon Windows (Multi-resolution)
│   ├── icon.png                 # App Icon PNG 256x256
│   └── guide/                   # Ảnh chụp màn hình hướng dẫn
├── dist/
│   ├── installer/
│   │   └── PDFBatchRenamer-Setup-v1.0.3.exe  # Bộ cài đặt Windows Inno Setup
│   ├── PDFBatchRenamer-v1.0.3-Portable.zip    # Bản Portable không cần cài đặt
│   └── version.json             # Release manifest phục vụ Auto-Updater
├── releases/
│   └── version.json             # Manifest đồng bộ repo GitHub
├── src/
│   ├── core/
│   │   ├── config.py            # Quản lý cấu hình, đường dẫn, app data
│   │   ├── engine.py            # Bộ máy điều phối trích xuất & đổi tên
│   │   ├── extractor.py         # Trích xuất văn bản từ PDF (PyMuPDF + OCR)
│   │   ├── history.py           # Quản lý CSDL lịch sử đổi tên & Undo Rollback
│   │   ├── models.py            # Data classes (Rule, Field, FileItem, Result)
│   │   ├── ocr.py               # Tích hợp Tesseract OCR đa luồng
│   │   ├── rules.py             # Logic Regex Rule Engine & validation
│   │   ├── sanitizer.py         # Làm sạch tên file, chống Path Traversal
│   │   ├── updater.py           # Auto-Updater kiểm tra GitHub Releases
│   │   └── version.py           # Định nghĩa __version__ = "1.0.3"
│   └── ui/
│       ├── about_dialog.py      # Hộp thoại Giới thiệu & Kiểm tra cập nhật
│       ├── guide_assets.py      # Đồ họa hướng dẫn HD Base64 tiếng Việt
│       ├── guide_dialog.py      # Hộp thoại Hướng dẫn sử dụng trực quan
│       ├── main_window.py       # Cửa sổ chính (Queue, Toolbar, Menu, Action)
│       ├── pdf_viewer.py        # Widget xem trước nội dung PDF & highlight
│       ├── rule_editor.py       # Hộp thoại cấu hình và tạo mới Rule Regex
│       ├── settings_dialog.py   # Cài đặt ứng dụng (OCR, Theme, Auto-Update)
│       └── themes.py            # Bảng màu QSS (Light Mode & Dark Mode)
├── tests/
│   ├── test_core_engine.py      # Test trích xuất, regex, rule matching
│   ├── test_bank_transfer_e2e.py# Test E2E kịch bản sao kê ngân hàng
│   ├── test_sanitizer.py        # Test bảo mật tên file, ký tự cấm, traversal
│   └── test_ui_components.py    # Test giao diện PySide6 với pytest-qt
├── tools/
│   ├── build.py                 # Script chạy PyInstaller build bundle
│   ├── build_installer.py       # Script biên dịch Inno Setup & tạo Portable Zip
│   ├── make_fixtures.py         # Tạo file PDF test giả lập (Synthetic Test Data)
│   ├── publish_release.py       # 1-Command Release Pipeline (Build + Tag + Push)
│   └── security_guard.py        # Quét an ninh DLP & chống rò rỉ dữ liệu trước push
├── .gitignore                   # Chặn commit *.pdf thật, secrets, *.env
├── build.spec                   # File cấu hình PyInstaller
├── installer.iss                # Kịch bản Inno Setup Installer
└── requirements.txt             # Danh sách thư viện Python
```

---

## 4. QUY CHUẨN AN NINH & CHỐNG RÒ RỈ DỮ LIỆU (DLP & INVARIANTS)

Khi phát triển hoặc bảo trì dự án, **Antigravity 2.0 bắt buộc tuân thủ nghiêm ngặt 5 nguyên tắc bảo mật**:

1. **Nguyên tắc Dữ liệu Giả lập (Zero Real-Data Invariant)**:
   - **Tuyệt đối cấm commit hoặc lưu trữ file PDF thật** (hóa đơn, sao kê, căn cước, hợp đồng doanh nghiệp) vào kho mã nguồn hoặc kho test.
   - Mọi dữ liệu test **bắt buộc được tạo tự động qua `tools/make_fixtures.py`** với thông tin giả lập (Synthetic Data).
2. **Bộ lọc Chống Rò rỉ Dữ liệu Nhạy cảm (DLP & Secret Leak Protection)**:
   - `.gitignore` bắt buộc chặn: `*.pdf`, `*.env*`, `*CLAUDE*.md`, `*BRIEF*.md`, `credentials*`, `token*`, `*.pem`, `*.key`.
   - Trước mọi commit / push, script `tools/security_guard.py` tự động quét toàn bộ cây thư mục để phát hiện và ngăn chặn nếu phát hiện API keys, private keys, passwords hoặc file nhạy cảm.
3. **Phòng chống tấn công Path Traversal & File System Injection**:
   - Mọi tên file sinh ra từ Rule Regex **bắt buộc phải đi qua `src/core/sanitizer.py`**.
   - Loại bỏ triệt để các chuỗi nguy hiểm: `../`, `..\`, `/`, `\`, null bytes `\x00`, và các ký tự cấm của Windows (`: * ? " < > |`).
4. **Quy chuẩn Không Tự Mở Trình Duyệt (Zero Browser Policy)**:
   - Tuyệt đối không sử dụng công cụ `browser_subagent` hay tự ý mở trình duyệt trên máy người dùng. Mọi kiểm thử được xác thực qua lệnh terminal (`pytest`, script kiểm tra).
5. **Publisher & Thương hiệu Nhất Quán**:
   - Tên ứng dụng: **PDF Batch Renamer**.
   - Publisher: **Đình Nhất**.
   - GitHub Repository: `https://github.com/dudinhnhat1993/pdf-batch-renamer`.

---

## 5. QUY TRÌNH PHÁT HÀNH 1 LỆNH DUY NHẤT (1-COMMAND RELEASE PIPELINE)

Để nâng cấp phiên bản mới (ví dụ từ `v1.0.3` lên `v1.0.4`), chỉ cần thực thi **1 lệnh duy nhất**:

```powershell
# Chạy trong môi trường ảo (.venv)
python tools/publish_release.py --version 1.0.4 --notes "Bổ sung tính năng X" "Tối ưu hóa OCR Y" --push
```

### Chuỗi tự động hóa bên dưới của lệnh:
1. **Security Pre-flight**: Chạy `tools/security_guard.py` đảm bảo không có rò rỉ secret hoặc file nhạy cảm.
2. **Version Bump**: Tự động cập nhật `__version__ = "1.0.4"` trong `src/core/version.py` và `installer.iss`.
3. **Build Bundle**: Chạy PyInstaller biên dịch bundle ứng dụng đầy đủ (`tools/build.py`).
4. **Compile Setup**: Chạy Inno Setup đóng gói `PDFBatchRenamer-Setup-v1.0.4.exe` và nén `PDFBatchRenamer-v1.0.4-Portable.zip`.
5. **Generate Manifest**: Tính toán mã băm SHA-256 chính xác và cập nhật `dist/version.json` + `releases/version.json`.
6. **Git Auto-Release**: Tự động `git commit`, tạo Git tag `v1.0.4` và `git push origin main --tags` để kích hoạt GitHub Actions Cloud Release.

---

## 6. HƯỚNG DẪN DÀNH CHO ANTIGRAVITY 2.0 TIẾP TỤC PHÁT TRIỂN

Khi nạp prompt này vào Antigravity 2.0, bạn có thể tiếp tục thực hiện ngay các tính năng mở rộng nằm trong lộ trình kế tiếp:

### Gợi ý các tính năng mở rộng tiếp theo (Milestone v1.1.0+):
- [ ] **AI Smart Extraction (Local LLM / Ollama)**: Tích hợp chế độ gợi ý Regex và trích xuất thực thể thông minh từ nội dung tài liệu phức tạp không theo khuôn mẫu.
- [ ] **Watch Folder Daemon (Thư mục tự động)**: Chế độ chạy ngầm giám sát thư mục designated, tự động phát hiện file PDF mới thả vào và đổi tên theo quy tắc được gán.
- [ ] **Xuất báo cáo & Bảng kê (Export Excel/CSV/JSON)**: Cho phép xuất danh sách các hóa đơn/chứng từ đã bóc tách ra bảng Excel kèm các trường thông tin (Số HĐ, Ngày, Tiền, Đối tác) phục vụ nhập liệu kế toán.
- [ ] **Hỗ trợ Plugin / Script tùy biến**: Cho phép người dùng viết đoạn mã Python ngắn để định dạng lại tên file phức tạp.

---
*Tài liệu này đã được đồng bộ và nạp đầy đủ context vào hệ thống bộ nhớ Antigravity 2.0.*

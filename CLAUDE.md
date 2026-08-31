# CLAUDE.md — PDF Batch Renamer

App desktop Windows (Python 3.11 + PySide6) đổi tên hàng loạt PDF chứng từ logistics
dựa trên nội dung bên trong file. **Rule-based là chính, AI chỉ là fallback tùy chọn.**

## 1. Nguyên tắc bất biến (không được vi phạm khi code)

1. **Rule trước, AI sau.** AI (tầng 5) mặc định TẮT toàn cục, chỉ chạy khi bật ở cả
   Settings lẫn profile VÀ vẫn thiếu field bắt buộc sau tầng 0–4.
2. **Deterministic.** Cùng file + cùng rule version → cùng field trích được và cùng
   tên file "cơ sở". (Ngoại lệ có chủ đích: `{counter}`, hậu tố `_01` chống trùng, và
   thư mục con theo ngày xử lý phụ thuộc ngữ cảnh chạy — xem §6.)
3. **Không bỏ sót âm thầm.** Mọi file vào queue đều kết thúc ở đúng 1 trạng thái cuối:
   Thành công / Trùng / Lỗi. File lỗi → `output/_Loi/` kèm `<tên>.txt` ghi lý do.
4. **Không mất dữ liệu.** Mode Move luôn backup + ghi operation log để Undo.
5. **No-code.** Mọi rule/profile tạo và sửa được 100% qua GUI. Không bắt user viết regex.
6. **AI chỉ đề xuất.** Rule do AI sinh phải qua duyệt thủ công + regression test +
   versioning y hệt rule viết tay. App không bao giờ tự sửa rule.
7. **Lỗi cô lập theo file.** Một file lỗi không được làm chết batch. Mọi exception có log.

## 2. Kiến trúc

```
src/
  core/            # thuần logic, KHÔNG import PySide6 — phải test được headless
    models.py      # dataclass: Profile, FieldSpec, ExtractedField, FileJob, Layer, JobStatus
    errors.py      # cây exception nghiệp vụ, mỗi lớp có .code ghi vào file .txt cách ly
    config.py      # %APPDATA%/PDFBatchRenamer/config.json, đường dẫn, keyring, assets
    timeutil.py    # DB lưu UTC, hiển thị theo giờ máy
    db.py          # SQLite schema + migration, connection an toàn đa luồng
    pdfdoc.py      # mở PDF (thử password), text layer + bbox, render trang thành ảnh
    extractor.py   # điều phối pipeline 5 tầng, trả ExtractionResult
    ocr.py         # Tesseract (auto-detect exe), OCR trang → text + word boxes
    zonal.py       # cắt vùng theo % trang, lấy text/OCR trong vùng
    barcode.py     # pyzbar, tự tắt khi thiếu VC++ Redistributable
    metadata.py    # pypdf: Title/Author/AcroForm
    ai_client.py   # OpenAI-compatible, few-shot build động, validate output
    rules.py       # load/save profile JSON, match profile, regex tầng 1, versioning
    rule_builder.py# sinh regex ứng viên từ đoạn text bôi chọn + giải thích tiếng Việt
    regression.py  # so 2 version rule trên bộ file mẫu, báo field nào kém đi
    textloc.py     # định vị 1 giá trị trên trang → bbox (provenance + rule builder)
    validators.py  # ISO 6346 check digit, parse/format ngày theo format profile
    normalize.py   # từ điển alias → tên công ty chuẩn
    masterdata.py  # tra cứu Excel (openpyxl), cache theo mtime
    namer.py       # render template token → tên file hợp lệ Windows
    mover.py       # copy/move, thư mục con theo ngày, chống trùng, backup, undo log
    dedup.py       # SHA-256 + registry SQLite
    learning.py    # provenance, correction, dataset JSONL, counter, thống kê
    pipeline.py    # plan (Preview) / apply, ThreadPoolExecutor, timeout, hủy batch
    bootstrap.py   # dựng thư mục dữ liệu, seed profile mẫu, logging
    watcher.py     # watchdog + chờ file ổn định 3s
    report.py      # CSV/Excel báo cáo + số liệu dashboard 30 ngày
  ui/              # PySide6, chỉ gọi core, không chứa logic nghiệp vụ
    qt_helpers.py       # đổi ảnh PIL sang Qt, màu trạng thái, theme
    pdf_view.py         # render trang + overlay bbox từng từ, click/bôi chọn
    preview_model.py    # model bảng Preview + bảng field (sửa tay được)
    main_window.py      # kéo-thả, queue, Preview, log, worker nền, Undo
    settings_dialog.py  # toàn bộ cấu hình
    rule_builder_wizard.py  # wizard 4 bước: click keyword, bôi chọn chữ, kéo khung vùng
    rule_editor.py      # bật/tắt, nhân bản, ưu tiên, file mẫu, version, master data, rule pack
    correction_dialog.py# Learning Loop: sửa tay -> đề xuất rule -> duyệt -> regression
    stats_dialog.py     # dashboard tỉ lệ match 30 ngày + export dataset JSONL
  cli.py           # entry point CLI, exit code 0/1/2
  app.py           # entry point GUI
tests/  fixtures/  assets/  build.spec  README.md
```

**Luật phụ thuộc:** `ui/` → `core/`; `core/` không bao giờ import `ui/`. `cli.py` chỉ
dùng `core/`. Mọi I/O ngoài (Tesseract, AI, Excel, filesystem) đi qua 1 module để mock được.

## 3. Pipeline 5 tầng

| Tầng | Module | Chạy khi |
|---|---|---|
| 0 chuẩn bị text | extractor + ocr | luôn; text layer < 50 ký tự → OCR ≤3 trang đầu |
| 1 regex theo nhãn | rules | luôn |
| 2 zonal | zonal | thiếu field bắt buộc **HOẶC** còn field trống có khai báo zone * |
| 3 barcode/QR | barcode | thiếu field bắt buộc **HOẶC** còn field trống có `from_barcode` * |
| 4 metadata/AcroForm | metadata | thiếu field bắt buộc **HOẶC** còn field trống có `metadata_key` * |
| 5 AI | ai_client | **chỉ khi** thiếu field bắt buộc VÀ bật ở cả global + profile |

\* Vế thứ hai chỉ áp dụng khi profile bật `fill_optional_fields` (mặc định BẬT). Tắt
toggle này thì tầng 2–4 quay về hành vi tiết kiệm: chỉ chạy khi thiếu field bắt buộc.
Tầng 5 KHÔNG bao giờ được nới lỏng vì nó tốn tiền và gửi dữ liệu ra ngoài.

Mỗi field trích được ghi `Provenance(file_hash, layer, rule_id, raw_value, page, bbox,
profile_id, rule_version, timestamp)` vào SQLite — nền dữ liệu cho Learning Loop.
Field từ tầng 5 phải pass regex validate của chính field đó, fail thì loại bỏ.

## 4. Lưu trữ

- `config.json` tại `%APPDATA%/PDFBatchRenamer/` — settings, đường dẫn, toggle.
- `profiles/*.json` + `profiles/_versions/<profile>/<n>.json` — rule + lịch sử version.
- `data.db` (SQLite) — dedup registry, provenance, correction, dataset, thống kê.
- **API key CHỈ trong keyring (Windows Credential Manager).** Không bao giờ vào JSON/log.

## 5. Quy ước code

- Type hints đầy đủ; docstring 1–2 dòng. **Comment tiếng Việt ở logic nghiệp vụ**,
  tên biến/hàm/class tiếng Anh. Chuỗi hiển thị cho user: tiếng Việt.
- Không `except:` trần. Exception nghiệp vụ kế thừa `PdfRenamerError` trong `core/errors.py`.
- Không print trong core — dùng `logging` (`logger = logging.getLogger(__name__)`).
- Đường dẫn dùng `pathlib.Path`. Không hardcode separator.
- Hàm core nhận/ trả dataclass, không nhận widget hay dict lỏng lẻo.
- Format: black (line 100) + ruff. requirements.txt ghim version chính xác (`==`).

## 6. Đặt tên file

Token: `{doc_date} {number} {company} {doctype} {original_name} {counter}` + field tự định nghĩa.
Làm sạch: bỏ `\ / : * ? " < > |`, ký tự điều khiển, khoảng trắng thừa; giới hạn 120 ký tự
(cắt ở giữa, giữ phần đuôi phân biệt); tùy chọn bỏ dấu tiếng Việt. Trùng tên → `_01`, `_02`.

## 7. Test

pytest, mock OCR/AI/keyring. Bắt buộc phủ: 5 tầng pipeline, match profile, sinh regex từ
text bôi chọn, ISO 6346 check digit, parse ngày, template namer, chống trùng tên, thư mục
theo ngày, dedup hash, master data Excel, rule versioning + regression test, provenance.
Fixtures tự sinh bằng script (reportlab/PyMuPDF): PDF text layer, PDF scan giả lập,
PDF barcode, PDF có password, Excel master data.

## 8. Trạng thái phase

- [x] Phase 1 — core engine + CLI + test (313 test pass, 2 skip khi thiếu Tesseract)
- [x] Phase 2 — GUI + Visual Rule Builder + zonal + Rule Editor (451 test pass)
- [x] Phase 3 — master data, watch folder, báo cáo, rule pack, Learning Loop (551 test)
- [x] Phase 4 — build exe (lite/full) + README người dùng cuối

## 9. Quyết định đã chốt (2026-08-31)

1. **Tesseract:** Phase 1–3 không bundle, auto-detect exe, test OCR dùng mock + 1 test
   integration tự skip khi không có Tesseract. **Phase 4 build 2 bản:** `lite` (không
   bundle) và `full` (bundle Tesseract portable + traineddata eng & vie) cho người dùng
   cuối không tự cài được.
2. **`{counter}`:** per profile per ngày, lưu SQLite, format `{counter:03}`.
   **Chỉ dùng trong template của profile "Chung".** Profile nghiệp vụ không dùng
   `{counter}` để giữ deterministic.
3. **`{doc_date}`:** mặc định ghi `YYYY-MM-DD`; override bằng `{doc_date:ddMMyyyy}`.
4. **CLI `--profile`:** tùy chọn. Có → ép profile, bỏ qua điều kiện nhận diện.
5. **Watch folder:** auto-detect theo thứ tự ưu tiên; Settings có ô pin 1 profile cố định.
6. **Backup:** `_backup/<session_id>/`, KHÔNG tự xoá; dọn theo tuổi **mặc định 30 ngày**
   (cấu hình được) + nút "Dọn backup".
7. **Đóng gói:** 2 exe onedir — `PDFBatchRenamer.exe` (GUI, windowed) và
   `pdf-renamer.exe` (CLI, console).
8. **Master data Excel:** load vào memory đầu batch, cache theo mtime, mở read-only.
   File khoá/thiếu → cảnh báo trong Preview, KHÔNG fail batch.
9. **AI:** client OpenAI-compatible generic, 4 preset (DeepSeek/OpenAI/Ollama/LM Studio)
   không preselect. Toggle bật AI phải hiện cảnh báo gửi nội dung chứng từ ra ngoài.
10. **Barcode:** thiếu VC++ Redistributable → tắt tầng 3 + cảnh báo log, KHÔNG crash.
11. **Determinism:** khoá ở tầng field trích được + tên cơ sở (chưa gồm thư mục ngày,
    `{counter}`, hậu tố `_01`).

## 10. Quyết định bổ sung sau Phase 1 (2026-08-31)

12. **Cổng chặn tầng 2–4 được nới** theo mô tả ở §3, kèm toggle `fill_optional_fields`
    trên từng profile (mặc định BẬT).
13. **Kết quả về muộn bị hủy.** File vượt timeout bị đánh lỗi và batch đi tiếp; luồng nền
    vẫn chạy nốt nhưng kết quả của nó bị vứt bỏ hoàn toàn — không ghi dedup registry,
    không ghi provenance, không copy/move — chỉ log `late result discarded`. Nhờ vậy xử
    lý lại file đó về sau KHÔNG bị báo Trùng.
14. **Điều kiện loại trừ** (`exclude_conditions`) trên profile, có quyền phủ quyết
    conditions. Dùng cho chứng từ chồng lấn (Invoice NOT contains "PACKING LIST") để
    người dùng không phải mày mò thứ tự ưu tiên. `--profile` vẫn bỏ qua cả loại trừ.
15. **tessdata riêng của app** tại `%APPDATA%/PDFBatchRenamer/tessdata`. Thư mục tessdata
    trong Program Files cần quyền admin mới ghi được, mà app phải chạy không cần admin —
    nên gói ngôn ngữ bổ sung (`vie`) để ở đây và báo cho Tesseract qua `TESSDATA_PREFIX`.
16. **Template B/L mặc định** có thêm `{container}`: số container lấy từ barcode giờ ra
    được tới tên file.

## 11. Quyết định trong Phase 2 (2026-08-31)

17. **Năm 2 chữ số**: profile hỗ trợ `dd/mm/yy`; mốc thế kỷ **yy ≤ 49 → 20xx, còn lại
    → 19xx** (khác mặc định của Python là 00–68 → 20xx, vốn cho ra "2060" vô lý).
18. **Panel field là QDockWidget**, neo được PHẢI hoặc DƯỚI, **mặc định DƯỚI** (cột
    "Tên mới" rất dài nên bảng chính cần hết chiều ngang). Vị trí lưu vào
    `config.field_panel_area`.
19. **Log**: logger của pdfminer/pdfplumber/PIL bị hạ xuống ERROR; thêm `RepeatFilter`
    gom dòng trùng (cho qua lần đầu, lần hai báo đã gom, sau đó im). Lỗi thật (>= ERROR)
    KHÔNG bao giờ bị gom.
20. **Không dùng ký hiệu ✔/✘ trong danh sách** — không phải font Windows nào cũng có.
    Dùng chữ + màu (xanh = bắt được, đỏ = chưa).
21. **tessdata**: nút "Cài gói ngôn ngữ còn thiếu" chép từ bản Tesseract đã cài, không có
    thì tải từ kho `tesseract-ocr/tessdata`, luôn ghi vào thư mục riêng của app.

## 12. Quyết định trong Phase 3 (2026-08-31)

22. **Lọc trong vùng zonal** (`zone_filter`, `zone_filter_value`): none | label | line |
    regex. Không có bước này thì field zonal bắt cả cụm text, vô dụng trên chứng từ thật.
    Hộp thoại cảnh báo khi vùng chứa nhiều giá trị và tự gợi ý cách lọc.
23. **Key chuẩn cho tên field** (`number`, `doc_date`, `company`, `container`): hộp thoại
    tạo field gợi ý sẵn để tên field khớp token template, tránh cảnh "field so_container
    nhưng template viết {container}".
24. **Palette token bước 4** đánh dấu token chưa có field (làm mờ + nhãn), và cảnh báo khi
    template dùng token đó. `{counter}` có trong palette nhưng kèm cảnh báo phá deterministic.
25. **Cắt chữ theo từng cột**: cột đường dẫn cắt ĐẦU (giữ đuôi `…\output6-08-31`),
    cột tên file cắt GIỮA. Dùng `ElideDelegate` vì QTableView chỉ có 1 kiểu cắt chung.
26. **Learning Loop**: correction ghi ngay khi user sửa (status `new`); chỉ khi user duyệt
    đề xuất rule thì mới `approve_correction` — lúc đó mới ghi dataset kèm TEXT, và đó là
    nguồn few-shot duy nhất cho tầng 5. Rule mới luôn qua regression + tạo version mới.
27. **Watch folder trong GUI** chạy trên luồng riêng của watchdog; kết quả về GUI qua
    signal (`_WatchBridge`), không đụng widget từ luồng nền.
28. **Báo cáo CSV ghi kèm BOM UTF-8** để Excel tiếng Việt mở ra không thành rác.

## 13. Quyết định trong Phase 4 (2026-08-31)

29. **tessdata KHÔNG fallback âm thầm.** Ô cấu hình để trống -> luôn dùng
    `%APPDATA%/PDFBatchRenamer/tessdata`, tự tạo và **mồi** sẵn eng/osd/vie từ bản
    Tesseract đang dùng. Trước đây thư mục rỗng thì app lặng lẽ đọc tessdata của
    Program Files, nên người dùng cài gói `vie` vào thư mục app mà không hiểu vì sao
    vẫn báo thiếu.
30. **Điểm dừng cho lọc "sau nhãn"** (`zone_filter_stop`): tại nhãn kế tiếp / tại 2+
    khoảng trắng / theo regex. Không có nó thì lọc theo nhãn ôm hết phần còn lại của dòng.
    `LABEL_RE` phải neo đầu dòng-hoặc-sau-khoảng-trắng và không chứa chữ số, nếu không
    regex ăn lẹm vào giữa giá trị rồi cắt nhầm.
31. **Bản xem trước vùng giữ nguyên xuống dòng** — trước đây gộp thành 1 dòng nên "lấy
    dòng thứ N" trong hộp thoại khác hẳn lúc chạy thật.
32. **Không dùng ký hiệu Unicode đặc biệt** (tick, chéo, cảnh báo, mũi tên) ở BẤT KỲ đâu
    trong `src/` — dùng chữ + màu. Có test quét toàn bộ `src/` chặn tái phạm.
33. **Cột "Thư mục đích" hiển thị đường dẫn tương đối** so với output gốc; tooltip giữ
    full path. Cột đường dẫn cắt ĐẦU, cột tên file cắt GIỮA (`ElideDelegate`).
34. **Nút kiểm tra master data chạy thử bằng giá trị THẬT** lấy từ file mẫu, không chỉ
    đếm số dòng Excel — bind nhầm field vào nhầm cột phải lộ ra ngay.
35. **Đóng gói**: 2 exe trong cùng 1 thư mục onedir. Tesseract portable của bản `full`
    được chép vào cạnh exe SAU khi PyInstaller chạy, không qua `datas` — PyInstaller xếp
    lại mọi `.dll` trong datas thành binary ở thư mục gốc làm bộ DLL bị nhân đôi (+180 MB).
36. **`pdf-renamer --check`** in chẩn đoán môi trường: dùng khi hỗ trợ người dùng và khi
    kiểm chứng bản build.

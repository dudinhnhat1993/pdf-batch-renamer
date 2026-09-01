# PDF Batch Renamer — Brief cho Antigravity

## 1. Mục tiêu

Sửa và hoàn thiện dự án desktop Windows tại:

`C:\Users\Admin\Claude\Projects\PDF Batch Renamer`

Đây là ứng dụng đổi tên hàng loạt PDF chứng từ/logistics theo nội dung bên trong, không dựa vào tên file cũ:

`kéo-thả file/thư mục → đọc text/OCR → áp profile/rule → preview → sửa field nếu cần → copy/move → output/<ngày xử lý>/`

Dự án đã có v1.0, không được viết lại từ đầu hoặc phá API hiện có. Trước khi sửa, đọc:

- `CLAUDE.md`
- `README.md`
- `src/core/`
- `src/ui/`
- `tests/`
- `tools/`
- `dist/` nếu cần kiểm tra build

Tạo checkpoint/branch trước khi thay đổi. Không xóa dữ liệu người dùng trong `%APPDATA%\PDFBatchRenamer`.

## 2. Trạng thái hiện tại

Theo báo cáo v1.0:

- 610 test pass, 0 skip.
- `ruff check src tests tools` sạch.
- Có GUI và CLI.
- Có profile, Rule Editor, Visual Rule Builder, regex, zonal, barcode, metadata, OCR, optional AI fallback, master data Excel, watch folder, report, statistics, Learning Loop, provenance, dedup hash, backup, undo.
- Build:
  - `dist\PDFBatchRenamer-lite`
  - `dist\PDFBatchRenamer-full`
- Mỗi bản có:
  - `PDFBatchRenamer.exe`
  - `pdf-renamer.exe`
  - `_internal\`
- Bản full có `tesseract\`, gồm OCR và `eng/vie`.

## 3. Vấn đề cần sửa trước tiên

Người dùng đã chạy bản full trên Windows và nạp PDF `test-2.pdf`, nhưng sau khi chọn file, bảng chính không hiển thị file. Ảnh màn hình cho thấy:

- GUI mở bình thường.
- Log có dòng: `INFO Đã nạp 1 file PDF từ 1 đường dẫn`.
- Nhưng bảng queue vẫn trống.
- Panel field trống.
- Status bar vẫn không phản ánh một file đang chờ.
- Có dòng: `Đã nạp 1 file PDF. Bấm “Xem trước” để xử lý.`

Ảnh tham khảo: file ảnh đính kèm trong conversation có tên `image.jpg`/ảnh cuối. Không phụ thuộc tuyệt đối vào tên ảnh; hãy tái hiện bằng test tự động.

### Giả thuyết cần điều tra

Không được đoán rồi sửa mù. Dùng debug/log/test để xác định:

1. `set_jobs()` hoặc model queue có nhận đúng danh sách job không.
2. Có signal/slot nào cập nhật model nhưng không gọi `layoutChanged`, `beginResetModel/endResetModel`, `rowsInserted`, hoặc không giữ reference model không.
3. Có filter trạng thái đang ẩn toàn bộ job `Chờ` không.
4. Có lỗi do GUI chạy từ thư mục `dist`/PyInstaller khiến đường dẫn, config, SQLite hoặc profile load khác môi trường dev không.
5. Có exception bị nuốt sau dòng log nạp file.
6. Có race giữa worker/preview và model reset.
7. Có khác biệt giữa `_on_files_dropped`, `_on_choose_files`, `_on_choose_folder`, `set_jobs()` và đường gọi trong bản frozen.
8. Có vấn đề Qt model/view khi `QTableView` đang dùng proxy model, dock panel, hoặc resize/elide delegate.

## 4. Acceptance test bắt buộc cho lỗi không hiển thị file

Tạo test regression và kiểm tra thủ công cả source lẫn bản frozen:

### GUI test

- Nạp một PDF bằng nút `Chọn file`.
- Nạp một PDF bằng kéo-thả.
- Nạp một thư mục có PDF.
- Sau mỗi thao tác:
  - bảng có đúng số dòng;
  - tên cũ hiển thị `test-2.pdf`;
  - trạng thái là `Chờ`;
  - status bar là `Chờ: 1 · Lỗi: 0 (tổng 1)` hoặc nội dung tương đương;
  - panel field có thể trống trước khi bấm `Xem trước`, nhưng không được làm bảng biến mất;
  - không có exception bị nuốt.
- Nạp lại cùng file: xử lý theo chính sách hiện tại, không crash.
- Nạp PDF có password: vẫn hiện một dòng lỗi trong bảng, không bị biến mất.
- Nạp file không phải PDF: hiển thị cảnh báo rõ, không làm mất các file PDF hợp lệ.

### Frozen build test

Chạy trực tiếp:

```bat
cd /d "C:\Users\Admin\Claude\Projects\PDF Batch Renamer\dist\PDFBatchRenamer-full"
PDFBatchRenamer.exe
```

Nếu cần chạy GUI qua log debug, thêm tùy chọn debug tạm thời hoặc ghi log vào `%APPDATA%\PDFBatchRenamer\logs\`.

Không dùng `python -m src.app` để kết luận bản frozen hoạt động; phải test đúng `PDFBatchRenamer.exe`.

## 5. Mục tiêu nghiệp vụ với file test-2.pdf

File đính kèm `test-2.pdf` có text layer, 1 trang, khoảng 700 ký tự. Nội dung quan trọng:

```text
Nội dung
946C60716DK7PDT7 6197ICBVC2A4YP8C TAM CK PKT
YE2607006 T04.26

Thời gian
16-07-2026 22:23:43

10:21 17/7/26
VietinBank iPay
```

Người dùng muốn tên file cơ sở là:

`TAM CK PKT YE2607006 T04.26.pdf`

và muốn file được xuất vào thư mục theo ngày xử lý, ví dụ:

`<output-root>\2026-08-31\TAM CK PKT YE2607006 T04.26.pdf`

Ngày xử lý phải là ngày hệ thống lúc thực sự áp dụng/copy/move, không phải ngày chứng từ. Khi chạy vào ngày khác, dùng ngày thực tế của máy.

## 6. Cách tạo rule cho test-2.pdf

Không hardcode riêng tên file `test-2.pdf`. Phải tạo profile/rule thông qua GUI hoặc fixture rule, để áp dụng được cho các file cùng loại.

### Profile đề xuất

- Tên: `Chuyển khoản ngân hàng` hoặc `Bank Transfer`.
- Mã loại: `BANK_TRANSFER`.
- Điều kiện nhận diện:
  - chứa `VietinBank iPay`, hoặc
  - chứa `Chi tiết giao dịch` và `Nội dung`.
- Điều kiện loại trừ: không cần nếu profile đủ đặc hiệu.

### Field cần tạo

Field chính:

- key: `description` hoặc `transfer_content`
- nhãn: `Nội dung`
- bắt buộc: bật
- cách lấy: text sau nhãn `Nội dung`
- điểm dừng: tại nhãn kế tiếp `Trạng thái`, hoặc chọn dòng/regex phù hợp
- giá trị kỳ vọng:

`TAM CK PKT YE2607006 T04.26`

Cần loại bỏ hai mã tham chiếu đứng trước trên cùng đoạn:

`946C60716DK7PDT7 6197ICBVC2A4YP8C`

Không chọn toàn bộ vùng chứa các mã đó. Nếu dùng regex, ưu tiên regex có nhãn và neo cấu trúc dòng, ví dụ ý tưởng:

```regex
(?im)^Nội dung\s*\n(?:[^\n]*\s+){2}(?P<description>TAM\s+CK\s+PKT\s+YE\d{7}\s+T\d{2}\.\d{2})\s*$
```

Không ép dùng regex trên nếu layout thực tế khác; Visual Rule Builder phải cho phép bôi chọn chính xác cụm nhiều từ.

Có thể tạo thêm field tùy chọn:

- `doc_date`: lấy ngày từ `Thời gian`, chỉ lấy `16-07-2026`, bỏ giờ.
- `reference`: lấy số sau `Số tham chiếu:`.
- `bank`: `VietinBank` hoặc `TMCP A Chau`, tùy nhu cầu.

Không dùng số tài khoản, tên cá nhân hoặc số tiền trong tên file nếu không cần thiết.

### Template tên file

Template tối thiểu:

```text
{description}
```

Kết quả phải là:

```text
TAM CK PKT YE2607006 T04.26.pdf
```

Không tự động đổi thành `TAM_CK...` trừ khi profile có tùy chọn thay khoảng trắng bằng `_` bật. Người dùng yêu cầu giữ khoảng trắng trong trường hợp này.

Nếu cần thêm loại chứng từ:

```text
{doctype}_{description}
```

nhưng bản test chính phải chứng minh template chỉ `{description}` tạo đúng tên mong muốn.

## 7. Output theo ngày

Kiểm tra và sửa để workflow hoạt động đầy đủ:

1. Settings có output root, ví dụ `C:\Users\Admin\Desktop\PDF_Output`.
2. Bật `Tạo thư mục con theo ngày xử lý`.
3. Template folder mặc định `{YYYY}-{MM}-{DD}`.
4. Preview phải hiển thị thư mục đích tương đối, ví dụ `2026-08-31`.
5. Khi bấm `Áp dụng` ở chế độ Copy:
   - tạo `<output-root>\2026-08-31\`;
   - copy file sang đó;
   - giữ file gốc;
   - tên file đúng.
6. Với Move:
   - có backup và operation log;
   - Undo khôi phục được.
7. Dry-run không tạo file, không ghi dedup/provenance/counter thật.
8. Ngày xử lý lấy từ clock/timezone máy, nhất quán với cấu hình hiện tại.

Thêm acceptance test end-to-end:

```text
input\test-2.pdf
→ output\YYYY-MM-DD\TAM CK PKT YE2607006 T04.26.pdf
```

Không hardcode `2026-08-31` trong production code; test phải mock clock hoặc dùng ngày hiện tại.

## 8. Chọn nhiều chữ trong PDF

Vấn đề đã phát hiện trước đó vẫn phải được giữ đúng:

- Trong chế độ bôi chọn text, kéo chuột qua nhiều word box phải chọn được nhiều từ.
- Giá trị:

`TAM CK PKT YE2607006 T04.26`

phải có thể được chọn nguyên cụm.

- Các từ được chọn phải highlight.
- Click đơn vẫn chọn một từ.
- Kéo khung zonal là chế độ riêng, không được nhầm với text selection.
- Text layer phải hiển thị rõ ở zoom phù hợp.
- Với PDF scan, OCR word box vẫn phải hỗ trợ chọn nhiều từ nếu có confidence hợp lệ.

## 9. Kiểm tra profile/rule persistence

Vì bản frozen có thể đang đọc nhầm thư mục dữ liệu:

- Hiển thị trong `--check` và log:
  - application home;
  - config path;
  - SQLite path;
  - profiles/rule pack path;
  - output root;
  - Tesseract path;
  - tessdata path.
- Source và frozen phải dùng cùng quy tắc `%APPDATA%\PDFBatchRenamer`, trừ khi có `PDFRENAMER_HOME` override.
- Không lưu rule vào thư mục cài đặt `dist` nếu đó không phải thiết kế.
- Khi tạo profile qua GUI, đóng/mở app lại phải còn profile.
- Khi chọn `test-2.pdf`, profile mới phải match sau khi reload.

## 10. Yêu cầu debug trước khi sửa

Thực hiện theo thứ tự:

1. Đọc code liên quan đến queue/model/view và đường nạp file.
2. Tạo test tái hiện lỗi bảng trống.
3. Chạy test để chứng minh lỗi trước sửa.
4. Thêm logging có cấu trúc cho:
   - input paths;
   - discovered PDF paths;
   - job count trước/sau set_jobs;
   - model rowCount;
   - model reset/insert;
   - selected row;
   - exception traceback.
5. Sửa root cause, không chỉ gọi `viewport().update()` hoặc refresh mù.
6. Chạy test regression.
7. Chạy GUI offscreen nếu có thể.
8. Chạy bản frozen thật.

Không chấp nhận các cách sửa sau nếu không có root-cause proof:

- sleep tùy tiện;
- gọi refresh liên tục bằng timer;
- bắt exception rồi bỏ qua;
- tạo một model mới nhưng không gắn lại view;
- hardcode hiển thị `test-2.pdf`;
- bỏ qua file vì profile chưa match.

## 11. Phase thực thi cho Antigravity

### Phase A — Fix file không hiển thị

- Tái hiện bằng `test-2.pdf`.
- Fix queue/model/view.
- Thêm regression tests.
- Xác nhận GUI source và frozen full.

### Phase B — Tạo và chạy rule cho test-2.pdf

- Dùng Visual Rule Builder để tạo profile bank transfer.
- Hỗ trợ chọn nhiều chữ.
- Tạo field description.
- Template `{description}`.
- Preview đúng tên.

### Phase C — End-to-end output

- Chọn Copy.
- Chọn output root tạm.
- Preview.
- Apply.
- Xác nhận file được tạo trong thư mục ngày hiện tại và file gốc vẫn còn.
- Chạy lần hai để xác nhận dedup không làm mất dòng hoặc làm GUI trống.

### Phase D — Chất lượng phát hành

- Chạy toàn bộ pytest.
- Ruff.
- Build lite/full nếu code thay đổi ảnh hưởng build.
- Test `pdf-renamer.exe --check`.
- Test GUI frozen.
- Cập nhật README nếu hành vi/user workflow thay đổi.
- Chụp screenshot sau sửa nếu cần.
- Không tag v1.1 cho đến khi acceptance test pass.

## 12. Báo cáo bắt buộc sau khi hoàn thành

Báo cáo ngắn nhưng có bằng chứng:

1. Root cause tại sao nạp 1 file nhưng bảng trống.
2. File nào đã sửa.
3. Test tái hiện trước sửa và test regression sau sửa.
4. Kết quả `pytest` và `ruff`.
5. Kết quả chạy GUI frozen.
6. Kết quả end-to-end với `test-2.pdf`:
   - profile;
   - field description;
   - tên preview;
   - output path;
   - file gốc còn hay không.
7. Nếu chưa thể sửa, phải nói rõ blocker và log/traceback, không tuyên bố hoàn thành dựa trên code chưa chạy thật.

## 13. Lưu ý bảo mật

`test-2.pdf` có thông tin giao dịch ngân hàng, tài khoản, tên người và số tiền. Không bật AI/cloud để xử lý file này trong test. AI phải giữ tắt. Không đưa nội dung PDF vào log đầy đủ; chỉ log field cần thiết hoặc masking dữ liệu nhạy cảm.

Bắt đầu bằng việc xác định root cause lỗi bảng trống và tạo regression test trước khi sửa code.
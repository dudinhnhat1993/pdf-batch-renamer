# Bàn giao thiết kế → PySide6

Nguồn thiết kế: `PDF Batch Renamer.dc.html` (mockup 6 màn hình, canvas 1440×900).

```
handoff/
├─ design/theme_tokens.json          (1) bảng mã màu + metrics, nguồn duy nhất của sự thật
└─ src/ui/
   ├─ theme.py                       loader: JSON → QSS, đổi theme không cần khởi động lại
   ├─ main_window.py                 Màn hình 1: toolbar, queue table, inspector, dock, log, status bar
   ├─ styles/
   │  ├─ theme.qss                   (2) template dùng @token@ — CHỈ sửa file này
   │  ├─ theme_dark.qss              sinh tự động để review
   │  └─ theme_light.qss             sinh tự động để review
   └─ widgets/
      ├─ status_badge.py             delegate vẽ badge pill trong cột Trạng thái
      ├─ inspector_panel.py          field rows, sửa 1-chạm → phát signal học tập
      └─ pdf_preview_dock.py         canvas retina 2×, hover/select từ, Ctrl+click, zonal drag
```

## Khởi động

```python
from PySide6.QtWidgets import QApplication
from src.ui.theme import Theme
from src.ui.main_window import MainWindow

app = QApplication(sys.argv)
theme = Theme.load(mode="dark")     # "light" cho theme sáng
theme.apply(app)
win = MainWindow(theme, queue_model)
win.show()
```

Đổi theme lúc chạy: `theme.set_mode("light"); theme.apply(app)` — QSS được render lại toàn bộ, các widget tự vẽ (badge, canvas PDF) đọc `theme.palette` nên cập nhật ngay sau `update()`.

## Quy ước cần giữ

- **Không hardcode màu trong Python.** Mọi màu lấy qua `theme.color("...")` hoặc token trong QSS. `theme.py` sẽ raise `KeyError` nếu QSS tham chiếu token không tồn tại — lỗi lộ ngay lúc dev thay vì ra cửa sổ nửa vời.
- **Biến thể nút = dynamic property**, không phải objectName: `variant="primary" | "secondary" | "accent"`, `danger="true"`, `state="running|done"`, `selected="true"`. Sau khi đổi property phải gọi `repolish(widget)`.
- **Phím tắt nằm trong tooltip**, không nằm trong label nút — đó là điều kiện để toolbar 50px vừa 1440px mà nhóm Cài đặt/Hướng dẫn vẫn ghim phải.
- **Badge trạng thái vẽ bằng delegate**, QSS không vẽ được pill trong cell. Item lưu mã trạng thái ở `STATUS_ROLE`.
- **Canvas PDF**: rasterise ở `devicePixelRatio × 2.0`, `QImage.setDevicePixelRatio()` trước khi tạo QPixmap — bỏ bước này là mất độ nét.

## Còn thiếu, cần Squad bổ sung

- `src/ui/wizard/` (Màn hình 2), `profile_manager.py` (3), `settings_dialog.py` (4), `stats_view.py` (5), `learning_dialog.py` (6) — QSS đã có sẵn selector cho tất cả (`#WizardHeader`, `#WizardStepDot`, `#TokenChip`, `#SuggestionCard`, `#DropZone`, `#ProfileList`, `QTabBar`, `#DialogHeader/#DialogFooter`).
- Bộ icon SVG 16px trong resource `:/icons/` — tên dùng trong `main_window.py`: `file-plus, folder, trash, search, play, stop, checklist, wand, panel-right, gear, bulb`.
- `InspectorPanel.show_row()` đang `NotImplementedError` — controller cần map row → danh sách field rồi gọi `show_fields()`.
- Font `Be Vietnam Pro` và `JetBrains Mono` đặt trong `assets/fonts/*.ttf`; `Theme._register_fonts()` tự nạp.

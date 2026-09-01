"""Hộp thoại Cài đặt — toàn bộ cấu hình sửa được ở đây, không cần đụng config.json."""

from __future__ import annotations

import logging
import threading

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..core.config import AppConfig, delete_api_key, get_api_key, save_config, set_api_key
from ..core.models import Profile
from ..core.ocr import OcrEngine, find_tesseract, install_language_pack
from .icons import get_app_icon

logger = logging.getLogger(__name__)

AI_PRESETS = {
    "— Chọn nhà cung cấp —": "",
    "DeepSeek": "https://api.deepseek.com/v1",
    "OpenAI": "https://api.openai.com/v1",
    "Ollama (chạy trên máy)": "http://localhost:11434/v1",
    "LM Studio (chạy trên máy)": "http://localhost:1234/v1",
}

AI_WARNING = (
    "LƯU Ý: bật AI đồng nghĩa NỘI DUNG CHỨNG TỪ (số tiền, tên khách hàng, số B/L) được gửi "
    "tới dịch vụ bên ngoài. Muốn an toàn tuyệt đối, dùng preset Ollama hoặc LM Studio — "
    "hai cái này chạy ngay trên máy, dữ liệu không rời khỏi máy."
)


def _browse_row(line: QLineEdit, on_click) -> QWidget:
    """Ô nhập kèm nút chọn đường dẫn."""
    box = QWidget()
    layout = QHBoxLayout(box)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(line, 1)
    button = QPushButton("Chọn…")
    button.clicked.connect(on_click)
    layout.addWidget(button)
    return box




class SettingsDialog(QDialog):
    """Đọc AppConfig vào form, ghi ngược lại khi bấm Lưu."""

    def __init__(self, config: AppConfig, profiles: list[Profile], parent=None) -> None:
        super().__init__(parent)
        self.setWindowIcon(get_app_icon())
        self.setWindowTitle("Cài đặt")
        self.resize(720, 620)
        self.config = config
        self.profiles = profiles
        self._missing_languages: list[str] = []

        self.tabs = QTabWidget(self)
        self.tabs.addTab(self._tab_general(), "Chung")
        self.tabs.addTab(self._tab_ocr(), "OCR && Barcode")
        self.tabs.addTab(self._tab_ai(), "AI (tùy chọn)")
        self.tabs.addTab(self._tab_watch(), "Watch folder")
        self.tabs.currentChanged.connect(self._on_tab_changed)
        self._ocr_checked = False
        self._ai_key_loaded = False
        tabs = self.tabs

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        save_btn = buttons.button(QDialogButtonBox.StandardButton.Save)
        save_btn.setText("Lưu")
        save_btn.setProperty("variant", "primary")
        save_btn.setMinimumWidth(90)
        cancel_btn = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        cancel_btn.setText("Hủy")
        cancel_btn.setProperty("variant", "secondary")
        cancel_btn.setMinimumWidth(80)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(self._build_preset_bar())
        layout.addWidget(tabs, 1)
        layout.addWidget(buttons)

        self._load()

    # ------------------------------------------------------------- Presets
    def _build_preset_bar(self) -> QWidget:
        box = QGroupBox("Cấu hình nhanh (Khuyên dùng)")
        layout = QHBoxLayout(box)
        layout.setContentsMargins(10, 8, 10, 8)

        btn_default = QPushButton("Mặc định chuẩn")
        btn_default.setToolTip("Cấu hình tối ưu: tự nhận diện chứng từ, lưu trữ an toàn, gom thư mục ngày.")
        btn_default.clicked.connect(lambda: self._apply_quick_preset("default"))

        btn_fast = QPushButton("Siêu tốc (PDF chuẩn)")
        btn_fast.setToolTip("Tắt OCR quét ảnh để xử lý hàng nghìn hóa đơn điện tử / PDF có sẵn text trong vài giây.")
        btn_fast.clicked.connect(lambda: self._apply_quick_preset("fast"))

        btn_deep = QPushButton("Quét sâu (Scan & Barcode)")
        btn_deep.setToolTip("Bật nhận dạng ký tự quang học OCR tiếng Việt và quét mã vạch cho tài liệu scan, ảnh chụp.")
        btn_deep.clicked.connect(lambda: self._apply_quick_preset("deep"))

        layout.addWidget(btn_default)
        layout.addWidget(btn_fast)
        layout.addWidget(btn_deep)
        return box

    def _apply_quick_preset(self, preset_name: str) -> None:
        if preset_name == "default":
            self.mode.setCurrentIndex(0)
            self.subfolder_enabled.setChecked(True)
            self.subfolder_pattern.setText("{YYYY}-{MM}-{DD}")
            self.strip_accents.setChecked(False)
            self.max_name_length.setValue(120)
            self.workers.setValue(4)
            self.timeout_seconds.setValue(30)
            self.dedup_enabled.setChecked(True)
            self.ocr_enabled.setChecked(True)
            self.ocr_min_chars.setValue(50)
            self.ocr_max_pages.setValue(3)
            self.ocr_dpi.setValue(300)
            self.barcode_enabled.setChecked(True)
            self.barcode_max_pages.setValue(3)
            QMessageBox.information(
                self, "Cấu hình nhanh",
                "Đã áp dụng Preset: [Mặc định chuẩn]\n\n"
                "- Tự nhận diện và trích xuất mọi loại chứng từ\n"
                "- Tự động gom file vào thư mục theo ngày\n"
                "- Chế độ Copy an toàn & Chống xử lý trùng lặp"
            )
        elif preset_name == "fast":
            self.ocr_enabled.setChecked(False)
            self.barcode_enabled.setChecked(False)
            self.workers.setValue(6)
            self.timeout_seconds.setValue(10)
            QMessageBox.information(
                self, "Cấu hình nhanh",
                "Đã áp dụng Preset: [Siêu tốc (PDF chuẩn)]\n\n"
                "- Tắt OCR & Barcode để đạt tốc độ xử lý tối đa\n"
                "- Thích hợp cho hóa đơn điện tử, hợp đồng, phiếu PDF văn phòng"
            )
        elif preset_name == "deep":
            self.ocr_enabled.setChecked(True)
            self.ocr_min_chars.setValue(30)
            self.ocr_max_pages.setValue(5)
            self.ocr_dpi.setValue(300)
            self.barcode_enabled.setChecked(True)
            self.barcode_max_pages.setValue(5)
            self.workers.setValue(3)
            self.timeout_seconds.setValue(60)
            QMessageBox.information(
                self, "Cấu hình nhanh",
                "Đã áp dụng Preset: [Quét sâu (Scan & Barcode)]\n\n"
                "- Bật OCR quét kỹ tới 5 trang đầu\n"
                "- Nhận dạng mã vạch, QR Code và số container ISO"
            )

    TAB_GENERAL, TAB_OCR, TAB_AI, TAB_WATCH = range(4)

    def show_tab(self, index: int) -> None:
        self.tabs.setCurrentIndex(index)

    # ------------------------------------------------------------- các tab

    def _tab_general(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)

        self.output_root = QLineEdit()
        form.addRow("Thư mục output:", _browse_row(self.output_root, self._pick_output))

        self.subfolder_enabled = QCheckBox("Tạo thư mục con theo ngày xử lý")
        self.subfolder_pattern = QLineEdit()
        self.subfolder_pattern.setPlaceholderText("{YYYY}-{MM}-{DD}  hoặc  {YYYY}/{MM}")
        form.addRow(self.subfolder_enabled)
        form.addRow("Mẫu thư mục con:", self.subfolder_pattern)

        self.mode = QComboBox()
        self.mode.addItem("Copy — giữ nguyên file gốc (khuyến nghị)", "copy")
        self.mode.addItem("Move — chuyển file đi, có backup", "move")
        form.addRow("Chế độ:", self.mode)

        self.strip_accents = QCheckBox("Bỏ dấu tiếng Việt trong tên file")
        self.strip_accents.setToolTip(
            "Bật khi phần mềm kế toán cũ không đọc được tên file có dấu."
        )
        form.addRow(self.strip_accents)

        self.max_name_length = QSpinBox()
        self.max_name_length.setRange(20, 255)
        form.addRow("Giới hạn độ dài tên file:", self.max_name_length)

        self.workers = QSpinBox()
        self.workers.setRange(1, 32)
        form.addRow("Số luồng xử lý:", self.workers)

        self.timeout_seconds = QSpinBox()
        self.timeout_seconds.setRange(10, 3600)
        self.timeout_seconds.setSuffix(" giây")
        form.addRow("Timeout mỗi file:", self.timeout_seconds)

        self.dedup_enabled = QCheckBox("Kiểm tra file đã xử lý (chống trùng theo nội dung)")
        form.addRow(self.dedup_enabled)

        self.backup_retention_days = QSpinBox()
        self.backup_retention_days.setRange(0, 3650)
        self.backup_retention_days.setSuffix(" ngày (0 = giữ mãi)")
        form.addRow("Giữ backup:", self.backup_retention_days)

        self.passwords = QPlainTextEdit()
        self.passwords.setPlaceholderText("Mỗi dòng 1 mật khẩu, thử lần lượt từ trên xuống")
        self.passwords.setFixedHeight(70)
        form.addRow("Mật khẩu PDF:", self.passwords)

        self.masterdata_source = QLineEdit()
        form.addRow(
            "File Excel master data:", _browse_row(self.masterdata_source, self._pick_masterdata)
        )

        self.company_dictionary = QLineEdit()
        self.company_dictionary.setPlaceholderText("Để trống = dùng từ điển mặc định của app")
        form.addRow(
            "Từ điển tên công ty:", _browse_row(self.company_dictionary, self._pick_dictionary)
        )

        self.theme_mode = QComboBox()
        self.theme_mode.addItem("Sáng — Nền sáng, rõ nét, dễ nhìn (Khuyên dùng)", "light")
        self.theme_mode.addItem("Tối — Dark Mode", "dark")
        form.addRow("Giao diện màu sắc:", self.theme_mode)
        return page

    def _tab_ocr(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)

        self.ocr_enabled = QCheckBox("Bật OCR cho PDF scan")
        form.addRow(self.ocr_enabled)

        self.ocr_min_chars = QSpinBox()
        self.ocr_min_chars.setRange(0, 10000)
        self.ocr_min_chars.setToolTip("Ít hơn ngần này ký tự thì coi là bản scan và chuyển sang OCR")
        form.addRow("Ngưỡng coi là bản scan:", self.ocr_min_chars)

        self.ocr_max_pages = QSpinBox()
        self.ocr_max_pages.setRange(1, 50)
        form.addRow("Số trang đầu đem OCR:", self.ocr_max_pages)

        self.ocr_dpi = QSpinBox()
        self.ocr_dpi.setRange(72, 600)
        form.addRow("DPI khi render trang:", self.ocr_dpi)

        self.ocr_languages = QLineEdit()
        self.ocr_languages.setPlaceholderText("vie+eng")
        form.addRow("Ngôn ngữ:", self.ocr_languages)

        self.tesseract_path = QLineEdit()
        self.tesseract_path.setPlaceholderText("Để trống = tự dò")
        form.addRow("tesseract.exe:", _browse_row(self.tesseract_path, self._pick_tesseract))

        self.tessdata_path = QLineEdit()
        self.tessdata_path.setPlaceholderText("Để trống = dùng thư mục tessdata riêng của app")
        form.addRow("Thư mục tessdata:", _browse_row(self.tessdata_path, self._pick_tessdata))

        self.ocr_status = QLabel()
        self.ocr_status.setWordWrap(True)
        self.ocr_status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        check = QPushButton("Kiểm tra Tesseract")
        check.clicked.connect(self._check_tesseract)
        self.install_lang = QPushButton("Cài gói ngôn ngữ còn thiếu")
        self.install_lang.clicked.connect(self._install_missing_languages)
        self.install_lang.setEnabled(False)

        button_row = QWidget()
        button_layout = QVBoxLayout(button_row)
        button_layout.setContentsMargins(0, 0, 0, 0)
        button_layout.addWidget(check)
        button_layout.addWidget(self.install_lang)
        form.addRow(button_row, self.ocr_status)

        self.barcode_enabled = QCheckBox("Bật quét barcode/QR")
        form.addRow(self.barcode_enabled)

        self.barcode_max_pages = QSpinBox()
        self.barcode_max_pages.setRange(1, 50)
        form.addRow("Số trang đầu quét mã:", self.barcode_max_pages)

        from ..core.barcode import AVAILABLE, UNAVAILABLE_REASON

        status = QLabel(
            "Sẵn sàng." if AVAILABLE else UNAVAILABLE_REASON or "Không dùng được pyzbar."
        )
        status.setWordWrap(True)
        form.addRow("Trạng thái barcode:", status)
        return page

    def _tab_ai(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        warning = QLabel(AI_WARNING)
        warning.setWordWrap(True)
        warning.setStyleSheet("QLabel { background: rgba(255,180,0,40); padding: 8px; }")
        layout.addWidget(warning)

        form = QFormLayout()
        self.ai_enabled = QCheckBox("Bật AI fallback (tầng 5) trên toàn app")
        self.ai_enabled.setToolTip(
            "Vẫn phải bật riêng cho từng profile thì tầng 5 mới chạy. "
            "AI chỉ chạy khi 4 tầng rule đã không tìm đủ field bắt buộc."
        )
        form.addRow(self.ai_enabled)

        self.ai_preset = QComboBox()
        for name in AI_PRESETS:
            self.ai_preset.addItem(name)
        self.ai_preset.currentTextChanged.connect(self._apply_preset)
        form.addRow("Nhà cung cấp:", self.ai_preset)

        self.ai_base_url = QLineEdit()
        form.addRow("Base URL:", self.ai_base_url)

        self.ai_model = QLineEdit()
        self.ai_model.setPlaceholderText("vd deepseek-chat, gpt-4o-mini, qwen2.5:7b")
        form.addRow("Model:", self.ai_model)

        self.ai_api_key = QLineEdit()
        self.ai_api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.ai_api_key.setPlaceholderText("Lưu trong Windows Credential Manager")
        clear_key = QPushButton("Xóa key")
        clear_key.clicked.connect(self._clear_api_key)
        key_row = QWidget()
        key_layout = QHBoxLayout(key_row)
        key_layout.setContentsMargins(0, 0, 0, 0)
        key_layout.addWidget(self.ai_api_key, 1)
        key_layout.addWidget(clear_key)
        form.addRow("API key:", key_row)

        self.ai_timeout = QSpinBox()
        self.ai_timeout.setRange(5, 600)
        self.ai_timeout.setSuffix(" giây")
        form.addRow("Timeout:", self.ai_timeout)

        self.ai_max_chars = QSpinBox()
        self.ai_max_chars.setRange(500, 100000)
        self.ai_max_chars.setSingleStep(500)
        form.addRow("Số ký tự gửi tối đa:", self.ai_max_chars)

        layout.addLayout(form)

        self.ai_status = QLabel()
        self.ai_status.setWordWrap(True)
        test = QPushButton("Thử kết nối (gửi 1 câu ngắn)")
        test.setToolTip(
            "Gửi một câu rất ngắn tới model để kiểm tra base URL / API key / tên model. "
            "KHÔNG gửi nội dung chứng từ nào."
        )
        test.clicked.connect(self._test_ai)
        layout.addWidget(test)
        layout.addWidget(self.ai_status)

        note = QLabel(
            "App chỉ gửi TEXT đã trích, không gửi ảnh trang. Mọi field AI trả về đều phải "
            "qua rule validate của profile; không đạt thì bị loại bỏ."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch(1)
        return page

    def _test_ai(self) -> None:
        """Gọi thật 1 lần với nội dung vô hại để người dùng biết cấu hình đã đúng chưa."""
        from ..core.ai_client import AiClient, AiSettings

        base_url = self.ai_base_url.text().strip()
        model = self.ai_model.text().strip()
        if not base_url or not model:
            self.ai_status.setText("Cần điền cả Base URL lẫn Model trước khi thử.")
            self.ai_status.setStyleSheet("QLabel { color: #9a6700; }")
            return

        client = AiClient(
            AiSettings(
                base_url=base_url,
                model=model,
                api_key=self.ai_api_key.text().strip(),
                timeout=min(self.ai_timeout.value(), 30),
            )
        )
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            reply = client.complete(
                [{"role": "user", "content": "Tra loi dung 1 tu: OK"}]
            )
        finally:
            QApplication.restoreOverrideCursor()

        if reply:
            self.ai_status.setText(f"OK — model trả lời: {reply.strip()[:120]}")
            self.ai_status.setStyleSheet("QLabel { color: #1a7f37; }")
        else:
            self.ai_status.setText(
                "KHÔNG gọi được. Kiểm tra Base URL, API key, tên model, và xem log để biết "
                "chi tiết. Nếu dùng Ollama/LM Studio thì nhớ bật server trước."
            )
            self.ai_status.setStyleSheet("QLabel { color: #cf222e; }")

    def _tab_watch(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)

        self.watch_enabled = QCheckBox("Bật theo dõi thư mục")
        form.addRow(self.watch_enabled)

        self.watch_folder = QLineEdit()
        form.addRow("Thư mục theo dõi:", _browse_row(self.watch_folder, self._pick_watch))

        self.watch_stable = QSpinBox()
        self.watch_stable.setRange(1, 60)
        self.watch_stable.setSuffix(" giây")
        self.watch_stable.setToolTip("Chờ kích thước file đứng yên ngần này giây rồi mới xử lý")
        form.addRow("Chờ file ổn định:", self.watch_stable)

        self.watch_profile = QComboBox()
        self.watch_profile.addItem("Tự nhận diện (khuyến nghị)", "")
        for p in self.profiles:
            self.watch_profile.addItem(p.name, p.id)
        form.addRow("Ép dùng profile:", self.watch_profile)

        note = QLabel(
            "File rơi vào thư mục này được xử lý ngay, KHÔNG qua màn hình Preview. "
            "File lỗi vẫn được đưa vào thư mục cách ly như thường."
        )
        note.setWordWrap(True)
        form.addRow(note)
        return page

    # ---------------------------------------------------------- nạp / lưu

    def _load(self) -> None:
        c = self.config
        self.output_root.setText(c.output_root)
        self.subfolder_enabled.setChecked(c.subfolder_enabled)
        self.subfolder_pattern.setText(c.subfolder_pattern)
        self.mode.setCurrentIndex(0 if c.mode == "copy" else 1)
        self.strip_accents.setChecked(c.strip_accents)
        self.max_name_length.setValue(c.max_name_length)
        self.workers.setValue(c.workers)
        self.timeout_seconds.setValue(c.timeout_seconds)
        self.dedup_enabled.setChecked(c.dedup_enabled)
        self.backup_retention_days.setValue(c.backup_retention_days)
        self.passwords.setPlainText("\n".join(c.passwords))
        self.masterdata_source.setText(c.masterdata_source)
        self.company_dictionary.setText(c.company_dictionary)
        idx_theme = self.theme_mode.findData(c.theme or "light")
        self.theme_mode.setCurrentIndex(max(0, idx_theme))

        self.ocr_enabled.setChecked(c.ocr.enabled)
        self.ocr_min_chars.setValue(c.ocr.min_chars)
        self.ocr_max_pages.setValue(c.ocr.max_pages)
        self.ocr_dpi.setValue(c.ocr.dpi)
        self.ocr_languages.setText(c.ocr.languages)
        self.tesseract_path.setText(c.ocr.tesseract_path)
        self.tessdata_path.setText(c.ocr.tessdata_path)
        self.barcode_enabled.setChecked(c.barcode.enabled)
        self.barcode_max_pages.setValue(c.barcode.max_pages)

        self.ai_enabled.setChecked(c.ai.enabled)
        self.ai_base_url.setText(c.ai.base_url)
        self.ai_model.setText(c.ai.model)
        self.ai_timeout.setValue(c.ai.timeout)
        self.ai_max_chars.setValue(c.ai.max_chars)
        self.watch_enabled.setChecked(c.watch.enabled)
        self.watch_folder.setText(c.watch.folder)
        self.watch_stable.setValue(c.watch.stable_seconds)
        index = self.watch_profile.findData(c.watch.pinned_profile)
        self.watch_profile.setCurrentIndex(max(0, index))

        # Không tải nặng khi khởi tạo — để giao diện mở lên tức thì trong 0.01s

    def _on_tab_changed(self, index: int) -> None:
        if index == self.TAB_OCR and not self._ocr_checked:
            self._ocr_checked = True
            self._check_tesseract()
        elif index == self.TAB_AI and not self._ai_key_loaded:
            self._ai_key_loaded = True
            self._load_api_key_async()

    def _load_api_key_async(self) -> None:
        def worker():
            try:
                key = get_api_key()
                QTimer.singleShot(0, lambda: self.ai_api_key.setText(key))
            except Exception:
                pass
        threading.Thread(target=worker, daemon=True).start()

    def _save(self) -> None:
        c = self.config
        if not self.output_root.text().strip():
            QMessageBox.warning(self, "Thiếu thông tin", "Chưa chọn thư mục output.")
            return

        c.output_root = self.output_root.text().strip()
        c.subfolder_enabled = self.subfolder_enabled.isChecked()
        c.subfolder_pattern = self.subfolder_pattern.text().strip() or "{YYYY}-{MM}-{DD}"
        c.mode = self.mode.currentData()
        c.strip_accents = self.strip_accents.isChecked()
        c.max_name_length = self.max_name_length.value()
        c.workers = self.workers.value()
        c.timeout_seconds = self.timeout_seconds.value()
        c.dedup_enabled = self.dedup_enabled.isChecked()
        c.backup_retention_days = self.backup_retention_days.value()
        c.passwords = [p for p in self.passwords.toPlainText().splitlines() if p]
        c.masterdata_source = self.masterdata_source.text().strip()
        c.company_dictionary = self.company_dictionary.text().strip()
        new_theme = self.theme_mode.currentData() or "light"
        old_theme = getattr(c, "theme", "light")
        c.theme = new_theme
        if old_theme != new_theme and self.parent() and hasattr(self.parent(), "_apply_theme"):
            self.parent()._apply_theme(new_theme)

        c.ocr.enabled = self.ocr_enabled.isChecked()
        c.ocr.min_chars = self.ocr_min_chars.value()
        c.ocr.max_pages = self.ocr_max_pages.value()
        c.ocr.dpi = self.ocr_dpi.value()
        c.ocr.languages = self.ocr_languages.text().strip() or "vie+eng"
        c.ocr.tesseract_path = self.tesseract_path.text().strip()
        c.ocr.tessdata_path = self.tessdata_path.text().strip()
        c.barcode.enabled = self.barcode_enabled.isChecked()
        c.barcode.max_pages = self.barcode_max_pages.value()

        c.ai.enabled = self.ai_enabled.isChecked()
        c.ai.base_url = self.ai_base_url.text().strip()
        c.ai.model = self.ai_model.text().strip()
        c.ai.timeout = self.ai_timeout.value()
        c.ai.max_chars = self.ai_max_chars.value()

        c.watch.enabled = self.watch_enabled.isChecked()
        c.watch.folder = self.watch_folder.text().strip()
        c.watch.stable_seconds = self.watch_stable.value()
        c.watch.pinned_profile = self.watch_profile.currentData() or ""

        # API key KHÔNG bao giờ vào config.json — chỉ đi qua Credential Manager
        key = self.ai_api_key.text().strip()
        if key and not set_api_key(key):
            QMessageBox.warning(
                self, "Không lưu được API key",
                "Windows Credential Manager không phản hồi. AI sẽ không dùng được key này.",
            )

        save_config(c)
        self.accept()

    # -------------------------------------------------------------- tiện ích

    def _pick_output(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Chọn thư mục output", self.output_root.text())
        if path:
            self.output_root.setText(path)

    def _pick_watch(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Chọn thư mục theo dõi", self.watch_folder.text())
        if path:
            self.watch_folder.setText(path)

    def _pick_masterdata(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Chọn file Excel", "", "Excel (*.xlsx *.xlsm)")
        if path:
            self.masterdata_source.setText(path)

    def _pick_dictionary(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Chọn từ điển", "", "JSON (*.json)")
        if path:
            self.company_dictionary.setText(path)

    def _pick_tesseract(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Chọn tesseract.exe", "", "Chương trình (*.exe)")
        if path:
            self.tesseract_path.setText(path)
            self._check_tesseract()

    def _pick_tessdata(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Chọn thư mục tessdata")
        if path:
            self.tessdata_path.setText(path)
            self._check_tesseract()

    def _wanted_languages(self) -> list[str]:
        raw = self.ocr_languages.text().strip() or "vie+eng"
        return [code.strip() for code in raw.split("+") if code.strip()]

    def _check_tesseract(self) -> None:
        """Kiểm tra Tesseract chạy ngầm trong Worker Thread để không khóa giao diện."""
        self.ocr_status.setText("Đang kiểm tra Tesseract…")
        tess_path = self.tesseract_path.text().strip()
        langs_text = self.ocr_languages.text().strip() or "vie+eng"
        dpi_val = self.ocr_dpi.value()
        tessdata_p = self.tessdata_path.text().strip()
        wanted = self._wanted_languages()

        def worker():
            exe = find_tesseract(tess_path)
            if not exe:
                def on_not_found():
                    self.install_lang.setEnabled(False)
                    self.ocr_status.setText(
                        "Chưa tìm thấy Tesseract. PDF có sẵn text vẫn xử lý bình thường; "
                        "chỉ PDF scan là không đọc được."
                    )
                QTimer.singleShot(0, on_not_found)
                return

            engine = OcrEngine(tess_path, langs_text, dpi_val, tessdata_p)
            try:
                langs = engine.available_languages()
            except Exception:
                langs = []
            missing = [c for c in wanted if c not in langs]

            def on_done():
                self._missing_languages = missing
                used = engine.tessdata or "(mặc định của Tesseract)"
                lines = [
                    f"tesseract.exe: {exe}",
                    f"Thư mục tessdata đang dùng: {used}",
                    f"Ngôn ngữ có sẵn: {', '.join(langs) or 'không đọc được'}",
                ]
                if missing:
                    lines.append(
                        "THIẾU GÓI: "
                        + ", ".join(missing)
                        + " — bấm “Cài gói ngôn ngữ còn thiếu” bên trái."
                    )
                else:
                    lines.append("OK — đủ gói ngôn ngữ đang cấu hình.")
                self.ocr_status.setText("\n".join(lines))
                self.ocr_status.setStyleSheet(
                    "QLabel { color: %s; }" % ("#9a6700" if missing else "#1a7f37")
                )
                self.install_lang.setEnabled(bool(missing))

            QTimer.singleShot(0, on_done)

        threading.Thread(target=worker, daemon=True).start()

    def _install_missing_languages(self) -> None:
        """Cài gói còn thiếu vào tessdata riêng của app — không cần quyền admin."""
        missing = list(getattr(self, "_missing_languages", []))
        if not missing:
            return

        target = self.tessdata_path.text().strip() or None
        exe = find_tesseract(self.tesseract_path.text().strip())
        self.install_lang.setEnabled(False)
        self.install_lang.setText("Đang cài…")
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        results: list[str] = []
        try:
            for code in missing:
                ok, message = install_language_pack(code, target, exe)
                results.append(("OK — " if ok else "LỖI — ") + message)
        finally:
            QApplication.restoreOverrideCursor()
            self.install_lang.setText("Cài gói ngôn ngữ còn thiếu")

        self._check_tesseract()
        QMessageBox.information(self, "Cài gói ngôn ngữ", "\n\n".join(results))

    def _apply_preset(self, name: str) -> None:
        url = AI_PRESETS.get(name, "")
        if url:
            self.ai_base_url.setText(url)

    def _clear_api_key(self) -> None:
        delete_api_key()
        self.ai_api_key.clear()
        QMessageBox.information(self, "Đã xóa", "API key đã bị xóa khỏi Credential Manager.")

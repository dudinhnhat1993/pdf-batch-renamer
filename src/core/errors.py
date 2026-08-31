"""Cây exception nghiệp vụ của app. Mọi lỗi có thể đoán trước đều kế thừa PdfRenamerError."""

from __future__ import annotations


class PdfRenamerError(Exception):
    """Lỗi nghiệp vụ gốc — luôn có thông điệp tiếng Việt hiển thị được cho user."""

    #: Mã lý do ngắn, dùng để ghi vào file .txt trong thư mục cách ly
    code: str = "unknown"


class PdfOpenError(PdfRenamerError):
    """Không mở được file PDF (hỏng, không phải PDF, thiếu quyền)."""

    code = "pdf-open-failed"


class PasswordProtectedError(PdfOpenError):
    """PDF có mật khẩu và không password nào trong Settings mở được."""

    code = "password-protected"


class ExtractionError(PdfRenamerError):
    """Pipeline chạy xong nhưng vẫn thiếu field bắt buộc."""

    code = "missing-required-field"

    def __init__(self, message: str, missing: list[str] | None = None) -> None:
        super().__init__(message)
        self.missing = missing or []


class ProfileError(PdfRenamerError):
    """Profile sai cấu trúc hoặc không load được."""

    code = "profile-invalid"


class TemplateError(PdfRenamerError):
    """Template đặt tên tham chiếu token không tồn tại hoặc cú pháp sai."""

    code = "template-invalid"


class ConfigError(PdfRenamerError):
    """Cấu hình thiếu hoặc sai — CLI trả exit code 2 khi gặp lỗi này."""

    code = "config-invalid"


class OcrUnavailableError(PdfRenamerError):
    """Cần OCR nhưng không tìm thấy Tesseract."""

    code = "ocr-unavailable"


class TimeoutError_(PdfRenamerError):
    """Xử lý 1 file vượt quá timeout cấu hình."""

    code = "timeout"


class MasterDataError(PdfRenamerError):
    """Không tra cứu được file Excel master data (thiếu file, khóa, sai tên cột)."""

    code = "masterdata-unavailable"

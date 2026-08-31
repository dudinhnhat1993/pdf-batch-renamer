"""Bọc Tesseract: tự dò tesseract.exe, OCR 1 trang thành text + bbox từng từ.

Tầng 0 gọi module này khi text layer quá ít ký tự (PDF scan).
Bản build 'full' ở Phase 4 bundle Tesseract portable — _bundled_paths() lo phần đó.
"""

from __future__ import annotations

import logging
import os
import shutil
import sys
from functools import lru_cache
from pathlib import Path

from .models import PageText, Word

logger = logging.getLogger(__name__)

_WINDOWS_CANDIDATES = [
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
]


def _bundled_paths() -> list[Path]:
    """Tesseract đi kèm trong bản build full (PyInstaller onedir hoặc onefile)."""
    roots: list[Path] = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        roots.append(Path(meipass))
    roots.append(Path(sys.argv[0]).resolve().parent)
    roots.append(Path(__file__).resolve().parents[2])
    return [r / "tesseract" / "tesseract.exe" for r in roots]


@lru_cache(maxsize=8)
def find_tesseract(configured: str = "") -> str:
    """Tìm tesseract.exe theo thứ tự: cấu hình tay -> bundle -> PATH -> thư mục cài mặc định."""
    if configured and Path(configured).exists():
        return configured
    for cand in _bundled_paths():
        if cand.exists():
            return str(cand)
    found = shutil.which("tesseract")
    if found:
        return found
    for cand in _WINDOWS_CANDIDATES:
        if Path(cand).exists():
            return cand
    local = os.environ.get("LOCALAPPDATA")
    if local:
        cand = Path(local) / "Programs" / "Tesseract-OCR" / "tesseract.exe"
        if cand.exists():
            return str(cand)
    return ""


# Gói đi kèm mọi bản cài Tesseract — chép sang thư mục của app để nó không bao giờ rỗng
# Bản full bundle sẵn cả vie -> mồi luôn để lần đầu mở là OCR tiếng Việt được ngay
SEED_LANGUAGES = ("eng.traineddata", "osd.traineddata", "vie.traineddata")


def ensure_app_tessdata(exe: str = "") -> Path:
    """Dựng thư mục tessdata riêng của app và mồi sẵn gói cơ bản từ bản Tesseract đã cài.

    Thư mục tessdata trong Program Files cần quyền admin mới ghi được, nên gói ngôn ngữ
    bổ sung (vd 'vie') phải nằm ở đây.
    """
    from .config import tessdata_dir

    target = tessdata_dir()
    target.mkdir(parents=True, exist_ok=True)
    if any(target.glob("*.traineddata")):
        return target

    source = bundled_tessdata_of(exe or find_tesseract())
    if source is None:
        return target
    for name in SEED_LANGUAGES:
        candidate = source / name
        if not candidate.exists():
            continue
        try:
            shutil.copy2(candidate, target / name)
            logger.info("Đã mồi %s vào tessdata riêng của app (%s)", name, target)
        except OSError as exc:
            logger.warning("Không chép được %s: %s", name, exc)
    return target


def find_tessdata(configured: str = "", exe: str = "") -> str:
    """Thư mục traineddata app THỰC DÙNG.

    Ô cấu hình để trống thì LUÔN dùng thư mục riêng của app (tự tạo nếu chưa có).
    KHÔNG bao giờ âm thầm rơi về tessdata mặc định của Tesseract — làm thế thì người dùng
    cài thêm gói 'vie' vào thư mục app mà app lại đọc chỗ khác, không hiểu vì sao thiếu.
    """
    if configured and Path(configured).is_dir():
        return configured
    return str(ensure_app_tessdata(exe))


TESSDATA_URL = "https://raw.githubusercontent.com/tesseract-ocr/tessdata/main/{code}.traineddata"


def _default_downloader(url: str, timeout: int = 120) -> bytes:
    import urllib.request

    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return resp.read()


def bundled_tessdata_of(exe: str) -> Path | None:
    """Thư mục tessdata đi kèm bản Tesseract đã cài (thường nằm cạnh tesseract.exe)."""
    if not exe:
        return None
    candidate = Path(exe).resolve().parent / "tessdata"
    return candidate if candidate.is_dir() else None


def install_language_pack(
    code: str,
    target_dir: Path | str | None = None,
    exe: str = "",
    downloader=None,
) -> tuple[bool, str]:
    """Cài 1 gói ngôn ngữ vào thư mục tessdata riêng của app (không cần quyền admin).

    Ưu tiên chép từ bản Tesseract đã cài; không có thì tải từ kho tessdata chính thức.
    Trả (thành công, thông điệp tiếng Việt để hiện thẳng cho người dùng).
    """
    from .config import tessdata_dir

    code = (code or "").strip()
    if not code:
        return False, "Chưa cho biết cần cài gói ngôn ngữ nào."

    target = Path(target_dir) if target_dir else tessdata_dir()
    target.mkdir(parents=True, exist_ok=True)
    destination = target / f"{code}.traineddata"
    if destination.exists():
        return True, f"Gói '{code}' đã có sẵn trong {target}."

    source_dir = bundled_tessdata_of(exe or find_tesseract())
    if source_dir is not None:
        source = source_dir / f"{code}.traineddata"
        if source.exists():
            try:
                shutil.copy2(source, destination)
                return True, f"Đã chép gói '{code}' từ {source_dir} sang {target}."
            except OSError as exc:
                logger.error("Chép gói ngôn ngữ thất bại: %s", exc)

    # Không có sẵn trên máy -> tải từ kho chính thức của Tesseract
    fetch = downloader or _default_downloader
    url = TESSDATA_URL.format(code=code)
    try:
        data = fetch(url)
    except Exception as exc:
        return False, (
            f"Không tải được gói '{code}' ({type(exc).__name__}). "
            f"Bạn có thể tải tay tại {url} rồi chép vào {target}."
        )
    if not data or len(data) < 10000:
        return False, f"File tải về cho gói '{code}' không hợp lệ. Hãy tải tay từ {url}."

    try:
        tmp = destination.with_suffix(".part")
        tmp.write_bytes(data)
        tmp.replace(destination)
    except OSError as exc:
        return False, f"Không ghi được vào {target}: {exc}"
    return True, f"Đã tải và cài gói '{code}' vào {target} ({len(data) // 1024} KB)."


class OcrEngine:
    """Chạy OCR trên ảnh trang PDF. Không tìm thấy Tesseract thì available=False."""

    def __init__(
        self,
        tesseract_path: str = "",
        languages: str = "vie+eng",
        dpi: int = 300,
        tessdata_path: str = "",
    ) -> None:
        self.languages = languages
        self.dpi = dpi
        self.exe = find_tesseract(tesseract_path)
        self.tessdata = find_tessdata(tessdata_path, self.exe)
        self._pytesseract = None
        if self.exe:
            try:
                import pytesseract

                pytesseract.pytesseract.tesseract_cmd = self.exe
                self._pytesseract = pytesseract
            except ImportError as exc:  # pragma: no cover - môi trường thiếu gói
                logger.error("Không import được pytesseract: %s", exc)

        if self.tessdata and self._pytesseract is not None:
            # pytesseract không cho truyền env riêng cho từng lần gọi, và chuỗi config
            # có dấu ngoặc kép bị shlex trên Windows hiểu sai khi đường dẫn có khoảng
            # trắng — nên báo thư mục tessdata qua biến môi trường của tiến trình.
            os.environ["TESSDATA_PREFIX"] = self.tessdata
            logger.debug("Dùng tessdata tại %s", self.tessdata)

    @property
    def available(self) -> bool:
        return self._pytesseract is not None

    def available_languages(self) -> list[str]:
        """Danh sách gói ngôn ngữ đang dùng được — Settings hiển thị để user tự kiểm tra."""
        if not self.available:
            return []
        try:
            return sorted(self._pytesseract.get_languages(config=""))
        except Exception as exc:
            logger.warning("Không liệt kê được ngôn ngữ Tesseract: %s", exc)
            return []

    def image_to_page(self, image, page_index: int, scale: float = 1.0) -> PageText:
        """OCR 1 ảnh PIL thành PageText. scale = số pixel trên 1 point (dpi/72)."""
        if not self.available:
            return PageText(index=page_index, width=0, height=0, from_ocr=True)

        data = self._pytesseract.image_to_data(
            image,
            lang=self.languages,
            output_type=self._pytesseract.Output.DICT,
        )
        words: list[Word] = []
        lines: dict[tuple[int, int, int], list[str]] = {}
        for i, raw in enumerate(data["text"]):
            token = (raw or "").strip()
            if not token:
                continue
            try:
                conf = float(data["conf"][i])
            except (TypeError, ValueError):
                conf = -1.0
            if conf < 0:
                continue
            x, y = data["left"][i], data["top"][i]
            w, h = data["width"][i], data["height"][i]
            words.append(
                Word(
                    text=token,
                    x0=x / scale,
                    y0=y / scale,
                    x1=(x + w) / scale,
                    y1=(y + h) / scale,
                )
            )
            key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
            lines.setdefault(key, []).append(token)

        text = "\n".join(" ".join(tokens) for _, tokens in sorted(lines.items()))
        return PageText(
            index=page_index,
            width=image.width / scale,
            height=image.height / scale,
            text=text,
            words=words,
            from_ocr=True,
        )

    def image_to_text(self, image) -> str:
        """OCR nhanh chỉ lấy text, dùng cho vùng zonal cắt nhỏ."""
        if not self.available:
            return ""
        return (self._pytesseract.image_to_string(image, lang=self.languages) or "").strip()

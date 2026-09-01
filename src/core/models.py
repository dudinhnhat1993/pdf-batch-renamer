"""Dataclass dùng chung cho toàn app. Core trao đổi bằng các kiểu này, không dùng dict lỏng."""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum, IntEnum
from pathlib import Path
from typing import Any


class Layer(IntEnum):
    """5 tầng của pipeline trích dữ liệu. Tầng sau chỉ chạy khi còn thiếu field bắt buộc."""

    TEXT = 0
    REGEX = 1
    ZONAL = 2
    BARCODE = 3
    METADATA = 4
    AI = 5

    @property
    def label_vi(self) -> str:
        return {
            0: "Chuẩn bị text",
            1: "Regex theo nhãn",
            2: "Vùng tọa độ",
            3: "Barcode/QR",
            4: "Metadata/Form",
            5: "AI",
        }[int(self)]


class JobStatus(str, Enum):  # noqa: UP042 - cần so sánh trực tiếp với chuỗi khi đọc/ghi JSON
    """Trạng thái cuối của 1 file — không file nào được rời queue mà thiếu trạng thái."""

    PENDING = "pending"
    PROCESSING = "processing"
    SUCCESS = "success"
    DUPLICATE = "duplicate"
    ERROR = "error"

    @property
    def label_vi(self) -> str:
        return {
            "pending": "Chờ",
            "processing": "Đang xử lý",
            "success": "Thành công",
            "duplicate": "Trùng",
            "error": "Lỗi",
        }[self.value]


# --------------------------------------------------------------------------- text


@dataclass
class Word:
    """1 từ kèm bbox theo đơn vị point của trang PDF (gốc tọa độ ở góc trên-trái)."""

    text: str
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def center(self) -> tuple[float, float]:
        return ((self.x0 + self.x1) / 2, (self.y0 + self.y1) / 2)


@dataclass
class PageText:
    index: int
    width: float
    height: float
    text: str = ""
    words: list[Word] = field(default_factory=list)
    from_ocr: bool = False


@dataclass
class DocumentText:
    pages: list[PageText] = field(default_factory=list)
    ocr_used: bool = False

    @property
    def text(self) -> str:
        return "\n".join(p.text for p in self.pages)

    @property
    def char_count(self) -> int:
        return sum(len(p.text.strip()) for p in self.pages)


# --------------------------------------------------------------------------- rules


@dataclass
class Zone:
    """Vùng chữ nhật trên trang, lưu theo tỉ lệ 0..1 để không phụ thuộc DPI hay khổ giấy."""

    page: int = 0
    x0: float = 0.0
    y0: float = 0.0
    x1: float = 1.0
    y1: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Zone:
        return cls(**{k: d[k] for k in ("page", "x0", "y0", "x1", "y1") if k in d})


@dataclass
class MasterDataLookup:
    """Khai báo tra cứu Excel: lấy giá trị field này, dò trong cột key, trả về cột value."""

    source: str = ""  # đường dẫn .xlsx, rỗng = dùng file mặc định trong config
    sheet: str = ""  # rỗng = sheet đầu tiên
    key_column: str = ""
    value_column: str = ""
    target_field: str = ""  # tên field mới sinh ra để dùng trong template

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> MasterDataLookup:
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class FieldSpec:
    """Định nghĩa 1 field cần trích, gồm nhiều regex dự phòng chạy lần lượt tới khi trúng."""

    name: str
    label: str = ""
    required: bool = False
    patterns: list[str] = field(default_factory=list)
    zone: Zone | None = None
    # Tinh lọc giá trị bên trong vùng: none | label | line | regex (xem core/zonal.py)
    zone_filter: str = "none"
    zone_filter_value: str = ""
    # Với zone_filter="label": cắt đuôi ở đâu — "" | label | gap | regex
    zone_filter_stop: str = ""
    zone_stop_value: str = ""
    # Kiểu validate: none | date | container | regex
    validate: str = "none"
    # Regex validate giá trị cuối — bắt buộc dùng để lọc output của tầng AI
    validate_regex: str = ""
    # Áp từ điển chuẩn hóa tên công ty sau khi trích
    normalize_company: bool = False
    # Cho phép tầng 3 (barcode) điền field này
    from_barcode: bool = False
    # Khóa metadata/AcroForm cho tầng 4, vd "Title" hoặc tên form field
    metadata_key: str = ""
    masterdata: MasterDataLookup | None = None

    def __post_init__(self) -> None:
        if not self.label:
            self.label = self.name

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["zone"] = self.zone.to_dict() if self.zone else None
        d["masterdata"] = self.masterdata.to_dict() if self.masterdata else None
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> FieldSpec:
        data = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        if data.get("zone"):
            data["zone"] = Zone.from_dict(data["zone"])
        if data.get("masterdata"):
            data["masterdata"] = MasterDataLookup.from_dict(data["masterdata"])
        return cls(**data)


@dataclass
class MatchCondition:
    """Điều kiện nhận diện profile: keyword thường hoặc regex."""

    kind: str = "keyword"  # keyword | regex
    value: str = ""
    case_sensitive: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> MatchCondition:
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class Profile:
    """Bộ rule cho 1 loại chứng từ. Lưu thành 1 file JSON, sửa 100% qua GUI."""

    id: str = ""
    name: str = ""
    doctype: str = ""
    enabled: bool = True
    priority: int = 100  # số nhỏ hơn = được thử match trước
    conditions: list[MatchCondition] = field(default_factory=list)
    condition_mode: str = "any"  # any = trúng 1 điều kiện là đủ; all = phải trúng hết
    # Điều kiện LOẠI TRỪ: trúng bất kỳ cái nào là profile này bị loại, dù conditions có
    # trúng hay không. Dùng cho chứng từ chồng lấn (Invoice NOT contains "PACKING LIST").
    exclude_conditions: list[MatchCondition] = field(default_factory=list)
    fields: list[FieldSpec] = field(default_factory=list)
    # Các format ngày thử lần lượt khi parse, dùng token dd/mm/yyyy
    date_formats: list[str] = field(default_factory=lambda: ["dd/mm/yyyy"])
    template: str = "{original_name}"
    ai_enabled: bool = False
    # BẬT: tầng 2–4 chạy thêm để điền field tùy chọn còn trống (barcode, zonal, metadata).
    # TẮT: quay về hành vi tiết kiệm — chỉ chạy khi thiếu field BẮT BUỘC. Dùng cho chứng
    # từ nặng nhiều trang, nơi quét barcode/OCR vùng tốn thời gian mà không đáng.
    fill_optional_fields: bool = True
    version: int = 1
    samples: list[str] = field(default_factory=list)  # tối đa 5 file mẫu cho regression
    is_fallback: bool = False  # profile "Chung", chỉ dùng khi không cái nào khác match
    output_dir: str = ""  # Thư mục đích riêng (rỗng = dùng config.output_root)

    def __post_init__(self) -> None:
        if not self.id:
            self.id = uuid.uuid4().hex[:12]
        if not self.doctype:
            self.doctype = self.name

    def field_by_name(self, name: str) -> FieldSpec | None:
        return next((f for f in self.fields if f.name == name), None)

    @property
    def required_fields(self) -> list[str]:
        return [f.name for f in self.fields if f.required]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "doctype": self.doctype,
            "enabled": self.enabled,
            "priority": self.priority,
            "conditions": [c.to_dict() for c in self.conditions],
            "condition_mode": self.condition_mode,
            "exclude_conditions": [c.to_dict() for c in self.exclude_conditions],
            "fields": [f.to_dict() for f in self.fields],
            "date_formats": list(self.date_formats),
            "template": self.template,
            "ai_enabled": self.ai_enabled,
            "fill_optional_fields": self.fill_optional_fields,
            "version": self.version,
            "samples": list(self.samples),
            "is_fallback": self.is_fallback,
            "output_dir": self.output_dir,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Profile:
        data = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        data["conditions"] = [MatchCondition.from_dict(c) for c in d.get("conditions", [])]
        data["exclude_conditions"] = [
            MatchCondition.from_dict(c) for c in d.get("exclude_conditions", [])
        ]
        data["fields"] = [FieldSpec.from_dict(f) for f in d.get("fields", [])]
        return cls(**data)


# --------------------------------------------------------------------------- kết quả


@dataclass
class ExtractedField:
    """1 giá trị trích được, kèm đủ provenance để phục vụ Learning Loop về sau."""

    name: str
    value: str
    raw_value: str = ""
    layer: Layer = Layer.REGEX
    # Định danh rule đã tạo ra giá trị: "pattern[0]", "zone", "barcode", "metadata:Title", "ai"
    rule_id: str = ""
    page: int = -1
    bbox: tuple[float, float, float, float] | None = None
    edited_by_user: bool = False  # True khi user sửa tay trong màn hình Preview

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["layer"] = int(self.layer)
        return d


@dataclass
class ExtractionResult:
    """Kết quả pipeline cho 1 file."""

    fields: dict[str, ExtractedField] = field(default_factory=dict)
    document: DocumentText = field(default_factory=DocumentText)
    profile_id: str = ""
    profile_name: str = ""
    layers_used: list[Layer] = field(default_factory=list)
    missing_required: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def value(self, name: str, default: str = "") -> str:
        f = self.fields.get(name)
        return f.value if f else default


@dataclass
class FileJob:
    """1 file trong queue, mang trạng thái từ lúc nạp tới lúc ghi ra output."""

    source: Path
    status: JobStatus = JobStatus.PENDING
    message: str = ""
    size: int = 0
    file_hash: str = ""
    profile_id: str = ""
    profile_name: str = ""
    fields: dict[str, ExtractedField] = field(default_factory=dict)
    # Tên cơ sở do template sinh ra — phần deterministic, chưa gồm hậu tố chống trùng
    base_name: str = ""
    new_name: str = ""
    dest_dir: Path | None = None
    layers_used: list[Layer] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    error_code: str = ""
    duration_ms: int = 0
    # Thông tin lần xử lý trước, điền khi trạng thái là Trùng
    previous: dict[str, Any] | None = None

    @property
    def dest_path(self) -> Path | None:
        return (self.dest_dir / self.new_name) if self.dest_dir and self.new_name else None

    def field_values(self) -> dict[str, str]:
        return {k: v.value for k, v in self.fields.items()}

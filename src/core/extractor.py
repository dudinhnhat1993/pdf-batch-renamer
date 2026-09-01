"""Điều phối pipeline trích dữ liệu 5 tầng.

Tầng sau CHỈ chạy khi vẫn còn thiếu field bắt buộc — rule rẻ và chắc chắn chạy trước,
OCR/barcode/AI đắt đỏ chỉ chạy khi thật sự cần.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from pathlib import Path

from .ai_client import AiClient, FewShotExample
from .config import AppConfig
from .errors import MasterDataError
from .masterdata import MasterDataStore
from .metadata import lookup as metadata_lookup
from .metadata import read_metadata
from .models import (
    DocumentText,
    ExtractedField,
    ExtractionResult,
    FieldSpec,
    Layer,
    PageText,
    Profile,
)
from .normalize import CompanyDictionary
from .ocr import OcrEngine
from .pdfdoc import PdfDocument
from .rules import run_regex_field, select_profile
from .textloc import locate
from .validators import validate_field_value
from .zonal import apply_zone_filter, extract_zone

logger = logging.getLogger(__name__)


class Extractor:
    """Chạy 5 tầng cho 1 file và trả về ExtractionResult kèm provenance đầy đủ."""

    def __init__(
        self,
        config: AppConfig,
        profiles: list[Profile],
        *,
        ocr: OcrEngine | None = None,
        ai_client: AiClient | None = None,
        masterdata: MasterDataStore | None = None,
        dictionary: CompanyDictionary | None = None,
        examples_provider: Callable[[str], list[FewShotExample]] | None = None,
    ) -> None:
        self.config = config
        self.profiles = profiles
        self.ocr = ocr
        self.ai_client = ai_client
        self.masterdata = masterdata
        self.dictionary = dictionary or CompanyDictionary()
        self.examples_provider = examples_provider

    # ------------------------------------------------------------- tầng 0

    def read_document(self, doc: PdfDocument) -> DocumentText:
        """Tầng 0: lấy text layer; quá ít ký tự thì coi là scan và OCR N trang đầu."""
        pages: list[PageText] = []
        for index in range(doc.page_count):
            try:
                pages.append(doc.page_text(index))
            except Exception as exc:
                logger.warning("Không đọc được text trang %s: %s", index, exc)
                width, height = doc.page_size(index)
                pages.append(PageText(index=index, width=width, height=height))

        document = DocumentText(pages=pages)
        cfg = self.config.ocr
        if document.char_count >= cfg.min_chars or not cfg.enabled:
            return document

        if self.ocr is None or not self.ocr.available:
            logger.warning("PDF ít text nhưng không dùng được Tesseract: %s", doc.path.name)
            return document

        scale = doc.render_scale(cfg.dpi)
        for index in range(min(cfg.max_pages, doc.page_count)):
            try:
                image = doc.render_page(index, dpi=cfg.dpi)
                pages[index] = self.ocr.image_to_page(image, index, scale)
            except Exception as exc:
                logger.error("OCR trang %s thất bại: %s", index, exc)
        document.ocr_used = any(p.from_ocr for p in pages)
        return document

    # ------------------------------------------------------- tầng 2/3/4/5

    def _fill_zonal(
        self, doc: PdfDocument, spec: FieldSpec, document: DocumentText
    ) -> ExtractedField | None:
        if spec.zone is None:
            return None
        text, bbox = extract_zone(doc, spec.zone, self.ocr, self.config.ocr.dpi)
        if not text.strip():
            return None
        # Vùng thường bắt cả cụm -> tinh lọc thêm theo khai báo của field
        value = apply_zone_filter(
            text,
            spec.zone_filter,
            spec.zone_filter_value,
            spec.zone_filter_stop,
            spec.zone_stop_value,
        )
        if not value.strip():
            return None
        return ExtractedField(
            name=spec.name,
            value=value.strip(),
            raw_value=text.strip(),
            layer=Layer.ZONAL,
            rule_id="zone",
            page=spec.zone.page,
            bbox=bbox,
        )

    def _fill_barcode(self, spec: FieldSpec, hits: list, profile: Profile) -> ExtractedField | None:
        """Chọn mã đầu tiên pass validate của field — tránh nhặt nhầm mã QR quảng cáo."""
        if not spec.from_barcode or not hits:
            return None
        fallback = None
        for hit in hits:
            ok, value = validate_field_value(
                hit.data,
                spec.validate,
                date_formats=profile.date_formats,
                regex=spec.validate_regex,
            )
            candidate = ExtractedField(
                name=spec.name,
                value=value or hit.data.strip(),
                raw_value=hit.data,
                layer=Layer.BARCODE,
                rule_id=f"barcode:{hit.kind}",
                page=hit.page,
                bbox=hit.bbox,
            )
            if ok:
                return candidate
            fallback = fallback or candidate
        # Không mã nào hợp lệ: trả mã đầu để validate chung ở dưới loại bỏ và ghi cảnh báo
        return fallback

    def _fill_metadata(self, spec: FieldSpec, values: dict[str, str]) -> ExtractedField | None:
        if not spec.metadata_key:
            return None
        value = metadata_lookup(values, spec.metadata_key)
        if not value:
            return None
        return ExtractedField(
            name=spec.name,
            value=value,
            raw_value=value,
            layer=Layer.METADATA,
            rule_id=f"metadata:{spec.metadata_key}",
        )

    # ------------------------------------------------------------ hậu xử lý

    def _postprocess(
        self, profile: Profile, fields: dict[str, ExtractedField], result: ExtractionResult
    ) -> None:
        """Validate, chuẩn hóa tên công ty, rồi tra master data. Field sai bị LOẠI BỎ."""
        for name in list(fields.keys()):
            spec = profile.field_by_name(name)
            if spec is None:
                continue
            f = fields[name]
            ok, value = validate_field_value(
                f.value,
                spec.validate,
                date_formats=profile.date_formats,
                regex=spec.validate_regex,
            )
            if not ok:
                result.warnings.append(
                    f"Field '{spec.label}' có giá trị không hợp lệ ({f.value!r}) — đã loại bỏ"
                )
                del fields[name]
                continue
            f.value = value
            if spec.normalize_company:
                f.value = self.dictionary.normalize(f.value)

        # Master data chạy sau cùng vì phụ thuộc field đã sạch
        for spec in profile.fields:
            if not spec.masterdata or not spec.masterdata.target_field:
                continue
            source = fields.get(spec.name)
            if source is None or not source.value:
                continue
            if self.masterdata is None:
                continue
            try:
                value = self.masterdata.lookup(spec.masterdata, source.value)
            except MasterDataError as exc:
                result.warnings.append(f"Master data: {exc}")
                continue
            if value:
                fields[spec.masterdata.target_field] = ExtractedField(
                    name=spec.masterdata.target_field,
                    value=value,
                    raw_value=source.value,
                    layer=source.layer,
                    rule_id=f"masterdata:{spec.name}",
                )

    @staticmethod
    def _missing_required(profile: Profile, fields: dict[str, ExtractedField]) -> list[str]:
        return [
            spec.name
            for spec in profile.fields
            if spec.required and not fields.get(spec.name, None)
        ]

    @staticmethod
    def _candidates(
        profile: Profile,
        fields: dict[str, ExtractedField],
        predicate: Callable[[FieldSpec], bool],
    ) -> list[FieldSpec]:
        """Các field còn trống mà chính field đó khai báo dùng tầng đang xét."""
        return [s for s in profile.fields if s.name not in fields and predicate(s)]

    def _should_run_layer(
        self,
        profile: Profile,
        fields: dict[str, ExtractedField],
        candidates: list[FieldSpec],
    ) -> bool:
        """Cổng chặn tầng 2–4.

        Chạy khi CÒN THIẾU FIELD BẮT BUỘC, hoặc khi vẫn còn field trống mà field đó khai
        báo dùng đúng tầng này (chỉ khi profile bật 'Điền đủ field tùy chọn').
        Tắt toggle -> quay về hành vi tiết kiệm cũ, hợp với chứng từ nặng nhiều trang.
        """
        if self._missing_required(profile, fields):
            return True
        return bool(profile.fill_optional_fields and candidates)

    # ---------------------------------------------------------------- chạy

    def extract(self, path: Path | str, forced_profile: str = "") -> ExtractionResult:
        """Chạy toàn bộ pipeline cho 1 file. Ném PdfOpenError/PasswordProtectedError nếu không mở được."""
        result = ExtractionResult()
        with PdfDocument(path, self.config.passwords) as doc:
            document = self.read_document(doc)
            result.document = document
            result.layers_used.append(Layer.TEXT)

            profile = select_profile(self.profiles, document.text, forced_profile)
            if profile is None:
                result.warnings.append("Không có profile nào khả dụng")
                return result
            result.profile_id = profile.id
            result.profile_name = profile.name

            fields: dict[str, ExtractedField] = {}

            # Tầng 1 — regex theo nhãn
            for spec in profile.fields:
                found = run_regex_field(spec, document)
                if found:
                    fields[spec.name] = found
            if any(f.layer == Layer.REGEX for f in fields.values()):
                result.layers_used.append(Layer.REGEX)

            # Tầng 2 — zonal
            zonal_specs = self._candidates(profile, fields, lambda s: s.zone is not None)
            if self._should_run_layer(profile, fields, zonal_specs):
                used = False
                for spec in zonal_specs:
                    found = self._fill_zonal(doc, spec, document)
                    if found:
                        fields[spec.name] = found
                        used = True
                if used:
                    result.layers_used.append(Layer.ZONAL)

            # Tầng 3 — barcode/QR
            barcode_specs = self._candidates(profile, fields, lambda s: s.from_barcode)
            if self.config.barcode.enabled and self._should_run_layer(
                profile, fields, barcode_specs
            ):
                from .barcode import AVAILABLE, UNAVAILABLE_REASON, scan_document

                if not AVAILABLE:
                    result.warnings.append(UNAVAILABLE_REASON)
                elif barcode_specs:
                    hits = scan_document(doc, self.config.barcode.max_pages, self.config.ocr.dpi)
                    used = False
                    for spec in barcode_specs:
                        found = self._fill_barcode(spec, hits, profile)
                        if found:
                            fields[spec.name] = found
                            used = True
                    if used:
                        result.layers_used.append(Layer.BARCODE)

            # Tầng 4 — metadata + AcroForm
            metadata_specs = self._candidates(profile, fields, lambda s: bool(s.metadata_key))
            if self._should_run_layer(profile, fields, metadata_specs) and metadata_specs:
                values = read_metadata(doc.path, doc.password)
                used = False
                for spec in metadata_specs:
                    found = self._fill_metadata(spec, values)
                    if found:
                        fields[spec.name] = found
                        used = True
                if used:
                    result.layers_used.append(Layer.METADATA)

            # Tầng 5 — AI fallback (mặc định TẮT, phải bật ở cả Settings lẫn profile)
            missing = self._missing_required(profile, fields)
            if missing and self._ai_ready(profile):
                self._run_ai(profile, document, missing, fields, result)

            self._postprocess(profile, fields, result)
            result.fields = fields
            result.missing_required = self._missing_required(profile, fields)
            return result

    # ------------------------------------------------------------- tầng 5

    def _ai_ready(self, profile: Profile) -> bool:
        return bool(
            self.config.ai.enabled
            and profile.ai_enabled
            and self.ai_client is not None
            and self.ai_client.configured
        )

    def _run_ai(
        self,
        profile: Profile,
        document: DocumentText,
        missing: list[str],
        fields: dict[str, ExtractedField],
        result: ExtractionResult,
    ) -> None:
        examples = self.examples_provider(profile.id) if self.examples_provider else []
        accepted, rejected = self.ai_client.extract(profile, document.text, missing, examples)
        for name, value in accepted.items():
            page, bbox = self._locate_in_document(document, value)
            fields[name] = ExtractedField(
                name=name,
                value=value,
                raw_value=value,
                layer=Layer.AI,
                rule_id="ai",
                page=page,
                bbox=bbox,
            )
        if accepted:
            result.layers_used.append(Layer.AI)
        if rejected:
            result.warnings.append(
                "AI trả về field không hợp lệ, đã loại bỏ: " + ", ".join(sorted(rejected))
            )

    @staticmethod
    def _locate_in_document(
        document: DocumentText, value: str
    ) -> tuple[int, tuple[float, float, float, float] | None]:
        """Dò xem giá trị AI trả về nằm ở trang nào — vừa để provenance, vừa để kiểm chứng."""
        for page in document.pages:
            if value and re.search(re.escape(value), page.text, re.IGNORECASE):
                return page.index, locate(page, value)
        return -1, None

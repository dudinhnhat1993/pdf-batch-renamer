"""Test OCR với Tesseract THẬT. Tự bỏ qua khi máy chưa cài Tesseract.

Chạy riêng:  pytest -m integration
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from src.core.extractor import Extractor
from src.core.models import FieldSpec, MatchCondition, Profile
from src.core.ocr import OcrEngine, find_tesseract

pytestmark = pytest.mark.integration


def real_tessdata() -> str:
    """Thư mục tessdata thật của máy.

    Fixture isolated_home đổi PDFRENAMER_HOME sang thư mục tạm nên OcrEngine không tự
    tìm thấy gói ngôn ngữ đã cài — test tích hợp phải trỏ thẳng vào thư mục thật.
    """
    base = os.environ.get("APPDATA")
    if not base:
        return ""
    path = Path(base) / "PDFBatchRenamer" / "tessdata"
    return str(path) if path.is_dir() and any(path.glob("*.traineddata")) else ""


@pytest.fixture(autouse=True)
def keep_tessdata_env():
    """OcrEngine đặt TESSDATA_PREFIX ở mức tiến trình — trả lại nguyên trạng sau test."""
    before = os.environ.get("TESSDATA_PREFIX")
    yield
    if before is None:
        os.environ.pop("TESSDATA_PREFIX", None)
    else:
        os.environ["TESSDATA_PREFIX"] = before


def make_engine(languages: str) -> OcrEngine:
    if not find_tesseract():
        pytest.skip("Chưa cài Tesseract — bỏ qua test OCR thật")
    engine = OcrEngine(languages=languages, tessdata_path=real_tessdata())
    if not engine.available:
        pytest.skip("pytesseract không dùng được")
    return engine


@pytest.fixture
def real_ocr():
    return make_engine("eng")


def scanned_profile() -> Profile:
    return Profile(
        id="scan",
        name="Scan Invoice",
        doctype="INV",
        conditions=[MatchCondition(value="INVOICE")],
        fields=[
            FieldSpec(
                name="number",
                required=True,
                patterns=[r"Invoice\s*No\.?\s*:?\s*([A-Z0-9\-]+)"],
            )
        ],
        template="{number}",
    )


def test_ocr_that_doc_duoc_pdf_scan(config, pdfs, real_ocr):
    config.ocr.enabled = True
    config.ocr.languages = "eng"
    result = Extractor(config, [scanned_profile()], ocr=real_ocr).extract(pdfs["scanned"])

    assert result.document.ocr_used is True
    assert "INVOICE" in result.document.text.upper()
    assert result.value("number").startswith("INV-2026")


def test_ocr_that_tra_ve_bbox_tung_tu(pdfs, real_ocr):
    from src.core.pdfdoc import PdfDocument

    with PdfDocument(pdfs["scanned"]) as doc:
        image = doc.render_page(0, dpi=200)
        page = real_ocr.image_to_page(image, 0, doc.render_scale(200))

    assert page.words
    assert all(w.x1 > w.x0 and w.y1 > w.y0 for w in page.words)


def test_goi_ngon_ngu_vie_da_cai_va_dung_duoc():
    """Gói 'vie' phải có sẵn — Rule Builder cho chứng từ scan tiếng Việt phụ thuộc vào nó."""
    if not real_tessdata():
        pytest.skip("Chưa cài gói ngôn ngữ vào tessdata riêng của app")
    engine = make_engine("vie+eng")
    langs = engine.available_languages()
    assert "vie" in langs
    assert "eng" in langs


def test_ocr_that_doc_duoc_chung_tu_tieng_viet(pdfs):
    from src.core.pdfdoc import PdfDocument

    if not real_tessdata():
        pytest.skip("Chưa cài gói ngôn ngữ vào tessdata riêng của app")
    engine = make_engine("vie+eng")
    with PdfDocument(pdfs["scanned_vi"]) as doc:
        page = engine.image_to_page(doc.render_page(0, dpi=300), 0, doc.render_scale(300))

    text = page.text.upper()
    assert "HOA DON" in text or "HÓA ĐƠN" in text
    assert "HD-2026-0155" in page.text


def test_goi_vie_thuc_su_can_thiet_voi_chung_tu_co_dau(pdfs):
    """Chứng minh bằng số liệu: thiếu gói 'vie' thì chữ có dấu bị đọc sai."""
    from src.core.pdfdoc import PdfDocument

    if not real_tessdata():
        pytest.skip("Chưa cài gói ngôn ngữ vào tessdata riêng của app")

    with PdfDocument(pdfs["scanned_vi_accent"]) as doc:
        image = doc.render_page(0, dpi=300)
        scale = doc.render_scale(300)
        only_eng = make_engine("eng").image_to_page(image, 0, scale).text
        with_vie = make_engine("vie+eng").image_to_page(image, 0, scale).text

    # Số chứng từ (thuần ASCII) thì bản nào cũng đọc được
    assert "HD-2026-0155" in only_eng
    assert "HD-2026-0155" in with_vie
    # Nhưng chữ có dấu thì chỉ bản có gói vie mới ra đúng
    assert "CÔNG TY" in with_vie
    assert "CÔNG TY" not in only_eng

"""Test pipeline 5 tầng. OCR và AI đều được mock — không gọi Tesseract hay mạng thật."""

from __future__ import annotations

import json

import pytest
from src.core.ai_client import AiClient, AiSettings
from src.core.errors import PasswordProtectedError, PdfOpenError
from src.core.extractor import Extractor
from src.core.models import FieldSpec, Layer, MasterDataLookup, MatchCondition, Profile, Zone
from src.core.normalize import CompanyDictionary


def invoice_profile(**overrides) -> Profile:
    base = Profile(
        id="test-invoice",
        name="Test Invoice",
        doctype="INV",
        conditions=[MatchCondition(value="COMMERCIAL INVOICE")],
        fields=[
            FieldSpec(
                name="number",
                label="Số hóa đơn",
                required=True,
                patterns=[r"Invoice\s*No\.?\s*:?\s*([A-Z0-9\-]+)"],
            ),
            FieldSpec(
                name="doc_date",
                label="Ngày",
                patterns=[r"Invoice\s*Date\s*:?\s*(\d{2}/\d{2}/\d{4})"],
                validate="date",
            ),
        ],
        date_formats=["dd/mm/yyyy"],
        template="{doc_date}_{doctype}_{number}",
    )
    for key, value in overrides.items():
        setattr(base, key, value)
    return base


def fake_ai_client(payload: dict) -> AiClient:
    """AiClient với transport giả, trả về JSON định sẵn."""

    def transport(url, body, headers, timeout):
        return {"choices": [{"message": {"content": json.dumps(payload)}}]}

    return AiClient(AiSettings(base_url="http://fake/v1", model="test"), transport=transport)


# ------------------------------------------------------------------ tầng 0/1


class TestLayer0And1:
    def test_pdf_co_text_layer_khong_can_ocr(self, config, pdfs, fake_ocr):
        ocr = fake_ocr("KHONG BAO GIO DUOC DUNG")
        config.ocr.enabled = True
        ex = Extractor(config, [invoice_profile()], ocr=ocr)
        result = ex.extract(pdfs["invoice"])

        assert ocr.calls == 0
        assert result.document.ocr_used is False
        assert result.value("number") == "INV-2026-00871"
        assert result.value("doc_date") == "15/03/2026"
        assert Layer.REGEX in result.layers_used

    def test_pdf_scan_it_text_thi_chuyen_sang_ocr(self, config, pdfs, fake_ocr):
        ocr = fake_ocr(
            "GLOBAL FREIGHT SERVICES\nCOMMERCIAL INVOICE\n"
            "Invoice No.: INV-2026-SCAN01\nInvoice Date: 20/03/2026"
        )
        config.ocr.enabled = True
        ex = Extractor(config, [invoice_profile()], ocr=ocr)
        result = ex.extract(pdfs["scanned"])

        assert ocr.calls > 0
        assert result.document.ocr_used is True
        assert result.value("number") == "INV-2026-SCAN01"

    def test_khong_co_tesseract_thi_canh_bao_chu_khong_chet(self, config, pdfs, fake_ocr, profiles):
        # PDF scan + không có Tesseract -> không trích được gì, nhưng KHÔNG được ném exception
        config.ocr.enabled = True
        ex = Extractor(config, profiles, ocr=fake_ocr("", available=False))
        result = ex.extract(pdfs["scanned"])
        assert result.fields == {}
        assert result.profile_name == "Chung"  # rơi về profile fallback

    def test_nguong_ocr_ton_trong_cau_hinh(self, config, pdfs, fake_ocr):
        ocr = fake_ocr("COMMERCIAL INVOICE\nInvoice No.: TU-OCR")
        config.ocr.enabled = True
        config.ocr.min_chars = 100000  # ép mọi file đều bị coi là scan
        ex = Extractor(config, [invoice_profile()], ocr=ocr)
        assert ex.extract(pdfs["invoice"]).value("number") == "TU-OCR"

    def test_regex_du_phong(self, config, pdfs):
        profile = invoice_profile()
        profile.fields[0].patterns = [r"KHONG-TRUNG (\w+)", r"Invoice No\.?:?\s*([A-Z0-9\-]+)"]
        result = Extractor(config, [profile]).extract(pdfs["invoice"])
        assert result.fields["number"].rule_id == "pattern[1]"


# -------------------------------------------------------------------- tầng 2


class TestLayer2Zonal:
    def test_zonal_chay_khi_thieu_field_bat_buoc(self, config, pdfs):
        profile = invoice_profile()
        profile.fields[0].patterns = []  # không có regex -> phải nhờ tầng zonal
        profile.fields[0].zone = Zone(page=0, x0=0.0, y0=0.0, x1=1.0, y1=1.0)

        result = Extractor(config, [profile]).extract(pdfs["invoice"])
        assert "INV-2026-00871" in result.value("number")
        assert result.fields["number"].layer == Layer.ZONAL
        assert Layer.ZONAL in result.layers_used

    def test_zonal_khong_chay_khi_da_du_field_bat_buoc(self, config, pdfs):
        profile = invoice_profile()
        profile.fields[1].zone = Zone(page=0, x0=0, y0=0, x1=1, y1=1)
        result = Extractor(config, [profile]).extract(pdfs["invoice"])
        assert Layer.ZONAL not in result.layers_used

    def test_zone_tro_vao_trang_khong_ton_tai(self, config, pdfs):
        profile = invoice_profile()
        profile.fields[0].patterns = []
        profile.fields[0].zone = Zone(page=99, x0=0, y0=0, x1=1, y1=1)
        result = Extractor(config, [profile]).extract(pdfs["invoice"])
        assert result.missing_required == ["number"]


# -------------------------------------------------------------------- tầng 3


class TestLayer3Barcode:
    def test_doc_so_container_tu_barcode(self, config, pdfs):
        from src.core.barcode import AVAILABLE

        if not AVAILABLE:
            pytest.skip("pyzbar không dùng được trên máy này")

        profile = Profile(
            id="bl-barcode",
            name="BL Barcode",
            doctype="BL",
            conditions=[MatchCondition(value="BILL OF LADING")],
            fields=[
                FieldSpec(
                    name="container",
                    label="Số container",
                    required=True,
                    from_barcode=True,
                    validate="container",
                )
            ],
            template="{container}",
        )
        result = Extractor(config, [profile]).extract(pdfs["barcode"])
        assert result.value("container") == "MSKU2482484"
        assert result.fields["container"].layer == Layer.BARCODE

    def test_tat_barcode_trong_config(self, config, pdfs):
        config.barcode.enabled = False
        profile = Profile(
            id="bl-barcode", name="BL", doctype="BL",
            conditions=[MatchCondition(value="BILL OF LADING")],
            fields=[FieldSpec(name="container", required=True, from_barcode=True)],
            template="{container}",
        )
        result = Extractor(config, [profile]).extract(pdfs["barcode"])
        assert result.missing_required == ["container"]


# -------------------------------------------------------------------- tầng 4


class TestLayer4Metadata:
    def test_doc_title_tu_metadata(self, config, pdfs):
        profile = invoice_profile()
        profile.fields[0].patterns = []
        profile.fields[0].metadata_key = "Title"

        result = Extractor(config, [profile]).extract(pdfs["invoice"])
        assert "INV-2026-00871" in result.value("number")
        assert result.fields["number"].layer == Layer.METADATA


# -------------------------------------------------------------------- tầng 5


class TestLayer5Ai:
    def test_ai_tat_mac_dinh(self, config, pdfs):
        profile = invoice_profile()
        profile.fields[0].patterns = []
        profile.ai_enabled = True  # bật ở profile nhưng Settings vẫn tắt

        client = fake_ai_client({"number": "INV-TU-AI"})
        result = Extractor(config, [profile], ai_client=client).extract(pdfs["invoice"])
        assert result.missing_required == ["number"]

    def test_ai_can_bat_ca_o_profile(self, config, pdfs):
        config.ai.enabled = True
        profile = invoice_profile()
        profile.fields[0].patterns = []
        profile.ai_enabled = False

        client = fake_ai_client({"number": "INV-TU-AI"})
        result = Extractor(config, [profile], ai_client=client).extract(pdfs["invoice"])
        assert result.missing_required == ["number"]

    def test_ai_chay_khi_bat_ca_hai_va_con_thieu_field(self, config, pdfs):
        config.ai.enabled = True
        profile = invoice_profile()
        profile.fields[0].patterns = []
        profile.ai_enabled = True

        client = fake_ai_client({"number": "INV-2026-00871"})
        result = Extractor(config, [profile], ai_client=client).extract(pdfs["invoice"])
        assert result.value("number") == "INV-2026-00871"
        assert result.fields["number"].layer == Layer.AI
        assert Layer.AI in result.layers_used

    def test_ai_khong_chay_khi_khong_thieu_gi(self, config, pdfs):
        config.ai.enabled = True
        profile = invoice_profile()
        profile.ai_enabled = True

        client = fake_ai_client({"number": "SAI-BET"})
        result = Extractor(config, [profile], ai_client=client).extract(pdfs["invoice"])
        assert result.value("number") == "INV-2026-00871"
        assert Layer.AI not in result.layers_used

    def test_field_ai_khong_qua_duoc_validate_thi_bi_loai(self, config, pdfs):
        config.ai.enabled = True
        profile = invoice_profile()
        profile.ai_enabled = True
        profile.fields[0].patterns = []
        profile.fields[0].validate = "container"  # AI trả về thứ không phải container

        client = fake_ai_client({"number": "KHONG-PHAI-CONTAINER"})
        result = Extractor(config, [profile], ai_client=client).extract(pdfs["invoice"])
        assert result.missing_required == ["number"]
        assert any("AI trả về field không hợp lệ" in w for w in result.warnings)


# ------------------------------------------------------------- password/lỗi


class TestPassword:
    def test_khong_co_password_thi_bao_loi_ro_rang(self, config, pdfs):
        with pytest.raises(PasswordProtectedError):
            Extractor(config, [invoice_profile()]).extract(pdfs["encrypted"])

    def test_thu_lan_luot_danh_sach_password(self, config, pdfs):
        config.passwords = ["sai-1", "sai-2", "logistics2026"]
        result = Extractor(config, [invoice_profile()]).extract(pdfs["encrypted"])
        assert result.value("number") == "INV-2026-00871"

    def test_file_khong_ton_tai(self, config, tmp_path):
        with pytest.raises(PdfOpenError):
            Extractor(config, [invoice_profile()]).extract(tmp_path / "khong-co.pdf")


# ------------------------------------------------------------- hậu xử lý


class TestPostprocess:
    def test_gia_tri_khong_qua_validate_bi_loai_bo(self, config, pdfs):
        profile = invoice_profile()
        profile.fields[0].validate = "container"
        result = Extractor(config, [profile]).extract(pdfs["invoice"])
        assert "number" not in result.fields
        assert any("không hợp lệ" in w for w in result.warnings)

    def test_chuan_hoa_ten_cong_ty(self, config, pdfs):
        profile = invoice_profile()
        profile.fields.append(
            FieldSpec(
                name="company",
                patterns=[r"Seller:\s*([^\n]+)"],
                normalize_company=True,
            )
        )
        dictionary = CompanyDictionary({"HAPAG-LLOYD AG": "Hapag-Lloyd"})
        result = Extractor(config, [profile], dictionary=dictionary).extract(pdfs["invoice"])
        assert result.value("company") == "Hapag-Lloyd"

    def test_tra_cuu_master_data_sinh_them_field(self, config, pdfs):
        from src.core.masterdata import MasterDataStore

        profile = invoice_profile()
        profile.fields.append(
            FieldSpec(
                name="ma_kh",
                patterns=[r"(KH\d{3})"],
                masterdata=MasterDataLookup(
                    source=str(pdfs["masterdata"]),
                    key_column="Ma KH",
                    value_column="Ten cong ty",
                    target_field="ten_kh",
                ),
            )
        )
        # Ghép mã KH vào text bằng cách dùng chính profile trên file có sẵn: dùng regex giả
        profile.fields[-1].patterns = [r"(ACME)"]
        profile.fields[-1].masterdata.key_column = "Ten cong ty"
        profile.fields[-1].masterdata.value_column = "MST"

        store = MasterDataStore()
        result = Extractor(config, [profile], masterdata=store).extract(pdfs["invoice"])
        # "ACME" không có trong cột tra cứu -> không sinh field, nhưng KHÔNG được lỗi
        assert "ten_kh" not in result.fields
        assert result.value("number") == "INV-2026-00871"

    def test_master_data_thieu_file_chi_canh_bao(self, config, pdfs):
        from src.core.masterdata import MasterDataStore

        profile = invoice_profile()
        profile.fields.append(
            FieldSpec(
                name="ma_kh",
                patterns=[r"(ACME)"],
                masterdata=MasterDataLookup(
                    source="Z:/khong-ton-tai.xlsx",
                    key_column="A",
                    value_column="B",
                    target_field="ten_kh",
                ),
            )
        )
        result = Extractor(config, [profile], masterdata=MasterDataStore()).extract(pdfs["invoice"])
        assert any("Master data" in w for w in result.warnings)
        assert result.value("number") == "INV-2026-00871"  # batch vẫn chạy bình thường


class TestDeterminism:
    def test_cung_file_cung_rule_ra_cung_ket_qua(self, config, pdfs):
        ex = Extractor(config, [invoice_profile()])
        first = ex.extract(pdfs["invoice"])
        second = ex.extract(pdfs["invoice"])
        assert {k: v.value for k, v in first.fields.items()} == {
            k: v.value for k, v in second.fields.items()
        }

    def test_provenance_duoc_ghi_day_du(self, config, pdfs):
        result = Extractor(config, [invoice_profile()]).extract(pdfs["invoice"])
        f = result.fields["number"]
        assert f.layer == Layer.REGEX
        assert f.rule_id == "pattern[0]"
        assert f.page == 0
        assert f.bbox is not None  # định vị được trên trang
        assert f.raw_value


class TestProfileSelection:
    def test_dung_profile_chung_khi_khong_match(self, config, pdfs, profiles):
        result = Extractor(config, profiles).extract(pdfs["unknown"])
        assert result.profile_name == "Chung"

    def test_bo_profile_mau_di_kem_chay_dung_tren_fixture(self, config, pdfs, profiles):
        result = Extractor(config, profiles).extract(pdfs["bill_of_lading"])
        assert result.profile_name == "Bill of Lading"
        assert result.value("number") == "HLCUSGN2412345"
        assert result.value("container") == "MSKU2482484"


class TestLayerGating:
    """Cổng chặn tầng 2–4: thiếu field bắt buộc HOẶC còn field tùy chọn khai báo tầng đó."""

    def _barcode_profile(self, **kw) -> Profile:
        p = Profile(
            id="bl-opt",
            name="BL",
            doctype="BL",
            conditions=[MatchCondition(value="BILL OF LADING")],
            fields=[
                FieldSpec(
                    name="number",
                    required=True,
                    patterns=[r"B/L\s*No\.?\s*:?\s*([A-Z0-9]+)"],
                ),
                FieldSpec(
                    name="container",
                    label="Số container",
                    required=False,  # TÙY CHỌN — điểm mấu chốt của thay đổi này
                    from_barcode=True,
                    validate="container",
                ),
            ],
            template="{number}_{container}",
        )
        for k, v in kw.items():
            setattr(p, k, v)
        return p

    def test_field_tuy_chon_van_duoc_dien_boi_tang_barcode(self, config, pdfs):
        from src.core.barcode import AVAILABLE

        if not AVAILABLE:
            pytest.skip("pyzbar không dùng được trên máy này")

        result = Extractor(config, [self._barcode_profile()]).extract(pdfs["barcode"])
        assert result.value("number") == "ONEYSGNF1234567"  # field bắt buộc đã có từ tầng 1
        assert result.value("container") == "MSKU2482484"  # nhưng tầng 3 vẫn chạy
        assert Layer.BARCODE in result.layers_used

    def test_tat_toggle_thi_quay_ve_hanh_vi_tiet_kiem(self, config, pdfs):
        profile = self._barcode_profile(fill_optional_fields=False)
        result = Extractor(config, [profile]).extract(pdfs["barcode"])
        assert result.value("number") == "ONEYSGNF1234567"
        assert result.value("container") == ""
        assert Layer.BARCODE not in result.layers_used

    def test_toggle_tat_van_chay_khi_thieu_field_bat_buoc(self, config, pdfs):
        profile = self._barcode_profile(fill_optional_fields=False)
        profile.fields[0].patterns = [r"KHONG-BAO-GIO-TRUNG (\w+)"]
        profile.fields[1].required = True
        result = Extractor(config, [profile]).extract(pdfs["barcode"])
        assert result.value("container") == "MSKU2482484"

    def test_zonal_dien_field_tuy_chon(self, config, pdfs):
        profile = invoice_profile()
        profile.fields[1].patterns = []  # doc_date là field tùy chọn
        profile.fields[1].zone = Zone(page=0, x0=0.0, y0=0.0, x1=1.0, y1=1.0)
        profile.fields[1].validate = "none"

        result = Extractor(config, [profile]).extract(pdfs["invoice"])
        assert result.value("number") == "INV-2026-00871"  # bắt buộc đã đủ từ tầng 1
        assert "15/03/2026" in result.value("doc_date")  # tầng 2 vẫn chạy cho field tùy chọn
        assert Layer.ZONAL in result.layers_used

    def test_metadata_dien_field_tuy_chon(self, config, pdfs):
        profile = invoice_profile()
        profile.fields.append(FieldSpec(name="tieu_de", label="Tiêu đề", metadata_key="Title"))
        result = Extractor(config, [profile]).extract(pdfs["invoice"])
        assert "INV-2026-00871" in result.value("tieu_de")
        assert Layer.METADATA in result.layers_used

    def test_khong_co_field_nao_khai_bao_thi_khong_chay_tang_do(self, config, pdfs):
        # Profile không có field nào dùng barcode/metadata -> không tốn công quét
        profile = invoice_profile()
        result = Extractor(config, [profile]).extract(pdfs["invoice"])
        assert Layer.BARCODE not in result.layers_used
        assert Layer.METADATA not in result.layers_used
        assert Layer.ZONAL not in result.layers_used

    def test_tang_5_ai_van_giu_cong_chan_nghiem(self, config, pdfs):
        # AI KHÔNG được nới lỏng: đủ field bắt buộc là không gọi, dù còn field tùy chọn trống
        config.ai.enabled = True
        profile = invoice_profile()
        profile.ai_enabled = True
        profile.fields.append(FieldSpec(name="ghi_chu", label="Ghi chú"))  # tùy chọn, trống

        client = fake_ai_client({"ghi_chu": "AI KHONG DUOC GOI"})
        result = Extractor(config, [profile], ai_client=client).extract(pdfs["invoice"])
        assert result.value("ghi_chu") == ""
        assert Layer.AI not in result.layers_used

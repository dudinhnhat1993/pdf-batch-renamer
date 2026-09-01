"""Test tầng 5: dựng prompt, bóc JSON, và validate output của AI."""

from __future__ import annotations

import json

from src.core.ai_client import (
    AiClient,
    AiSettings,
    FewShotExample,
    build_messages,
    parse_response,
    validate_ai_fields,
)
from src.core.models import FieldSpec, Profile


def profile() -> Profile:
    return Profile(
        id="inv",
        name="Invoice",
        doctype="INV",
        fields=[
            FieldSpec(name="number", label="Số hóa đơn", validate="regex",
                      validate_regex=r"^INV-\d+$"),
            FieldSpec(name="doc_date", label="Ngày", validate="date"),
            FieldSpec(name="container", label="Container", validate="container"),
        ],
        date_formats=["dd/mm/yyyy"],
    )


class TestBuildMessages:
    def test_co_system_prompt_cam_bia_gia_tri(self):
        messages = build_messages(profile(), "van ban", ["number"])
        assert messages[0]["role"] == "system"
        assert "không đoán" in messages[0]["content"]

    def test_liet_ke_dung_field_con_thieu(self):
        messages = build_messages(profile(), "van ban", ["number"])
        instruction = messages[1]["content"]
        assert '"number"' in instruction and '"container"' not in instruction

    def test_them_goi_y_cho_field_ngay_va_container(self):
        instruction = build_messages(profile(), "x", ["doc_date", "container"])[1]["content"]
        assert "dd/mm/yyyy" in instruction
        assert "ISO 6346" in instruction

    def test_few_shot_tu_vi_du_da_duyet(self):
        examples = [FewShotExample(text="VAN BAN MAU", fields={"number": "INV-1"})]
        messages = build_messages(profile(), "van ban", ["number"], examples)
        assistant = [m for m in messages if m["role"] == "assistant"]
        assert len(assistant) == 1
        assert json.loads(assistant[0]["content"]) == {"number": "INV-1"}

    def test_cat_bot_text_qua_dai(self):
        messages = build_messages(profile(), "X" * 50000, ["number"], max_chars=100)
        assert len(messages[-1]["content"]) < 200


class TestParseResponse:
    def test_json_thuan(self):
        assert parse_response('{"number": "INV-1"}') == {"number": "INV-1"}

    def test_json_boc_trong_markdown(self):
        assert parse_response('```json\n{"number": "INV-1"}\n```') == {"number": "INV-1"}

    def test_json_lan_trong_van_ban(self):
        assert parse_response('Day la ket qua: {"number": "INV-1"} het.') == {"number": "INV-1"}

    def test_json_hong_tra_dict_rong(self):
        assert parse_response("khong phai json") == {}
        assert parse_response("") == {}
        assert parse_response('{"number": }') == {}

    def test_gia_tri_null_thanh_chuoi_rong(self):
        assert parse_response('{"number": null}') == {"number": ""}

    def test_json_khong_phai_object(self):
        assert parse_response("[1, 2, 3]") == {}


class TestValidateAiFields:
    def test_nhan_field_hop_le(self):
        accepted, rejected = validate_ai_fields(profile(), {"number": "INV-123"}, ["number"])
        assert accepted == {"number": "INV-123"} and rejected == []

    def test_loai_field_khong_qua_validate_regex(self):
        accepted, rejected = validate_ai_fields(profile(), {"number": "SAI"}, ["number"])
        assert accepted == {} and rejected == ["number"]

    def test_loai_container_sai_check_digit(self):
        accepted, rejected = validate_ai_fields(
            profile(), {"container": "CSQU3054384"}, ["container"]
        )
        assert accepted == {} and "container" in rejected

    def test_nhan_container_dung_va_chuan_hoa(self):
        accepted, _ = validate_ai_fields(profile(), {"container": "csqu 305438 3"}, ["container"])
        assert accepted == {"container": "CSQU3054383"}

    def test_loai_ngay_khong_hop_le(self):
        accepted, rejected = validate_ai_fields(profile(), {"doc_date": "31/02/2026"}, ["doc_date"])
        assert accepted == {} and "doc_date" in rejected

    def test_loai_field_khong_khai_bao_trong_profile(self):
        accepted, rejected = validate_ai_fields(profile(), {"tu_bia_ra": "X"}, ["number"])
        assert accepted == {} and rejected == ["tu_bia_ra"]

    def test_loai_gia_tri_rong(self):
        accepted, rejected = validate_ai_fields(profile(), {"number": "   "}, ["number"])
        assert accepted == {} and rejected == ["number"]


class TestAiClient:
    def test_chua_cau_hinh_thi_khong_goi(self):
        client = AiClient(AiSettings())
        assert client.configured is False
        assert client.complete([{"role": "user", "content": "x"}]) == ""

    def test_endpoint_tu_them_duong_dan(self):
        client = AiClient(AiSettings(base_url="https://api.deepseek.com/v1", model="m"))
        assert client._endpoint() == "https://api.deepseek.com/v1/chat/completions"

    def test_endpoint_giu_nguyen_neu_da_day_du(self):
        client = AiClient(AiSettings(base_url="http://x/v1/chat/completions", model="m"))
        assert client._endpoint() == "http://x/v1/chat/completions"

    def test_loi_mang_khong_lam_chet_batch(self):
        def boom(url, payload, headers, timeout):
            raise ConnectionError("mat mang")

        client = AiClient(AiSettings(base_url="http://x", model="m"), transport=boom)
        assert client.complete([]) == ""

    def test_gui_api_key_trong_header(self):
        seen = {}

        def transport(url, payload, headers, timeout):
            seen.update(headers)
            return {"choices": [{"message": {"content": "{}"}}]}

        client = AiClient(
            AiSettings(base_url="http://x", model="m", api_key="secret"), transport=transport
        )
        client.complete([])
        assert seen["Authorization"] == "Bearer secret"

    def test_extract_tra_ve_field_da_validate(self):
        def transport(url, payload, headers, timeout):
            content = json.dumps({"number": "INV-9", "container": "SAI"})
            return {"choices": [{"message": {"content": content}}]}

        client = AiClient(AiSettings(base_url="http://x", model="m"), transport=transport)
        accepted, rejected = client.extract(profile(), "van ban", ["number", "container"])
        assert accepted == {"number": "INV-9"}
        assert rejected == ["container"]

    def test_temperature_0_de_giu_deterministic(self):
        seen = {}

        def transport(url, payload, headers, timeout):
            seen.update(payload)
            return {"choices": [{"message": {"content": "{}"}}]}

        AiClient(AiSettings(base_url="http://x", model="m"), transport=transport).complete([])
        assert seen["temperature"] == 0.0
        assert seen["stream"] is False

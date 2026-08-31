"""Test Learning Loop đầy đủ: sửa tay -> đề xuất rule -> duyệt -> regression -> vào profile.

Nguyên tắc bất biến được kiểm chứng ở đây: KHÔNG đường nào tự ghi vào profile khi người
dùng chưa bấm duyệt.
"""

from __future__ import annotations

import os
import shutil

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QMessageBox  # noqa: E402
from src.core.learning import LearningStore  # noqa: E402
from src.core.models import FieldSpec, MatchCondition, Profile  # noqa: E402
from src.core.pipeline import Pipeline  # noqa: E402
from src.core.rules import ProfileStore  # noqa: E402
from src.ui.correction_dialog import (  # noqa: E402
    CorrectionRuleDialog,
    propose_zone,
    read_document,
)


@pytest.fixture
def store(tmp_path) -> ProfileStore:
    s = ProfileStore(tmp_path / "profiles", tmp_path / "profiles" / "_versions")
    s.save(
        Profile(
            id="inv",
            name="Invoice",
            doctype="INV",
            conditions=[MatchCondition(value="COMMERCIAL INVOICE")],
            fields=[
                FieldSpec(
                    name="number",
                    label="Số hóa đơn",
                    required=True,
                    patterns=[r"Invoice\s*No\.?\s*:?\s*([A-Z0-9\-]+)"],
                )
            ],
            template="{number}",
        )
    )
    return s


@pytest.fixture
def job(config, profiles, db, pdfs, tmp_path):
    folder = tmp_path / "in"
    folder.mkdir()
    shutil.copy2(pdfs["invoice"], folder / "inv.pdf")
    pipeline = Pipeline(config, profiles, db)
    return pipeline.plan([folder])[0]


class TestDocLaiFile:
    def test_doc_duoc_text(self, config, pdfs):
        document = read_document(config, pdfs["invoice"])
        assert document is not None
        assert "INV-2026-00871" in document.text

    def test_file_hong_khong_lam_chet(self, config, tmp_path):
        bad = tmp_path / "khong-phai.pdf"
        bad.write_bytes(b"day khong phai pdf")
        assert read_document(config, bad) is None


class TestDeXuatVung:
    def test_de_xuat_vung_quanh_gia_tri(self, config, pdfs):
        document = read_document(config, pdfs["invoice"])
        proposal = propose_zone(document, "INV-2026-00871")
        assert proposal is not None
        zone, preview = proposal
        assert 0.0 <= zone.x0 < zone.x1 <= 1.0
        assert "INV-2026-00871" in preview

    def test_gia_tri_khong_co_tren_trang(self, config, pdfs):
        document = read_document(config, pdfs["invoice"])
        assert propose_zone(document, "KHONG-CO-GIA-TRI-NAY") is None


class TestCorrectionRuleDialog:
    def _dialog(self, qapp, config, store, job, value="INV-2026-00871"):
        return CorrectionRuleDialog(config, store, store.get("inv"), job, "number", value)

    def test_de_xuat_ca_regex_lan_vung(self, qapp, config, store, job):
        dialog = self._dialog(qapp, config, store, job)
        kinds = {kind for _b, kind, _p in dialog._options}
        assert "regex" in kinds and "zone" in kinds

    def test_chay_thu_ngay_tren_file_do(self, qapp, config, store, job):
        dialog = self._dialog(qapp, config, store, job)
        assert dialog.test_result.text().startswith("OK —")

    def test_giu_cach_tim_cu_lam_du_phong(self, qapp, config, store, job):
        dialog = self._dialog(qapp, config, store, job)
        dialog.keep_old.setChecked(True)
        spec = dialog.build_field()
        assert len(spec.patterns) >= 2  # cách mới + cách cũ

    def test_bo_cach_cu_khi_khong_giu(self, qapp, config, store, job):
        dialog = self._dialog(qapp, config, store, job)
        dialog.keep_old.setChecked(False)
        spec = dialog.build_field()
        assert len(spec.patterns) == 1

    def test_chon_vung_thi_field_co_zone(self, qapp, config, store, job):
        dialog = self._dialog(qapp, config, store, job)
        for button, kind, _payload in dialog._options:
            if kind == "zone":
                button.setChecked(True)
                break
        spec = dialog.build_field()
        assert spec.zone is not None
        assert spec.zone_filter == "none"

    def test_khong_tu_ghi_vao_profile_khi_chua_duyet(self, qapp, config, store, job):
        before = store.get("inv").version
        self._dialog(qapp, config, store, job)  # chỉ mở hộp thoại, không bấm gì
        assert store.get("inv").version == before
        assert store.get("inv").fields[0].patterns == [
            r"Invoice\s*No\.?\s*:?\s*([A-Z0-9\-]+)"
        ]

    def test_duyet_thi_them_vao_profile_va_tao_version_moi(
        self, qapp, config, store, job, monkeypatch
    ):
        monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
        dialog = self._dialog(qapp, config, store, job)
        dialog._approve()

        saved = store.get("inv")
        assert dialog.saved_profile is not None
        assert saved.version == 2
        assert len(saved.fields[0].patterns) >= 2

    def test_gia_tri_la_thi_khong_de_xuat_duoc(self, qapp, config, store, job):
        dialog = self._dialog(qapp, config, store, job, value="GIA-TRI-KHONG-CO-TRONG-FILE")
        assert dialog._options == []
        assert not dialog.ok_button.isEnabled()

    def test_regression_kem_di_thi_hoi_lai(self, qapp, config, store, job, pdfs, monkeypatch):
        monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)

        # Gắn file mẫu và ép cách tìm mới làm hỏng field -> regression phải phát hiện
        profile = store.get("inv")
        profile.samples = [str(pdfs["invoice"])]
        store.save(profile, bump_version=False)

        dialog = self._dialog(qapp, config, store, job)
        dialog.keep_old.setChecked(False)
        for button, kind, payload in dialog._options:
            if kind == "regex":
                payload.pattern = r"KHONG-BAO-GIO-TRUNG (\w+)"
                button.setChecked(True)
                break

        asked = []

        def fake_warning(*args, **kwargs):
            asked.append(args)
            return QMessageBox.StandardButton.Cancel

        monkeypatch.setattr(QMessageBox, "warning", fake_warning)
        dialog._approve()

        assert asked, "phải cảnh báo khi rule mới làm field kém đi"
        assert store.get("inv").version == 1  # tôn trọng Hủy


class TestDatasetTuCorrection:
    def test_duyet_correction_ghi_dataset_co_text(self, db):
        learning = LearningStore(db)
        cid = learning.record_correction(
            field_name="number", old_value="A1", new_value="A2", profile_id="inv"
        )
        learning.approve_correction(
            cid,
            text="COMMERCIAL INVOICE\nInvoice No.: A2",
            fields={"number": "A2"},
            profile_id="inv",
            rule_version=3,
        )

        rows = learning.corrections(profile_id="inv", status="approved")
        assert len(rows) == 1

        examples = learning.few_shot_examples("inv")
        assert examples and examples[0].fields == {"number": "A2"}
        assert "Invoice No.: A2" in examples[0].text

    def test_chua_duyet_thi_khong_vao_dataset(self, db):
        learning = LearningStore(db)
        learning.record_correction(
            field_name="number", old_value="A1", new_value="A2", profile_id="inv"
        )
        assert learning.few_shot_examples("inv") == []

    def test_duyet_khong_co_text_thi_khong_ghi_dataset(self, db):
        learning = LearningStore(db)
        cid = learning.record_correction(
            field_name="number", old_value="", new_value="A2", profile_id="inv"
        )
        learning.approve_correction(cid, text="", fields={"number": "A2"}, profile_id="inv")
        assert learning.few_shot_examples("inv") == []
        assert learning.correction(cid)["status"] == "approved"

    def test_few_shot_di_thang_vao_prompt_cua_tang_5(self, db):
        """Correction đã duyệt phải xuất hiện trong prompt gửi cho AI."""
        from src.core.ai_client import build_messages

        learning = LearningStore(db)
        cid = learning.record_correction(
            field_name="number", old_value="", new_value="INV-9", profile_id="inv"
        )
        learning.approve_correction(
            cid,
            text="COMMERCIAL INVOICE\nInvoice No.: INV-9",
            fields={"number": "INV-9"},
            profile_id="inv",
        )

        profile = Profile(id="inv", name="Invoice", fields=[FieldSpec(name="number")])
        messages = build_messages(
            profile, "van ban moi", ["number"], learning.few_shot_examples("inv")
        )
        assistant = [m for m in messages if m["role"] == "assistant"]
        assert assistant and "INV-9" in assistant[0]["content"]

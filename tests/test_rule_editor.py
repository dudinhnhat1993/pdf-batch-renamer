"""Test Rule Editor: bật/tắt, nhân bản, kéo-thả ưu tiên, file mẫu, version + regression."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QMessageBox  # noqa: E402
from src.core.learning import LearningStore  # noqa: E402
from src.core.models import FieldSpec, MatchCondition, Profile  # noqa: E402
from src.core.rules import ProfileStore  # noqa: E402
from src.ui.rule_editor import MAX_SAMPLES, RuleEditorDialog  # noqa: E402


@pytest.fixture
def store(tmp_path) -> ProfileStore:
    s = ProfileStore(tmp_path / "profiles", tmp_path / "profiles" / "_versions")
    s.save(
        Profile(
            id="bl", name="Bill of Lading", doctype="BL", priority=10,
            conditions=[MatchCondition(value="BILL OF LADING")],
            fields=[FieldSpec(name="number", label="Số B/L", required=True,
                              patterns=[r"B/L\s*No\.[\s:.\-#]*([A-Z0-9]+)"])],
            template="{number}",
        )
    )
    s.save(
        Profile(
            id="inv", name="Invoice", doctype="INV", priority=20,
            conditions=[MatchCondition(value="INVOICE")],
            fields=[FieldSpec(name="number", label="Số hóa đơn",
                              patterns=[r"Invoice No\.[\s:.\-#]*([A-Z0-9\-]+)"])],
            template="{number}",
        )
    )
    s.save(Profile(id="chung", name="Chung", doctype="DOC", priority=999, is_fallback=True))
    return s


@pytest.fixture
def editor(qapp, config, store, db):
    dialog = RuleEditorDialog(config, store, LearningStore(db))
    yield dialog
    dialog.close()


def row_of(editor: RuleEditorDialog, profile_id: str) -> int:
    for i in range(editor.profile_list.count()):
        if editor.profile_list.item(i).data(Qt.ItemDataRole.UserRole) == profile_id:
            return i
    raise AssertionError(f"không thấy profile {profile_id}")


class TestDanhSach:
    def test_hien_du_profile_theo_thu_tu_uu_tien(self, editor):
        names = [editor.profile_list.item(i).text() for i in range(editor.profile_list.count())]
        assert len(names) == 3
        assert names[0].startswith("Bill of Lading")
        assert names[-1].startswith("Chung")

    def test_hien_version_va_so_file_da_match(self, editor):
        assert "v1" in editor.profile_list.item(0).text()
        assert "30 ngày" in editor.profile_list.item(0).text()

    def test_chon_dong_thi_nap_chi_tiet(self, editor):
        editor.profile_list.setCurrentRow(row_of(editor, "inv"))
        assert editor.name.text() == "Invoice"
        assert editor.doctype.text() == "INV"
        assert editor.conditions.list.count() == 1


class TestBatTat:
    def test_bo_tick_la_tat_profile_va_luu_ngay(self, editor, store):
        item = editor.profile_list.item(row_of(editor, "inv"))
        item.setCheckState(Qt.CheckState.Unchecked)
        assert store.get("inv").enabled is False

    def test_tick_lai_la_bat(self, editor, store):
        item = editor.profile_list.item(row_of(editor, "inv"))
        item.setCheckState(Qt.CheckState.Unchecked)
        item.setCheckState(Qt.CheckState.Checked)
        assert store.get("inv").enabled is True

    def test_bat_tat_khong_tao_version_moi(self, editor, store):
        before = store.get("inv").version
        editor.profile_list.item(row_of(editor, "inv")).setCheckState(Qt.CheckState.Unchecked)
        assert store.get("inv").version == before


class TestThuTuUuTien:
    def test_keo_tha_ghi_lai_so_uu_tien(self, editor, store):
        # Đảo thứ tự: Invoice lên đầu, B/L xuống sau
        editor.profiles = [store.get("inv"), store.get("bl"), store.get("chung")]
        editor._loading = True
        editor.profile_list.clear()
        for p in editor.profiles:
            from PySide6.QtWidgets import QListWidgetItem

            item = QListWidgetItem(p.name)
            item.setData(Qt.ItemDataRole.UserRole, p.id)
            editor.profile_list.addItem(item)
        editor._loading = False

        editor._on_rows_moved()
        assert store.get("inv").priority < store.get("bl").priority

    def test_profile_du_phong_luon_o_cuoi(self, editor, store):
        editor._on_rows_moved()
        assert store.get("chung").priority == 999


class TestNhanBan:
    def test_ban_sao_duoc_tat_san(self, editor, store, monkeypatch):
        monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
        editor.profile_list.setCurrentRow(row_of(editor, "inv"))
        editor._duplicate()

        clones = [p for p in store.load_all() if p.name.endswith("(bản sao)")]
        assert len(clones) == 1
        assert clones[0].enabled is False  # không tranh match với bản gốc
        assert clones[0].id != "inv"
        assert clones[0].fields[0].name == "number"

    def test_ban_sao_co_lich_su_version_rieng(self, editor, store, monkeypatch):
        monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
        editor.profile_list.setCurrentRow(row_of(editor, "inv"))
        editor._duplicate()
        clone = next(p for p in store.load_all() if p.name.endswith("(bản sao)"))
        assert store.versions(clone.id) == [1]


class TestXoa:
    def test_khong_cho_xoa_profile_du_phong(self, editor, store, monkeypatch):
        warned = []
        monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warned.append(a))
        editor.profile_list.setCurrentRow(row_of(editor, "chung"))
        editor._delete()
        assert warned and store.get("chung") is not None

    def test_xoa_profile_thuong(self, editor, store, monkeypatch):
        monkeypatch.setattr(
            QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes
        )
        editor.profile_list.setCurrentRow(row_of(editor, "inv"))
        editor._delete()
        assert store.get("inv") is None
        assert store.versions("inv") == [1]  # lịch sử vẫn còn trên đĩa


class TestFileMau:
    def test_gioi_han_5_file(self, editor, pdfs, monkeypatch):
        infos = []
        monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: infos.append(a))
        editor.profile_list.setCurrentRow(row_of(editor, "inv"))

        from PySide6.QtWidgets import QListWidgetItem

        for i in range(MAX_SAMPLES):
            item = QListWidgetItem(f"mau{i}.pdf")
            item.setData(Qt.ItemDataRole.UserRole, f"C:/mau{i}.pdf")
            editor.samples.addItem(item)

        editor._add_sample()
        assert infos, "phải báo đã đủ file mẫu"
        assert editor.samples.count() == MAX_SAMPLES

    def test_file_mau_duoc_luu_cung_profile(self, editor, store, pdfs, monkeypatch):
        monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
        editor.profile_list.setCurrentRow(row_of(editor, "inv"))

        from PySide6.QtWidgets import QListWidgetItem

        item = QListWidgetItem(pdfs["invoice"].name)
        item.setData(Qt.ItemDataRole.UserRole, str(pdfs["invoice"]))
        editor.samples.addItem(item)

        editor._save_current()
        assert store.get("inv").samples == [str(pdfs["invoice"])]


class TestLuuVaRegression:
    def test_luu_tao_version_moi(self, editor, store, monkeypatch):
        monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
        editor.profile_list.setCurrentRow(row_of(editor, "inv"))
        editor.template.setText("{doctype}_{number}")
        editor._save_current()

        saved = store.get("inv")
        assert saved.version == 2 and saved.template == "{doctype}_{number}"

    def test_khong_cho_luu_profile_thuong_khong_co_dieu_kien(self, editor, store, monkeypatch):
        warned = []
        monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warned.append(a))
        editor.profile_list.setCurrentRow(row_of(editor, "inv"))
        editor.conditions.list.clear()
        editor._save_current()

        assert warned
        assert store.get("inv").version == 1  # không lưu gì cả

    def _barcode_editor(self, config, store, db, pdfs):
        """Profile B/L có field container lấy từ barcode — tắt toggle là mất field đó."""
        from src.core.barcode import AVAILABLE

        if not AVAILABLE:
            pytest.skip("pyzbar không dùng được trên máy này")

        store.save(
            Profile(
                id="bl-bc", name="BL barcode", doctype="BL", priority=5,
                conditions=[MatchCondition(value="BILL OF LADING")],
                fields=[
                    FieldSpec(name="number", label="Số B/L", required=True,
                              patterns=[r"B/L\s*No\.[\s:.\-#]*([A-Z0-9]+)"]),
                    FieldSpec(name="container", label="Số container",
                              from_barcode=True, validate="container"),
                ],
                template="{number}_{container}",
                samples=[str(pdfs["barcode"])],
            )
        )
        dialog = RuleEditorDialog(config, store, LearningStore(db))
        dialog.profile_list.setCurrentRow(row_of(dialog, "bl-bc"))
        return dialog

    def test_tat_toggle_lam_mat_field_thi_canh_bao_va_ton_trong_huy(
        self, qapp, config, store, db, pdfs, monkeypatch
    ):
        monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
        editor = self._barcode_editor(config, store, db, pdfs)
        try:
            asked = []

            def fake_warning(*args, **kwargs):
                asked.append(args)
                return QMessageBox.StandardButton.Cancel

            monkeypatch.setattr(QMessageBox, "warning", fake_warning)

            editor.fill_optional.setChecked(False)  # container sẽ không còn được điền
            editor._save_current()

            assert asked, "phải cảnh báo vì có field match kém đi"
            assert "Số container" in str(asked[0])
            assert store.get("bl-bc").fill_optional_fields is True  # đã tôn trọng Hủy
            assert store.get("bl-bc").version == 1
        finally:
            editor.close()

    def test_van_luu_duoc_khi_nguoi_dung_xac_nhan(
        self, qapp, config, store, db, pdfs, monkeypatch
    ):
        monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
        monkeypatch.setattr(
            QMessageBox, "warning", lambda *a, **k: QMessageBox.StandardButton.Save
        )
        editor = self._barcode_editor(config, store, db, pdfs)
        try:
            editor.fill_optional.setChecked(False)
            editor._save_current()
            saved = store.get("bl-bc")
            assert saved.fill_optional_fields is False and saved.version == 2
        finally:
            editor.close()

    def test_regression_bao_ro_field_nao_kem_di(self, config, store, pdfs):
        from src.core.regression import run_regression

        old = store.get("inv")
        old.samples = [str(pdfs["invoice"])]
        new = Profile.from_dict(old.to_dict())
        new.version = 2
        new.fields[0].patterns = [r"KHONG-BAO-GIO-TRUNG (\w+)"]

        report = run_regression(old, new, old.samples, config=config)
        assert report.has_regression
        assert "Số hóa đơn" in report.summary_vi()
        assert "[KÉM]" in report.summary_vi()


class TestRollback:
    def test_quay_ve_version_cu_tao_version_moi(self, editor, store, monkeypatch):
        monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
        monkeypatch.setattr(
            QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes
        )
        editor.profile_list.setCurrentRow(row_of(editor, "inv"))
        editor.template.setText("{doctype}_{number}")
        editor._save_current()
        assert store.get("inv").version == 2

        # Chọn v1 trong danh sách version rồi rollback
        for i in range(editor.versions.count()):
            if editor.versions.item(i).data(Qt.ItemDataRole.UserRole) == 1:
                editor.versions.setCurrentRow(i)
                break
        editor._rollback()

        restored = store.get("inv")
        assert restored.version == 3  # rollback vẫn là 1 thay đổi
        assert restored.template == "{number}"  # nội dung quay về như v1
        assert store.versions("inv") == [1, 2, 3]  # lịch sử không mất

    def test_chua_chon_version_thi_bao(self, editor, monkeypatch):
        infos = []
        monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: infos.append(a))
        editor.profile_list.setCurrentRow(row_of(editor, "inv"))
        editor.versions.setCurrentRow(-1)
        editor._rollback()
        assert infos


class TestDieuKienLoaiTru:
    def test_them_va_luu_dieu_kien_loai_tru(self, editor, store, monkeypatch):
        monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
        editor.profile_list.setCurrentRow(row_of(editor, "inv"))

        editor.excludes.input.setText("PACKING LIST")
        editor.excludes._add()
        editor._save_current()

        saved = store.get("inv")
        assert [c.value for c in saved.exclude_conditions] == ["PACKING LIST"]
        assert saved.exclude_conditions[0].kind == "keyword"

    def test_them_dieu_kien_dang_regex(self, editor, store, monkeypatch):
        monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
        editor.profile_list.setCurrentRow(row_of(editor, "inv"))

        editor.excludes.kind.setCurrentIndex(1)  # regex
        editor.excludes.input.setText(r"\bPROFORMA\b")
        editor.excludes._add()
        editor._save_current()

        saved = store.get("inv")
        assert saved.exclude_conditions[0].kind == "regex"

    def test_toggle_dien_du_field_tuy_chon_duoc_luu(self, editor, store, monkeypatch):
        monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
        editor.profile_list.setCurrentRow(row_of(editor, "inv"))
        editor.fill_optional.setChecked(False)
        editor._save_current()
        assert store.get("inv").fill_optional_fields is False

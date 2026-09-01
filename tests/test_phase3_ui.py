"""Test GUI Phase 3: master data trong Rule Editor, rule pack, watch folder, thống kê."""

from __future__ import annotations

import os
import shutil

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QMessageBox  # noqa: E402
from src.core.bootstrap import build_context  # noqa: E402
from src.core.learning import LearningStore  # noqa: E402
from src.core.models import FieldSpec, MatchCondition, Profile  # noqa: E402
from src.core.rules import ProfileStore  # noqa: E402
from src.ui.main_window import MainWindow  # noqa: E402
from src.ui.rule_editor import RuleEditorDialog  # noqa: E402
from src.ui.stats_dialog import StatsDialog  # noqa: E402


@pytest.fixture
def store(tmp_path) -> ProfileStore:
    s = ProfileStore(tmp_path / "profiles", tmp_path / "profiles" / "_versions")
    s.save(
        Profile(
            id="inv",
            name="Invoice",
            doctype="INV",
            conditions=[MatchCondition(value="INVOICE")],
            fields=[
                FieldSpec(name="ma_kh", label="Mã khách hàng", patterns=[r"(KH\d{3})"]),
                FieldSpec(name="number", label="Số hóa đơn", patterns=[r"INV-(\d+)"]),
            ],
            template="{number}",
        )
    )
    return s


@pytest.fixture
def editor(qapp, config, store, db):
    dialog = RuleEditorDialog(config, store, LearningStore(db))
    dialog.profile_list.setCurrentRow(0)
    yield dialog
    dialog.close()


def select_md_field(editor: RuleEditorDialog, name: str) -> None:
    index = [editor.md_field.itemData(i) for i in range(editor.md_field.count())].index(name)
    editor.md_field.setCurrentIndex(index)


class TestMasterDataTrongGui:
    def test_liet_ke_field_cua_profile(self, editor):
        names = [editor.md_field.itemData(i) for i in range(editor.md_field.count())]
        assert names == ["ma_kh", "number"]

    def test_khai_bao_va_luu_duoc(self, editor, store, pdfs, monkeypatch):
        monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
        select_md_field(editor, "ma_kh")
        editor.md_source.setText(str(pdfs["masterdata"]))
        editor.md_key.setText("Ma KH")
        editor.md_value.setText("Ten cong ty")
        editor.md_target.setText("ten_kh")
        editor._save_current()

        spec = store.get("inv").field_by_name("ma_kh")
        assert spec.masterdata is not None
        assert spec.masterdata.key_column == "Ma KH"
        assert spec.masterdata.target_field == "ten_kh"

    def test_khai_bao_thieu_thi_khong_luu(self, editor, store, monkeypatch):
        monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
        select_md_field(editor, "ma_kh")
        editor.md_key.setText("Ma KH")  # thiếu cột value và target
        editor._save_current()
        assert store.get("inv").field_by_name("ma_kh").masterdata is None

    def test_moi_field_giu_khai_bao_rieng(self, editor, store, pdfs, monkeypatch):
        monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
        select_md_field(editor, "ma_kh")
        editor.md_source.setText(str(pdfs["masterdata"]))
        editor.md_key.setText("Ma KH")
        editor.md_value.setText("Ten cong ty")
        editor.md_target.setText("ten_kh")

        select_md_field(editor, "number")  # chuyển field -> khai báo cũ phải được giữ
        assert editor.md_key.text() == ""

        select_md_field(editor, "ma_kh")
        assert editor.md_key.text() == "Ma KH"

    def test_nut_kiem_tra_bao_so_dong(self, editor, pdfs):
        select_md_field(editor, "ma_kh")
        editor.md_source.setText(str(pdfs["masterdata"]))
        editor.md_key.setText("Ma KH")
        editor.md_value.setText("Ten cong ty")
        editor._test_masterdata()
        assert "Đọc được 3 dòng" in editor.md_status.text()
        # Chưa có file mẫu -> phải nói rõ là chưa chạy thử được, không báo OK suông
        assert "Chưa chạy thử được" in editor.md_status.text()

    def test_nut_kiem_tra_bao_loi_ro_rang(self, editor, pdfs):
        select_md_field(editor, "ma_kh")
        editor.md_source.setText(str(pdfs["masterdata"]))
        editor.md_key.setText("Cot Khong Ton Tai")
        editor.md_value.setText("Ten cong ty")
        editor._test_masterdata()
        assert editor.md_status.text().startswith("Lỗi:")

    def test_khai_bao_chay_that_qua_pipeline(self, editor, store, config, pdfs, monkeypatch):
        """Khai báo trong GUI phải thật sự sinh ra field mới khi chạy pipeline."""
        from src.core.extractor import Extractor
        from src.core.masterdata import MasterDataStore

        monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
        select_md_field(editor, "ma_kh")
        editor.md_source.setText(str(pdfs["masterdata"]))
        editor.md_key.setText("Ten cong ty")
        editor.md_value.setText("MST")
        editor.md_target.setText("mst")
        editor.conditions.input.setText("COMMERCIAL INVOICE")
        editor.conditions._add()
        editor._save_current()

        profile = store.get("inv")
        profile.fields[0].patterns = [r"(Cong ty TNHH Acme Logistics)"]
        # Field ma_kh không có trên hóa đơn mẫu -> dùng regex khớp đúng giá trị trong Excel
        spec = profile.field_by_name("ma_kh")
        assert spec.masterdata.target_field == "mst"

        result = Extractor(config, [profile], masterdata=MasterDataStore()).extract(
            pdfs["invoice"]
        )
        # Hóa đơn mẫu không chứa tên công ty đó nên không sinh field — nhưng KHÔNG được lỗi
        assert "mst" not in result.fields
        assert result.profile_name == "Invoice"


class TestRulePackGui:
    def test_xuat_roi_nhap_lai(self, editor, store, tmp_path, monkeypatch):
        from PySide6.QtWidgets import QFileDialog

        pack = tmp_path / "pack.json"
        monkeypatch.setattr(
            QFileDialog, "getSaveFileName", lambda *a, **k: (str(pack), "JSON (*.json)")
        )
        monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
        editor._export_pack()
        assert pack.exists()

        monkeypatch.setattr(
            QFileDialog, "getOpenFileName", lambda *a, **k: (str(pack), "JSON (*.json)")
        )
        monkeypatch.setattr(
            QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes
        )
        editor._import_pack()

        profiles = store.load_all()
        assert len(profiles) == 2  # bản gốc + bản nhập
        assert any(p.name.endswith("(nhập)") for p in profiles)

    def test_huy_nhap_thi_khong_doi_gi(self, editor, store, tmp_path, monkeypatch):
        from PySide6.QtWidgets import QFileDialog

        pack = tmp_path / "pack.json"
        store.export_pack(pack)
        monkeypatch.setattr(
            QFileDialog, "getOpenFileName", lambda *a, **k: (str(pack), "JSON (*.json)")
        )
        monkeypatch.setattr(
            QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No
        )
        editor._import_pack()
        assert len(store.load_all()) == 1


class TestWatchFolderGui:
    def _window(self, ctx):
        return MainWindow(ctx)

    def test_bat_khi_chua_chon_thu_muc_thi_canh_bao(
        self, qapp, isolated_home, output_root, monkeypatch
    ):
        warned = []
        monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warned.append(a))
        # Cài đặt sẽ mở ra -> chặn lại để test không treo
        monkeypatch.setattr(MainWindow, "_open_settings", lambda self: None)

        ctx = build_context()
        ctx.config.output_root = str(output_root)
        window = self._window(ctx)
        try:
            window.act_watch.setChecked(True)
            assert warned
            assert window.act_watch.isChecked() is False
            assert window.watcher is None
        finally:
            window.close()
            ctx.close()

    def test_bat_va_tat_theo_doi(self, qapp, isolated_home, output_root, tmp_path):
        watch_dir = tmp_path / "inbox"
        watch_dir.mkdir()

        ctx = build_context()
        ctx.config.output_root = str(output_root)
        ctx.config.watch.folder = str(watch_dir)
        window = self._window(ctx)
        try:
            window.act_watch.setChecked(True)
            assert window.watcher is not None
            assert window.watch_pipeline is not None

            window.act_watch.setChecked(False)
            assert window.watcher is None
        finally:
            window.close()
            ctx.close()

    def test_xu_ly_file_moi_va_bao_ve_gui(
        self, qapp, isolated_home, output_root, tmp_path, pdfs
    ):
        watch_dir = tmp_path / "inbox"
        watch_dir.mkdir()

        ctx = build_context()
        ctx.config.output_root = str(output_root)
        ctx.config.watch.folder = str(watch_dir)
        window = self._window(ctx)
        try:
            window.act_watch.setChecked(True)
            messages = []
            window.watch_bridge.processed.connect(messages.append)

            target = watch_dir / "inv.pdf"
            shutil.copy2(pdfs["invoice"], target)
            window._handle_watched_file(target)  # gọi thẳng, không chờ watchdog

            assert messages and "inv.pdf" in messages[0]
            assert list(output_root.rglob("*.pdf")), "file phải được ghi ra output"
        finally:
            window.act_watch.setChecked(False)
            window.close()
            ctx.close()

    def test_dong_app_thi_dung_theo_doi(self, qapp, isolated_home, output_root, tmp_path):
        watch_dir = tmp_path / "inbox"
        watch_dir.mkdir()

        ctx = build_context()
        ctx.config.output_root = str(output_root)
        ctx.config.watch.folder = str(watch_dir)
        window = self._window(ctx)
        window.act_watch.setChecked(True)
        assert window.watcher is not None

        window.close()
        assert window.watcher is None
        ctx.close()


class TestStatsDialog:
    def test_hien_so_lieu_theo_profile(self, qapp, db, bundled_profiles):
        learning = LearningStore(db)
        for _ in range(4):
            learning.record_match("invoice", "success", "a.pdf")
        learning.record_match("invoice", "error", "b.pdf")

        dialog = StatsDialog(learning, bundled_profiles)
        try:
            assert dialog.table.rowCount() == 1
            assert dialog.table.item(0, 0).text() == "Invoice"
            assert dialog.table.item(0, 1).text() == "5"
            assert dialog.table.item(0, 5).text() == "80.0%"
            assert dialog.table.item(0, 6).text() == "Cần để mắt"
            assert "Tổng 5 file" in dialog.summary.text()
        finally:
            dialog.close()

    def test_dem_correction_chua_duyet(self, qapp, db, bundled_profiles):
        learning = LearningStore(db)
        learning.record_match("invoice", "success", "a.pdf")
        learning.record_correction(
            field_name="number", old_value="A", new_value="B", profile_id="invoice"
        )

        dialog = StatsDialog(learning, bundled_profiles)
        try:
            assert "1 chỉnh sửa tay chưa được duyệt" in dialog.summary.text()
        finally:
            dialog.close()

    def test_khong_co_du_lieu_thi_bao_ro(self, qapp, db, bundled_profiles):
        dialog = StatsDialog(learning := LearningStore(db), bundled_profiles)
        try:
            assert dialog.table.rowCount() == 0
            assert "Chưa có dữ liệu" in dialog.summary.text()
            assert learning is not None
        finally:
            dialog.close()

    def test_doi_khoang_thoi_gian(self, qapp, db, bundled_profiles):
        dialog = StatsDialog(LearningStore(db), bundled_profiles)
        try:
            dialog.period.setCurrentIndex(0)  # 7 ngày
            assert dialog.period.currentData() == 7
        finally:
            dialog.close()

    def test_xuat_dataset_jsonl(self, qapp, db, bundled_profiles, tmp_path, monkeypatch):
        from PySide6.QtWidgets import QFileDialog

        learning = LearningStore(db)
        learning.save_dataset_row(
            text="COMMERCIAL INVOICE", fields={"number": "A1"}, profile_id="invoice"
        )
        out = tmp_path / "dataset.jsonl"
        monkeypatch.setattr(
            QFileDialog, "getSaveFileName", lambda *a, **k: (str(out), "JSON Lines (*.jsonl)")
        )
        monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)

        dialog = StatsDialog(learning, bundled_profiles)
        try:
            dialog._export_dataset()
            assert out.exists()
            assert "COMMERCIAL INVOICE" in out.read_text(encoding="utf-8")
        finally:
            dialog.close()


class TestBaoCaoGui:
    def test_xuat_bao_cao_tu_cua_so_chinh(
        self, qapp, isolated_home, output_root, tmp_path, pdfs, monkeypatch
    ):
        from PySide6.QtWidgets import QFileDialog
        from src.core.pipeline import Pipeline

        folder = tmp_path / "in"
        folder.mkdir()
        shutil.copy2(pdfs["invoice"], folder / "inv.pdf")

        ctx = build_context()
        ctx.config.output_root = str(output_root)
        window = MainWindow(ctx)
        try:
            pipeline = Pipeline(ctx.config, ctx.profiles, ctx.db)
            window.pipeline = pipeline
            window._on_plan_done(pipeline.plan([folder]))

            report = tmp_path / "bao-cao.csv"
            monkeypatch.setattr(
                QFileDialog, "getSaveFileName", lambda *a, **k: (str(report), "CSV cho Excel (*.csv)")
            )
            monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
            window._export_report()

            assert report.exists()
            content = report.read_text(encoding="utf-8-sig")
            assert "inv.pdf" in content and "Tên mới" in content
        finally:
            window.close()
            ctx.close()

    def test_khong_co_job_thi_nut_bao_cao_tat(self, qapp, isolated_home, output_root):
        ctx = build_context()
        ctx.config.output_root = str(output_root)
        window = MainWindow(ctx)
        try:
            assert not window.act_report.isEnabled()
        finally:
            window.close()
            ctx.close()

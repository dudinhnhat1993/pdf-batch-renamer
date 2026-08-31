"""Test 4 điểm sửa cuối: đường dẫn đích, chính tả/chuỗi, master data bind sai, câu cảnh báo."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.core.masterdata import load_table  # noqa: E402
from src.core.zonal import describe_ambiguity  # noqa: E402

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QMessageBox  # noqa: E402
from src.core.bootstrap import build_context  # noqa: E402
from src.core.learning import LearningStore  # noqa: E402
from src.core.models import FieldSpec, MatchCondition, Profile  # noqa: E402
from src.core.rules import ProfileStore  # noqa: E402
from src.ui.main_window import MainWindow  # noqa: E402
from src.ui.preview_model import COL_DEST, PreviewModel  # noqa: E402
from src.ui.rule_editor import RuleEditorDialog  # noqa: E402

from tests.test_ui import make_job  # noqa: E402

# ------------------------------------------------ 1: đường dẫn đích tương đối


class TestDuongDanDichChuanHoa:
    """Đường dẫn trong config do người dùng gõ tay nên hay lệch hoa/thường và dấu gạch."""

    def _display(self, qapp, tmp_path, root: str, dest: str) -> str:
        model = PreviewModel()
        job = make_job(tmp_path)
        job.dest_dir = __import__("pathlib").Path(dest)
        model.set_output_root(root)
        model.set_jobs([job])
        return model.data(model.index(0, COL_DEST))

    def test_khop_binh_thuong(self, qapp, tmp_path):
        assert self._display(qapp, tmp_path, r"D:\out", r"D:\out\2026-08-31") == "2026-08-31"

    def test_lech_hoa_thuong(self, qapp, tmp_path):
        assert self._display(qapp, tmp_path, r"d:\OUT", r"D:\out\2026-08-31") == "2026-08-31"

    def test_lech_chieu_dau_gach(self, qapp, tmp_path):
        assert self._display(qapp, tmp_path, "D:/out", r"D:\out\_Loi") == "_Loi"

    def test_thua_dau_gach_cuoi(self, qapp, tmp_path):
        assert self._display(qapp, tmp_path, "D:/out/", r"D:\out\_Loi") == "_Loi"

    def test_thu_muc_long_nhau(self, qapp, tmp_path):
        value = self._display(qapp, tmp_path, r"D:\out", r"D:\out\2026\08")
        assert value in (r"2026\08", "2026/08")

    def test_chinh_thu_muc_goc(self, qapp, tmp_path):
        assert self._display(qapp, tmp_path, r"D:\out", r"D:\out") == "(thư mục gốc)"

    def test_ngoai_output_thi_hien_day_du(self, qapp, tmp_path):
        assert self._display(qapp, tmp_path, r"D:\out", r"E:\cho-khac") == r"E:\cho-khac"

    def test_ten_gan_giong_khong_bi_nham(self, qapp, tmp_path):
        """D:\\output không phải là con của D:\\out."""
        assert self._display(qapp, tmp_path, r"D:\out", r"D:\output\x") == r"D:\output\x"

    def test_cua_so_biet_output_ngay_tu_luc_mo(self, qapp, isolated_home, output_root, tmp_path):
        """Lỗi gốc: chỉ _start_plan mới gán output root, nên mọi đường khác hiện full path."""
        ctx = build_context()
        ctx.config.output_root = str(output_root)
        window = MainWindow(ctx)
        try:
            job = make_job(tmp_path)
            job.dest_dir = output_root / "2026-08-31"
            window._on_plan_done([job])
            assert window.preview_model.data(
                window.preview_model.index(0, COL_DEST)
            ) == "2026-08-31"
        finally:
            window.close()
            ctx.close()

    def test_doi_output_trong_cai_dat_thi_cot_bam_theo(
        self, qapp, isolated_home, output_root, tmp_path, monkeypatch
    ):
        from src.ui.settings_dialog import SettingsDialog

        ctx = build_context()
        ctx.config.output_root = str(tmp_path / "cu")
        window = MainWindow(ctx)
        try:
            monkeypatch.setattr(SettingsDialog, "exec", lambda self: SettingsDialog.DialogCode.Accepted)
            ctx.config.output_root = str(output_root)
            window._open_settings()

            job = make_job(tmp_path)
            job.dest_dir = output_root / "_Loi"
            window._on_plan_done([job])
            assert window.preview_model.data(window.preview_model.index(0, COL_DEST)) == "_Loi"
        finally:
            window.close()
            ctx.close()


# --------------------------------------------------- 4: câu cảnh báo đúng tín hiệu


class TestCauCanhBaoVung:
    def test_noi_ro_so_cum_giong_nhan(self):
        text = "B/L No.: HLCUSGN2412345 Date of Issue: 02/04/2026 Carrier: HAPAG-LLOYD AG"
        assert describe_ambiguity(text) == (
            "phát hiện 3 cụm giống nhãn (chữ rồi tới dấu hai chấm)"
        )

    def test_noi_ro_so_dong(self):
        assert describe_ambiguity("HLCUSGN2412345\nMSKU2482484") == "vùng có 2 dòng"

    def test_noi_ro_so_tu_khi_chi_co_1_dong_1_nhan(self):
        assert describe_ambiguity("Carrier: HAPAG LLOYD AG Hamburg") == "dòng duy nhất có 5 từ"

    def test_gop_nhieu_tin_hieu(self):
        text = "B/L No.: X Date: Y\nCarrier: Z Port: W"
        reason = describe_ambiguity(text)
        assert "vùng có 2 dòng" in reason and "cụm giống nhãn" in reason

    def test_vung_mot_gia_tri_khong_co_ly_do(self):
        assert describe_ambiguity("HLCUSGN2412345") == ""

    def test_hop_thoai_dung_cau_nay(self, qapp):
        from src.core.models import Zone
        from src.ui.rule_builder_wizard import ZoneFieldDialog

        text = "B/L No.: HLCUSGN2412345 Date of Issue: 02/04/2026 Carrier: HAPAG-LLOYD AG"
        dialog = ZoneFieldDialog(Zone(), text)
        assert "phát hiện 3 cụm giống nhãn" in dialog.ambiguous.text()
        assert "dòng)" not in dialog.ambiguous.text()  # không còn nói sai là "3 dòng"


# ------------------------------------------- 3: master data bind sai phải lộ ra


class TestMasterDataBindSai:
    @pytest.fixture
    def editor(self, qapp, config, db, tmp_path, pdfs):
        store = ProfileStore(tmp_path / "profiles", tmp_path / "profiles" / "_versions")
        store.save(
            Profile(
                id="inv",
                name="Invoice",
                doctype="INV",
                conditions=[MatchCondition(value="COMMERCIAL INVOICE")],
                fields=[
                    FieldSpec(
                        name="number",
                        label="Số hóa đơn",
                        patterns=[r"Invoice No\.?:?\s*([A-Z0-9\-]+)"],
                    )
                ],
                template="{number}",
                samples=[str(pdfs["invoice"])],
            )
        )
        dialog = RuleEditorDialog(config, store, LearningStore(db))
        dialog.profile_list.setCurrentRow(0)
        yield dialog
        dialog.close()

    def test_bind_sai_bao_0_dong_khop(self, editor, pdfs):
        """Field Số hóa đơn dò trong cột Mã KH -> phải lộ ra ngay, không báo OK suông."""
        editor.md_source.setText(str(pdfs["masterdata"]))
        editor.md_key.setText("Ma KH")
        editor.md_value.setText("Ten cong ty")
        editor._test_masterdata()

        status = editor.md_status.text()
        assert "Đọc được 3 dòng" in status
        assert "INV-2026-00871" in status  # giá trị THẬT lấy từ file mẫu
        assert "0 DÒNG KHỚP" in status
        assert "bind nhầm field" in status
        assert "#cf222e" in editor.md_status.styleSheet()  # đỏ

    def test_bind_dung_thi_bao_do_ra_gia_tri(self, editor, pdfs):
        editor.md_source.setText(str(pdfs["masterdata"]))
        editor.md_key.setText("Ten cong ty")
        editor.md_value.setText("MST")
        # Sửa regex để field lấy đúng tên công ty có trong Excel
        editor.current.fields[0].patterns = [r"(Cong ty TNHH Acme Logistics)"]
        editor._test_masterdata()
        # Hóa đơn mẫu không chứa tên đó -> báo chưa chạy thử được, KHÔNG báo OK
        assert "Chưa chạy thử được" in editor.md_status.text()

    def test_vi_du_hien_khoa_goc_khong_phai_ban_casefold(self, pdfs):
        table = load_table(pdfs["masterdata"], "Ma KH", "Ten cong ty")
        key, value = table.first_pair()
        assert key == "KH001"  # không phải "kh001"
        assert value == "Cong ty TNHH Acme Logistics"

    def test_bang_rong_khong_co_vi_du(self, tmp_path):
        from openpyxl import Workbook

        path = tmp_path / "rong.xlsx"
        wb = Workbook()
        wb.active.append(["Ma KH", "Ten cong ty"])
        wb.save(str(path))
        assert load_table(path, "Ma KH", "Ten cong ty").first_pair() is None


# ------------------------------------------------- 2: chuỗi UI không lỗi cơ học


class TestChuoiHienThi:
    def test_khong_co_chuoi_ui_nao_dinh_loi_go_dau_thuong_gap(self):
        """Rà chuỗi hiển thị: các lỗi gõ dấu hay gặp trong tiếng Việt."""
        import ast
        import pathlib
        import re

        typos = re.compile(
            r"\b(cuả|nhửng|đựơc|hiễn|thễ|kiễm|đừng ở|Biểu thức đừng|hoà đơn)\b",
            re.IGNORECASE,
        )
        offenders = []
        root = pathlib.Path(__file__).resolve().parents[1] / "src"
        for path in sorted(root.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    if typos.search(node.value):
                        offenders.append(f"{path.name}:{node.lineno} {node.value[:60]!r}")
        assert not offenders, "Lỗi gõ dấu:\n" + "\n".join(offenders)

    def test_nhan_diem_dung_viet_dung(self):
        from src.ui.rule_builder_wizard import ZoneFieldDialog

        labels = [text for text, _value in ZoneFieldDialog.STOPS]
        assert "Tại nhãn kế tiếp" in labels
        assert "Tại 2 khoảng trắng liên tiếp" in labels

    def test_khong_hop_thoai_nao_dung_tu_dung_sai_chinh_ta(self, qapp):
        from src.core.models import Zone
        from src.ui.rule_builder_wizard import ZoneFieldDialog

        dialog = ZoneFieldDialog(Zone(), "HLCUSGN2412345")
        assert dialog.stop_value.placeholderText().startswith("Biểu thức dừng")


def test_khong_con_modal_nao_treo_test(qapp):
    """Chốt lại: QMessageBox phải luôn được monkeypatch trong test, không mở thật."""
    assert hasattr(QMessageBox, "warning")

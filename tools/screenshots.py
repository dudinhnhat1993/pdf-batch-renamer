"""Chụp ảnh giao diện ở chế độ offscreen để xem nhanh bố cục mà không cần mở app.

Chạy:  python tools/screenshots.py <thư_mục_đích>
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtGui import QFont, QFontDatabase  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QListWidgetItem  # noqa: E402
from src.core.bootstrap import build_context  # noqa: E402
from src.core.learning import LearningStore  # noqa: E402
from src.core.models import FieldSpec  # noqa: E402
from src.core.pipeline import Pipeline  # noqa: E402
from tools.make_fixtures import generate_all  # noqa: E402

SHOTS: list[str] = []


def grab(widget, path: Path) -> None:
    """Chụp 1 widget. Mỗi ảnh 1 tên riêng — kiểm tra để không ghi đè nhầm."""
    if path.name in SHOTS:
        raise SystemExit(f"Trùng tên ảnh: {path.name}")
    SHOTS.append(path.name)
    widget.show()
    QApplication.processEvents()
    widget.grab().save(str(path))
    size = path.stat().st_size
    print(f"  {path.name:44} {size // 1024:4} KB")


def load_font(app) -> None:
    """Nền offscreen không tự nạp font hệ thống -> chữ ra ô vuông. Nạp tay 1 font Windows."""
    for candidate in ("segoeui.ttf", "arial.ttf", "tahoma.ttf"):
        font_file = Path("C:/Windows/Fonts") / candidate
        if not font_file.exists():
            continue
        font_id = QFontDatabase.addApplicationFont(str(font_file))
        families = QFontDatabase.applicationFontFamilies(font_id)
        if families:
            app.setFont(QFont(families[0], 9))
            return


def main(out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="pdfbr_shots_"))
    os.environ["PDFRENAMER_HOME"] = str(work / "home")

    fixtures = generate_all(work / "fixtures")
    inbox = work / "inbox"
    inbox.mkdir()
    for key in ("invoice", "bill_of_lading", "packing_list", "barcode", "encrypted"):
        shutil.copy2(fixtures[key], inbox / fixtures[key].name)

    app = QApplication.instance() or QApplication([])
    load_font(app)
    ctx = build_context()
    ctx.config.output_root = str(work / "output")

    from src.ui.main_window import MainWindow
    from src.ui.rule_builder_wizard import FieldDialog, RuleBuilderWizard
    from src.ui.rule_editor import RuleEditorDialog
    from src.ui.settings_dialog import SettingsDialog

    # ------------------------------------------------------------ cửa sổ chính
    window = MainWindow(ctx)
    window.resize(1420, 900)
    pipeline = Pipeline(ctx.config, ctx.profiles, ctx.db)
    window.pipeline = pipeline
    window._add_paths([inbox])
    # Model cần biết thư mục output gốc thì cột "Thư mục đích" mới rút gọn được
    window.preview_model.set_output_root(ctx.config.output_root)
    window._on_plan_done(pipeline.plan([inbox]))
    grab(window, out_dir / "01-cua-so-chinh-panel-duoi.png")

    # Panel field neo bên phải (tùy chọn thứ hai)
    window.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, window.field_dock)
    QApplication.processEvents()
    grab(window, out_dir / "02-cua-so-chinh-panel-phai.png")

    # ------------------------------------------------------------------ settings
    settings = SettingsDialog(ctx.config, ctx.profiles)
    settings.resize(780, 700)
    grab(settings, out_dir / "03a-cai-dat-tab-chung.png")
    settings.show_tab(SettingsDialog.TAB_OCR)  # ảnh cần chụp ĐÚNG tab OCR
    QApplication.processEvents()
    grab(settings, out_dir / "03b-cai-dat-tab-ocr-thieu-goi.png")

    # Chụp thêm trạng thái ĐỦ gói: trỏ vào thư mục tessdata thật của máy
    real_tessdata = Path(os.environ.get("APPDATA", "")) / "PDFBatchRenamer" / "tessdata"
    if real_tessdata.is_dir():
        settings.tessdata_path.setText(str(real_tessdata))
        settings._check_tesseract()
        QApplication.processEvents()
        grab(settings, out_dir / "03c-cai-dat-tab-ocr-du-goi.png")

    # ------------------------------------------------------------------- wizard
    wizard = RuleBuilderWizard(ctx.config, ctx.store)
    wizard.resize(1250, 820)
    wizard.load_sample(fixtures["bill_of_lading"])
    wizard.sample_page.path_label.setText(str(fixtures["bill_of_lading"]))
    grab(wizard, out_dir / "04-wizard-b1-nap-mau.png")

    wizard.next()
    wizard.state.selected_text = "BILL OF LADING"
    wizard.identify_page.on_selection("BILL OF LADING")
    wizard.identify_page.name.setText("Bill of Lading (thử)")
    wizard.identify_page.doctype.setText("BL")
    wizard.identify_page._add(wizard.identify_page.conditions)
    wizard.state.selected_text = "PACKING LIST"
    wizard.identify_page._add(wizard.identify_page.excludes)
    wizard.state.selected_text = "BILL OF LADING"
    wizard.identify_page.on_selection("BILL OF LADING")
    grab(wizard, out_dir / "05-wizard-b2-nhan-dien-va-loai-tru.png")

    dialog = FieldDialog(wizard.state.text, "HLCUSGN2412345")
    dialog.name.setCurrentText("number")
    dialog.label.setText("Số B/L")
    dialog.required.setChecked(True)
    dialog.resize(720, 560)
    grab(dialog, out_dir / "06-sinh-regex-tu-boi-chon.png")

    wizard.state.profile.fields = [
        FieldSpec(name="number", label="Số B/L", required=True, patterns=[dialog.custom.text()]),
        FieldSpec(
            name="container", label="Số container", from_barcode=True, validate="container",
            patterns=[r"\b([A-Z]{4}\s?\d{6}\s?\d)\b"],
        ),
    ]
    wizard.next()
    wizard.field_page._refresh()
    wizard.field_page.on_selection("HLCUSGN2412345")
    grab(wizard, out_dir / "07-wizard-b3-field-che-do-chu.png")

    # Chế độ kéo khung vùng: kéo thật bằng QTest để khung hiện lên trong ảnh
    wizard.field_page.mode_zone.setChecked(True)
    QApplication.processEvents()
    view = wizard.preview.view
    QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(60, 150))
    QTest.mouseMove(view.viewport(), QPoint(430, 205))
    QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(430, 205))
    QApplication.processEvents()
    grab(wizard, out_dir / "08-wizard-b3-keo-khung-vung.png")

    if wizard.state.selected_zone is not None:
        from src.ui.rule_builder_wizard import ZoneFieldDialog

        zone_dialog = ZoneFieldDialog(
            wizard.state.selected_zone, wizard.state.selected_zone_text
        )
        zone_dialog.name.setCurrentText("so_container")
        zone_dialog.label.setText("Số container")
        zone_dialog.resize(600, 420)
        grab(zone_dialog, out_dir / "09-tao-field-tu-vung.png")

    wizard.field_page.mode_text.setChecked(True)
    wizard.next()
    wizard.template_page.template.setText("{doc_date}_{doctype}_{number}_{container}")
    QApplication.processEvents()
    grab(wizard, out_dir / "10-wizard-b4-template-xem-truoc.png")

    # -------------------------------------------------------------- rule editor
    editor = RuleEditorDialog(ctx.config, ctx.store, LearningStore(ctx.db))
    editor.resize(1180, 800)
    editor.profile_list.setCurrentRow(0)
    item = QListWidgetItem(fixtures["bill_of_lading"].name)
    item.setData(Qt.ItemDataRole.UserRole, str(fixtures["bill_of_lading"]))
    editor.samples.addItem(item)
    QApplication.processEvents()
    grab(editor, out_dir / "11-quan-ly-rule.png")

    # ------------------------------------------------------ Phase 3: thống kê
    from src.ui.stats_dialog import StatsDialog

    learning = LearningStore(ctx.db)
    for _ in range(9):
        learning.record_match("bill-of-lading", "success", "bl.pdf")
    for _ in range(6):
        learning.record_match("invoice", "success", "inv.pdf")
    learning.record_match("invoice", "error", "inv-loi.pdf")
    learning.record_match("invoice", "duplicate", "inv-trung.pdf")
    for _ in range(3):
        learning.record_match("packing-list", "success", "pl.pdf")
    for _ in range(2):
        learning.record_match("packing-list", "error", "pl-loi.pdf")
    learning.record_correction(
        field_name="number", old_value="INV-2026-0O871", new_value="INV-2026-00871",
        profile_id="invoice",
    )

    stats = StatsDialog(learning, ctx.profiles)
    stats.resize(900, 560)
    stats.reload()
    grab(stats, out_dir / "12-thong-ke-30-ngay.png")

    # ------------------------------------------- Phase 3: master data trong GUI
    editor2 = RuleEditorDialog(ctx.config, ctx.store, learning)
    editor2.resize(1180, 820)
    for row in range(editor2.profile_list.count()):
        if editor2.profile_list.item(row).text().startswith("Invoice"):
            editor2.profile_list.setCurrentRow(row)
            break
    # Gắn file mẫu để nút kiểm tra chạy thử được bằng giá trị THẬT
    sample_item = QListWidgetItem(fixtures["invoice"].name)
    sample_item.setData(Qt.ItemDataRole.UserRole, str(fixtures["invoice"]))
    editor2.samples.addItem(sample_item)

    editor2.md_source.setText(str(fixtures["masterdata"]))
    editor2.md_key.setText("Ma KH")
    editor2.md_value.setText("Ten cong ty")
    editor2.md_target.setText("ten_kh")
    editor2._test_masterdata()
    editor2.scroll_to_masterdata()
    QApplication.processEvents()
    grab(editor2, out_dir / "13-master-data-trong-rule-editor.png")

    # Ca BIND SAI: field "Số hóa đơn" mà lại dò trong cột mã khách hàng -> phải báo 0 dòng khớp
    for row in range(editor2.md_field.count()):
        if editor2.md_field.itemData(row) == "number":
            editor2.md_field.setCurrentIndex(row)
            break
    editor2.md_source.setText(str(fixtures["masterdata"]))
    editor2.md_key.setText("Ma KH")
    editor2.md_value.setText("Ten cong ty")
    editor2.md_target.setText("ten_kh")
    editor2._test_masterdata()
    editor2.scroll_to_masterdata()
    QApplication.processEvents()
    grab(editor2, out_dir / "15-master-data-bind-sai-0-dong-khop.png")

    # ---------------------------------------- Phase 3: Learning Loop từ sửa tay
    from src.ui.correction_dialog import CorrectionRuleDialog

    invoice_profile = next(p for p in ctx.profiles if p.id == "invoice")
    invoice_job = next(j for j in window.preview_model.jobs if "invoice_text" in j.source.name)
    correction = CorrectionRuleDialog(
        ctx.config, ctx.store, invoice_profile, invoice_job, "number", "INV-2026-00871"
    )
    correction.resize(780, 620)
    grab(correction, out_dir / "14-tao-rule-tu-sua-tay.png")

    ctx.close()
    print("Xong:", out_dir)


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "docs" / "screenshots")

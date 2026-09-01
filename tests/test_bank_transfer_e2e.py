"""End-to-end tests for Bank Transfer profile (test-2.pdf), date subfolder output, and Multi-word selection."""

from __future__ import annotations

import shutil
from datetime import date

from src.core.bootstrap import build_context
from src.core.extractor import Extractor
from src.core.models import JobStatus
from src.core.mover import undo_session
from src.core.pipeline import Pipeline
from src.ui.main_window import MainWindow
from src.ui.preview_model import COL_DEST, COL_NEW, COL_OLD, COL_PROFILE, COL_STATUS


class TestBankTransferE2E:
    def test_nhan_dien_profile_bank_transfer(self, pdfs, profiles, config):
        """test-2.pdf phải khớp với profile bank_transfer (Chuyển khoản ngân hàng)."""
        extractor = Extractor(config, profiles)
        doc = extractor.extract(pdfs["bank_transfer"])
        assert doc.profile_id == "bank_transfer"
        assert doc.profile_name == "Chuyển khoản ngân hàng"

    def test_trich_xuat_field_description_va_loai_bo_ma_tham_chieu(self, pdfs, profiles, config):
        """Field description phải trích xuất đúng 'TAM CK PKT YE2607006 T04.26', bỏ 2 mã tham chiếu trước đó."""
        extractor = Extractor(config, profiles)
        result = extractor.extract(pdfs["bank_transfer"])
        assert result.profile_id == "bank_transfer"
        assert "description" in result.fields

        val = result.fields["description"].value
        cleaned_val = " ".join(val.split())
        assert cleaned_val == "TAM CK PKT YE2607006 T04.26"

    def test_render_template_giu_nguyen_khoang_trang(self, config, profiles, db, pdfs):
        """Template {description} phải cho ra tên file 'TAM CK PKT YE2607006 T04.26.pdf'."""
        pipeline = Pipeline(config, profiles, db)
        job = pipeline.plan_one(pdfs["bank_transfer"], dry_run=True)

        assert job.status == JobStatus.PENDING
        assert job.new_name == "TAM CK PKT YE2607006 T04.26.pdf"
        assert "_" not in job.new_name  # Không tự động đổi khoảng trắng thành gạch dưới

    def test_output_thu_muc_ngay_xu_ly_mode_copy(self, config, profiles, db, pdfs, output_root, tmp_path):
        """Chế độ Copy với thư mục con theo ngày xử lý: tạo file đúng chỗ và giữ nguyên file gốc."""
        config.mode = "copy"
        config.subfolder_by_date = True
        config.subfolder_date_format = "%Y-%m-%d"
        today_str = date.today().strftime("%Y-%m-%d")

        src_file = tmp_path / "test-2.pdf"
        shutil.copy2(pdfs["bank_transfer"], src_file)

        pipeline = Pipeline(config, profiles, db)
        job = pipeline.plan_one(src_file)
        assert job.dest_dir == output_root / today_str

        summary = pipeline.apply([job])
        assert summary.success == 1
        assert summary.errors == 0

        expected_dest = output_root / today_str / "TAM CK PKT YE2607006 T04.26.pdf"
        assert expected_dest.exists()
        assert src_file.exists()  # File gốc vẫn còn ở mode copy

    def test_output_thu_muc_ngay_xu_ly_mode_move_kem_undo(self, config, profiles, db, pdfs, output_root, tmp_path):
        """Chế độ Move: di chuyển file, tạo backup và hoàn tác (Undo) thành công."""
        config.mode = "move"
        config.subfolder_by_date = True
        config.subfolder_date_format = "%Y-%m-%d"
        today_str = date.today().strftime("%Y-%m-%d")

        src_file = tmp_path / "test-2.pdf"
        shutil.copy2(pdfs["bank_transfer"], src_file)

        pipeline = Pipeline(config, profiles, db)
        job = pipeline.plan_one(src_file)
        summary = pipeline.apply([job])
        assert summary.success == 1

        expected_dest = output_root / today_str / "TAM CK PKT YE2607006 T04.26.pdf"
        assert expected_dest.exists()
        assert not src_file.exists()  # File gốc đã bị di chuyển

        # Hoàn tác qua session log
        assert summary.log_path is not None
        undone, errs = undo_session(summary.log_path)
        assert undone == 1
        assert len(errs) == 0
        assert src_file.exists()  # File gốc được khôi phục
        assert not expected_dest.exists()

    def test_dry_run_khong_tao_file_that(self, config, profiles, db, pdfs, output_root, tmp_path):
        """Dry-run chỉ tính toán, không ghi bất kỳ file nào ra đĩa."""
        config.mode = "copy"
        config.subfolder_by_date = True
        today_str = date.today().strftime("%Y-%m-%d")

        src_file = tmp_path / "test-2.pdf"
        shutil.copy2(pdfs["bank_transfer"], src_file)

        pipeline = Pipeline(config, profiles, db)
        job = pipeline.plan_one(src_file, dry_run=True)
        assert job.status == JobStatus.PENDING
        assert not (output_root / today_str).exists()

    def test_gui_nap_va_plan_bank_transfer_pdf(self, qapp, isolated_home, output_root, pdfs, tmp_path):
        """Kiểm tra toàn bộ luồng trên GUI MainWindow: nạp test-2.pdf -> hiển thị bảng -> plan -> áp dụng."""
        src_file = tmp_path / "test-2.pdf"
        shutil.copy2(pdfs["bank_transfer"], src_file)

        ctx = build_context()
        ctx.config.output_root = str(output_root)
        ctx.config.subfolder_by_date = True
        ctx.config.mode = "copy"
        window = MainWindow(ctx)
        try:
            # 1. Nạp file -> xuất hiện ngay trong bảng với trạng thái Chờ
            window._add_paths([src_file])
            assert window.preview_model.rowCount() == 1
            assert window.preview_model.data(window.preview_model.index(0, COL_OLD)) == "test-2.pdf"
            assert window.preview_model.data(window.preview_model.index(0, COL_STATUS)) == "Chờ"

            # 2. Chạy plan
            pipeline = window._make_pipeline()
            assert pipeline is not None
            window.pipeline = pipeline
            jobs = pipeline.plan(list(window.pending_paths), dry_run=False)
            window._on_plan_done(jobs)

            # 3. Kiểm tra bảng sau khi plan
            assert window.preview_model.rowCount() == 1
            assert window.preview_model.data(window.preview_model.index(0, COL_NEW)) == "TAM CK PKT YE2607006 T04.26.pdf"
            assert window.preview_model.data(window.preview_model.index(0, COL_PROFILE)) == "Chuyển khoản ngân hàng"
            today_str = date.today().strftime("%Y-%m-%d")
            assert window.preview_model.data(window.preview_model.index(0, COL_DEST)) == today_str
            assert window.act_apply.isEnabled()
        finally:
            window.close()
            ctx.close()

    def test_boi_chon_nhieu_tu_va_nhieu_dong_trong_pdf_view(self, qapp):
        """Bôi chọn nhiều từ trải dài trên 2 dòng phải lấy đúng toàn bộ cụm 'TAM CK PKT YE2607006 T04.26'."""
        from PySide6.QtCore import QRectF
        from PySide6.QtGui import QPixmap
        from src.core.models import PageText, Word
        from src.ui.pdf_view import PdfPageView

        view = PdfPageView()
        page = PageText(
            index=0,
            width=595,
            height=842,
            words=[
                Word("Nội", 50, 100, 70, 112),
                Word("dung", 75, 100, 100, 112),
                Word("946C60716DK7PDT7", 105, 100, 190, 112),
                Word("6197ICBVC2A4YP8C", 195, 100, 280, 112),
                Word("TAM", 285, 100, 310, 112),
                Word("CK", 315, 100, 335, 112),
                Word("PKT", 340, 100, 365, 112),
                Word("YE2607006", 285, 120, 345, 132),
                Word("T04.26", 350, 120, 390, 132),
                Word("Trạng", 50, 140, 80, 152),
                Word("thái", 85, 140, 110, 152),
            ],
        )
        view.load_page(QPixmap(1240, 1754), page, dpi=150)
        s = 150 / 72.0

        # Kéo khung bao trọn vùng 2 dòng của cụm TAM CK PKT YE2607006 T04.26
        rect = QRectF(280 * s, 95 * s, 120 * s, 42 * s)
        selected_words = view._words_in_rect(rect)

        assert [w.text for w in selected_words] == ["TAM", "CK", "PKT", "YE2607006", "T04.26"]
        assert view._join(selected_words) == "TAM CK PKT YE2607006 T04.26"

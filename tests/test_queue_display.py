"""Test bảng hàng đợi (queue table) trong MainWindow: nạp file, hiển thị ngay lập tức, đếm file, lọc file."""

from __future__ import annotations

import shutil

from src.core.bootstrap import build_context
from src.core.models import JobStatus
from src.ui.main_window import MainWindow
from src.ui.preview_model import COL_NEW, COL_OLD, COL_STATUS


class TestQueueDisplay:
    def _window(self, ctx) -> MainWindow:
        return MainWindow(ctx)

    def test_nap_mot_file_pdf_hien_thi_ngay_lap_tuc(self, qapp, isolated_home, output_root, pdfs, tmp_path):
        """Nạp 1 file PDF: bảng phải có đúng 1 dòng, tên cũ đúng, trạng thái Chờ, chưa có tên mới."""
        src_pdf = tmp_path / "test-2.pdf"
        shutil.copy2(pdfs["invoice"], src_pdf)

        ctx = build_context()
        ctx.config.output_root = str(output_root)
        window = self._window(ctx)
        try:
            window._add_paths([src_pdf])

            # Kiểm tra số dòng trong model
            assert window.preview_model.rowCount() == 1
            job = window.preview_model.job_at(0)
            assert job is not None
            assert job.source.name == "test-2.pdf"
            assert job.status == JobStatus.PENDING

            # Kiểm tra hiển thị trong bảng
            idx_status = window.preview_model.index(0, COL_STATUS)
            idx_old = window.preview_model.index(0, COL_OLD)
            idx_new = window.preview_model.index(0, COL_NEW)
            assert window.preview_model.data(idx_status) == "Chờ"
            assert window.preview_model.data(idx_old) == "test-2.pdf"
            assert window.preview_model.data(idx_new) == "—"

            # Kiểm tra nhãn đếm trạng thái
            assert "Chờ: 1" in window.counts.text()
            assert "tổng 1" in window.counts.text()

            # Nút Xem trước phải bật, nút Áp dụng chưa bật
            assert window.act_scan.isEnabled()
            assert not window.act_apply.isEnabled()
        finally:
            window.close()
            ctx.close()

    def test_nap_nhieu_file_va_thu_muc(self, qapp, isolated_home, output_root, pdfs, tmp_path):
        """Nạp thư mục chứa nhiều PDF: bảng hiển thị đủ số dòng tương ứng."""
        folder = tmp_path / "incoming"
        folder.mkdir()
        shutil.copy2(pdfs["invoice"], folder / "doc1.pdf")
        shutil.copy2(pdfs["bill_of_lading"], folder / "doc2.pdf")
        shutil.copy2(pdfs["packing_list"], folder / "doc3.pdf")

        ctx = build_context()
        ctx.config.output_root = str(output_root)
        window = self._window(ctx)
        try:
            window._add_paths([folder])
            assert window.preview_model.rowCount() == 3
            assert "Chờ: 3" in window.counts.text()
            assert "tổng 3" in window.counts.text()

            names = {window.preview_model.job_at(i).source.name for i in range(3)}
            assert names == {"doc1.pdf", "doc2.pdf", "doc3.pdf"}
        finally:
            window.close()
            ctx.close()

    def test_nap_file_khong_phai_pdf_co_canh_bao_khong_mat_file_hop_le(
        self, qapp, isolated_home, output_root, pdfs, tmp_path, caplog
    ):
        """Nạp file .txt hoặc .docx kèm file .pdf: file không phải PDF bị bỏ qua kèm log warning, PDF hợp lệ vẫn vào bảng."""
        valid_pdf = tmp_path / "valid.pdf"
        shutil.copy2(pdfs["invoice"], valid_pdf)
        invalid_txt = tmp_path / "note.txt"
        invalid_txt.write_text("Hello", encoding="utf-8")
        invalid_docx = tmp_path / "word.docx"
        invalid_docx.write_bytes(b"PK000")

        ctx = build_context()
        ctx.config.output_root = str(output_root)
        window = self._window(ctx)
        try:
            with caplog.at_level("WARNING"):
                window._add_paths([valid_pdf, invalid_txt, invalid_docx])

            assert window.preview_model.rowCount() == 1
            assert window.preview_model.job_at(0).source.name == "valid.pdf"
            assert any("Bỏ qua 2 file không phải PDF" in rec.message for rec in caplog.records)
        finally:
            window.close()
            ctx.close()

    def test_nap_lai_cung_file_khong_nhan_doi_dong(self, qapp, isolated_home, output_root, pdfs, tmp_path):
        """Nạp lại cùng một file PDF không tạo dòng trùng lặp trong bảng."""
        pdf_file = tmp_path / "sample.pdf"
        shutil.copy2(pdfs["invoice"], pdf_file)

        ctx = build_context()
        ctx.config.output_root = str(output_root)
        window = self._window(ctx)
        try:
            window._add_paths([pdf_file])
            assert window.preview_model.rowCount() == 1

            # Nạp lại lần 2
            window._add_paths([pdf_file])
            assert window.preview_model.rowCount() == 1
        finally:
            window.close()
            ctx.close()

    def test_xoa_danh_sach_lam_sach_bang(self, qapp, isolated_home, output_root, pdfs, tmp_path):
        """Bấm Xóa danh sách (_clear) phải dọn sạch pending_paths, preview_model và fields_model."""
        pdf_file = tmp_path / "doc.pdf"
        shutil.copy2(pdfs["invoice"], pdf_file)

        ctx = build_context()
        ctx.config.output_root = str(output_root)
        window = self._window(ctx)
        try:
            window._add_paths([pdf_file])
            assert window.preview_model.rowCount() == 1

            window._clear()
            assert len(window.pending_paths) == 0
            assert window.preview_model.rowCount() == 0
            assert window.fields_model.rowCount() == 0
            assert window.counts.text() == "Chưa có file nào."
        finally:
            window.close()
            ctx.close()

    def test_chon_dong_khi_chua_plan_hien_thong_tin_cho(self, qapp, isolated_home, output_root, pdfs, tmp_path):
        """Chọn 1 dòng ở trạng thái Chờ (chưa plan) hiển thị thông báo hướng dẫn thân thiện."""
        pdf_file = tmp_path / "waiting.pdf"
        shutil.copy2(pdfs["invoice"], pdf_file)

        ctx = build_context()
        ctx.config.output_root = str(output_root)
        window = self._window(ctx)
        try:
            window._add_paths([pdf_file])
            window._select_row(0)
            assert "đang chờ xử lý" in window.detail_label.text()
            assert "waiting.pdf" in window.detail_label.text()
        finally:
            window.close()
            ctx.close()

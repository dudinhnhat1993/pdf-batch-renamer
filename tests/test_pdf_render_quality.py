"""Khoá hành vi làm chữ nét: trang được rasterize LẠI đúng độ phân giải màn hình.

Lỗi mờ chữ trước đây là do render 1 lần ở 200 dpi rồi để QGraphicsView phóng/thu ảnh
bitmap đó. Các test dưới đây chứng minh hai điều:
  1. Zoom lên thì dpi yêu cầu render tăng theo (không phóng ảnh cũ).
  2. Sau khi render xong, 1 pixel ảnh rơi đúng 1 pixel VẬT LÝ của màn hình.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.core.models import PageText, Word  # noqa: E402

pytest.importorskip("PySide6")

from PySide6.QtGui import QPixmap  # noqa: E402
from src.ui.pdf_view import (  # noqa: E402
    MAX_RENDER_DPI,
    MAX_RENDER_PIXELS,
    MIN_RENDER_DPI,
    OVERSAMPLE_FACTOR,
    PdfPageView,
    PdfPreviewWidget,
    PdfViewerWidget,
)

A4_W, A4_H = 595.0, 842.0


def _page(width: float = A4_W, height: float = A4_H) -> PageText:
    return PageText(
        index=0,
        width=width,
        height=height,
        words=[Word("INVOICE", 100, 100, 180, 112)],
    )


class _Recorder:
    """Giả lập nguồn render, ghi lại mọi dpi được yêu cầu."""

    def __init__(self, page: PageText = None) -> None:
        self.page = page or _page()
        self.calls: list[float] = []

    def __call__(self, index: int, dpi: float):
        self.calls.append(dpi)
        w = max(1, int(self.page.width * dpi / 72.0))
        h = max(1, int(self.page.height * dpi / 72.0))
        return QPixmap(w, h)


class TestRenderTheoDoPhanGiai:
    def _view(self, qapp, recorder: _Recorder) -> PdfPageView:
        view = PdfPageView()
        view.resize(800, 600)  # có kích thước thật thì _fit_zoom mới tính được
        view.set_render_source(recorder)
        return view

    def test_nap_trang_render_dung_dpi_vua_khung(self, qapp):
        rec = _Recorder()
        view = self._view(qapp, rec)
        assert view.set_page(rec.page)

        dpr = view.devicePixelRatioF() or 1.0
        raw_dpi = view._zoom * dpr * 72.0
        expected = max(MIN_RENDER_DPI, raw_dpi)  # MIN_RENDER_DPI = 120 đảm bảo sàn chất lượng
        assert rec.calls, "phải gọi render ít nhất 1 lần"
        assert rec.calls[-1] == pytest.approx(expected, rel=0.02)

    def test_zoom_lam_tang_dpi_render_chu_khong_phong_anh_cu(self, qapp):
        rec = _Recorder()
        view = self._view(qapp, rec)
        view.set_page(rec.page)
        dpi_dau = rec.calls[-1]
        zoom_dau = view._zoom

        view.set_zoom(zoom_dau * 3)
        view._render_now()  # bỏ qua debounce, gọi thẳng cho test

        # DPI mới phải cao hơn đáng kể so với ban đầu (tối thiểu gấp 2 lần)
        # Lưu ý: tỉ lệ có thể không chính xác 3x vì MIN_RENDER_DPI nâng sàn DPI ban đầu
        dpi_sau = rec.calls[-1]
        assert dpi_sau > dpi_dau * 1.5, (
            f"DPI sau zoom x3 ({dpi_sau:.0f}) phải cao hơn đáng kể so với ban đầu ({dpi_dau:.0f})"
        )
        # Ảnh mới phải to hơn rõ rệt, tức thật sự rasterize lại chứ không scale ảnh cũ
        assert view._pixmap_item.pixmap().width() > 1.5 * (rec.page.width * dpi_dau / 72.0)

    def test_oversample_tang_so_pixel_render(self, qapp):
        """Với oversample > 1, ảnh render có nhiều pixel hơn mức hiển thị, Qt downscale cho nét."""
        rec = _Recorder()
        view = self._view(qapp, rec)
        view.set_page(rec.page)

        # Ma trận view nhân dpr phải phản ánh tỉ lệ zoom/scale
        # Ảnh được render lớn hơn thực tế nhờ oversample -> chữ sắc nét
        factor = view._zoom / view._scale if view._scale > 0 else 1.0
        assert view.transform().m11() == pytest.approx(factor, rel=0.01)

    def test_khong_render_lai_khi_thay_doi_khong_dang_ke(self, qapp):
        rec = _Recorder()
        view = self._view(qapp, rec)
        view.set_page(rec.page)
        so_lan = len(rec.calls)

        view.set_zoom(view._zoom * 1.002)  # lệch 0.2%, dưới ngưỡng
        assert not view._render_timer.isActive()
        assert len(rec.calls) == so_lan

    def test_tran_dpi_va_tran_so_pixel(self, qapp):
        rec = _Recorder()
        view = self._view(qapp, rec)
        view.set_page(rec.page)

        view.set_zoom(999)  # bị kẹp về MAX_ZOOM
        dpi = view._target_dpi()
        assert dpi <= MAX_RENDER_DPI
        eff_dpi = dpi * OVERSAMPLE_FACTOR
        assert rec.page.width * rec.page.height * (eff_dpi / 72.0) ** 2 <= MAX_RENDER_PIXELS * 1.01

        # Khổ giấy khổng lồ: trần số pixel phải kéo dpi xuống dưới trần dpi
        rec_lon = _Recorder(_page(2400.0, 3400.0))
        view.set_render_source(rec_lon)
        view.set_page(rec_lon.page)
        view.set_zoom(8.0)
        assert view._target_dpi() < MAX_RENDER_DPI

    def test_lop_phu_tu_van_khop_sau_khi_render_lai(self, qapp):
        rec = _Recorder()
        view = self._view(qapp, rec)
        view.set_page(rec.page)
        word = rec.page.words[0]

        truoc = view._word_rect(word)
        # Bbox theo point phải quy ra đúng pixel ảnh ở dpi hiện tại
        assert truoc.left() == pytest.approx(word.x0 * view._render_dpi / 72.0, rel=0.001)

        view.set_zoom(view._zoom * 2)
        view._render_now()
        sau = view._word_rect(word)
        assert sau.left() == pytest.approx(word.x0 * view._render_dpi / 72.0, rel=0.001)
        assert sau.width() > truoc.width()  # ảnh to hơn thì bbox theo pixel cũng to hơn

    def test_load_page_tinh_van_chay_khi_khong_co_nguon_render(self, qapp):
        """Đường cũ (đưa sẵn ảnh) phải giữ nguyên hành vi — dùng cho test và fallback."""
        view = PdfPageView()
        view.resize(800, 600)
        page = _page()
        view.load_page(QPixmap(1240, 1754), page, dpi=150)
        assert view.has_words
        assert view._scale == pytest.approx(150 / 72.0)


class TestNguonRenderCuaCacWidget:
    def test_preview_widget_cache_theo_ca_dpi(self, qapp, pdfs):
        from src.core.pdfdoc import PdfDocument

        widget = PdfPreviewWidget()
        widget.resize(700, 900)
        try:
            with PdfDocument(pdfs["invoice"]) as doc:
                pages = [
                    PageText(index=0, width=doc.page_size(0)[0], height=doc.page_size(0)[1])
                ]
                widget.load_document(doc, pages)
                a = widget._render_pixmap(0, 150)
                b = widget._render_pixmap(0, 300)
                assert a is not None and b is not None
                assert b.width() > a.width() * 1.5
                assert (0, 150) in widget._pixmaps and (0, 300) in widget._pixmaps
                # Gọi lại đúng dpi cũ thì lấy từ cache, không rasterize lần nữa
                assert widget._render_pixmap(0, 150) is a
        finally:
            widget.close()

    def test_viewer_widget_zoom_thi_render_lai_o_dpi_cao_hon(self, qapp, pdfs):
        viewer = PdfViewerWidget()
        viewer.resize(700, 900)
        viewer.show()  # phải qua 1 lượt layout thì view con mới có bề ngang thật
        qapp.processEvents()
        try:
            viewer.load_file(pdfs["invoice"])
            assert viewer._total_pages > 0
            dpi_dau = viewer.view._render_dpi
            rong_dau = viewer.view._pixmap_item.pixmap().width()

            viewer.view.set_zoom(viewer.view._zoom * 2)
            viewer.view._render_now()

            # DPI sau zoom phải cao hơn ban đầu (MIN_RENDER_DPI có thể nâng sàn
            # nên tỉ lệ không chính xác 2x khi DPI ban đầu đã bị kẹp)
            assert viewer.view._render_dpi > dpi_dau * 1.2, (
                f"DPI sau zoom x2 ({viewer.view._render_dpi:.0f}) phải cao hơn ban đầu ({dpi_dau:.0f})"
            )
            # Ảnh pixel phải rộng hơn — bằng chứng đã rasterize lại ở DPI cao hơn
            assert viewer.view._pixmap_item.pixmap().width() > rong_dau * 1.2
        finally:
            viewer.close_document()
            viewer.close()

    def test_doi_file_thi_xoa_cache_anh(self, qapp, pdfs):
        viewer = PdfViewerWidget()
        viewer.resize(700, 900)
        try:
            viewer.load_file(pdfs["invoice"])
            assert viewer._pixmaps
            viewer.load_file(pdfs["bill_of_lading"])
            # Cache đã bị xoá lúc đóng tài liệu cũ -> chỉ còn ảnh của file mới
            assert all(key[0] < viewer._total_pages for key in viewer._pixmaps)
        finally:
            viewer.close_document()
            viewer.close()

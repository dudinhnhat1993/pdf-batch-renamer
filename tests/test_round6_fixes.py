"""Test Round 6 fixes:
1. Preview scans for files without rules (no NameError on _ScanWorker, job status ERROR shown correctly).
2. QuickGuideDialog renders with QLabel+QPixmap per-step layout (no QTextBrowser).
"""

from pathlib import Path
import pytest
from PySide6.QtWidgets import QLabel, QScrollArea
from src.core.bootstrap import build_context
from src.core.models import FileJob, JobStatus
from src.ui.main_window import MainWindow, QuickGuideDialog, _ScanWorker, _ProcessWorker


class TestRound6Fixes:
    def test_workers_exist(self):
        assert _ScanWorker is not None
        assert _ProcessWorker is not None

    def test_preview_scan_worker_for_unmatched_file(self, qapp, tmp_path):
        dummy_pdf = tmp_path / "480379 (GTN).pdf"
        dummy_pdf.write_bytes(b"%PDF-1.4 dummy content")

        ctx = build_context()
        win = MainWindow(ctx)
        try:
            win.preview_model.set_jobs([FileJob(source=dummy_pdf, status=JobStatus.PENDING)])
            assert len(win.preview_model.jobs) == 1
            assert win.preview_model.jobs[0].status == JobStatus.PENDING

            job = win.pipeline.plan_one(dummy_pdf)
            assert job.status == JobStatus.ERROR
            assert job.error_code in ("no-profile", "read-failed", "pdf-open-failed")

            win._on_batch_finished([job])
            assert win.preview_model.jobs[0].status == JobStatus.ERROR

            win.table.selectRow(0)
            win._on_row_selected()
            assert win.inspector.lbl_file.text() == "480379 (GTN).pdf"
        finally:
            win.close()
            ctx.close()

    def test_quick_guide_dialog_renders_with_qlabel_layout(self, qapp):
        guide = QuickGuideDialog()
        try:
            assert "PDF Batch Renamer" in guide.windowTitle()
            # New layout uses QScrollArea + QLabel (not QTextBrowser)
            scrolls = guide.findChildren(QScrollArea)
            assert len(scrolls) >= 3, "Expected at least 3 QScrollAreas (one per tab)"
            labels = guide.findChildren(QLabel)
            all_text = " ".join(lbl.text() for lbl in labels if lbl.text())
            # Verify step keywords are present
            assert "BUOC" in all_text or "BƯỚC" in all_text
            assert "NAP FILE PDF" in all_text or "NAP" in all_text or "NẠP" in all_text
            assert "XEM TRUOC" in all_text or "XEM TRƯỚC" in all_text or "F5" in all_text
            assert "AP DUNG" in all_text or "ÁP DỤNG" in all_text or "Ctrl" in all_text
            assert "WIZARD" in all_text or "LOAI" in all_text
            assert "RULE" in all_text or "QUAN LY" in all_text
        finally:
            guide.close()

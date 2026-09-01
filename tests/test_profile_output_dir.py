from datetime import date

import pytest
from PySide6.QtWidgets import QApplication
from src.core.config import AppConfig
from src.core.db import Database
from src.core.models import ExtractionResult, JobStatus, MatchCondition, Profile
from src.core.mover import Mover
from src.core.pipeline import Pipeline
from src.core.rules import ProfileStore
from src.ui.rule_editor import RuleEditorDialog
from src.ui.settings_dialog import SettingsDialog


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_profile_output_dir_serialization():
    p = Profile(
        id="custom_p",
        name="Chuyển khoản",
        template="{description}",
        output_dir="D:/KeToan/ChuyenKhoan",
    )
    d = p.to_dict()
    assert d["output_dir"] == "D:/KeToan/ChuyenKhoan"

    p2 = Profile.from_dict(d)
    assert p2.output_dir == "D:/KeToan/ChuyenKhoan"


def test_mover_custom_root_support(tmp_path):
    default_root = tmp_path / "default_out"
    custom_root = tmp_path / "custom_out"
    config = AppConfig(output_root=str(default_root), subfolder_enabled=False)
    mover = Mover(config)

    # Không truyền root -> dùng default
    assert mover.destination_dir() == default_root

    # Truyền root riêng -> dùng root riêng
    assert mover.destination_dir(root=custom_root) == custom_root

    # Bật subfolder theo ngày
    config.subfolder_enabled = True
    config.subfolder_pattern = "{YYYY}-{MM}-{DD}"
    when = date(2026, 8, 31)
    assert mover.destination_dir(when=when, root=custom_root) == custom_root / "2026-08-31"


def test_pipeline_routes_to_profile_output_dir(tmp_path):
    default_root = tmp_path / "default_out"
    custom_root = tmp_path / "custom_bank"
    pdf_file = tmp_path / "sample.pdf"
    pdf_file.write_bytes(b"%PDF-1.4 mock content")

    config = AppConfig(output_root=str(default_root), subfolder_enabled=True, subfolder_pattern="{YYYY}-{MM}-{DD}")
    db = Database(tmp_path / "db.sqlite")

    p = Profile(
        id="bank",
        name="Bank",
        template="TestFile",
        output_dir=str(custom_root),
        conditions=[MatchCondition(kind="keyword", value="mock", case_sensitive=False)],
    )

    pipe = Pipeline(config, [p], db)
    mock_result = ExtractionResult(profile_id="bank", fields={})
    pipe.extractor.extract = lambda path, forced_profile=None: mock_result

    when = date(2026, 8, 31)
    job = pipe.plan_one(pdf_file, forced_profile="bank", when=when)

    assert job.status != JobStatus.ERROR
    assert job.dest_dir == custom_root / "2026-08-31"
    assert job.profile_id == "bank"


def test_pipeline_fallback_to_default_when_output_dir_empty(tmp_path):
    default_root = tmp_path / "default_out"
    pdf_file = tmp_path / "sample2.pdf"
    pdf_file.write_bytes(b"%PDF-1.4 mock content 2")

    config = AppConfig(output_root=str(default_root), subfolder_enabled=True, subfolder_pattern="{YYYY}-{MM}-{DD}")
    db = Database(tmp_path / "db.sqlite")

    p = Profile(
        id="general",
        name="General",
        template="GeneralFile",
        output_dir="",
        conditions=[MatchCondition(kind="keyword", value="mock", case_sensitive=False)],
    )

    pipe = Pipeline(config, [p], db)
    mock_result = ExtractionResult(profile_id="general", fields={})
    pipe.extractor.extract = lambda path, forced_profile=None: mock_result

    when = date(2026, 8, 31)
    job = pipe.plan_one(pdf_file, forced_profile="general", when=when)

    assert job.dest_dir == default_root / "2026-08-31"


def test_rule_editor_loads_and_saves_output_dir(qapp, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)

    store = ProfileStore(tmp_path / "profiles")
    p = Profile(
        id="p1",
        name="Profile 1",
        template="{name}",
        output_dir="C:/Custom/Dir",
        conditions=[MatchCondition(kind="keyword", value="test", case_sensitive=False)],
    )
    store.save(p)

    config = AppConfig()
    editor = RuleEditorDialog(config, store)
    editor.profile_list.setCurrentRow(0)

    assert editor.output_dir.text() == "C:/Custom/Dir"

    # Sửa đường dẫn và lưu
    editor.output_dir.setText("D:/New/Target/Folder")
    editor._save_current()

    saved = store.get("p1")
    assert saved is not None
    assert saved.output_dir == "D:/New/Target/Folder"


def test_settings_dialog_instant_open(qapp, tmp_path):
    config = AppConfig()
    profiles = []
    dlg = SettingsDialog(config, profiles)
    # Tab 0 is General, verify no blocking calls happened
    assert dlg.tabs.currentIndex() == SettingsDialog.TAB_GENERAL
    assert dlg.output_root.text() == config.output_root
    dlg.close()

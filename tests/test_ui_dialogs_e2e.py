"""Comprehensive E2E test suite for all dialogs and wizards triggered from MainWindow."""

from PySide6.QtWidgets import QMessageBox
from src.core.bootstrap import build_context
from src.core.models import FieldSpec
from src.ui.main_window import MainWindow
from src.ui.rule_builder_wizard import RuleBuilderWizard
from src.ui.rule_editor import RuleEditorDialog
from src.ui.settings_dialog import SettingsDialog
from src.ui.stats_dialog import StatsDialog


def test_main_window_open_wizard_and_create_profile(qapp, isolated_home, output_root, pdfs):
    ctx = build_context()
    ctx.config.output_root = str(output_root)
    window = MainWindow(ctx)

    # 1. Instantiate Wizard via MainWindow context
    wiz = RuleBuilderWizard(ctx.config, ctx.store)
    try:
        assert wiz.config.passwords == ctx.config.passwords
        assert wiz.store == ctx.store

        # 2. Test Step 1: Load sample file
        sample_pdf = pdfs["invoice"]
        wiz.load_sample(sample_pdf)
        assert wiz.state.document is not None
        assert len(wiz.state.document.pages) > 0
        assert wiz.sample_page.isComplete()

        # 3. Test Step 2: Identification conditions
        wiz.state.selected_text = "HOA DON"
        wiz.identify_page.name.setText("Test Hoa Don E2E")
        wiz.identify_page.doctype.setText("HD")
        wiz.identify_page._add(wiz.identify_page.conditions)
        assert wiz.identify_page.isComplete()
        assert wiz.identify_page.validatePage()

        # 4. Test Step 3: Field extraction
        wiz.state.profile.fields = [
            FieldSpec(name="number", label="Số HĐ", patterns=[r"INV-(\d+)"], required=True),
        ]
        wiz.field_page._refresh()
        assert wiz.field_page.isComplete()

        # 5. Test Step 4: Template
        wiz.template_page.initializePage()
        wiz.template_page.template.setText("{doctype}_{number}")
        wiz.template_page._update_preview()
        assert wiz.template_page.validatePage()

        # 6. Finish & Save
        wiz.store.save(wiz.state.profile)

        # Verify profile was saved to store
        loaded = ctx.store.get(wiz.state.profile.id)
        assert loaded is not None
        assert loaded.name == "Test Hoa Don E2E"
    finally:
        wiz.state.close()
        window.close()
        ctx.close()


def test_main_window_action_triggers(qapp, isolated_home, output_root, monkeypatch):
    """Test clicking toolbar actions and menu actions directly on MainWindow."""
    ctx = build_context()
    ctx.config.output_root = str(output_root)
    window = MainWindow(ctx)

    wizard_opened = []
    editor_opened = []
    settings_opened = []
    stats_opened = []
    guide_opened = []

    def mock_wizard_exec(self):
        wizard_opened.append(True)
        assert self.config == ctx.config
        assert self.store == ctx.store
        return 0

    def mock_editor_exec(self):
        editor_opened.append(True)
        assert self.config == ctx.config
        assert self.store == ctx.store
        return 0

    def mock_settings_exec(self):
        settings_opened.append(True)
        assert self.config == ctx.config
        return 0

    def mock_stats_exec(self):
        stats_opened.append(True)
        assert self.learning == ctx.learning
        return 0

    def mock_guide_exec(self):
        guide_opened.append(True)
        return 0

    monkeypatch.setattr(RuleBuilderWizard, "exec", mock_wizard_exec)
    monkeypatch.setattr(RuleEditorDialog, "exec", mock_editor_exec)
    monkeypatch.setattr(SettingsDialog, "exec", mock_settings_exec)
    monkeypatch.setattr(StatsDialog, "exec", mock_stats_exec)
    from src.ui.main_window import QuickGuideDialog
    monkeypatch.setattr(QuickGuideDialog, "exec", mock_guide_exec)

    # Trigger action Add Profile (Wizard)
    window.act_wizard.trigger()
    assert len(wizard_opened) == 1

    # Trigger action Rule Manager (Editor)
    window.act_rules.trigger()
    assert len(editor_opened) == 1

    # Trigger action Settings
    window.act_settings.trigger()
    assert len(settings_opened) == 1

    # Trigger action Stats
    window.act_stats.trigger()
    assert len(stats_opened) == 1

    # Trigger action Guide
    window.act_guide.trigger()
    assert len(guide_opened) == 1

    window.close()
    ctx.close()


def test_main_window_open_rule_editor(qapp, isolated_home, output_root):
    ctx = build_context()
    ctx.config.output_root = str(output_root)

    # Test RuleEditorDialog instantiation with context
    dlg = RuleEditorDialog(ctx.config, ctx.store, ctx.learning)
    assert dlg.config == ctx.config
    assert dlg.store == ctx.store
    assert len(dlg.profiles) > 0

    # Test selecting first profile
    dlg.profile_list.setCurrentRow(0)
    assert dlg.current is not None

    dlg.close()
    ctx.close()


def test_main_window_open_settings_and_presets(qapp, isolated_home, output_root, monkeypatch):
    monkeypatch.setattr("src.ui.settings_dialog.save_config", lambda c: None)
    monkeypatch.setattr("src.ui.settings_dialog.set_api_key", lambda *a, **k: True)
    monkeypatch.setattr("src.ui.settings_dialog.find_tesseract", lambda: None)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)

    ctx = build_context()
    ctx.config.output_root = str(output_root)

    dlg = SettingsDialog(ctx.config, ctx.profiles)
    assert dlg.config == ctx.config

    # Apply default preset
    dlg._apply_quick_preset("default")
    assert dlg.workers.value() == 4
    assert dlg.subfolder_enabled.isChecked() is True

    # Apply fast preset
    dlg._apply_quick_preset("fast")
    assert dlg.ocr_enabled.isChecked() is False

    # Apply deep preset
    dlg._apply_quick_preset("deep")
    assert dlg.ocr_enabled.isChecked() is True
    assert dlg.barcode_enabled.isChecked() is True

    dlg.close()
    ctx.close()


def test_main_window_theme_toggle_and_settings(qapp, isolated_home, output_root, monkeypatch):
    monkeypatch.setattr("src.ui.settings_dialog.save_config", lambda c: None)
    monkeypatch.setattr("src.core.config.save_config", lambda c: None)

    ctx = build_context()
    ctx.config.output_root = str(output_root)
    window = MainWindow(ctx)

    # 1. Verify default theme is light
    assert window.theme.mode == "light"
    assert ctx.config.theme == "light"

    # 2. Toggle to dark mode
    window._toggle_theme()
    assert window.theme.mode == "dark"
    assert ctx.config.theme == "dark"

    # 3. Toggle back to light mode
    window._toggle_theme()
    assert window.theme.mode == "light"
    assert ctx.config.theme == "light"

    # 4. Settings dialog theme dropdown
    dlg = SettingsDialog(ctx.config, ctx.profiles, parent=window)
    assert dlg.theme_mode.currentData() == "light"
    dlg.theme_mode.setCurrentIndex(1)  # dark
    assert dlg.theme_mode.currentData() == "dark"
    dlg._save()
    assert ctx.config.theme == "dark"
    assert window.theme.mode == "dark"

    # Reset back to light
    dlg.theme_mode.setCurrentIndex(0)
    dlg._save()
    assert ctx.config.theme == "light"
    assert window.theme.mode == "light"

    dlg.close()
    window.close()
    ctx.close()

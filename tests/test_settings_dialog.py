from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)
if not hasattr(QtWidgets, "QCheckBox"):
    pytest.skip("PySide6 QtWidgets is incomplete in this environment", allow_module_level=True)

from lyon.core.settings import Settings
from lyon.ui import settings_dialog as settings_dialog_module
from lyon.ui.settings_dialog import SettingsDialog


@pytest.fixture(scope="module")
def app():
    existing = QtWidgets.QApplication.instance()
    if existing is not None:
        return existing
    return QtWidgets.QApplication([])


class _NoMissingPathPrompt:
    Yes = 1
    No = 0

    @staticmethod
    def question(*_, **__):
        raise AssertionError("missing-path confirmation should not be shown")


class _ConfirmMissingPathPrompt:
    Yes = 1
    No = 0

    @staticmethod
    def question(*_, **__):
        return _ConfirmMissingPathPrompt.Yes


class _RejectMissingPathPrompt:
    Yes = 1
    No = 0

    @staticmethod
    def question(*_, **__):
        return _RejectMissingPathPrompt.No


def test_settings_dialog_toggles_metadata_diagnostics(app, monkeypatch):
    dialog = SettingsDialog(Settings(metadata_diagnostics_enabled=False), None)
    monkeypatch.setattr(settings_dialog_module, "QMessageBox", _NoMissingPathPrompt)

    assert not dialog.metadata_diagnostics.isChecked()

    dialog.metadata_diagnostics.setChecked(True)
    dialog._accept()

    assert dialog.result_settings.metadata_diagnostics_enabled is True


def test_settings_dialog_persists_library_paths_without_duplicates(app, monkeypatch):
    dialog = SettingsDialog(Settings(library_paths=["/music/one"]), None)
    monkeypatch.setattr(settings_dialog_module, "QMessageBox", _ConfirmMissingPathPrompt)

    dialog.library_paths.addItem("/music/two")
    dialog.library_paths.addItem("/music/two")
    dialog._accept()

    assert dialog.result_settings.library_paths == ["/music/one", "/music/two"]


def test_settings_dialog_rejects_new_missing_library_path(app, monkeypatch):
    dialog = SettingsDialog(Settings(library_paths=[]), None)
    monkeypatch.setattr(settings_dialog_module, "QMessageBox", _RejectMissingPathPrompt)

    dialog.library_paths.addItem("/missing/music")
    dialog._accept()

    assert dialog.result_settings.library_paths == []

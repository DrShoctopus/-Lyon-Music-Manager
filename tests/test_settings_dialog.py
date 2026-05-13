from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)
if not hasattr(QtWidgets, "QCheckBox"):
    pytest.skip("PySide6 QtWidgets is incomplete in this environment", allow_module_level=True)

from lyon.core.settings import Settings
from lyon.ui.settings_dialog import SettingsDialog


@pytest.fixture(scope="module")
def app():
    existing = QtWidgets.QApplication.instance()
    if existing is not None:
        return existing
    return QtWidgets.QApplication([])


def test_settings_dialog_toggles_metadata_diagnostics(app):
    dialog = SettingsDialog(Settings(metadata_diagnostics_enabled=False), None)

    assert not dialog.metadata_diagnostics.isChecked()

    dialog.metadata_diagnostics.setChecked(True)
    dialog._accept()

    assert dialog.result_settings.metadata_diagnostics_enabled is True

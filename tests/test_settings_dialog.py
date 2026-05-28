from __future__ import annotations

import os
from unittest.mock import MagicMock

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)
QtCore = pytest.importorskip("PySide6.QtCore", exc_type=ImportError)
QtTest = pytest.importorskip("PySide6.QtTest", exc_type=ImportError)
if not hasattr(QtWidgets, "QCheckBox"):
    pytest.skip("PySide6 QtWidgets is incomplete in this environment", allow_module_level=True)

from lyon.core.settings import Settings
from lyon.ui.about import COPYRIGHT_NOTICE
from lyon.ui import settings_dialog as settings_dialog_module
from lyon.ui.settings_dialog import SettingsDialog
from lyon.ui.styles import WMP_QSS


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


def test_settings_dialog_opens_wide_enough_for_top_tabs(app):
    previous_stylesheet = app.styleSheet()
    app.setStyleSheet(WMP_QSS)
    try:
        dialog = SettingsDialog(Settings(), None)
        tabs = dialog.findChild(QtWidgets.QTabWidget)
        assert tabs is not None

        margins = dialog.layout().contentsMargins()
        needed_width = tabs.tabBar().sizeHint().width() + margins.left() + margins.right()

        assert dialog.width() >= needed_width
        assert dialog.minimumWidth() >= needed_width
        assert dialog.width() <= needed_width + 4
    finally:
        app.setStyleSheet(previous_stylesheet)


def test_settings_dialog_spinbox_up_buttons_increment(app):
    previous_stylesheet = app.styleSheet()
    app.setStyleSheet(WMP_QSS)
    try:
        dialog = SettingsDialog(Settings(crossfade_seconds=3, replaygain_preamp_db=0.0), None)
        dialog.show()
        app.processEvents()

        for spinbox, expected in ((dialog.crossfade_seconds, 4), (dialog.rg_preamp, 0.5)):
            option = QtWidgets.QStyleOptionSpinBox()
            spinbox.initStyleOption(option)
            up_button = spinbox.style().subControlRect(
                QtWidgets.QStyle.CC_SpinBox,
                option,
                QtWidgets.QStyle.SC_SpinBoxUp,
                spinbox,
            )
            assert up_button.isValid()

            QtTest.QTest.mouseClick(
                spinbox,
                QtCore.Qt.LeftButton,
                QtCore.Qt.NoModifier,
                up_button.center(),
            )
            app.processEvents()
            assert spinbox.value() == expected
    finally:
        app.setStyleSheet(previous_stylesheet)


def test_settings_dialog_persists_library_paths_without_duplicates(app, monkeypatch):
    dialog = SettingsDialog(Settings(library_paths=["/music/one"]), None)
    monkeypatch.setattr(settings_dialog_module, "QMessageBox", _ConfirmMissingPathPrompt)

    dialog.library_paths.addItem("/music/two")
    dialog.library_paths.addItem("/music/two")
    dialog._accept()

    assert dialog.result_settings.library_paths == ["/music/one", "/music/two"]


def test_settings_dialog_persists_watched_folder_toggle(app, monkeypatch):
    dialog = SettingsDialog(Settings(watch_library_folders=True), None)

    dialog.watch_library_folders.setChecked(False)
    dialog._accept()

    assert dialog.result_settings.watch_library_folders is False


def test_settings_dialog_persists_crossfade_seconds(app):
    dialog = SettingsDialog(Settings(crossfade_seconds=3), None)

    assert dialog.crossfade_seconds.value() == 3

    dialog.crossfade_seconds.setValue(7)
    dialog._accept()

    assert dialog.result_settings.crossfade_seconds == 7


def test_settings_dialog_persists_dlna_options(app):
    dialog = SettingsDialog(
        Settings(
            dlna_enabled=False,
            dlna_port=8200,
            dlna_friendly_name="Sea Lyon Media Manager",
            dlna_bind_address="0.0.0.0",
        ),
        None,
    )

    dialog.dlna_enabled.setChecked(True)
    dialog.dlna_port.setValue(0)
    dialog.dlna_name.setText("Living Room Library")
    dialog.dlna_bind_address.setText("127.0.0.1")
    dialog._accept()

    assert dialog.result_settings.dlna_enabled is True
    assert dialog.result_settings.dlna_port == 0
    assert dialog.result_settings.dlna_friendly_name == "Living Room Library"
    assert dialog.result_settings.dlna_bind_address == "127.0.0.1"


def test_settings_dialog_connect_lastfm_starts_auth(app):
    scrobbler = MagicMock()
    scrobbler.lastfm_token_ready.connect = MagicMock()
    scrobbler.lastfm_auth_complete.connect = MagicMock()
    scrobbler.lastfm_auth_failed.connect = MagicMock()
    dialog = SettingsDialog(Settings(), None, scrobbler=scrobbler)

    dialog._connect_lastfm()

    scrobbler.start_lastfm_auth.assert_called_once()


def test_settings_dialog_about_tab_matches_help_about(app):
    """Settings About tab must mirror Help → About: copyright + description present,
    no third-party acknowledgements (those live in a separate Acknowledgements tab)."""
    from lyon import __app_name__, __version__
    dialog = SettingsDialog(Settings(), None)
    about_text = "\n".join(label.text() for label in dialog.findChildren(QtWidgets.QLabel))

    assert COPYRIGHT_NOTICE in about_text
    assert __app_name__ in about_text
    assert __version__ in about_text
    assert "Windows 10 / 11" in about_text
    assert "Apple Silicon" in about_text


def test_settings_dialog_rejects_new_missing_library_path(app, monkeypatch):
    dialog = SettingsDialog(Settings(library_paths=[]), None)
    monkeypatch.setattr(settings_dialog_module, "QMessageBox", _RejectMissingPathPrompt)

    dialog.library_paths.addItem("/missing/music")
    dialog._accept()

    assert dialog.result_settings.library_paths == []

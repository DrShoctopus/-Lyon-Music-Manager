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
from lyon.ui import settings_dialog as settings_dialog_module
from lyon.ui.about import COPYRIGHT_NOTICE
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


def test_settings_dialog_marks_blank_theaudiodb_key_as_opt_out(app, monkeypatch):
    dialog = SettingsDialog(Settings(theaudiodb_api_key="123"), None)
    monkeypatch.setattr(settings_dialog_module, "QMessageBox", _NoMissingPathPrompt)

    dialog.audiodb_key.clear()
    dialog._accept()

    assert dialog.result_settings.theaudiodb_api_key == ""
    assert dialog.result_settings.theaudiodb_api_key_opt_out is True


def test_settings_dialog_persists_youtube_browser_cookies_option(app, monkeypatch):
    dialog = SettingsDialog(Settings(), None)
    monkeypatch.setattr(settings_dialog_module, "QMessageBox", _NoMissingPathPrompt)

    assert dialog.yt_browser_cookies_browser.isEnabled() is False

    dialog.yt_use_browser_cookies.setChecked(True)
    dialog.yt_browser_cookies_browser.setCurrentText("Chrome")
    dialog._accept()

    assert dialog.result_settings.yt_use_browser_cookies is True
    assert dialog.result_settings.yt_browser_cookies_browser == "chrome"


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


def test_settings_dialog_form_fields_have_room_to_grow(app):
    dialog = SettingsDialog(Settings(), None)

    forms = dialog.findChildren(QtWidgets.QFormLayout)
    assert forms
    for form in forms:
        assert form.fieldGrowthPolicy() == (
            QtWidgets.QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow
        )

    for widget in (
        dialog.root_edit,
        dialog.library_paths,
        dialog.contact,
        dialog.yt_save_dir,
        dialog.lbz_token,
        dialog.update_appcast_url,
    ):
        assert widget.minimumWidth() >= 420

    for combo in (
        dialog.audio_output_combo,
        dialog.audio_device_combo,
        dialog.rg_mode,
        dialog.rip_fmt,
        dialog.yt_video_quality,
    ):
        assert combo.minimumWidth() >= 220
        assert combo.sizeAdjustPolicy() == (
            QtWidgets.QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )


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


def test_settings_dialog_rejects_non_https_update_feed_url(app):
    default_url = Settings().update_appcast_url
    dialog = SettingsDialog(Settings(update_appcast_url=default_url), None)

    dialog.update_appcast_url.setText("http://example.test/appcast.xml")
    dialog._accept()

    assert dialog.result_settings.update_appcast_url == default_url


def test_settings_dialog_check_now_rejects_non_https_update_feed_url(app):
    default_url = Settings().update_appcast_url

    class Parent(QtWidgets.QWidget):
        def __init__(self):
            super().__init__()
            self.settings = Settings(update_appcast_url=default_url)
            self.checked = False
            self.toast_host = None

        def check_for_updates_now(self, *, toast_host=None):
            self.checked = True
            self.toast_host = toast_host

    parent = Parent()
    dialog = SettingsDialog(Settings(update_appcast_url=default_url), parent)

    dialog.update_appcast_url.setText("http://example.test/appcast.xml")
    dialog._on_check_for_updates_clicked()

    assert parent.checked is True
    assert parent.toast_host is dialog
    assert parent.settings.update_appcast_url == default_url


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

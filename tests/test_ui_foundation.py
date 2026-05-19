from __future__ import annotations

import importlib
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)


@pytest.fixture(scope="module")
def app():
    existing = QtWidgets.QApplication.instance()
    if existing is not None:
        return existing
    return QtWidgets.QApplication([])


def test_theme_constants_exported():
    from lyon.ui import theme

    for name in (
        "TEXT_PRIMARY", "TEXT_SECONDARY", "TEXT_MUTED", "TEXT_DIM",
        "ACCENT_CYAN", "ACCENT_BLUE",
        "BG_DEEP", "BG_PANEL", "BORDER_DEFAULT",
        "STATUS_OK", "STATUS_WARNING", "STATUS_ERROR", "STATUS_FAILED",
    ):
        value = getattr(theme, name)
        assert isinstance(value, str)
        assert value.startswith("#") and len(value) == 7


def test_icons_returns_qicon_for_known_name(app):
    from PySide6.QtGui import QIcon

    from lyon.ui.icons import icon

    assert isinstance(icon("play"), QIcon)
    assert isinstance(icon("does-not-exist"), QIcon)


def test_icons_has_asset_reports_false_when_missing():
    from lyon.ui.icons import has_asset

    assert has_asset("definitely-not-a-real-icon-name") is False


def test_font_scaled_returns_int(app):
    from lyon.ui.widgets import font_scaled

    assert isinstance(font_scaled(20), int)
    assert font_scaled(20) >= 1
    assert font_scaled(0) >= 1


def test_ui_modules_import(app):
    for mod in (
        "lyon.ui.branding",
        "lyon.ui.diagnostics_dialog",
        "lyon.ui.equalizer_dialog",
        "lyon.ui.first_run_dialog",
        "lyon.ui.icons",
        "lyon.ui.library_view",
        "lyon.ui.now_playing",
        "lyon.ui.queue_dialog",
        "lyon.ui.radio_view",
        "lyon.ui.ripper_view",
        "lyon.ui.settings_dialog",
        "lyon.ui.styles",
        "lyon.ui.theme",
        "lyon.ui.video_player_view",
        "lyon.ui.widgets",
        "lyon.ui.youtube_view",
        "lyon.ui.yt_download_dialog",
    ):
        importlib.import_module(mod)

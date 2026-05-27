"""Phase 7: accessibility + branding sweep.

Locks in three guarantees:
1. No UI module reintroduces inline setStyleSheet (drift sink).
2. Symbolic / icon-only widgets carry an accessibleName.
3. The QSS exposes :focus rules for buttons, tabs, sliders, inputs
   so keyboard navigation is visible.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtCore = pytest.importorskip("PySide6.QtCore", exc_type=ImportError)
QtWidgets = pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)


_UI_MODULES_NO_INLINE_STYLES = (
    "lyon/ui/library_view.py",
    "lyon/ui/artist_panel.py",
    "lyon/ui/now_playing.py",
    "lyon/ui/radio_view.py",
    "lyon/ui/video_player_view.py",
    "lyon/ui/youtube_view.py",
    "lyon/ui/ripper_view.py",
    "lyon/ui/toast.py",
    "lyon/ui/osd.py",
    "lyon/ui/transport.py",
)


@pytest.fixture(scope="module")
def app():
    existing = QtWidgets.QApplication.instance()
    if existing is not None:
        return existing
    return QtWidgets.QApplication([])


@pytest.mark.parametrize("module_path", _UI_MODULES_NO_INLINE_STYLES)
def test_ui_module_has_no_inline_setstylesheet(module_path):
    src = Path(module_path).read_text(encoding="utf-8")
    cleaned = re.sub(r"#.*", "", src)  # strip comments
    assert "setStyleSheet" not in cleaned, (
        f"{module_path} still contains setStyleSheet — use a named QSS class instead."
    )


def test_styles_module_owns_the_central_stylesheet_call():
    """styles.py is the only UI module allowed to apply WMP_QSS."""
    src = Path("lyon/ui/styles.py").read_text(encoding="utf-8")
    cleaned = re.sub(r"#.*", "", src)
    occurrences = cleaned.count("setStyleSheet")
    assert occurrences == 1, (
        f"Expected exactly 1 central setStyleSheet call in styles.py, found {occurrences}."
    )


def test_main_window_uses_central_stylesheet_helper():
    """MainWindow should not own stylesheet application directly."""
    src = Path("lyon/ui/main_window.py").read_text(encoding="utf-8")
    cleaned = re.sub(r"#.*", "", src)
    occurrences = cleaned.count("setStyleSheet")
    assert occurrences == 0, (
        f"Expected main_window.py to use apply_app_styles(), found {occurrences} direct calls."
    )


def test_toast_close_button_has_accessible_name(app):
    from lyon.ui.toast import Toast
    t = Toast("hi", duration_ms=0)
    close_btns = [
        b for b in t.findChildren(QtWidgets.QToolButton)
        if b.accessibleName() == "Dismiss notification"
    ]
    assert len(close_btns) == 1


def test_library_search_has_accessible_name(app):
    from lyon.ui.library_view import LibraryView

    class _EmptyLib:
        def all_artists(self, _): return []

    view = LibraryView(_EmptyLib())
    assert view.search.accessibleName() == "Library search"


def test_settings_about_tab_shows_branding_pixmap(app):
    from lyon.core.settings import Settings
    from lyon.ui.settings_dialog import SettingsDialog
    dlg = SettingsDialog(Settings.load())
    labels_with_pix = [
        l for l in dlg.findChildren(QtWidgets.QLabel)
        if l.pixmap() is not None and not l.pixmap().isNull()
    ]
    # At least one QLabel should carry the app icon pixmap.
    assert len(labels_with_pix) >= 1


_QSS = Path("lyon/ui/styles.py").read_text(encoding="utf-8")


@pytest.mark.parametrize("selector", [
    "QPushButton:focus",
    "QToolButton:focus",
    "QTabBar::tab:focus",
    "QSlider:focus",
    "QLineEdit:focus",
])
def test_qss_defines_focus_indicator_for(selector):
    """Keyboard users need a visible focus ring on every interactive class."""
    assert selector in _QSS, (
        f"QSS missing :focus rule for {selector} — keyboard navigation lacks visible focus."
    )


@pytest.mark.parametrize("object_name", [
    "videoCardTitle",
    "videoCardDuration",
    "videoCatalogTitle",
    "videoCatalogCount",
    "videoSplash",
    "videoFullscreenWindow",
    "videoSidebarSeparator",
    "nowPlayingCover",
    "youtubeThumb",
    "youtubeResults",
    "ripperCover",
])
def test_qss_defines_named_class(object_name):
    """Phase 7 added these object names — guard against regressions."""
    assert f"#{object_name}" in _QSS, f"QSS missing rule for #{object_name}"

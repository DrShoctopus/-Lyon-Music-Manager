"""Phase 5: OSD overlay widget tests."""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtCore = pytest.importorskip("PySide6.QtCore", exc_type=ImportError)
QtWidgets = pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from lyon.ui.osd import OSDOverlay


@pytest.fixture(scope="module")
def app():
    existing = QtWidgets.QApplication.instance()
    if existing is not None:
        return existing
    return QtWidgets.QApplication([])


@pytest.fixture
def host(app):
    w = QtWidgets.QWidget()
    w.resize(800, 600)
    w.show()
    app.processEvents()
    yield w
    w.hide()


def test_show_message_sets_text_and_shows(host, app):
    osd = OSDOverlay()
    osd.show_message("+5s", host, duration_ms=10_000)  # long timer; we close manually
    app.processEvents()
    assert osd.message() == "+5s"
    assert osd.isVisible()
    osd.hide()


def test_message_round_trip(host):
    osd = OSDOverlay()
    osd.show_message("Volume 75", host, duration_ms=10_000)
    assert osd.message() == "Volume 75"
    osd.hide()


def test_overlay_does_not_steal_focus(host, app):
    osd = OSDOverlay()
    host.setFocus()
    osd.show_message("Muted", host, duration_ms=10_000)
    app.processEvents()
    # The OSD must not become the focus widget.
    assert app.focusWidget() is not osd
    osd.hide()


def test_show_with_none_host_still_shows(app):
    """show_message must not crash when no host is provided."""
    osd = OSDOverlay()
    osd.show_message("Paused", None, duration_ms=10_000)
    app.processEvents()
    assert osd.message() == "Paused"
    osd.hide()

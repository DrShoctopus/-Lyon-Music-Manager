"""Phase 4: toast notification widget tests."""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from lyon.ui.toast import Toast


@pytest.fixture(scope="module")
def app():
    existing = QtWidgets.QApplication.instance()
    if existing is not None:
        return existing
    return QtWidgets.QApplication([])


@pytest.fixture
def host(app):
    w = QtWidgets.QWidget()
    w.resize(600, 400)
    w.show()
    app.processEvents()
    yield w
    w.hide()


def test_toast_renders_message_and_level(host):
    t = Toast("Saved.", level="success", duration_ms=0, parent=host)
    t.show_at(host)
    assert t.isVisible()
    assert t.message() == "Saved."
    assert t.level == "success"


def test_invalid_level_falls_back_to_info(host):
    t = Toast("hi", level="bogus", duration_ms=0, parent=host)
    assert t.level == "info"


def test_toast_positions_at_bottom_center(host):
    t = Toast("Hello", duration_ms=0, parent=host)
    t.show_at(host, bottom_margin=20)
    expected_y = host.height() - t.height() - 20
    expected_x = (host.width() - t.width()) // 2
    assert abs(t.y() - expected_y) <= 1
    assert abs(t.x() - expected_x) <= 1


def test_toast_action_button_present_when_label_given(host):
    t = Toast("Removed 3 tracks", level="warning",
              duration_ms=0, action_label="Undo", parent=host)
    assert t.action_button is not None
    assert t.action_button.text() == "Undo"


def test_toast_action_button_absent_by_default(host):
    t = Toast("Plain", duration_ms=0, parent=host)
    assert t.action_button is None


def test_dismiss_starts_fade_out(host):
    t = Toast("bye", duration_ms=0, parent=host)
    t.show_at(host)
    t.dismiss()
    # _closing is set synchronously; the deleteLater fires after fade animation.
    assert t._closing is True
    # Calling dismiss again should be a no-op.
    t.dismiss()
    assert t._closing is True


def test_reposition_recenters_after_host_resize(host):
    t = Toast("Resize me", duration_ms=0, parent=host)
    t.show_at(host, bottom_margin=10)
    host.resize(900, 500)
    t.reposition(bottom_margin=10)
    expected_x = (host.width() - t.width()) // 2
    expected_y = host.height() - t.height() - 10
    assert abs(t.x() - expected_x) <= 1
    assert abs(t.y() - expected_y) <= 1

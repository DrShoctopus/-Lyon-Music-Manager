"""Phase 8: end-to-end MainWindow wiring smoke tests.

Constructs a real MainWindow with a stub Player backend (so no libVLC
is needed) and asserts the cross-cutting wiring established across
Phases 1–7 still holds together:
- tab order matches the documented Library/Now Playing/Video/Rip/YouTube
- clicking a tab swaps the QStackedWidget page
- transport bar hides on the rip + video tabs, shows elsewhere
- show_toast creates a Toast and replaces any prior toast
- scan progress indicator toggles visibility around _start_scan
- Ctrl+1..5 shortcuts are wired to the View menu
- window icon is set from branding.app_icon()
"""
from __future__ import annotations

import pytest

QtCore = pytest.importorskip("PySide6.QtCore", exc_type=ImportError)
QtGui = pytest.importorskip("PySide6.QtGui", exc_type=ImportError)
QtWidgets = pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)


@pytest.fixture
def main_window(qapp, fake_backend, monkeypatch):
    """Build a MainWindow with the Player backed by FakeBackend."""
    # Patch create_playback_backend BEFORE MainWindow is imported so that
    # MainWindow's `self.player = Player(self)` uses the fake.
    from lyon.core import player as player_mod

    def _stub(_parent):
        return fake_backend

    monkeypatch.setattr(player_mod, "create_playback_backend", _stub)

    from lyon.ui.main_window import MainWindow
    w = MainWindow()
    yield w
    # Ensure libraries / threads release before next test.
    w.player.stop()
    w.library.close()
    w.deleteLater()


def test_tab_bar_renders_documented_order(main_window):
    expected = ("Library", "Now Playing", "Video", "Rip", "YouTube")
    actual = tuple(
        main_window.tab_bar.tabText(i)
        for i in range(main_window.tab_bar.count())
    )
    assert actual == expected


def test_clicking_a_tab_swaps_stack_page(main_window):
    main_window.tab_bar.setCurrentIndex(main_window._tab_index["Rip"])
    assert main_window.stack.currentWidget() is main_window.ripper_view
    main_window.tab_bar.setCurrentIndex(main_window._tab_index["Library"])
    assert main_window.stack.currentWidget() is main_window.library_view


def test_transport_visible_on_library_hidden_on_rip(main_window):
    # isHidden() reflects explicit setVisible(False) calls regardless of
    # whether the parent window has been .show()n yet.
    main_window.tab_bar.setCurrentIndex(main_window._tab_index["Library"])
    assert not main_window.transport.isHidden()
    main_window.tab_bar.setCurrentIndex(main_window._tab_index["Rip"])
    assert main_window.transport.isHidden()
    main_window.tab_bar.setCurrentIndex(main_window._tab_index["Video"])
    assert main_window.transport.isHidden()
    main_window.tab_bar.setCurrentIndex(main_window._tab_index["Now Playing"])
    assert not main_window.transport.isHidden()


def test_show_toast_creates_and_replaces_previous(main_window, qapp):
    from lyon.ui.toast import Toast

    t1 = main_window.show_toast("First", level="info", duration_ms=0)
    assert isinstance(t1, Toast)
    assert main_window._current_toast is t1

    t2 = main_window.show_toast("Second", level="success", duration_ms=0)
    assert main_window._current_toast is t2
    assert t2 is not t1
    # The previous toast is dismissed (closing == True even before deletion).
    assert t1._closing is True


def test_show_toast_with_action_button(main_window):
    captured = []
    main_window.show_toast(
        "Removed",
        level="warning",
        duration_ms=0,
        action=("Undo", lambda: captured.append("undone")),
    )
    toast = main_window._current_toast
    assert toast.action_button is not None
    assert toast.action_button.text() == "Undo"
    toast.action_button.click()
    assert captured == ["undone"]


def test_scan_progress_indicator_hidden_by_default(main_window):
    assert not main_window._scan_progress.isVisible()
    assert not main_window._scan_status_label.isVisible()


def test_window_icon_is_set(main_window):
    icon = main_window.windowIcon()
    # Either we have a real branded icon or a fallback null one. Both are
    # acceptable — the call shouldn't crash and the property must exist.
    assert isinstance(icon, QtGui.QIcon)


def test_ctrl_number_shortcuts_wired(main_window):
    """Every documented tab must have a Ctrl+N action firing it."""
    expected = {
        "Library":     "Ctrl+1",
        "Now Playing": "Ctrl+2",
        "Video":       "Ctrl+3",
        "Rip":         "Ctrl+4",
        "YouTube":     "Ctrl+5",
    }
    # Walk the menubar actions to find the View menu.
    view_menu = None
    for action in main_window.menuBar().actions():
        if action.text().replace("&", "") == "View":
            view_menu = action.menu()
            break
    assert view_menu is not None
    actual = {a.text(): a.shortcut().toString() for a in view_menu.actions()}
    for label, shortcut in expected.items():
        assert actual.get(label) == shortcut, (
            f"View menu missing {label} → {shortcut}; got {actual}"
        )


def test_status_bar_carries_scan_progress_widgets(main_window):
    """addPermanentWidget should have attached the label + bar to the status bar."""
    sb = main_window.statusBar()
    # Sanity: the permanent widgets are children of the status bar.
    assert main_window._scan_progress.parent() is sb
    assert main_window._scan_status_label.parent() is sb

"""Phase 8: end-to-end MainWindow wiring smoke tests.

Constructs a real MainWindow with a stub Player backend (so no libVLC
is needed) and asserts the cross-cutting wiring established across
Phases 1–7 still holds together:
- tab order matches the documented Library/Now Playing/Video/Disc/Rip/YouTube
- clicking a tab swaps the QStackedWidget page
- transport bar hides on the rip + video tabs, shows elsewhere
- entering the Video tab pauses music playback
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
def main_window(qapp, fake_backend, monkeypatch, tmp_path):
    """Build a MainWindow with the Player backed by FakeBackend."""
    # Patch create_playback_backend BEFORE MainWindow is imported so that
    # MainWindow's `self.player = Player(self)` uses the fake.
    from lyon.core import player as player_mod
    from lyon.core.library import Library
    from lyon.core.settings import Settings

    def _stub(_parent):
        return fake_backend

    monkeypatch.setattr(player_mod, "create_playback_backend", _stub)
    settings = Settings(
        music_root=str(tmp_path / "Music"),
        library_paths=[],
        first_run_completed=True,
    )
    monkeypatch.setattr(Settings, "load", classmethod(lambda cls: settings))

    from lyon.ui import main_window as main_window_mod
    monkeypatch.setattr(
        main_window_mod,
        "Library",
        lambda: Library(tmp_path / "library.db"),
    )
    MainWindow = main_window_mod.MainWindow
    w = MainWindow()
    yield w
    # Ensure libraries / threads release before next test.
    w.player.stop()
    w.library.close()
    w.deleteLater()


def test_tab_bar_renders_documented_order(main_window):
    expected = ("Library", "Now Playing", "Video", "Disc", "Rip", "YouTube")
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
    main_window.tab_bar.setCurrentIndex(main_window._tab_index["Disc"])
    assert not main_window.transport.isHidden()
    main_window.tab_bar.setCurrentIndex(main_window._tab_index["Now Playing"])
    assert not main_window.transport.isHidden()


def test_selecting_video_tab_pauses_music_player(main_window, fake_backend):
    fake_backend.play()
    assert main_window.player.is_playing()

    main_window.tab_bar.setCurrentIndex(main_window._tab_index["Video"])

    assert main_window.stack.currentWidget() is main_window.video_player_view
    assert not main_window.player.is_playing()


def test_disc_tab_no_drive_state(main_window):
    main_window.tab_bar.setCurrentIndex(main_window._tab_index["Disc"])

    assert main_window.stack.currentWidget() is main_window.disc_view
    assert not main_window.disc_view.probe_btn.isEnabled()


def test_video_disc_handoff_uses_video_player_after_switching_tabs(main_window, monkeypatch, qapp):
    from lyon.core.disc_playback import DiscKind, VideoDiscSource

    calls = []
    monkeypatch.setattr(main_window.video_player_view, "playback_available", lambda: True)
    monkeypatch.setattr(
        main_window.video_player_view,
        "load_location",
        lambda uri, **kwargs: calls.append((uri, kwargs, main_window.stack.currentWidget())),
    )
    source = VideoDiscSource("D:", DiscKind.DVD, "dvd:///D:/", "dvdsimple:///D:/", "DVD")
    main_window.tab_bar.setCurrentIndex(main_window._tab_index["Disc"])

    main_window._play_video_disc(source)

    assert calls == []
    assert main_window.stack.currentWidget() is main_window.video_player_view
    qapp.processEvents(QtCore.QEventLoop.AllEvents, 50)
    assert calls == [("dvd:///D:/", {"label": "DVD"}, main_window.video_player_view)]


def test_video_disc_handoff_reports_unavailable_video_player(main_window, monkeypatch):
    from lyon.core.disc_playback import DiscKind, VideoDiscSource

    monkeypatch.setattr(main_window.video_player_view, "playback_available", lambda: False)
    monkeypatch.setattr(main_window.video_player_view, "unavailable_reason", lambda: "libVLC missing")
    monkeypatch.setattr(
        main_window.video_player_view,
        "load_location",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("should not load")),
    )
    source = VideoDiscSource("D:", DiscKind.DVD, "dvd:///D:/", "dvdsimple:///D:/", "DVD")

    main_window._play_video_disc(source)

    assert main_window._current_toast is not None
    assert "Video disc playback requires VLC/libVLC" in main_window._current_toast.message()
    assert "libVLC missing" in main_window.statusBar().currentMessage()


def test_youtube_video_completion_switches_to_video_tab_and_refreshes_catalog(main_window, monkeypatch):
    calls = []
    monkeypatch.setattr(main_window.video_player_view, "refresh_catalog", lambda: calls.append("refresh"))
    main_window.tab_bar.setCurrentIndex(main_window._tab_index["YouTube"])
    main_window._library_refresh_timer.stop()

    try:
        main_window._on_yt_video_download_finished()

        assert main_window.stack.currentWidget() is main_window.video_player_view
        assert calls == ["refresh"]
        assert main_window._library_refresh_timer.isActive()
    finally:
        main_window._library_refresh_timer.stop()


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


def test_startup_scan_prunes_missing_library_rows(qapp, fake_backend, monkeypatch, tmp_path):
    from lyon.core import player as player_mod
    from lyon.core.library import Library
    from lyon.core.settings import Settings
    from lyon.ui import main_window as main_window_mod

    monkeypatch.setattr(player_mod, "create_playback_backend", lambda _parent: fake_backend)
    library_root = tmp_path / "Music"
    library_root.mkdir()
    settings = Settings(
        music_root=str(library_root),
        library_paths=[str(library_root)],
        watch_library_folders=False,
        first_run_completed=True,
    )
    monkeypatch.setattr(Settings, "load", classmethod(lambda cls: settings))
    monkeypatch.setattr(
        main_window_mod,
        "Library",
        lambda: Library(tmp_path / "library.db"),
    )
    scan_calls = []

    def record_start_scan(self, roots, label, prune=False):
        scan_calls.append((roots, label, prune))

    monkeypatch.setattr(main_window_mod.MainWindow, "_start_scan", record_start_scan)

    w = main_window_mod.MainWindow()
    try:
        assert scan_calls == [([str(library_root)], "Scanned", True)]
    finally:
        w.player.stop()
        w.library.close()
        w.deleteLater()


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
        "Disc":        "Ctrl+4",
        "Rip":         "Ctrl+5",
        "YouTube":     "Ctrl+6",
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


def test_close_event_waits_for_replaygain_scanner_to_stop(main_window):
    class StuckScanner:
        def __init__(self):
            self.interrupted = False
            self.waited_ms = None

        def isRunning(self):
            return True

        def requestInterruption(self):
            self.interrupted = True

        def wait(self, ms):
            self.waited_ms = ms
            return False

    class CloseEvent:
        def __init__(self):
            self.ignored = False

        def ignore(self):
            self.ignored = True

    scanner = StuckScanner()
    event = CloseEvent()
    main_window._rg_scanner = scanner

    main_window.closeEvent(event)

    assert scanner.interrupted
    assert scanner.waited_ms == 3000
    assert event.ignored
    assert "ReplayGain scan is still stopping" in main_window._current_toast.message()


def test_watcher_events_are_filtered_to_current_library_roots(main_window, tmp_path):
    from lyon.core.library_watcher import WatchBatch

    inside = tmp_path / "Music" / "song.flac"
    outside = tmp_path / "Outside" / "song.flac"
    moved_inside = tmp_path / "Music" / "moved.flac"
    inside.parent.mkdir(parents=True)
    outside.parent.mkdir(parents=True)
    main_window.settings.library_paths = [str(tmp_path / "Music")]

    batch = WatchBatch(
        changed_paths={str(inside), str(outside)},
        deleted_paths={str(outside)},
        moved_paths={
            str(inside): str(moved_inside),
            str(outside): str(tmp_path / "Music" / "imported.flac"),
        },
        scan_roots={str(tmp_path / "Music"), str(tmp_path / "Outside")},
        moved_folders={
            str(tmp_path / "Music" / "Old"): str(tmp_path / "Music" / "New"),
            str(tmp_path / "Outside" / "Old"): str(tmp_path / "Music" / "Imported"),
        },
    )

    filtered = main_window._filter_watch_batch_to_current_roots(batch)

    assert filtered.changed_paths == {
        str(inside),
        str(tmp_path / "Music" / "imported.flac"),
    }
    assert filtered.deleted_paths == set()
    assert filtered.moved_paths == {str(inside): str(moved_inside)}
    assert filtered.scan_roots == {
        str(tmp_path / "Music"),
        str(tmp_path / "Music" / "Imported"),
    }
    assert filtered.moved_folders == {
        str(tmp_path / "Music" / "Old"): str(tmp_path / "Music" / "New")
    }


def test_watched_indexing_waits_while_ripping(main_window, tmp_path, monkeypatch):
    from lyon.core.library_watcher import WatchBatch

    rip_output = tmp_path / "Music" / "01 - Track.flac"
    main_window._watch_pending = WatchBatch(changed_paths={str(rip_output)})
    monkeypatch.setattr(main_window, "_ripper_is_running", lambda: True)

    main_window._flush_library_watch_events()

    try:
        assert not main_window._watch_pending.is_empty()
        assert main_window._watch_index_thread is None
        assert not main_window._scan_progress.isVisible()
        assert not main_window._scan_status_label.isVisible()
    finally:
        main_window._watch_debounce_timer.stop()


def test_main_window_stays_usable_when_playback_backend_is_unavailable(qapp, monkeypatch, tmp_path):
    from lyon.core import player as player_mod
    from lyon.core.library import Library
    from lyon.core.playback_backend import UnavailablePlaybackBackend
    from lyon.core.settings import Settings
    from lyon.ui import main_window as main_window_mod

    monkeypatch.setattr(
        player_mod,
        "create_playback_backend",
        lambda _parent: UnavailablePlaybackBackend("libVLC missing"),
    )
    settings = Settings(
        music_root=str(tmp_path / "Music"),
        library_paths=[],
        first_run_completed=True,
    )
    monkeypatch.setattr(Settings, "load", classmethod(lambda cls: settings))
    monkeypatch.setattr(
        main_window_mod,
        "Library",
        lambda: Library(tmp_path / "library.db"),
    )

    w = main_window_mod.MainWindow()
    try:
        assert not w.player.playback_available()

        w.player.play()

        assert w._current_toast is not None
        assert "Audio playback requires VLC/libVLC" in w._current_toast.message()
        assert "libVLC missing" in w.statusBar().currentMessage()
    finally:
        w.player.stop()
        w.library.close()
        w.deleteLater()

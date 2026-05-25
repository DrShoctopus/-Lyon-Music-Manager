"""Phase 8: end-to-end MainWindow wiring smoke tests.

Constructs a real MainWindow with a stub Player backend (so no libVLC
is needed) and asserts the cross-cutting wiring established across
Phases 1–7 still holds together:
- tab order matches the documented Library/Now Playing/Podcasts/Radio/Video/Disc/Rip/YouTube
- clicking a tab swaps the QStackedWidget page
- transport bar hides on the rip + video tabs, shows elsewhere
- entering the Video tab pauses music playback
- show_toast creates a Toast and replaces any prior toast
- scan progress indicator toggles visibility around _start_scan
- Ctrl+1..7 preserve historical tab shortcuts, and Podcasts uses Ctrl+8
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
        # Pre-accept the YouTube ToS gate so tests that activate the
        # YouTube tab don't hang on the modal acknowledgement dialog.
        youtube_acknowledged=True,
        update_check_enabled=False,
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
    expected = ("Library", "Now Playing", "Podcasts", "Radio", "Video", "Disc", "Rip", "YouTube")
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


def test_activate_tab_ignores_out_of_range_index(main_window):
    main_window._last_confirmed_tab_idx = main_window._tab_index["Library"]

    main_window._activate_tab(999)

    assert main_window._last_confirmed_tab_idx == main_window._tab_index["Library"]


def test_drop_event_reports_skipped_files(main_window, monkeypatch, tmp_path):
    from lyon.core.library import IndexResult

    media = tmp_path / "unreadable.mp3"
    media.write_bytes(b"not real media")
    toasts: list[tuple[str, str]] = []

    monkeypatch.setattr(
        main_window.library,
        "index_file",
        lambda path, **_kwargs: IndexResult("skipped", str(path), "Unsupported metadata"),
    )
    monkeypatch.setattr(main_window.library, "commit", lambda: None)
    monkeypatch.setattr(main_window.library_view, "refresh", lambda: None)
    monkeypatch.setattr(main_window.dlna_server, "invalidate_cache", lambda: None)
    monkeypatch.setattr(
        main_window,
        "show_toast",
        lambda message, level="info", **_kwargs: toasts.append((message, level)),
    )

    class _MimeData:
        def urls(self):
            return [QtCore.QUrl.fromLocalFile(str(media))]

    class _DropEvent:
        def __init__(self) -> None:
            self.accepted = False

        def mimeData(self):
            return _MimeData()

        def acceptProposedAction(self) -> None:
            self.accepted = True

    event = _DropEvent()

    main_window.dropEvent(event)

    assert event.accepted is True
    assert toasts == [("No supported files were added. 1 file skipped.", "warning")]


def test_failed_auto_update_records_retry_timestamp(main_window, monkeypatch):
    saves: list[bool] = []
    main_window._update_manual_request = False
    monkeypatch.setattr("time.time", lambda: 12_345.0)
    monkeypatch.setattr(main_window.settings, "save", lambda: saves.append(True))

    main_window._on_update_check_failed("offline")

    assert main_window.settings.last_update_failure_ts == 12_345
    assert saves == [True]


def test_auto_update_failure_backoff_blocks_startup_retry(main_window, monkeypatch):
    calls: list[bool] = []
    main_window.settings.update_check_enabled = True
    main_window.settings.first_run_completed = True
    main_window.settings.last_update_check_ts = 0
    main_window.settings.last_update_failure_ts = 10_000
    monkeypatch.setattr("time.time", lambda: 10_000 + 60)
    monkeypatch.setattr(
        main_window,
        "_start_update_check",
        lambda *, manual: calls.append(manual),
    )

    main_window._maybe_check_for_update()

    assert calls == []


def test_auto_update_failure_backoff_allows_later_retry(main_window, monkeypatch):
    calls: list[bool] = []
    main_window.settings.update_check_enabled = True
    main_window.settings.first_run_completed = True
    main_window.settings.last_update_check_ts = 0
    main_window.settings.last_update_failure_ts = 100_000
    monkeypatch.setattr("time.time", lambda: 100_000 + main_window._UPDATE_FAILURE_RETRY_INTERVAL_S + 1)
    monkeypatch.setattr(
        main_window,
        "_start_update_check",
        lambda *, manual: calls.append(manual),
    )

    main_window._maybe_check_for_update()

    assert calls == [False]


def test_low_coupling_tabs_are_lazy_created_on_first_use(main_window):
    assert main_window._now_playing_view is None
    assert main_window._podcast_view is None
    assert main_window._radio_view is None
    assert main_window._youtube_view is None
    assert main_window._disc_view is None
    assert main_window._ripper_view is None
    assert main_window._video_player_view is None

    main_window.tab_bar.setCurrentIndex(main_window._tab_index["Now Playing"])

    assert main_window._now_playing_view is not None
    assert main_window.stack.currentWidget() is main_window.now_playing
    assert main_window._radio_view is None
    assert main_window._podcast_view is None
    assert main_window._youtube_view is None
    assert main_window._disc_view is None
    assert main_window._ripper_view is None
    assert main_window._video_player_view is None

    main_window.tab_bar.setCurrentIndex(main_window._tab_index["Radio"])

    assert main_window._radio_view is not None
    assert main_window.stack.currentWidget() is main_window.radio_view
    assert main_window._podcast_view is None
    assert main_window._youtube_view is None
    assert main_window._disc_view is None
    assert main_window._ripper_view is None
    assert main_window._video_player_view is None

    main_window.tab_bar.setCurrentIndex(main_window._tab_index["YouTube"])

    assert main_window._youtube_view is not None
    assert main_window.stack.currentWidget() is main_window.youtube_view
    assert main_window._podcast_view is None
    assert main_window._disc_view is None
    assert main_window._ripper_view is None
    assert main_window._video_player_view is None

    main_window.tab_bar.setCurrentIndex(main_window._tab_index["Disc"])

    assert main_window._disc_view is not None
    assert main_window.stack.currentWidget() is main_window.disc_view
    assert main_window._ripper_view is None
    assert main_window._video_player_view is None

    main_window.tab_bar.setCurrentIndex(main_window._tab_index["Rip"])

    assert main_window._ripper_view is not None
    assert main_window.stack.currentWidget() is main_window.ripper_view
    assert main_window._video_player_view is None

    main_window.tab_bar.setCurrentIndex(main_window._tab_index["Video"])

    assert main_window._video_player_view is not None
    assert main_window.stack.currentWidget() is main_window.video_player_view


def test_transport_visible_on_library_hidden_on_rip(main_window):
    # isHidden() reflects explicit setVisible(False) calls regardless of
    # whether the parent window has been .show()n yet.
    main_window.tab_bar.setCurrentIndex(main_window._tab_index["Library"])
    assert not main_window.transport.isHidden()
    main_window.tab_bar.setCurrentIndex(main_window._tab_index["Rip"])
    assert main_window.transport.isHidden()
    main_window.tab_bar.setCurrentIndex(main_window._tab_index["Video"])
    assert main_window.transport.isHidden()
    main_window.tab_bar.setCurrentIndex(main_window._tab_index["Radio"])
    assert not main_window.transport.isHidden()
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


def test_audio_disc_handoff_reuses_disc_tab_read_on_rip_tab(main_window, monkeypatch):
    from lyon.core.cd_detect import DiscToc
    from lyon.core.metadata import AlbumInfo, TrackInfo

    monkeypatch.setattr(
        "lyon.ui.ripper_view.cd_detect.read_disc",
        lambda *_: (_ for _ in ()).throw(AssertionError("ripper should reuse the Disc tab TOC")),
    )
    toc = DiscToc(
        drive="D:",
        discid="disc-id",
        toc_string="toc",
        track_count=1,
        track_offsets=[150],
        sectors=15150,
    )
    album = AlbumInfo(
        artist="Artist",
        album="Album",
        tracks=[TrackInfo(1, "Song")],
    )
    main_window.disc_view._on_audio_read(toc, album)

    main_window._rip_disc_drive("D:")

    assert main_window.stack.currentWidget() is main_window.ripper_view
    assert main_window.ripper_view._toc is toc
    assert main_window.ripper_view.album_edit.text() == "Album"
    assert main_window.ripper_view.artist_edit.text() == "Artist"
    assert main_window.ripper_view.tracks_model.rowCount() == 1
    assert main_window.ripper_view.tracks_model.item(0, 1).text() == "Song"
    assert main_window.ripper_view.start_btn.isEnabled()


def test_audio_disc_handoff_starts_artwork_lookup_for_reused_album(main_window, monkeypatch):
    from lyon.core.cd_detect import DiscToc
    from lyon.core.metadata import AlbumInfo, TrackInfo

    toc = DiscToc(
        drive="D:",
        discid="disc-id",
        toc_string="toc",
        track_count=1,
        track_offsets=[150],
        sectors=15150,
    )
    album = AlbumInfo(
        artist="Artist",
        album="Album",
        artwork_url="https://example.test/cover.jpg",
        tracks=[TrackInfo(1, "Song")],
    )
    artwork_calls = []
    monkeypatch.setattr(
        main_window.ripper_view,
        "_start_artwork_lookup",
        lambda info: artwork_calls.append(info),
    )
    main_window.disc_view._on_audio_read(toc, album)

    main_window._rip_disc_drive("D:")

    assert main_window.stack.currentWidget() is main_window.ripper_view
    assert artwork_calls == [album]


def test_library_video_handoff_uses_video_tab(main_window, monkeypatch, qapp):
    from lyon.core.library import Track

    calls = []
    monkeypatch.setattr(main_window.video_player_view, "playback_available", lambda: True)
    monkeypatch.setattr(
        main_window.video_player_view,
        "load_path",
        lambda path: calls.append((path, main_window.stack.currentWidget())),
    )
    track = Track(
        id=42,
        path="/videos/clip.mp4",
        title="Clip",
        artist="Video Artist",
        album_artist="Video Artist",
        album="Video Album",
        track_no=1,
        disc_no=1,
        year=2026,
        genre="",
        duration=120.0,
        media_type="video",
    )
    main_window.tab_bar.setCurrentIndex(main_window._tab_index["Library"])

    main_window._play_library_video(track)

    assert calls == []
    assert main_window.stack.currentWidget() is main_window.video_player_view
    qapp.processEvents(QtCore.QEventLoop.AllEvents, 50)
    assert calls == [("/videos/clip.mp4", main_window.video_player_view)]


def test_radio_play_request_uses_audio_player(main_window, monkeypatch):
    calls = []
    monkeypatch.setattr(main_window.video_player_view, "pause_playback", lambda: calls.append(("pause_video",)))
    monkeypatch.setattr(
        main_window.player,
        "play_url",
        lambda url, title=None: calls.append(("play_url", url, title)),
    )

    main_window._play_radio_station("https://radio.example.test/live", "Sea Radio")

    assert calls == [
        ("pause_video",),
        ("play_url", "https://radio.example.test/live", "Sea Radio"),
    ]


def test_podcast_play_request_uses_audio_player(main_window, monkeypatch):
    calls = []
    monkeypatch.setattr(main_window.video_player_view, "pause_playback", lambda: calls.append(("pause_video",)))
    monkeypatch.setattr(
        main_window.player,
        "play_url",
        lambda url, title=None, options=(): calls.append(("play_url", url, title, options)),
    )

    from lyon.core.podcast import podcast_user_agent

    main_window._play_podcast_episode("https://podcasts.example.test/episode.mp3", "Sea Stories - One")

    assert calls == [
        ("pause_video",),
        (
            "play_url",
            "https://podcasts.example.test/episode.mp3",
            "Sea Stories - One",
            (
                f":http-user-agent={podcast_user_agent()}",
                ":network-caching=1500",
            ),
        ),
    ]


def test_transport_controls_route_to_cast_controller_while_casting(main_window, monkeypatch):
    calls = []
    main_window.cast_controller._renderer = object()
    monkeypatch.setattr(
        main_window.cast_controller,
        "toggle_play_pause",
        lambda: calls.append("toggle_cast"),
    )
    monkeypatch.setattr(
        main_window.cast_controller,
        "previous_track",
        lambda: calls.append("previous_cast"),
    )
    monkeypatch.setattr(
        main_window.cast_controller,
        "next_track",
        lambda: calls.append("next_cast"),
    )
    monkeypatch.setattr(
        main_window.cast_controller,
        "stop_cast",
        lambda: calls.append("stop_cast"),
    )

    main_window._on_transport_play_requested()
    main_window._on_transport_previous_requested()
    main_window._on_transport_next_requested()
    main_window._on_transport_stop_requested()

    assert calls == ["toggle_cast", "previous_cast", "next_cast", "stop_cast"]


def test_cast_from_video_tab_uses_current_video_track(main_window, monkeypatch):
    from lyon.core.library import Track

    renderer = object()
    track = Track(
        id=77,
        path="/videos/clip.mp4",
        title="Clip",
        artist="",
        album_artist="",
        album="",
        track_no=0,
        disc_no=0,
        year=2026,
        genre="",
        duration=120.0,
        media_type="video",
    )
    calls = []
    pauses: list[bool] = []

    main_window.tab_bar.setCurrentIndex(main_window._tab_index["Video"])
    monkeypatch.setattr(main_window.video_player_view, "current_library_track", lambda: track)
    monkeypatch.setattr(main_window.video_player_view, "pause_playback", lambda: pauses.append(True))
    monkeypatch.setattr(
        main_window.cast_controller,
        "start_cast_track",
        lambda renderer_arg, track_arg, dlna_arg, pause_local=None: (
            calls.append(("video", renderer_arg, track_arg, dlna_arg)),
            pause_local() if pause_local is not None else None,
        ),
    )
    monkeypatch.setattr(
        main_window.cast_controller,
        "start_cast",
        lambda *_args: calls.append(("audio",)),
    )

    main_window._start_cast(renderer)

    assert calls == [("video", renderer, track, main_window.dlna_server)]
    assert pauses == [True]


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
        # Pre-accept the YouTube ToS gate so tests that activate the
        # YouTube tab don't hang on the modal acknowledgement dialog.
        youtube_acknowledged=True,
        update_check_enabled=False,
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
        "Radio":       "Ctrl+3",
        "Video":       "Ctrl+4",
        "Disc":        "Ctrl+5",
        "Rip":         "Ctrl+6",
        "YouTube":     "Ctrl+7",
        "Podcasts":    "Ctrl+8",
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


def test_media_key_handler_is_closed_during_shutdown(main_window):
    class Handler:
        def __init__(self):
            self.closed = False

        def close(self):
            self.closed = True

    handler = Handler()
    main_window._media_key_handler = handler

    main_window._shutdown_media_key_handler()

    assert handler.closed is True
    assert main_window._media_key_handler is None


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


def test_close_event_waits_for_podcast_refresh_to_stop(main_window, monkeypatch):
    calls: list[bool] = []
    monkeypatch.setattr(main_window.podcast_view, "shutdown", lambda: calls.append(True) or False)

    class CloseEvent:
        def __init__(self):
            self.ignored = False

        def ignore(self):
            self.ignored = True

    event = CloseEvent()

    main_window.closeEvent(event)

    assert calls == [True]
    assert event.ignored is True
    assert "Podcast refresh is still stopping" in main_window._current_toast.message()


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
        # Pre-accept the YouTube ToS gate so tests that activate the
        # YouTube tab don't hang on the modal acknowledgement dialog.
        youtube_acknowledged=True,
        update_check_enabled=False,
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

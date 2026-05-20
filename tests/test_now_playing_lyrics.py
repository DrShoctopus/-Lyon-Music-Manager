"""Tests for the Now Playing lyrics pipeline: LRCLIB fetch, cache, race-guard, settings toggle."""
from __future__ import annotations

import io
import json
import os
from unittest.mock import patch

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtCore = pytest.importorskip("PySide6.QtCore", exc_type=ImportError)
QtWidgets = pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from lyon.core.library import Track
from lyon.core.metadata import ArtistInfo
from lyon.core.player import Player
from lyon.core.settings import Settings
from lyon.ui.now_playing import NowPlayingView, _fetch_lrclib, _parse_lrc


class _FakeBackend(QtCore.QObject):
    state_changed = QtCore.Signal(str)
    position_changed = QtCore.Signal(int, int)
    end_reached = QtCore.Signal()

    def __init__(self) -> None:
        super().__init__()
        self._volume = 80
        self._muted = False
        self._playing = False

    def set_source(self, path: str, *, is_location=False, options=()) -> None: pass
    def play(self) -> None: self._playing = True
    def pause(self) -> None: self._playing = False
    def stop(self) -> None: self._playing = False
    def position(self) -> int: return 0
    def duration(self) -> int: return 0
    def set_position(self, ms: int) -> None: pass
    def set_volume(self, percent: int) -> None: self._volume = percent
    def volume(self) -> int: return self._volume
    def set_muted(self, muted: bool) -> None: self._muted = muted
    def is_muted(self) -> bool: return self._muted
    def is_playing(self) -> bool: return self._playing
    def apply_equalizer(self, enabled, bands, preamp=0) -> None: pass


@pytest.fixture(scope="module")
def app():
    existing = QtWidgets.QApplication.instance()
    return existing or QtWidgets.QApplication([])


@pytest.fixture
def player(app):
    return Player(backend=_FakeBackend())


def _track(track_id: int = 1, title: str = "Song", duration: float = 200.0) -> Track:
    return Track(
        id=track_id, path=f"/tmp/{title}.flac",
        title=title, artist="Artist", album_artist="Artist",
        album="Album", track_no=1, disc_no=1, year=2026,
        genre="", duration=duration,
    )


# ---- _parse_lrc: timing normalization -----------------------------------

def test_parse_lrc_applies_offset_tag():
    parsed = _parse_lrc("[offset: 250]\n[00:01.00]Line one\n[00:02.50]Line two")

    assert parsed == [(750, "Line one"), (2250, "Line two")]


def test_parse_lrc_clamps_offset_before_zero():
    parsed = _parse_lrc("[offset:750]\n[00:00.50]Intro")

    assert parsed == [(0, "Intro")]


def test_parse_lrc_handles_repeated_timestamps_for_same_line():
    parsed = _parse_lrc("[00:01.00][00:02.50]Echo")

    assert parsed == [(1000, "Echo"), (2500, "Echo")]


# ---- _fetch_lrclib: pure function tests ---------------------------------

class _FakeResponse:
    def __init__(self, status: int, body: bytes) -> None:
        self.status = status
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_fetch_lrclib_returns_synced_and_plain():
    payload = json.dumps({
        "syncedLyrics": "[00:01.00]Line one\n[00:05.00]Line two",
        "plainLyrics": "Line one\nLine two",
    }).encode()
    with patch("lyon.ui.now_playing.urllib.request.urlopen", return_value=_FakeResponse(200, payload)):
        synced, plain = _fetch_lrclib("Artist", "Song", "Album", 200.0)
    assert "[00:01.00]" in synced
    assert "Line one" in plain


def test_fetch_lrclib_returns_empty_on_404():
    with patch("lyon.ui.now_playing.urllib.request.urlopen", return_value=_FakeResponse(404, b"")):
        assert _fetch_lrclib("Artist", "Song", "Album", 200.0) == ("", "")


def test_fetch_lrclib_returns_empty_on_network_error():
    with patch("lyon.ui.now_playing.urllib.request.urlopen", side_effect=ConnectionError("offline")):
        assert _fetch_lrclib("Artist", "Song", "Album", 200.0) == ("", "")


def test_fetch_lrclib_returns_empty_on_malformed_json():
    with patch("lyon.ui.now_playing.urllib.request.urlopen", return_value=_FakeResponse(200, b"not json")):
        assert _fetch_lrclib("Artist", "Song", "Album", 200.0) == ("", "")


def test_fetch_lrclib_handles_missing_fields():
    # LRCLIB sometimes returns plain only, or null fields
    payload = json.dumps({"plainLyrics": "just text", "syncedLyrics": None}).encode()
    with patch("lyon.ui.now_playing.urllib.request.urlopen", return_value=_FakeResponse(200, payload)):
        synced, plain = _fetch_lrclib("A", "S", "Al", 100.0)
    assert synced == ""
    assert plain == "just text"


def test_fetch_lrclib_sends_correct_query_string():
    captured: dict[str, str] = {}

    def _capture(req, timeout):
        captured["url"] = req.full_url
        return _FakeResponse(200, b'{"syncedLyrics":"","plainLyrics":""}')

    with patch("lyon.ui.now_playing.urllib.request.urlopen", side_effect=_capture):
        _fetch_lrclib("Lady GaGa", "You and I", "Born This Way", 285.7)
    assert "artist_name=Lady+GaGa" in captured["url"]
    assert "track_name=You+and+I" in captured["url"]
    assert "album_name=Born+This+Way" in captured["url"]
    assert "duration=285" in captured["url"]   # truncated to int


# ---- _on_lyrics_ready: race-guard and routing ---------------------------

def test_on_lyrics_ready_ignores_stale_result(player):
    view = NowPlayingView(player, settings=Settings())
    view._lyrics_task_id = 42
    # Pre-load panel with placeholder so we can detect whether it was overwritten
    view._lyrics_panel.set_lyrics([], "Searching for lyrics…")
    # Stale response (task_id mismatch) — should not touch the panel
    view._on_lyrics_ready(7, "[00:01.00]Stale", "")
    labels = [lbl.text() for lbl in view._lyrics_panel._labels]
    assert any("Searching" in t for t in labels)
    # But it should still cache the stale result for later
    assert view._lyrics_cache[7] == ("[00:01.00]Stale", "")


def test_on_lyrics_ready_renders_synced_when_present(player):
    view = NowPlayingView(player, settings=Settings())
    view._lyrics_task_id = 1
    view._on_lyrics_ready(1, "[00:01.00]Hello\n[00:05.00]World", "Hello\nWorld")
    rendered = [lbl.text() for lbl in view._lyrics_panel._labels]
    # Synced path strips timestamps and shows lyric text
    assert "Hello" in rendered
    assert "World" in rendered


def test_on_lyrics_ready_falls_back_to_plain_when_no_synced(player):
    view = NowPlayingView(player, settings=Settings())
    view._lyrics_task_id = 1
    view._on_lyrics_ready(1, "", "Plain line A\nPlain line B")
    rendered = [lbl.text() for lbl in view._lyrics_panel._labels]
    assert "Plain line A" in rendered
    assert "Plain line B" in rendered


def test_on_lyrics_ready_shows_placeholder_when_both_empty(player):
    view = NowPlayingView(player, settings=Settings())
    view._lyrics_task_id = 1
    view._on_lyrics_ready(1, "", "")
    rendered = [lbl.text() for lbl in view._lyrics_panel._labels]
    assert rendered == ["No lyrics available."]


# ---- Cache behaviour ----------------------------------------------------

def test_lyrics_cache_persists_empty_result(player):
    view = NowPlayingView(player, settings=Settings())
    view._lyrics_task_id = 5
    view._on_lyrics_ready(5, "", "")
    assert view._lyrics_cache[5] == ("", "")


def test_lyrics_cache_serves_hit_without_spawning_thread(player, tmp_path):
    view = NowPlayingView(player, settings=Settings())
    track = _track(track_id=99)
    # Prime cache with a known synced result
    view._lyrics_cache[99] = ("[00:01.00]Cached line", "")
    # The track has no .lrc file and no real audio file with embedded tags,
    # so _load_lyrics will reach step 3 (online) where the cache should hit.
    with patch("lyon.ui.now_playing.threading.Thread") as mock_thread:
        view._load_lyrics(track)
    mock_thread.assert_not_called()
    rendered = [lbl.text() for lbl in view._lyrics_panel._labels]
    assert "Cached line" in rendered


def test_lyrics_cache_evicts_oldest_when_over_capacity(player):
    view = NowPlayingView(player, settings=Settings())
    view._PANEL_CACHE_MAX = 3  # shrink for the test
    view._lyrics_task_id = 1
    for i in range(1, 6):
        view._on_lyrics_ready(i, "", f"text{i}")
    # Capacity 3 → only the three newest survive
    assert set(view._lyrics_cache.keys()) == {3, 4, 5}


# ---- Settings toggle ----------------------------------------------------

def test_fetch_lyrics_online_disabled_skips_network(player, tmp_path):
    settings = Settings()
    settings.fetch_lyrics_online = False
    view = NowPlayingView(player, settings=settings)
    track = _track(track_id=1)
    with patch("lyon.ui.now_playing.threading.Thread") as mock_thread:
        view._load_lyrics(track)
    mock_thread.assert_not_called()
    rendered = [lbl.text() for lbl in view._lyrics_panel._labels]
    assert rendered == ["No lyrics available."]


def test_fetch_lyrics_online_enabled_spawns_thread(player):
    settings = Settings()
    settings.fetch_lyrics_online = True
    view = NowPlayingView(player, settings=settings)
    track = _track(track_id=2)
    with patch("lyon.ui.now_playing.threading.Thread") as mock_thread:
        view._load_lyrics(track)
    mock_thread.assert_called_once()
    assert view._lyrics_task_id == 2


def test_now_playing_side_panel_and_tabs_are_wide(player):
    view = NowPlayingView(player, settings=Settings())
    side_panel = view.findChild(QtWidgets.QWidget, "nowPlayingSidePanel")
    assert side_panel is not None
    assert side_panel.minimumWidth() == 440
    assert side_panel.maximumWidth() == 720
    assert (
        side_panel.sizePolicy().horizontalPolicy()
        == QtWidgets.QSizePolicy.Policy.Expanding
    )

    tabs = [
        btn for btn in view.findChildren(QtWidgets.QPushButton)
        if btn.objectName() == "panelTab"
    ]
    assert len(tabs) == 4
    assert all(
        tab.sizePolicy().horizontalPolicy() == QtWidgets.QSizePolicy.Policy.Expanding
        for tab in tabs
    )


def test_now_playing_artist_ready_renders_artist_panel(player):
    view = NowPlayingView(player, settings=Settings())
    view._artist_task_key = "artist"

    view._on_artist_ready(
        "artist",
        ArtistInfo(name="Artist", biography="Bio text.", genre="Rock"),
        None,
    )

    labels = [label.text() for label in view._artist_panel.findChildren(QtWidgets.QLabel)]
    assert "Artist" in labels
    assert "Bio text." in labels
    assert "Rock" in labels


def test_now_playing_artist_ready_ignores_stale_panel_update(player):
    view = NowPlayingView(player, settings=Settings())
    view._artist_task_key = "current"
    view._artist_panel.set_loading("Current")

    view._on_artist_ready("stale", ArtistInfo(name="Stale", biography="Wrong"), None)

    labels = [label.text() for label in view._artist_panel.findChildren(QtWidgets.QLabel)]
    assert "Current" in labels
    assert "Wrong" not in labels


def test_now_playing_artist_lookup_prefers_track_artist_over_album_artist(player):
    view = NowPlayingView(player, settings=Settings())
    track = _track(track_id=3)
    track.artist = "Actual Artist"
    track.album_artist = "Various Artists"

    with patch("lyon.ui.now_playing.threading.Thread"):
        view._load_artist_info(track)

    assert view._artist_task_key == "actual artist"


def test_now_playing_artist_ready_does_not_cache_empty_lookup(player):
    view = NowPlayingView(player, settings=Settings())
    view._artist_task_key = "artist"

    view._on_artist_ready("artist", None, None)

    assert "artist" not in view._artist_cache
    labels = [label.text() for label in view._artist_panel.findChildren(QtWidgets.QLabel)]
    assert "No artist information available." in labels


def test_now_playing_artist_empty_lookup_does_not_block_later_success(player):
    view = NowPlayingView(player, settings=Settings())
    view._artist_task_key = "artist"
    view._on_artist_ready("artist", None, None)
    view._artist_task_key = "artist"

    view._on_artist_ready(
        "artist",
        ArtistInfo(name="Artist", biography="Recovered bio."),
        None,
    )

    labels = [label.text() for label in view._artist_panel.findChildren(QtWidgets.QLabel)]
    assert "Recovered bio." in labels
    assert view._artist_cache["artist"][0].biography == "Recovered bio."


def test_synced_lyrics_scrolls_current_line_to_center(player, app):
    view = NowPlayingView(player, settings=Settings())
    view.resize(1100, 720)
    view._panel_stack.setCurrentIndex(1)
    view.show()
    app.processEvents()

    panel = view._lyrics_panel
    lines = [(i * 1000, f"Line {i}") for i in range(60)]
    panel.set_lyrics(lines)
    app.processEvents()

    panel.update_position(30_000)
    panel._recenter_current_line()
    app.processEvents()

    bar = panel._scroll.verticalScrollBar()
    line_center = panel._labels[30].geometry().center().y()
    viewport_center = bar.value() + (panel._scroll.viewport().height() / 2)
    assert abs(line_center - viewport_center) <= 2

    view.close()
    view.deleteLater()


def test_synced_lyrics_loaded_after_position_update_uses_current_position(player, app):
    view = NowPlayingView(player, settings=Settings())
    panel = view._lyrics_panel

    panel.update_position(5_500)
    panel.set_lyrics([(1_000, "Early"), (5_000, "Now"), (9_000, "Later")])
    app.processEvents()

    assert panel._current_line == 1
    assert panel._labels[1].objectName() == "lyricsLineCurrent"

    view.close()
    view.deleteLater()


def test_synced_lyrics_do_not_highlight_before_first_timestamp(player, app):
    view = NowPlayingView(player, settings=Settings())
    panel = view._lyrics_panel

    panel.set_lyrics([(10_000, "First vocal line"), (20_000, "Second")])
    panel.update_position(5_000)
    app.processEvents()

    assert panel._current_line == -1
    assert all(lbl.objectName() == "lyricsLine" for lbl in panel._labels)

    view.close()
    view.deleteLater()

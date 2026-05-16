from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtCore = pytest.importorskip("PySide6.QtCore", exc_type=ImportError)
QtWidgets = pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from lyon.core.library import Track
from lyon.core.player import Player, RepeatMode
from lyon.ui.now_playing import NowPlayingView, TransportBar
from lyon.ui.transport import (
    NextButton, PlayPauseButton, PlayPauseSideButton, PrevButton,
    RepeatButton, ShuffleButton, StopButton, VolumeButton,
)


class FakeBackend(QtCore.QObject):
    state_changed = QtCore.Signal(str)
    position_changed = QtCore.Signal(int, int)
    end_reached = QtCore.Signal()

    def __init__(self):
        super().__init__()
        self._volume = 80
        self._muted = False
        self._playing = False

    def set_source(self, path: str) -> None: pass
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
    if existing is not None:
        return existing
    return QtWidgets.QApplication([])


@pytest.fixture
def player(app):
    return Player(backend=FakeBackend())


def _track(title: str = "Hello", duration: float = 120.0) -> Track:
    return Track(
        id=1, path=f"/tmp/{title}.flac",
        title=title, artist="Artist", album_artist="Artist",
        album="Album", track_no=1, disc_no=1, year=2026,
        genre="", duration=duration,
    )


def test_play_pause_button_toggles_glyph(app):
    btn = PlayPauseButton()
    assert btn._glyph_name() == "play"
    btn.set_playing(True)
    assert btn._glyph_name() == "pause"
    assert btn.accessibleName() == "Pause"
    btn.set_playing(False)
    assert btn._glyph_name() == "play"
    assert btn.accessibleName() == "Play"


def test_play_pause_side_button_mirrors_primary(app):
    btn = PlayPauseSideButton()
    btn.set_playing(True)
    assert btn._glyph_name() == "pause"


def test_stop_prev_next_have_glyph_names(app):
    assert StopButton()._glyph_name() == "stop"
    assert PrevButton()._glyph_name() == "prev"
    assert NextButton()._glyph_name() == "next"


def test_shuffle_button_is_checkable(app):
    btn = ShuffleButton()
    assert btn.isCheckable()
    assert btn._glyph_name() == "shuffle"


def test_repeat_button_cycles_three_states(app):
    btn = RepeatButton()
    assert btn.state() == 0
    btn._on_clicked()
    assert btn.state() == 1
    assert btn._glyph_name() == "repeat-all"
    btn._on_clicked()
    assert btn.state() == 2
    assert btn._glyph_name() == "repeat-one"
    btn._on_clicked()
    assert btn.state() == 0
    assert btn._glyph_name() == "repeat-off"


def test_repeat_button_set_state_does_not_fire_state_changed(app):
    btn = RepeatButton()
    received: list[int] = []
    btn.state_changed.connect(received.append)
    btn.set_state(2)
    assert btn.state() == 2
    assert received == []  # programmatic set must not echo back


def test_volume_button_glyph_reflects_level(app):
    btn = VolumeButton()
    btn.set_state(0, False)
    assert btn._glyph_name() == "volume-muted"
    btn.set_state(20, False)
    assert btn._glyph_name() == "volume-low"
    btn.set_state(50, False)
    assert btn._glyph_name() == "volume-mid"
    btn.set_state(90, False)
    assert btn._glyph_name() == "volume-high"
    btn.set_state(90, True)
    assert btn._glyph_name() == "volume-muted"


def test_transport_bar_constructs_and_reacts_to_player(player):
    bar = TransportBar(player)
    bar.player.set_volume(40)
    bar.vol_btn.set_state(40, False)
    assert bar.vol_btn._glyph_name() == "volume-mid"

    bar.player.set_muted(True)
    bar.vol_btn.set_state(40, True)
    assert bar.vol_btn._glyph_name() == "volume-muted"


def test_transport_bar_repeat_button_syncs_with_player(player):
    bar = TransportBar(player)
    bar.repeat_btn._on_clicked()  # button: off → all, also drives player.cycle_repeat
    assert player.repeat() == RepeatMode.ALL
    assert bar.repeat_btn.state() == 1


def test_now_playing_view_updates_on_track_change(player):
    view = NowPlayingView(player)
    view._on_track(_track("Song A"))
    assert view.title.text() == "Song A"
    assert view.artist.text() == "Artist"
    assert view.album.text() == "Album"
    view._on_track(None)
    assert view.title.text() == "Nothing playing"


def test_now_playing_view_renders_queue_preview(player):
    view = NowPlayingView(player)
    player.set_queue([_track(f"T{i}") for i in range(5)], start_index=0)
    view._refresh_queue()
    # current index is 0, "up next" starts at 1 — expect 4 items
    visible = [view.queue_list.item(i).text() for i in range(view.queue_list.count())]
    assert any("T1" in t for t in visible)
    assert all("T0" not in t for t in visible)


def test_now_playing_view_format_strip_includes_codec(player):
    view = NowPlayingView(player)
    view._on_track(_track("X"))
    assert "FLAC" in view.format_strip.text()

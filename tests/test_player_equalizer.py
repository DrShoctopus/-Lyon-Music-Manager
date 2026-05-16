from __future__ import annotations

import pytest

QtCore = pytest.importorskip("PySide6.QtCore", exc_type=ImportError)
QObject = QtCore.QObject
Signal = QtCore.Signal

from lyon.core.library import Track
from lyon.core.player import Player
from lyon.core.playback_backend import UnavailablePlaybackBackend


class FakeBackend(QObject):
    state_changed = Signal(str)
    position_changed = Signal(int, int)
    end_reached = Signal()

    def __init__(self):
        super().__init__()
        self.equalizer_calls: list[tuple[bool, list[int]]] = []
        self.sources: list[str] = []
        self.play_count = 0
        self._position = 0
        self._volume = 80
        self._muted = False
        self._playing = False

    def set_source(self, path: str) -> None:
        self.sources.append(path)

    def play(self) -> None:
        self.play_count += 1
        self._playing = True

    def pause(self) -> None:
        self._playing = False

    def stop(self) -> None:
        self._playing = False

    def position(self) -> int:
        return self._position

    def duration(self) -> int:
        return 0

    def set_position(self, ms: int) -> None:
        self._position = ms

    def set_volume(self, percent: int) -> None:
        self._volume = percent

    def volume(self) -> int:
        return self._volume

    def set_muted(self, muted: bool) -> None:
        self._muted = muted

    def is_muted(self) -> bool:
        return self._muted

    def is_playing(self) -> bool:
        return self._playing

    def apply_equalizer(self, enabled: bool, bands: list[int], preamp: int = 0) -> None:
        self.equalizer_calls.append((enabled, list(bands), preamp))

    def cleanup(self) -> None:
        self._playing = False


def _track(path: str = "C:/Music/test.flac") -> Track:
    return Track(
        id=1,
        path=path,
        title="Test",
        artist="Artist",
        album_artist="Artist",
        album="Album",
        track_no=1,
        disc_no=1,
        year=2026,
        genre="",
        duration=120.0,
    )


def test_set_equalizer_normalizes_and_pushes_to_backend():
    backend = FakeBackend()
    player = Player(backend=backend)

    player.set_equalizer(True, [20, -20, 3, "4", 0], preamp=6)

    assert player.equalizer() == (True, [12, -12, 3, 4, 0, 0, 0, 0, 0, 0], 6)
    assert backend.equalizer_calls == [(True, [12, -12, 3, 4, 0, 0, 0, 0, 0, 0], 6)]


def test_equalizer_is_reapplied_on_track_load():
    backend = FakeBackend()
    player = Player(backend=backend)
    player.set_equalizer(True, [1, 2, 3, 4, 5, 6, 7, 8, 9, 10], preamp=3)

    player.set_queue([_track()])

    assert backend.sources == ["C:/Music/test.flac"]
    assert backend.play_count == 1
    assert backend.equalizer_calls[-1] == (True, [1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 3)


def test_queue_items_can_move_and_remove_without_losing_current_track():
    backend = FakeBackend()
    player = Player(backend=backend)
    tracks = [_track("C:/Music/one.flac"), _track("C:/Music/two.flac"), _track("C:/Music/three.flac")]

    player.set_queue(tracks, 1)
    player.move_queue_item(1, 0)

    assert [track.path for track in player.queue()] == [
        "C:/Music/two.flac",
        "C:/Music/one.flac",
        "C:/Music/three.flac",
    ]
    assert player.current_index() == 0
    assert player.current().path == "C:/Music/two.flac"

    player.remove_queue_index(1)

    assert [track.path for track in player.queue()] == ["C:/Music/two.flac", "C:/Music/three.flac"]
    assert player.current_index() == 0


def test_clear_queue_stops_playback_and_clears_current_track():
    backend = FakeBackend()
    player = Player(backend=backend)
    player.set_queue([_track("C:/Music/one.flac")])

    player.clear_queue()

    assert player.queue() == []
    assert player.current() is None
    assert player.current_index() == -1
    assert not backend.is_playing()


def test_removing_current_queue_item_while_stopped_does_not_autoplay_next_track():
    backend = FakeBackend()
    player = Player(backend=backend)
    player.set_queue([_track("C:/Music/one.flac"), _track("C:/Music/two.flac")])
    player.stop()
    backend.play_count = 0

    player.remove_queue_index(0)

    assert [track.path for track in player.queue()] == ["C:/Music/two.flac"]
    assert player.current_index() == -1
    assert player.current() is None
    assert backend.play_count == 0
    assert not backend.is_playing()


def test_removing_current_queue_item_while_playing_advances_to_next_track():
    backend = FakeBackend()
    player = Player(backend=backend)
    player.set_queue([_track("C:/Music/one.flac"), _track("C:/Music/two.flac")])

    player.remove_queue_index(0)

    assert [track.path for track in player.queue()] == ["C:/Music/two.flac"]
    assert player.current_index() == 0
    assert player.current().path == "C:/Music/two.flac"
    assert backend.sources[-1] == "C:/Music/two.flac"
    assert backend.is_playing()


def test_unavailable_backend_keeps_queue_but_does_not_fake_current_track():
    backend = UnavailablePlaybackBackend("libVLC missing")
    player = Player(backend=backend)
    unavailable: list[str] = []
    tracks = [_track("C:/Music/one.flac"), _track("C:/Music/two.flac")]

    player.playback_unavailable.connect(unavailable.append)
    player.set_queue(tracks, 1)

    assert player.queue() == tracks
    assert player.current() is None
    assert player.current_index() == -1
    assert not player.is_playing()
    assert unavailable == ["libVLC missing"]


def test_unavailable_backend_preserves_volume_mute_and_equalizer_state():
    backend = UnavailablePlaybackBackend("libVLC missing")
    player = Player(backend=backend)

    player.set_volume(33)
    player.set_muted(True)
    player.set_equalizer(True, [1, 2, 3], preamp=4)

    assert player.volume() == 33
    assert player.is_muted()
    assert player.equalizer() == (True, [1, 2, 3, 0, 0, 0, 0, 0, 0, 0], 4)


def test_crossfade_starts_next_backend_before_stopping_current():
    backends: list[FakeBackend] = []

    def factory(parent=None):
        backend = FakeBackend()
        backends.append(backend)
        return backend

    player = Player(backend_factory=factory)
    player.set_crossfade(5)
    player.set_queue([
        _track("C:/Music/one.flac"),
        _track("C:/Music/two.flac"),
    ])

    assert len(backends) == 1
    assert backends[0].is_playing()

    backends[0].position_changed.emit(115_000, 120_000)

    assert len(backends) == 2
    assert player.current_index() == 1
    assert backends[0].is_playing()
    assert backends[1].is_playing()
    assert backends[1].sources == ["C:/Music/two.flac"]
    assert backends[1].volume() == 0

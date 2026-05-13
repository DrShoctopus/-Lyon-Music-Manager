from __future__ import annotations

import pytest

QtCore = pytest.importorskip("PySide6.QtCore", exc_type=ImportError)
QObject = QtCore.QObject
Signal = QtCore.Signal

from lyon.core.library import Track
from lyon.core.player import Player


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

    def apply_equalizer(self, enabled: bool, bands: list[int]) -> None:
        self.equalizer_calls.append((enabled, list(bands)))


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

    player.set_equalizer(True, [20, -20, 3, "4", 0])

    assert player.equalizer() == (True, [12, -12, 3, 4, 0, 0, 0, 0, 0, 0])
    assert backend.equalizer_calls == [(True, [12, -12, 3, 4, 0, 0, 0, 0, 0, 0])]


def test_equalizer_is_reapplied_on_track_load():
    backend = FakeBackend()
    player = Player(backend=backend)
    player.set_equalizer(True, [1, 2, 3, 4, 5, 6, 7, 8, 9, 10])

    player.set_queue([_track()])

    assert backend.sources == ["C:/Music/test.flac"]
    assert backend.play_count == 1
    assert backend.equalizer_calls[-1] == (True, [1, 2, 3, 4, 5, 6, 7, 8, 9, 10])

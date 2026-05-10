"""Music player wrapping QMediaPlayer."""
from __future__ import annotations

from enum import Enum
from typing import Optional

from PySide6.QtCore import QObject, QUrl, Signal, Slot
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer

from .library import Track


class RepeatMode(Enum):
    OFF = "off"
    ONE = "one"
    ALL = "all"


class Player(QObject):
    track_changed = Signal(object)        # Track or None
    state_changed = Signal(str)           # "playing"/"paused"/"stopped"
    position_changed = Signal(int, int)   # (ms, total_ms)
    queue_changed = Signal()

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._player = QMediaPlayer(self)
        self._audio = QAudioOutput(self)
        self._player.setAudioOutput(self._audio)
        self._audio.setVolume(0.8)

        self._queue: list[Track] = []
        self._index: int = -1
        self._shuffle = False
        self._repeat = RepeatMode.OFF
        self._equalizer_enabled = False
        self._equalizer_bands = [0, 0, 0, 0, 0, 0]

        self._player.positionChanged.connect(self._emit_position)
        self._player.durationChanged.connect(self._emit_position_dur)
        self._player.playbackStateChanged.connect(self._on_state)
        self._player.mediaStatusChanged.connect(self._on_media_status)

    # --------------------------------------------------------------- queue
    def set_queue(self, tracks: list[Track], start_index: int = 0) -> None:
        self._queue = list(tracks)
        self._index = -1
        self.queue_changed.emit()
        if self._queue:
            self.play_index(max(0, min(start_index, len(self._queue) - 1)))

    def enqueue(self, tracks: list[Track]) -> None:
        was_empty = not self._queue
        self._queue.extend(tracks)
        self.queue_changed.emit()
        if was_empty:
            self.play_index(0)

    def queue(self) -> list[Track]:
        return list(self._queue)

    def current(self) -> Optional[Track]:
        if 0 <= self._index < len(self._queue):
            return self._queue[self._index]
        return None

    # --------------------------------------------------------------- transport
    def play_index(self, idx: int) -> None:
        if not (0 <= idx < len(self._queue)):
            return
        self._index = idx
        track = self._queue[idx]
        self._player.setSource(QUrl.fromLocalFile(track.path))
        self._player.play()
        self.track_changed.emit(track)

    def play(self) -> None:
        if self._index < 0 and self._queue:
            self.play_index(0)
            return
        self._player.play()

    def pause(self) -> None:
        self._player.pause()

    def toggle(self) -> None:
        if self._player.playbackState() == QMediaPlayer.PlayingState:
            self.pause()
        else:
            self.play()

    def stop(self) -> None:
        self._player.stop()

    def next(self) -> None:
        if not self._queue:
            return
        if self._repeat == RepeatMode.ONE:
            self.play_index(self._index)
            return
        nxt = self._next_index()
        if nxt is None:
            self.stop()
            self._index = -1
            self.track_changed.emit(None)
            return
        self.play_index(nxt)

    def previous(self) -> None:
        if self._player.position() > 4000:
            self._player.setPosition(0)
            return
        if self._index > 0:
            self.play_index(self._index - 1)

    def seek(self, ms: int) -> None:
        self._player.setPosition(ms)

    # --------------------------------------------------------------- modes
    def set_volume(self, percent: int) -> None:
        self._audio.setVolume(max(0.0, min(1.0, percent / 100.0)))

    def volume(self) -> int:
        return int(round(self._audio.volume() * 100))

    def set_equalizer(self, enabled: bool, bands: list[int]) -> None:
        """Store the active six-band equalizer curve.

        QMediaPlayer does not expose per-band DSP controls, so the player keeps
        the curve as runtime state for the equalizer UI and any future audio
        processing backend.
        """
        self._equalizer_enabled = bool(enabled)
        normalized = list(bands[:6])
        normalized.extend([0] * (6 - len(normalized)))
        self._equalizer_bands = [max(-12, min(12, int(value))) for value in normalized]

    def equalizer(self) -> tuple[bool, list[int]]:
        return self._equalizer_enabled, list(self._equalizer_bands)

    def set_muted(self, muted: bool) -> None:
        self._audio.setMuted(muted)

    def is_muted(self) -> bool:
        return self._audio.isMuted()

    def shuffle(self) -> bool:
        return self._shuffle

    def set_shuffle(self, on: bool) -> None:
        self._shuffle = bool(on)

    def repeat(self) -> RepeatMode:
        return self._repeat

    def cycle_repeat(self) -> RepeatMode:
        order = [RepeatMode.OFF, RepeatMode.ALL, RepeatMode.ONE]
        i = order.index(self._repeat)
        self._repeat = order[(i + 1) % len(order)]
        return self._repeat

    # --------------------------------------------------------------- internals
    def _next_index(self) -> Optional[int]:
        if self._shuffle:
            import random
            candidates = [i for i in range(len(self._queue)) if i != self._index]
            if not candidates:
                return self._index if self._repeat == RepeatMode.ALL else None
            return random.choice(candidates)
        if self._index + 1 < len(self._queue):
            return self._index + 1
        if self._repeat == RepeatMode.ALL:
            return 0
        return None

    @Slot(int)
    def _emit_position(self, pos: int) -> None:
        self.position_changed.emit(pos, self._player.duration())

    @Slot(int)
    def _emit_position_dur(self, dur: int) -> None:
        self.position_changed.emit(self._player.position(), dur)

    @Slot()
    def _on_state(self, state) -> None:
        mapping = {
            QMediaPlayer.PlayingState: "playing",
            QMediaPlayer.PausedState: "paused",
            QMediaPlayer.StoppedState: "stopped",
        }
        self.state_changed.emit(mapping.get(state, "stopped"))

    @Slot()
    def _on_media_status(self, status) -> None:
        if status == QMediaPlayer.EndOfMedia:
            self.next()

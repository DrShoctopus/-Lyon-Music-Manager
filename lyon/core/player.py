"""High-level music player with queue and transport logic."""
from __future__ import annotations

from enum import Enum
from typing import Optional

from PySide6.QtCore import QObject, Signal

from .library import Track
from .equalizer import flat_equalizer_bands, normalize_equalizer_bands
from .playback_backend import PlaybackBackend, create_playback_backend


class RepeatMode(Enum):
    OFF = "off"
    ONE = "one"
    ALL = "all"


class Player(QObject):
    track_changed = Signal(object)        # Track or None
    state_changed = Signal(str)           # "playing"/"paused"/"stopped"
    position_changed = Signal(int, int)   # (ms, total_ms)
    queue_changed = Signal()

    def __init__(self, parent: Optional[QObject] = None, backend: PlaybackBackend | None = None):
        super().__init__(parent)
        self._backend = backend or create_playback_backend(self)
        backend_parent = getattr(self._backend, "parent", None)
        if callable(backend_parent) and backend_parent() is None:
            self._backend.setParent(self)

        self._queue: list[Track] = []
        self._index: int = -1
        self._shuffle = False
        self._repeat = RepeatMode.OFF
        self._equalizer_enabled = False
        self._equalizer_bands = flat_equalizer_bands()

        self._backend.position_changed.connect(self.position_changed.emit)
        self._backend.state_changed.connect(self.state_changed.emit)
        self._backend.end_reached.connect(self.next)

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

    def current_index(self) -> int:
        return self._index

    def clear_queue(self) -> None:
        if not self._queue:
            return
        self.stop()
        self._queue = []
        self._index = -1
        self.queue_changed.emit()
        self.track_changed.emit(None)

    def remove_queue_index(self, idx: int) -> None:
        if not (0 <= idx < len(self._queue)):
            return
        removing_current = idx == self._index
        was_playing = self.is_playing()
        del self._queue[idx]
        if not self._queue:
            self.stop()
            self._index = -1
            self.queue_changed.emit()
            self.track_changed.emit(None)
            return
        if idx < self._index:
            self._index -= 1
        elif removing_current and was_playing:
            self._index = min(idx, len(self._queue) - 1)
            self.play_index(self._index)
            self.queue_changed.emit()
            return
        elif removing_current:
            self.stop()
            self._index = -1
            self.track_changed.emit(None)
        self.queue_changed.emit()

    def move_queue_item(self, old_index: int, new_index: int) -> None:
        if not (0 <= old_index < len(self._queue)) or not self._queue:
            return
        new_index = max(0, min(new_index, len(self._queue) - 1))
        if old_index == new_index:
            return
        item = self._queue.pop(old_index)
        self._queue.insert(new_index, item)
        if self._index == old_index:
            self._index = new_index
        elif old_index < self._index <= new_index:
            self._index -= 1
        elif new_index <= self._index < old_index:
            self._index += 1
        self.queue_changed.emit()

    def current(self) -> Optional[Track]:
        if 0 <= self._index < len(self._queue):
            return self._queue[self._index]
        return None

    def is_playing(self) -> bool:
        return self._backend.is_playing()

    # --------------------------------------------------------------- transport
    def play_index(self, idx: int) -> None:
        if not (0 <= idx < len(self._queue)):
            return
        self._index = idx
        track = self._queue[idx]
        self._backend.set_source(track.path)
        self._backend.apply_equalizer(self._equalizer_enabled, self._equalizer_bands)
        self._backend.play()
        self.track_changed.emit(track)

    def play(self) -> None:
        if self._index < 0 and self._queue:
            self.play_index(0)
            return
        self._backend.play()

    def pause(self) -> None:
        self._backend.pause()

    def toggle(self) -> None:
        if self._backend.is_playing():
            self.pause()
        else:
            self.play()

    def stop(self) -> None:
        self._backend.stop()

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
        if self._backend.position() > 4000:
            self._backend.set_position(0)
            return
        if self._index > 0:
            self.play_index(self._index - 1)

    def seek(self, ms: int) -> None:
        self._backend.set_position(ms)

    # --------------------------------------------------------------- modes
    def set_volume(self, percent: int) -> None:
        self._backend.set_volume(percent)

    def volume(self) -> int:
        return self._backend.volume()

    def set_equalizer(self, enabled: bool, bands: list[int]) -> None:
        """Store and apply the active ten-band equalizer curve."""
        self._equalizer_enabled = bool(enabled)
        self._equalizer_bands = normalize_equalizer_bands(bands)
        self._backend.apply_equalizer(self._equalizer_enabled, self._equalizer_bands)

    def equalizer(self) -> tuple[bool, list[int]]:
        return self._equalizer_enabled, list(self._equalizer_bands)

    def set_muted(self, muted: bool) -> None:
        self._backend.set_muted(muted)

    def is_muted(self) -> bool:
        return self._backend.is_muted()

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

"""High-level music player with queue and transport logic."""
from __future__ import annotations

import random
from enum import Enum
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import QObject, QTimer, Signal

from .library import Library, Track
from .equalizer import clamp_preamp, flat_equalizer_bands, normalize_equalizer_bands
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
    playback_unavailable = Signal(str)

    def __init__(
        self,
        parent: Optional[QObject] = None,
        backend: PlaybackBackend | None = None,
        library: Library | None = None,
        backend_factory: Callable[[QObject | None], PlaybackBackend] | None = None,
    ):
        super().__init__(parent)
        self._library = library
        self._backend_factory = (
            backend_factory if backend_factory is not None
            else (create_playback_backend if backend is None else None)
        )
        self._backend = backend or self._create_backend()
        self._adopt_backend(self._backend)

        self._queue: list[Track] = []
        self._index: int = -1
        self._shuffle = False
        self._repeat = RepeatMode.OFF
        self._equalizer_enabled = False
        self._equalizer_preamp = 0
        self._equalizer_bands = flat_equalizer_bands()

        self._crossfade_seconds = 0
        self._fade_timer: QTimer | None = None
        self._user_volume = 80   # tracks the volume the user actually wants
        self._fade_target = 80
        self._fade_step = 0
        self._fade_total_steps = 1
        self._fade_out_backend: PlaybackBackend | None = None

        self._rg_mode: str = "off"
        self._rg_preamp_db: float = 0.0
        self._rg_prevent_clipping: bool = True
        self._rg_multiplier: float = 1.0          # multiplier for the active backend
        self._rg_fade_out_multiplier: float = 1.0  # multiplier for the fading-out backend

        self._connect_backend(self._backend)

    # --------------------------------------------------------------- queue
    def load_queue(self, tracks: list[Track], current_index: int = 0) -> None:
        """Restore a saved queue without starting playback."""
        self._queue = list(tracks)
        self._index = max(-1, min(current_index, len(tracks) - 1)) if tracks else -1
        self.queue_changed.emit()
        if 0 <= self._index < len(self._queue):
            self.track_changed.emit(self._queue[self._index])

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

    def playback_available(self) -> bool:
        is_available = getattr(self._backend, "is_available", None)
        return bool(is_available()) if callable(is_available) else True

    def playback_unavailable_reason(self) -> str:
        reason = getattr(self._backend, "unavailable_reason", None)
        if callable(reason):
            return str(reason())
        return ""

    def is_playing(self) -> bool:
        return self._backend.is_playing()

    # --------------------------------------------------------------- transport
    def play_index(self, idx: int) -> None:
        if not (0 <= idx < len(self._queue)):
            return
        if not self._ensure_playback_available():
            return
        if self._should_crossfade_to(idx) and self._crossfade_to_index(idx):
            return
        self._cancel_crossfade()
        self._index = idx
        track = self._queue[idx]
        self._rg_multiplier = self._rg_multiplier_for_track(track)
        self._start_backend_track(self._backend, track, self._user_volume)
        self.track_changed.emit(track)

    def play(self) -> None:
        if self._index < 0 and self._queue:
            self.play_index(0)
            return
        if not self._ensure_playback_available():
            return
        self._backend.play()

    def pause(self) -> None:
        self._cancel_crossfade()
        self._backend.pause()

    def toggle(self) -> None:
        if self._backend.is_playing():
            self.pause()
        else:
            self.play()

    def stop(self) -> None:
        self._cancel_crossfade()
        self._backend.stop()

    def cleanup(self) -> None:
        """Release native backend resources. Call before the application exits."""
        self._cancel_crossfade()
        self._cleanup_backend(self._backend)

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
        self._cancel_crossfade()
        self._backend.set_position(ms)

    # --------------------------------------------------------------- modes
    def set_crossfade(self, seconds: int) -> None:
        self._crossfade_seconds = max(0, int(seconds))

    def set_volume(self, percent: int) -> None:
        self._cancel_crossfade(restore_active_volume=False)
        volume = _clamp_volume(percent)
        self._user_volume = volume
        self._backend.set_volume(self._rg_applied_vol(volume, self._rg_multiplier))

    def volume(self) -> int:
        return self._user_volume

    def set_equalizer(self, enabled: bool, bands: list[int], preamp: int = 0) -> None:
        """Store and apply the active ten-band equalizer curve."""
        self._equalizer_enabled = bool(enabled)
        self._equalizer_preamp = clamp_preamp(preamp)
        self._equalizer_bands = normalize_equalizer_bands(bands)
        self._backend.apply_equalizer(self._equalizer_enabled, self._equalizer_bands, self._equalizer_preamp)

    def equalizer(self) -> tuple[bool, list[int], int]:
        return self._equalizer_enabled, list(self._equalizer_bands), self._equalizer_preamp

    def set_replaygain(
        self,
        mode: str,
        preamp_db: float = 0.0,
        prevent_clipping: bool = True,
    ) -> None:
        self._rg_mode = mode
        self._rg_preamp_db = preamp_db
        self._rg_prevent_clipping = prevent_clipping
        track = self.current()
        self._rg_multiplier = self._rg_multiplier_for_track(track) if track else 1.0
        if self._fade_timer is None:
            self._backend.set_volume(self._rg_applied_vol(self._user_volume, self._rg_multiplier))

    def set_muted(self, muted: bool) -> None:
        self._backend.set_muted(muted)
        if self._fade_out_backend is not None:
            self._fade_out_backend.set_muted(muted)

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
    def _create_backend(self) -> PlaybackBackend:
        if self._backend_factory is None:
            return create_playback_backend(self)
        return self._backend_factory(self)

    def _adopt_backend(self, backend: PlaybackBackend) -> None:
        backend_parent = getattr(backend, "parent", None)
        if callable(backend_parent) and backend_parent() is None:
            backend.setParent(self)

    def _connect_backend(self, backend: PlaybackBackend) -> None:
        backend.position_changed.connect(self._on_position_changed)
        backend.state_changed.connect(self.state_changed.emit)
        backend.end_reached.connect(self._on_track_ended)

    def _disconnect_backend(self, backend: PlaybackBackend) -> None:
        for signal, slot in (
            (backend.position_changed, self._on_position_changed),
            (backend.state_changed, self.state_changed.emit),
            (backend.end_reached, self._on_track_ended),
        ):
            try:
                signal.disconnect(slot)
            except (RuntimeError, TypeError):
                pass

    @staticmethod
    def _cleanup_backend(backend: PlaybackBackend) -> None:
        cleanup = getattr(backend, "cleanup", None)
        if callable(cleanup):
            cleanup()

    def _dispose_transient_backend(self, backend: PlaybackBackend) -> None:
        self._cleanup_backend(backend)
        try:
            backend.setParent(None)
            backend.deleteLater()
        except RuntimeError:
            pass

    def _clear_fade_timer(self) -> None:
        timer = self._fade_timer
        self._fade_timer = None
        if timer is None:
            return
        timer.stop()
        try:
            timer.deleteLater()
        except RuntimeError:
            pass

    def _on_position_changed(self, pos_ms: int, dur_ms: int) -> None:
        self.position_changed.emit(pos_ms, dur_ms)
        self._maybe_auto_crossfade(pos_ms, dur_ms)

    def _on_track_ended(self) -> None:
        if self._library is not None and 0 <= self._index < len(self._queue):
            if not self._queue[self._index].is_library_item:
                self.next()
                return
            self._library.increment_play_count(self._queue[self._index].id)
        self.next()

    def _next_index(self) -> Optional[int]:
        if self._shuffle:
            candidates = [i for i in range(len(self._queue)) if i != self._index]
            if not candidates:
                return self._index if self._repeat == RepeatMode.ALL else None
            return random.choice(candidates)
        if self._index + 1 < len(self._queue):
            return self._index + 1
        if self._repeat == RepeatMode.ALL:
            return 0
        return None

    def _start_backend_track(
        self,
        backend: PlaybackBackend,
        track: Track,
        volume: int,
        muted: bool | None = None,
    ) -> None:
        backend.set_source(
            track.playback_uri or track.path,
            is_location=track.playback_is_location,
            options=track.playback_options,
        )
        backend.apply_equalizer(
            self._equalizer_enabled,
            self._equalizer_bands,
            self._equalizer_preamp,
        )
        backend.set_muted(self.is_muted() if muted is None else muted)
        backend.set_volume(self._rg_applied_vol(volume, self._rg_multiplier))
        backend.play()

    def _should_crossfade_to(self, idx: int) -> bool:
        return (
            self._crossfade_seconds > 0
            and self._backend_factory is not None
            and self._backend.is_playing()
            and 0 <= self._index < len(self._queue)
            and idx != self._index
        )

    def _maybe_auto_crossfade(self, pos_ms: int, dur_ms: int) -> None:
        if (
            self._crossfade_seconds <= 0
            or self._fade_timer is not None
            or self._repeat == RepeatMode.ONE
            or dur_ms <= 0
            or pos_ms <= 0
            or not self._backend.is_playing()
        ):
            return
        remaining_ms = dur_ms - pos_ms
        if remaining_ms > self._crossfade_seconds * 1000:
            return
        nxt = self._next_index()
        if nxt is None or nxt == self._index:
            return
        if (
            self._library is not None
            and 0 <= self._index < len(self._queue)
            and self._queue[self._index].is_library_item
        ):
            self._library.increment_play_count(self._queue[self._index].id)
        self._crossfade_to_index(nxt)

    def _crossfade_to_index(self, idx: int) -> bool:
        if self._backend_factory is None:
            return False
        if self._fade_timer is not None or self._fade_out_backend is not None:
            self._cancel_crossfade()
        try:
            next_backend = self._create_backend()
        except Exception:
            return False
        self._adopt_backend(next_backend)
        is_available = getattr(next_backend, "is_available", None)
        if callable(is_available) and not is_available():
            self._cleanup_backend(next_backend)
            return False

        previous_backend = self._backend
        muted = previous_backend.is_muted()
        self._disconnect_backend(previous_backend)
        self._backend = next_backend
        self._connect_backend(next_backend)

        self._rg_fade_out_multiplier = self._rg_multiplier
        self._index = idx
        track = self._queue[idx]
        self._rg_multiplier = self._rg_multiplier_for_track(track)
        self._start_backend_track(next_backend, track, 0, muted=muted)
        self.track_changed.emit(track)

        self._fade_out_backend = previous_backend
        self._clear_fade_timer()
        self._fade_target = self._user_volume
        self._fade_step = 0
        self._fade_total_steps = max(1, self._crossfade_seconds * 1000 // 50)
        self._fade_timer = QTimer(self)
        self._fade_timer.setInterval(50)
        self._fade_timer.timeout.connect(self._on_fade_tick)
        self._fade_timer.start()
        return True

    def _on_fade_tick(self) -> None:
        self._fade_step += 1
        progress = min(1.0, self._fade_step / self._fade_total_steps)
        in_vol = self._rg_applied_vol(int(self._fade_target * progress), self._rg_multiplier)
        out_vol = self._rg_applied_vol(
            int(self._fade_target * (1.0 - progress)), self._rg_fade_out_multiplier
        )
        self._backend.set_volume(in_vol)
        if self._fade_out_backend is not None:
            self._fade_out_backend.set_volume(out_vol)
        if self._fade_step >= self._fade_total_steps:
            self._finish_crossfade()

    def _finish_crossfade(self) -> None:
        self._clear_fade_timer()
        if self._fade_out_backend is not None:
            backend = self._fade_out_backend
            self._fade_out_backend = None
            backend.stop()
            self._dispose_transient_backend(backend)
        self._backend.set_volume(self._rg_applied_vol(self._fade_target, self._rg_multiplier))

    def _cancel_crossfade(self, *, restore_active_volume: bool = True) -> None:
        self._clear_fade_timer()
        if self._fade_out_backend is not None:
            backend = self._fade_out_backend
            self._fade_out_backend = None
            backend.stop()
            self._dispose_transient_backend(backend)
        if restore_active_volume:
            self._backend.set_volume(self._rg_applied_vol(self._user_volume, self._rg_multiplier))

    def _rg_multiplier_for_track(self, track: Track) -> float:
        if self._rg_mode == "off":
            return 1.0
        try:
            path = track.path
        except AttributeError:
            return 1.0
        if not path or not Path(path).is_file():
            return 1.0
        from .replaygain import read_track_gain, read_album_gain, gain_multiplier
        if self._rg_mode == "track":
            gain_db = read_track_gain(path)
        else:
            album_gain_db = read_album_gain(path)
            gain_db = album_gain_db if album_gain_db is not None else read_track_gain(path)
        if gain_db is None:
            return 1.0
        return gain_multiplier(gain_db, self._rg_preamp_db, self._rg_prevent_clipping)

    @staticmethod
    def _rg_applied_vol(raw: int, multiplier: float) -> int:
        return max(0, min(100, round(raw * multiplier)))

    def _ensure_playback_available(self) -> bool:
        if self.playback_available():
            return True
        reason = self.playback_unavailable_reason() or "VLC playback is unavailable."
        self.state_changed.emit("stopped")
        self.position_changed.emit(0, 0)
        self.playback_unavailable.emit(reason)
        return False


def _clamp_volume(value: object) -> int:
    try:
        volume = int(value)
    except (TypeError, ValueError):
        volume = 80
    return max(0, min(100, volume))

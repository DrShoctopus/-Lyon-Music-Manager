"""High-level music player with queue and transport logic."""
from __future__ import annotations

import inspect
import random
from enum import Enum
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import unquote, urlparse

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Signal

from .library import Library, Track
from .equalizer import clamp_preamp, flat_equalizer_bands, normalize_equalizer_bands
from .playback_backend import PlaybackBackend, create_playback_backend
from .radio import parse_stream_title


_GAPLESS_PREBUFFER_MS = 2000
_GAPLESS_VLC_OPTIONS: tuple[str, ...] = (
    "--audio-time-stretch-enabled=0",
    "--file-caching=150",
)


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
        self._gapless_vlc_options: tuple[str, ...] = ()
        self._backend = backend or self._create_backend()
        self._adopt_backend(self._backend)

        self._queue: list[Track] = []
        self._index: int = -1
        self._shuffle = False
        self._shuffle_played: set[int] = set()
        self._play_history: list[int] = []
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

        self._audio_output: str = ""
        self._audio_device: str = ""

        self._gapless_playback: bool = False
        self._gapless_prebuffer_backend: PlaybackBackend | None = None
        self._gapless_prebuffer_index: int = -1
        self._active_source_key: tuple | None = None

        self._connect_backend(self._backend)

    # --------------------------------------------------------------- queue
    def load_queue(self, tracks: list[Track], current_index: int = 0) -> None:
        """Restore a saved queue without starting playback."""
        self._queue = list(tracks)
        self._index = max(-1, min(current_index, len(tracks) - 1)) if tracks else -1
        self._active_source_key = None
        self._reset_play_tracking()
        if 0 <= self._index < len(self._queue):
            self._shuffle_played.add(self._index)
        self.queue_changed.emit()
        if 0 <= self._index < len(self._queue):
            self.track_changed.emit(self._queue[self._index])

    def set_queue(self, tracks: list[Track], start_index: int = 0) -> None:
        self._queue = list(tracks)
        self._index = -1
        self._active_source_key = None
        self._reset_play_tracking()
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
        self._active_source_key = None
        self._reset_play_tracking()
        self.queue_changed.emit()
        self.track_changed.emit(None)

    def remove_queue_index(self, idx: int) -> None:
        if not (0 <= idx < len(self._queue)):
            return
        self._remove_play_tracking_index(idx)
        removing_current = idx == self._index
        was_playing = self.is_playing()
        if idx == self._gapless_prebuffer_index:
            self._cancel_gapless_prebuffer()
        elif idx < self._gapless_prebuffer_index:
            self._gapless_prebuffer_index -= 1
        del self._queue[idx]
        if not self._queue:
            self.stop()
            self._index = -1
            self._active_source_key = None
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
            self._active_source_key = None
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
        pb = self._gapless_prebuffer_index
        if pb >= 0:
            if pb == old_index:
                self._gapless_prebuffer_index = new_index
            elif old_index < pb <= new_index:
                self._gapless_prebuffer_index -= 1
            elif new_index <= pb < old_index:
                self._gapless_prebuffer_index += 1
        self._move_play_tracking_index(old_index, new_index)
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
    def play_index(self, idx: int) -> bool:
        return self._play_index(idx)

    def _play_index(self, idx: int, *, record_history: bool = True) -> bool:
        if not (0 <= idx < len(self._queue)):
            return False
        if not self._ensure_playback_available():
            return False
        self._cancel_gapless_prebuffer()
        previous_index = self._index
        if self._should_crossfade_to(idx) and self._crossfade_to_index(
            idx,
            previous_index=previous_index,
            record_history=record_history,
        ):
            return True
        self._cancel_crossfade()
        track = self._queue[idx]
        old_multiplier = self._rg_multiplier
        self._rg_multiplier = self._rg_multiplier_for_track(track)
        if not self._start_backend_track(self._backend, track, self._user_volume):
            self._rg_multiplier = old_multiplier
            return False
        self._commit_track_index(idx, previous_index, record_history=record_history)
        return True

    def play(self) -> None:
        if self._index < 0 and self._queue:
            self.play_index(0)
            return
        if not self._ensure_playback_available():
            return
        track = self.current()
        if track is not None and self._active_source_key != self._track_source_key(track):
            self._cancel_crossfade()
            old_multiplier = self._rg_multiplier
            self._rg_multiplier = self._rg_multiplier_for_track(track)
            if self._start_backend_track(self._backend, track, self._user_volume):
                self._active_source_key = self._track_source_key(track)
            else:
                self._rg_multiplier = old_multiplier
            return
        self._backend.play()

    def play_url(
        self,
        uri: str,
        *,
        title: str | None = None,
        options: tuple[str, ...] = (),
    ) -> None:
        """Play a VLC location/MRL as a one-item, non-library queue."""
        uri = str(uri or "").strip()
        if not uri:
            return
        track = Track(
            id=0,
            path=uri,
            title=(title or "").strip() or _title_from_uri(uri),
            artist="Network Stream",
            album_artist="",
            album="",
            track_no=0,
            disc_no=0,
            year=0,
            genre="",
            duration=0.0,
            media_type="audio",
            playback_uri=uri,
            playback_is_location=True,
            playback_options=tuple(options),
            is_library_item=False,
        )
        self.set_queue([track], 0)

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
        self._cancel_gapless_prebuffer()
        self._backend.stop()

    def cleanup(self) -> None:
        """Release native backend resources. Call before the application exits."""
        self._cancel_crossfade()
        self._cancel_gapless_prebuffer()
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
            self._active_source_key = None
            self._reset_play_tracking()
            self.track_changed.emit(None)
            return
        self.play_index(nxt)

    def previous(self) -> None:
        if self._backend.position() > 4000:
            self._backend.set_position(0)
            return
        if self._shuffle:
            while self._play_history:
                idx = self._play_history.pop()
                if not (0 <= idx < len(self._queue)):
                    continue  # stale entry from a removed track — discard
                if idx != self._index:
                    self._play_index(idx, record_history=False)
                    return
                break  # history points at current track — stop here
            return
        if self._index > 0:
            self.play_index(self._index - 1)
        elif self._repeat == RepeatMode.ALL and self._queue:
            self.play_index(len(self._queue) - 1)

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

    def set_audio_device(self, audio_output: str, device_id: str) -> None:
        """Apply audio output module and device. Takes effect on next play()."""
        self._audio_output = audio_output
        self._audio_device = device_id
        self._set_backend_audio_device(self._backend, audio_output, device_id)
        if self._fade_out_backend is not None:
            self._set_backend_audio_device(self._fade_out_backend, audio_output, device_id)

    def set_gapless(self, enabled: bool) -> None:
        """Enable gapless pre-buffering. Has no effect when crossfade > 0."""
        self._gapless_playback = bool(enabled)
        self._gapless_vlc_options = _GAPLESS_VLC_OPTIONS if self._gapless_playback else ()

    def list_audio_outputs(self) -> list[tuple[str, str]]:
        lister = getattr(self._backend, "list_audio_outputs", None)
        if callable(lister):
            return lister()
        return []

    def list_audio_devices(self, audio_output: str = "") -> list[tuple[str, str]]:
        lister = getattr(self._backend, "list_audio_devices", None)
        if callable(lister):
            return lister(audio_output)
        return []

    def set_muted(self, muted: bool) -> None:
        self._backend.set_muted(muted)
        if self._fade_out_backend is not None:
            self._fade_out_backend.set_muted(muted)

    def is_muted(self) -> bool:
        return self._backend.is_muted()

    def shuffle(self) -> bool:
        return self._shuffle

    def set_shuffle(self, on: bool) -> None:
        was_shuffle = self._shuffle
        self._shuffle = bool(on)
        if not self._shuffle:
            self._reset_play_tracking()
        elif not was_shuffle:
            self._reset_play_tracking()
            if 0 <= self._index < len(self._queue):
                self._shuffle_played.add(self._index)
        elif 0 <= self._index < len(self._queue):
            self._shuffle_played.add(self._index)

    def repeat(self) -> RepeatMode:
        return self._repeat

    def cycle_repeat(self) -> RepeatMode:
        order = [RepeatMode.OFF, RepeatMode.ALL, RepeatMode.ONE]
        i = order.index(self._repeat)
        self._repeat = order[(i + 1) % len(order)]
        return self._repeat

    # --------------------------------------------------------------- internals
    def _create_backend(self) -> PlaybackBackend:
        factory = self._backend_factory or create_playback_backend
        if factory is create_playback_backend and _accepts_vlc_instance_options(factory):
            return factory(self, vlc_instance_options=self._gapless_vlc_options)
        return factory(self)

    def _adopt_backend(self, backend: PlaybackBackend) -> None:
        backend_parent = getattr(backend, "parent", None)
        if callable(backend_parent) and backend_parent() is None:
            backend.setParent(self)

    def _connect_backend(self, backend: PlaybackBackend) -> None:
        backend.position_changed.connect(self._on_position_changed)
        backend.state_changed.connect(self.state_changed.emit)
        backend.end_reached.connect(self._on_track_ended)
        metadata_signal = getattr(backend, "metadata_changed", None)
        if metadata_signal is not None:
            metadata_signal.connect(self._on_backend_metadata)

    def _disconnect_backend(self, backend: PlaybackBackend) -> None:
        slots: list[tuple[object, object]] = [
            (backend.position_changed, self._on_position_changed),
            (backend.state_changed, self.state_changed.emit),
            (backend.end_reached, self._on_track_ended),
        ]
        metadata_signal = getattr(backend, "metadata_changed", None)
        if metadata_signal is not None:
            slots.append((metadata_signal, self._on_backend_metadata))
        for signal, slot in slots:
            try:
                signal.disconnect(slot)
            except (RuntimeError, TypeError):
                pass

    @staticmethod
    def _cleanup_backend(backend: PlaybackBackend) -> None:
        cleanup = getattr(backend, "cleanup", None)
        if callable(cleanup):
            cleanup()

    @staticmethod
    def _set_backend_audio_device(
        backend: PlaybackBackend,
        audio_output: str,
        device_id: str,
    ) -> None:
        setter = getattr(backend, "set_audio_device", None)
        if callable(setter):
            setter(audio_output, device_id)

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

    def _reset_play_tracking(self) -> None:
        self._shuffle_played.clear()
        self._play_history.clear()

    def _commit_track_index(
        self,
        idx: int,
        previous_index: int,
        *,
        record_history: bool = True,
    ) -> None:
        if (
            record_history
            and 0 <= previous_index < len(self._queue)
            and previous_index != idx
        ):
            self._play_history.append(previous_index)
        self._index = idx
        self._active_source_key = self._track_source_key(self._queue[idx])
        if self._shuffle:
            self._shuffle_played.add(idx)
        self._precompute_rg_for_upcoming()
        self.track_changed.emit(self._queue[idx])

    def _remove_play_tracking_index(self, removed: int) -> None:
        self._play_history = [
            idx if idx < removed else idx - 1
            for idx in self._play_history
            if idx != removed
        ]
        self._shuffle_played = {
            idx if idx < removed else idx - 1
            for idx in self._shuffle_played
            if idx != removed
        }

    def _move_play_tracking_index(self, old_index: int, new_index: int) -> None:
        def remap(idx: int) -> int:
            if idx == old_index:
                return new_index
            if old_index < idx <= new_index:
                return idx - 1
            if new_index <= idx < old_index:
                return idx + 1
            return idx

        self._play_history = [remap(idx) for idx in self._play_history]
        self._shuffle_played = {remap(idx) for idx in self._shuffle_played}

    def _on_position_changed(self, pos_ms: int, dur_ms: int) -> None:
        self.position_changed.emit(pos_ms, dur_ms)
        self._maybe_auto_crossfade(pos_ms, dur_ms)
        self._maybe_gapless_prebuffer(pos_ms, dur_ms)

    def _on_backend_metadata(self, meta: dict) -> None:
        """Apply ICY/HLS metadata updates to the currently-streaming track.

        Library tracks always own their own tags, so we ignore metadata
        callbacks for them. Streams (``is_library_item=False`` with a remote
        ``playback_uri``) get their ``title`` / ``artist`` updated in place so
        the transport bar and Now Playing view refresh via ``track_changed``.
        """
        track = self.current()
        if track is None or track.is_library_item:
            return
        if not track.playback_is_location:
            return
        if not isinstance(meta, dict):
            return

        now_playing = str(meta.get("now_playing") or "").strip()
        artist = str(meta.get("artist") or "").strip()
        title = str(meta.get("title") or "").strip()

        # Prefer the explicit Artist/Title pair when VLC has parsed them.
        # Otherwise fall back to splitting the "Artist - Title" form that ICY
        # NowPlaying typically carries.
        if not artist and now_playing:
            parsed_artist, parsed_title = parse_stream_title(now_playing)
            if parsed_artist or parsed_title:
                artist = parsed_artist
                if parsed_title:
                    title = parsed_title

        # The station name is the user-facing label; preserve it as the album
        # so the transport bar's "{artist} — {album}" line reads
        # "Stream Artist — Station Name".
        if track.album == "" and track.title:
            track.album = track.title

        if artist:
            track.artist = artist
        if title:
            track.title = title
        elif now_playing:
            track.title = now_playing

        self.track_changed.emit(track)

    def _on_track_ended(self) -> None:
        if 0 <= self._index < len(self._queue):
            track = self._queue[self._index]
            if track.is_library_item and self._library is not None:
                self._library.increment_play_count(track.id)
        self._advance_after_end()

    def _advance_after_end(self) -> None:
        if self._gapless_prebuffer_backend is not None:
            self._promote_gapless_prebuffer()
        else:
            self.next()

    def _next_index(self) -> Optional[int]:
        if self._shuffle:
            played = set(self._shuffle_played)
            if 0 <= self._index < len(self._queue):
                played.add(self._index)
            candidates = [
                i for i in range(len(self._queue))
                if i != self._index and i not in played
            ]
            if not candidates and self._repeat == RepeatMode.ALL:
                self._shuffle_played.clear()
                if 0 <= self._index < len(self._queue):
                    self._shuffle_played.add(self._index)
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
    ) -> bool:
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
        result = backend.play()
        if result is False:
            return False
        if result is None:
            return backend.is_playing()
        return True

    @staticmethod
    def _track_source_key(track: Track) -> tuple:
        return (
            track.playback_uri or track.path,
            bool(track.playback_is_location),
            tuple(track.playback_options),
        )

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
        outgoing_track = (
            self._queue[self._index]
            if 0 <= self._index < len(self._queue)
            else None
        )
        if self._crossfade_to_index(nxt):
            if (
                self._library is not None
                and outgoing_track is not None
                and outgoing_track.is_library_item
            ):
                self._library.increment_play_count(outgoing_track.id)

    def _crossfade_to_index(
        self,
        idx: int,
        *,
        previous_index: int | None = None,
        record_history: bool = True,
    ) -> bool:
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
            self._dispose_transient_backend(next_backend)
            return False
        if self._audio_output or self._audio_device:
            self._set_backend_audio_device(next_backend, self._audio_output, self._audio_device)

        previous_backend = self._backend
        muted = previous_backend.is_muted()
        old_multiplier = self._rg_multiplier
        track = self._queue[idx]
        new_multiplier = self._rg_multiplier_for_track(track)
        self._rg_multiplier = new_multiplier
        if not self._start_backend_track(next_backend, track, 0, muted=muted):
            self._rg_multiplier = old_multiplier
            self._dispose_transient_backend(next_backend)
            return False

        self._disconnect_backend(previous_backend)
        self._backend = next_backend
        self._connect_backend(next_backend)

        self._rg_fade_out_multiplier = old_multiplier
        self._commit_track_index(
            idx,
            self._index if previous_index is None else previous_index,
            record_history=record_history,
        )

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

    def _maybe_gapless_prebuffer(self, pos_ms: int, dur_ms: int) -> None:
        if (
            not self._gapless_playback
            or self._backend_factory is None
            or self._crossfade_seconds > 0
            or self._gapless_prebuffer_backend is not None
            or self._fade_timer is not None
            or self._repeat == RepeatMode.ONE
            or dur_ms <= 0
            or pos_ms <= 0
            or not self._backend.is_playing()
        ):
            return
        if dur_ms - pos_ms > _GAPLESS_PREBUFFER_MS:
            return
        nxt = self._next_index()
        if nxt is None or nxt == self._index:
            return
        self._start_gapless_prebuffer(nxt)

    def _start_gapless_prebuffer(self, idx: int) -> None:
        try:
            backend = self._create_backend()
        except Exception:
            return
        self._adopt_backend(backend)
        is_available = getattr(backend, "is_available", None)
        if callable(is_available) and not is_available():
            self._cleanup_backend(backend)
            return
        if self._audio_output or self._audio_device:
            self._set_backend_audio_device(backend, self._audio_output, self._audio_device)
        track = self._queue[idx]
        backend.set_source(
            track.playback_uri or track.path,
            is_location=track.playback_is_location,
            options=track.playback_options,
        )
        backend.apply_equalizer(self._equalizer_enabled, self._equalizer_bands, self._equalizer_preamp)
        backend.set_muted(True)
        backend.set_volume(0)
        backend.play()
        backend.pause()
        backend.set_position(0)
        self._gapless_prebuffer_backend = backend
        self._gapless_prebuffer_index = idx

    def _promote_gapless_prebuffer(self) -> None:
        backend = self._gapless_prebuffer_backend
        idx = self._gapless_prebuffer_index
        self._gapless_prebuffer_backend = None
        self._gapless_prebuffer_index = -1
        if backend is None or not (0 <= idx < len(self._queue)):
            if backend is not None:
                self._cleanup_backend(backend)
            self.next()
            return
        muted = self._backend.is_muted()
        previous_index = self._index
        old_backend = self._backend
        self._disconnect_backend(old_backend)
        self._backend = backend
        self._connect_backend(backend)
        track = self._queue[idx]
        self._rg_multiplier = self._rg_multiplier_for_track(track)
        backend.set_muted(muted)
        backend.set_volume(self._rg_applied_vol(self._user_volume, self._rg_multiplier))
        backend.play()
        old_backend.stop()
        self._dispose_transient_backend(old_backend)
        self._commit_track_index(idx, previous_index)

    def _cancel_gapless_prebuffer(self) -> None:
        backend = self._gapless_prebuffer_backend
        self._gapless_prebuffer_backend = None
        self._gapless_prebuffer_index = -1
        if backend is not None:
            backend.stop()
            self._dispose_transient_backend(backend)

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

    def _precompute_rg_for_upcoming(self) -> None:
        """Warm the ReplayGain tag cache for the next few tracks in a background thread."""
        if self._rg_mode == "off":
            return
        upcoming: list[str] = []
        idx = self._index
        for offset in range(1, 4):
            nxt = idx + offset
            if nxt < len(self._queue):
                path = getattr(self._queue[nxt], "path", None)
                if path:
                    upcoming.append(path)
        if not upcoming:
            return
        mode = self._rg_mode

        class _WarmCache(QRunnable):
            def run(self):
                from .replaygain import read_track_gain, read_album_gain
                for p in upcoming:
                    if mode == "track":
                        read_track_gain(p)
                    else:
                        read_album_gain(p)
                        read_track_gain(p)

        QThreadPool.globalInstance().start(_WarmCache())

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


def _title_from_uri(uri: str) -> str:
    parsed = urlparse(uri)
    tail = Path(unquote(parsed.path or "")).name
    if parsed.hostname and tail:
        return f"{parsed.hostname} / {tail}"
    if parsed.hostname:
        return parsed.hostname
    return uri


def _accepts_vlc_instance_options(factory: Callable[..., PlaybackBackend]) -> bool:
    try:
        parameters = inspect.signature(factory).parameters.values()
    except (TypeError, ValueError):
        return True
    return any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD
        or parameter.name == "vlc_instance_options"
        for parameter in parameters
    )

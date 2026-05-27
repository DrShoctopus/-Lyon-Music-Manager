"""Playback backend implementations for Lyon's high-level player."""
from __future__ import annotations

import importlib
import logging
import os
from pathlib import Path
from typing import Any, Optional

from PySide6.QtCore import QObject, Signal

from .equalizer import EQ_BAND_COUNT
from .settings import bundled_bin_dir
from .vlc_equalizer import (
    EQ_FADE_INTERVAL_MS,
    VlcEqualizerController,
)


LOG = logging.getLogger(__name__)
# Lyon now exposes libVLC's complete native ten-band equalizer, so the
# UI band order maps directly to VLC's band indexes.
VLC_EQ_BAND_INDEXES = tuple(range(EQ_BAND_COUNT))
_DLL_DIRECTORY_HANDLES: list[Any] = []
_CONFIGURED_VLC_DIRS: set[Path] = set()


def _prepend_path(path: Path) -> None:
    current = os.environ.get("PATH", "")
    path_text = str(path)
    parts = current.split(os.pathsep) if current else []
    if path_text not in parts:
        os.environ["PATH"] = path_text + (os.pathsep + current if current else "")


def _decode_vlc_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _configure_vlc_runtime_path() -> None:
    """Expose a bundled VLC runtime to python-vlc when one is present.

    Source runs and PyInstaller builds may place VLC beside the existing bundled
    tools as ``bin/vlc``.  Adding that folder before importing ``vlc`` lets
    Windows resolve ``libvlc.dll`` and lets VLC find its plugin directory
    without requiring every user to install VLC globally.
    """
    vlc_dir = bundled_bin_dir() / "vlc"
    if not vlc_dir.exists() or vlc_dir in _CONFIGURED_VLC_DIRS:
        return

    _prepend_path(vlc_dir)
    add_dll_directory = getattr(os, "add_dll_directory", None)
    if add_dll_directory is not None:
        try:
            _DLL_DIRECTORY_HANDLES.append(add_dll_directory(str(vlc_dir)))
        except OSError as exc:
            LOG.warning("Could not add VLC runtime directory %s: %s", vlc_dir, exc)

    plugins_dir = vlc_dir / "plugins"
    if plugins_dir.exists():
        os.environ.setdefault("VLC_PLUGIN_PATH", str(plugins_dir))
    _CONFIGURED_VLC_DIRS.add(vlc_dir)


def close_dll_handles() -> None:
    """Release Windows DLL directory handles acquired by _configure_vlc_runtime_path."""
    for handle in _DLL_DIRECTORY_HANDLES:
        try:
            handle.close()
        except Exception as exc:
            LOG.debug("Could not close DLL directory handle: %s", exc)
    _DLL_DIRECTORY_HANDLES.clear()


class PlaybackBackend(QObject):
    """Interface shared by concrete playback engines."""

    state_changed = Signal(str)
    position_changed = Signal(int, int)
    end_reached = Signal()
    # Live stream metadata: {"now_playing": str, "title": str, "artist": str}.
    # Emitted when ICY headers or HLS chunk tags advertise a track change.
    metadata_changed = Signal(dict)
    # Source-level playback failure (e.g. DNS failure, 404, timeout). The
    # payload is the URL of the failed source so the caller can correlate it
    # with the user-facing title.
    error_occurred = Signal(str)

    def list_audio_outputs(self) -> list[tuple[str, str]]:
        """Return [(id, description), …] for available audio output modules."""
        return []

    def list_audio_devices(self, audio_output: str = "") -> list[tuple[str, str]]:
        """Return [(device_id, description), …] for the given output module."""
        return []

    def set_audio_device(self, audio_output: str, device_id: str) -> None:
        """Switch audio output module and/or device. Takes effect on next play()."""

    def set_source(
        self,
        path: str,
        *,
        is_location: bool = False,
        options: tuple[str, ...] = (),
    ) -> None:
        raise NotImplementedError

    def play(self) -> bool | None:
        raise NotImplementedError

    def pause(self) -> None:
        raise NotImplementedError

    def stop(self) -> None:
        raise NotImplementedError

    def position(self) -> int:
        raise NotImplementedError

    def duration(self) -> int:
        raise NotImplementedError

    def set_position(self, ms: int) -> None:
        raise NotImplementedError

    def set_volume(self, percent: int) -> None:
        raise NotImplementedError

    def volume(self) -> int:
        raise NotImplementedError

    def set_muted(self, muted: bool) -> None:
        raise NotImplementedError

    def is_muted(self) -> bool:
        raise NotImplementedError

    def is_playing(self) -> bool:
        raise NotImplementedError

    def apply_equalizer(self, enabled: bool, bands: list[int], preamp: int = 0) -> None:
        raise NotImplementedError

    def is_available(self) -> bool:
        return True

    def unavailable_reason(self) -> str:
        return ""

    def cleanup(self) -> None:
        """Release any native resources held by the backend. Safe to call on all backends."""


class UnavailablePlaybackBackend(PlaybackBackend):
    """Non-playing backend used when the required libVLC runtime is unavailable."""

    def __init__(self, reason: str, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._reason = reason
        self._volume = 80
        self._muted = False
        self._source = ""
        self._warned = False

    def set_source(
        self,
        path: str,
        *,
        is_location: bool = False,
        options: tuple[str, ...] = (),
    ) -> None:
        self._source = path

    def play(self) -> bool:
        if not self._warned:
            LOG.warning("Playback unavailable: %s", self._reason)
            self._warned = True
        self.state_changed.emit("stopped")
        self.position_changed.emit(0, 0)
        return False

    def pause(self) -> None:
        self.state_changed.emit("stopped")

    def stop(self) -> None:
        self.state_changed.emit("stopped")
        self.position_changed.emit(0, 0)

    def position(self) -> int:
        return 0

    def duration(self) -> int:
        return 0

    def set_position(self, ms: int) -> None:
        self.position_changed.emit(0, 0)

    def set_volume(self, percent: int) -> None:
        self._volume = max(0, min(100, int(percent)))

    def volume(self) -> int:
        return self._volume

    def set_muted(self, muted: bool) -> None:
        self._muted = bool(muted)

    def is_muted(self) -> bool:
        return self._muted

    def is_playing(self) -> bool:
        return False

    def apply_equalizer(self, enabled: bool, bands: list[int], preamp: int = 0) -> None:
        pass

    def is_available(self) -> bool:
        return False

    def unavailable_reason(self) -> str:
        return self._reason


class VlcPlaybackBackend(PlaybackBackend):
    """libVLC playback backend with real equalizer support."""

    def __init__(
        self,
        vlc_module: Any,
        parent: Optional[QObject] = None,
        *,
        audio_output: str = "",
        audio_device: str = "",
        vlc_instance_options: tuple[str, ...] = (),
    ):
        super().__init__(parent)
        from PySide6.QtCore import QMetaObject, Qt, QTimer, Q_ARG

        self._vlc = vlc_module
        self._instance = vlc_module.Instance(*vlc_instance_options)
        self._player = self._instance.media_player_new()
        if audio_output:
            try:
                self._player.audio_output_set(audio_output)
            except Exception as exc:
                LOG.debug("Could not set audio output %r: %s", audio_output, exc)
        if audio_device or audio_output:
            try:
                self._player.audio_output_device_set(audio_output or None, audio_device or None)
            except Exception as exc:
                LOG.debug("Could not set audio device %r: %s", audio_device, exc)
        self._volume = 80
        self._muted = False
        self._last_state = "stopped"
        self._last_position = (-1, -1)
        self._ended = False
        self._has_started_playback = False
        self._eq = VlcEqualizerController(
            vlc_module,
            self._player,
            VLC_EQ_BAND_INDEXES,
            context="VLC playback equalizer",
        )

        self._eq_fade_timer = QTimer(self)
        self._eq_fade_timer.setInterval(EQ_FADE_INTERVAL_MS)
        self._eq_fade_timer.timeout.connect(self._eq_fade_step)

        self._timer = QTimer(self)
        self._timer.setInterval(500)
        self._timer.timeout.connect(self._poll)

        # Live stream metadata pipeline. VLC fires meta events on a worker
        # thread; we hop back onto the GUI thread via a single-shot QTimer so
        # signal receivers always run with normal Qt thread affinity.
        self._meta_dispatch = QTimer(self)
        self._meta_dispatch.setSingleShot(True)
        self._meta_dispatch.setInterval(0)
        self._meta_dispatch.timeout.connect(self._emit_pending_metadata)
        self._media_event_callbacks: list[tuple[Any, int, Any]] = []
        self._current_media: Any = None
        self._current_source: str = ""
        self._error_emitted_for: str = ""
        self._last_emitted_metadata: dict[str, str] = {}
        self._QMetaObject = QMetaObject
        self._Qt = Qt
        self._Q_ARG = Q_ARG

    def set_source(
        self,
        path: str,
        *,
        is_location: bool = False,
        options: tuple[str, ...] = (),
    ) -> None:
        self._detach_media_events()
        media = (
            self._instance.media_new_location(path)
            if is_location
            else self._instance.media_new_path(str(path))
        )
        for option in options:
            try:
                media.add_option(option)
            except Exception as exc:
                LOG.debug("Could not add VLC media option %s: %s", option, exc)
        self._player.set_media(media)
        self._attach_media_events(media)
        media.release()  # drop our reference; VLC holds its own via set_media
        self._current_source = str(path)
        self._error_emitted_for = ""
        self._last_emitted_metadata = {}
        self._ended = False
        self._has_started_playback = False
        self._last_position = (-1, -1)
        self._player.audio_set_volume(self._volume)
        self._player.audio_set_mute(self._muted)
        self._eq.attach_to_player()

    def play(self) -> bool:
        ok = self._player.play() != -1
        if ok:
            self._timer.start()
            self._emit_state("playing")
        else:
            self._emit_state("stopped")
        return ok

    def pause(self) -> None:
        self._player.pause()
        self._timer.stop()
        self._emit_state("paused")

    def stop(self) -> None:
        self._player.stop()
        self._timer.stop()
        self._ended = False
        self._emit_state("stopped")
        self.position_changed.emit(0, max(0, self.duration()))

    def position(self) -> int:
        return max(0, int(self._player.get_time()))

    def duration(self) -> int:
        return max(0, int(self._player.get_length()))

    def set_position(self, ms: int) -> None:
        self._player.set_time(max(0, int(ms)))
        self.position_changed.emit(self.position(), self.duration())

    def set_volume(self, percent: int) -> None:
        self._volume = max(0, min(100, int(percent)))
        self._player.audio_set_volume(self._volume)

    def volume(self) -> int:
        return self._volume

    def set_muted(self, muted: bool) -> None:
        self._muted = bool(muted)
        self._player.audio_set_mute(self._muted)

    def is_muted(self) -> bool:
        return self._muted

    def is_playing(self) -> bool:
        return bool(self._player.is_playing())

    def list_audio_outputs(self) -> list[tuple[str, str]]:
        result: list[tuple[str, str]] = [("", "Default")]
        head: Any = None
        try:
            head = self._instance.audio_output_list_get()
            out = head
            while out:
                item = getattr(out, "contents", out)
                name = _decode_vlc_text(getattr(item, "name", None))
                desc = _decode_vlc_text(getattr(item, "description", None)) or name
                if name:
                    result.append((name, desc))
                out = getattr(item, "next", None)
        except Exception as exc:
            LOG.debug("Could not list audio outputs: %s", exc)
        finally:
            if head:
                release = getattr(self._vlc, "libvlc_audio_output_list_release", None)
                if callable(release):
                    try:
                        release(head)
                    except Exception as exc:
                        LOG.debug("Could not release audio output list: %s", exc)
        return result

    def list_audio_devices(self, audio_output: str = "") -> list[tuple[str, str]]:
        result: list[tuple[str, str]] = [("", "Default")]
        head: Any = None
        try:
            head = self._instance.audio_output_device_list_get(audio_output)
            dev = head
            while dev:
                item = getattr(dev, "contents", dev)
                device_id = _decode_vlc_text(getattr(item, "device", None))
                desc = _decode_vlc_text(getattr(item, "description", None)) or device_id
                if device_id:
                    result.append((device_id, desc))
                dev = getattr(item, "next", None)
        except Exception as exc:
            LOG.debug("Could not list audio devices for %r: %s", audio_output, exc)
        finally:
            if head:
                release = getattr(self._vlc, "libvlc_audio_output_device_list_release", None)
                if callable(release):
                    try:
                        release(head)
                    except Exception as exc:
                        LOG.debug("Could not release audio device list: %s", exc)
        return result

    def set_audio_device(self, audio_output: str, device_id: str) -> None:
        try:
            if audio_output:
                self._player.audio_output_set(audio_output)
            self._player.audio_output_device_set(audio_output or None, device_id or None)
        except Exception as exc:
            LOG.debug("Could not set audio device %r/%r: %s", audio_output, device_id, exc)

    def apply_equalizer(self, enabled: bool, bands: list[int], preamp: int = 0) -> None:
        self._eq_fade_timer.stop()
        if self._eq.apply(enabled, bands, preamp):
            self._eq_fade_timer.start()

    def _eq_fade_step(self) -> None:
        if not self._eq.fade_step():
            self._eq_fade_timer.stop()

    def _emit_state(self, state: str) -> None:
        if state != self._last_state:
            self._last_state = state
            self.state_changed.emit(state)

    # ---- live stream metadata ---------------------------------------------

    def _attach_media_events(self, media: Any) -> None:
        """Subscribe to VLC ``MediaMetaChanged`` events for ICY updates.

        VLC dispatches event callbacks from a worker thread. The handlers must
        therefore do as little as possible: they just schedule a debounced
        single-shot timer on the GUI thread to read the metadata.
        """
        event_manager = getattr(media, "event_manager", None)
        if not callable(event_manager):
            return
        try:
            em = event_manager()
        except Exception as exc:
            LOG.debug("Could not access media event_manager: %s", exc)
            return
        meta_event = self._meta_event_type()
        if meta_event is None or em is None:
            return
        handler = self._on_meta_event
        try:
            em.event_attach(meta_event, handler)
        except Exception as exc:
            LOG.debug("Could not attach MediaMetaChanged handler: %s", exc)
            return
        self._media_event_callbacks.append((em, meta_event, handler))
        self._current_media = media

    def _detach_media_events(self) -> None:
        for em, event_type, handler in self._media_event_callbacks:
            try:
                em.event_detach(event_type)
            except Exception as exc:
                LOG.debug("Could not detach VLC media event %s: %s", event_type, exc)
        self._media_event_callbacks.clear()
        self._current_media = None
        try:
            self._meta_dispatch.stop()
        except Exception:  # noqa: BLE001 — defensive during teardown
            pass

    def _meta_event_type(self) -> Any:
        event_type_cls = getattr(self._vlc, "EventType", None)
        if event_type_cls is None:
            return None
        return getattr(event_type_cls, "MediaMetaChanged", None)

    def _on_meta_event(self, _event: Any) -> None:
        # Runs on a VLC worker thread — must be cheap. Use invokeMethod to
        # marshal timer.start() onto the GUI thread that owns the timer object.
        try:
            self._QMetaObject.invokeMethod(
                self._meta_dispatch,
                "start",
                self._Qt.ConnectionType.QueuedConnection,
                self._Q_ARG(int, 60),
            )
        except Exception as exc:
            LOG.debug("Could not schedule metadata dispatch: %s", exc)

    def _emit_pending_metadata(self) -> None:
        media = self._current_media
        if media is None:
            return
        meta_cls = getattr(self._vlc, "Meta", None)
        if meta_cls is None:
            return
        get_meta = getattr(media, "get_meta", None)
        if not callable(get_meta):
            return

        def read(name: str) -> str:
            attr = getattr(meta_cls, name, None)
            if attr is None:
                return ""
            try:
                value = get_meta(attr)
            except Exception as exc:
                LOG.debug("Could not read VLC meta %s: %s", name, exc)
                return ""
            return _decode_vlc_text(value).strip()

        payload = {
            "now_playing": read("NowPlaying"),
            "title": read("Title"),
            "artist": read("Artist"),
            "artwork_url": read("ArtworkURL"),
        }
        if not any(payload.values()):
            return
        if payload == self._last_emitted_metadata:
            return
        self._last_emitted_metadata = payload
        self.metadata_changed.emit(payload)

    # ---- shutdown ----------------------------------------------------------

    def cleanup(self) -> None:
        """Release native libVLC resources. Must be called before the app exits."""
        self._eq_fade_timer.stop()
        self._timer.stop()
        self._detach_media_events()
        player = self._player
        instance = self._instance
        self._player = None  # type: ignore[assignment]
        self._instance = None  # type: ignore[assignment]
        try:
            player.stop()
            player.release()
        except Exception as exc:
            LOG.debug("Error releasing VLC player: %s", exc)
        try:
            instance.release()
        except Exception as exc:
            LOG.debug("Error releasing VLC instance: %s", exc)

    def _poll(self) -> None:
        player = self._player
        if player is None:
            self._timer.stop()
            return
        try:
            state = player.get_state()
        except Exception as exc:
            LOG.debug("VLC get_state failed (backend may be shutting down): %s", exc)
            self._timer.stop()
            return
        if state == self._vlc.State.Ended:
            pos = max(0, int(player.get_time()))
            dur = max(0, int(player.get_length()))
            if not self._has_started_playback and pos <= 0 and dur <= 0:
                self._timer.stop()
                self._emit_state("stopped")
                current = (0, 0)
                if current != self._last_position:
                    self._last_position = current
                    self.position_changed.emit(*current)
                return
            if not self._ended:
                self._ended = True
                self.end_reached.emit()
            return
        if state == self._vlc.State.Playing:
            self._has_started_playback = True
            self._emit_state("playing")
        elif state == self._vlc.State.Paused:
            self._emit_state("paused")
        elif state == self._vlc.State.Error:
            self._emit_state("stopped")
            source = self._current_source
            if source and source != self._error_emitted_for:
                self._error_emitted_for = source
                self.error_occurred.emit(source)
        elif state == self._vlc.State.Stopped:
            self._emit_state("stopped")
            source = self._current_source
            if (
                source
                and source != self._error_emitted_for
                and not self._has_started_playback
                and self._last_position == (0, 0)
            ):
                self._error_emitted_for = source
                self.error_occurred.emit(source)

        current = (max(0, int(player.get_time())), max(0, int(player.get_length())))
        if current != self._last_position:
            self._last_position = current
            self.position_changed.emit(*current)


def create_playback_backend(
    parent: Optional[QObject] = None,
    *,
    audio_output: str = "",
    audio_device: str = "",
    vlc_instance_options: tuple[str, ...] = (),
) -> PlaybackBackend:
    """Create the required VLC backend, preserving app startup if it is unavailable."""
    _configure_vlc_runtime_path()
    try:
        vlc_module = importlib.import_module("vlc")
    except Exception as exc:
        reason = f"python-vlc is not importable: {exc}"
        LOG.warning("VLC playback backend unavailable: %s", reason)
        return UnavailablePlaybackBackend(reason, parent)

    try:
        return VlcPlaybackBackend(
            vlc_module,
            parent,
            audio_output=audio_output,
            audio_device=audio_device,
            vlc_instance_options=vlc_instance_options,
        )
    except Exception as exc:
        reason = f"libVLC runtime could not be initialized: {exc}"
        LOG.warning("VLC playback backend unavailable: %s", reason)
        return UnavailablePlaybackBackend(reason, parent)

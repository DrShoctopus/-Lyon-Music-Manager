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

    def play(self) -> None:
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

    def play(self) -> None:
        if not self._warned:
            LOG.warning("Playback unavailable: %s", self._reason)
            self._warned = True
        self.state_changed.emit("stopped")
        self.position_changed.emit(0, 0)

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
    ):
        super().__init__(parent)
        from PySide6.QtCore import QTimer

        self._vlc = vlc_module
        self._instance = vlc_module.Instance()
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
        self._timer.setInterval(200)
        self._timer.timeout.connect(self._poll)

    def set_source(
        self,
        path: str,
        *,
        is_location: bool = False,
        options: tuple[str, ...] = (),
    ) -> None:
        media = (
            self._instance.media_new_location(path)
            if is_location
            else self._instance.media_new_path(str(Path(path)))
        )
        for option in options:
            try:
                media.add_option(option)
            except Exception as exc:
                LOG.debug("Could not add VLC media option %s: %s", option, exc)
        self._player.set_media(media)
        media.release()  # drop our reference; VLC holds its own via set_media
        self._ended = False
        self._last_position = (-1, -1)
        self._player.audio_set_volume(self._volume)
        self._player.audio_set_mute(self._muted)
        self._eq.attach_to_player()

    def play(self) -> None:
        self._player.play()
        self._timer.start()
        self._emit_state("playing")

    def pause(self) -> None:
        self._player.pause()
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

    def cleanup(self) -> None:
        """Release native libVLC resources. Must be called before the app exits."""
        self._eq_fade_timer.stop()
        self._timer.stop()
        try:
            self._player.stop()
            self._player.release()
        except Exception as exc:
            LOG.debug("Error releasing VLC player: %s", exc)
        try:
            self._instance.release()
        except Exception as exc:
            LOG.debug("Error releasing VLC instance: %s", exc)
        self._player = None  # type: ignore[assignment]
        self._instance = None  # type: ignore[assignment]

    def _poll(self) -> None:
        try:
            state = self._player.get_state()
        except Exception as exc:
            LOG.debug("VLC get_state failed (backend may be shutting down): %s", exc)
            self._timer.stop()
            return
        if state == self._vlc.State.Ended:
            if not self._ended:
                self._ended = True
                self.end_reached.emit()
            return
        if state == self._vlc.State.Playing:
            self._emit_state("playing")
        elif state == self._vlc.State.Paused:
            self._emit_state("paused")
        elif state in (self._vlc.State.Stopped, self._vlc.State.Error):
            self._emit_state("stopped")

        current = (self.position(), self.duration())
        if current != self._last_position:
            self._last_position = current
            self.position_changed.emit(*current)


def create_playback_backend(
    parent: Optional[QObject] = None,
    *,
    audio_output: str = "",
    audio_device: str = "",
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
        return VlcPlaybackBackend(vlc_module, parent, audio_output=audio_output, audio_device=audio_device)
    except Exception as exc:
        reason = f"libVLC runtime could not be initialized: {exc}"
        LOG.warning("VLC playback backend unavailable: %s", reason)
        return UnavailablePlaybackBackend(reason, parent)

"""Playback backend implementations for Lyon's high-level player."""
from __future__ import annotations

import importlib
import importlib.util
import logging
import os
from pathlib import Path
from typing import Any, Optional

from PySide6.QtCore import QObject, Signal

from .settings import bundled_bin_dir


LOG = logging.getLogger(__name__)
EQ_BAND_COUNT = 6
MIN_EQ_GAIN_DB = -12
MAX_EQ_GAIN_DB = 12
# VLC's native equalizer bands are 60, 170, 310, 600, 1k, 3k, 6k,
# 12k, 14k, and 16k Hz. Map Lyon's six UI bands (60, 150, 400,
# 1k, 3k, 10k Hz) to the closest useful VLC indexes.
VLC_EQ_BAND_INDEXES = (0, 1, 2, 4, 5, 7)
_DLL_DIRECTORY_HANDLES: list[Any] = []
_CONFIGURED_VLC_DIRS: set[Path] = set()


def normalize_equalizer_bands(bands: list[int]) -> list[int]:
    """Return exactly six integer EQ gains clamped to Lyon's UI range."""
    normalized = list(bands[:EQ_BAND_COUNT])
    normalized.extend([0] * (EQ_BAND_COUNT - len(normalized)))
    return [max(MIN_EQ_GAIN_DB, min(MAX_EQ_GAIN_DB, int(value))) for value in normalized]


def _prepend_path(path: Path) -> None:
    current = os.environ.get("PATH", "")
    path_text = str(path)
    parts = current.split(os.pathsep) if current else []
    if path_text not in parts:
        os.environ["PATH"] = path_text + (os.pathsep + current if current else "")


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


class PlaybackBackend(QObject):
    """Interface shared by concrete playback engines."""

    state_changed = Signal(str)
    position_changed = Signal(int, int)
    end_reached = Signal()

    def set_source(self, path: str) -> None:
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

    def apply_equalizer(self, enabled: bool, bands: list[int]) -> None:
        raise NotImplementedError


class QMediaPlaybackBackend(PlaybackBackend):
    """Qt Multimedia fallback backend.

    Qt does not expose per-band equalizer controls, so EQ state is accepted but
    intentionally not applied. The high-level Player still owns normalized EQ
    state, allowing the app to fall back safely if libVLC is unavailable.
    """

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        qtmultimedia = importlib.import_module("PySide6.QtMultimedia")
        self._qmedia_player_cls = qtmultimedia.QMediaPlayer
        self._player = qtmultimedia.QMediaPlayer(self)
        self._audio = qtmultimedia.QAudioOutput(self)
        self._player.setAudioOutput(self._audio)
        self._audio.setVolume(0.8)

        self._player.positionChanged.connect(self._emit_position)
        self._player.durationChanged.connect(self._emit_position_dur)
        self._player.playbackStateChanged.connect(self._on_state)
        self._player.mediaStatusChanged.connect(self._on_media_status)

    def set_source(self, path: str) -> None:
        from PySide6.QtCore import QUrl

        self._player.setSource(QUrl.fromLocalFile(path))

    def play(self) -> None:
        self._player.play()

    def pause(self) -> None:
        self._player.pause()

    def stop(self) -> None:
        self._player.stop()

    def position(self) -> int:
        return self._player.position()

    def duration(self) -> int:
        return self._player.duration()

    def set_position(self, ms: int) -> None:
        self._player.setPosition(ms)

    def set_volume(self, percent: int) -> None:
        self._audio.setVolume(max(0.0, min(1.0, percent / 100.0)))

    def volume(self) -> int:
        return int(round(self._audio.volume() * 100))

    def set_muted(self, muted: bool) -> None:
        self._audio.setMuted(muted)

    def is_muted(self) -> bool:
        return self._audio.isMuted()

    def is_playing(self) -> bool:
        return self._player.playbackState() == self._qmedia_player_cls.PlayingState

    def apply_equalizer(self, enabled: bool, bands: list[int]) -> None:
        _ = (enabled, bands)

    def _emit_position(self, pos: int) -> None:
        self.position_changed.emit(pos, self._player.duration())

    def _emit_position_dur(self, dur: int) -> None:
        self.position_changed.emit(self._player.position(), dur)

    def _on_state(self, state) -> None:
        mapping = {
            self._qmedia_player_cls.PlayingState: "playing",
            self._qmedia_player_cls.PausedState: "paused",
            self._qmedia_player_cls.StoppedState: "stopped",
        }
        self.state_changed.emit(mapping.get(state, "stopped"))

    def _on_media_status(self, status) -> None:
        if status == self._qmedia_player_cls.EndOfMedia:
            self.end_reached.emit()


class VlcPlaybackBackend(PlaybackBackend):
    """libVLC playback backend with real equalizer support."""

    def __init__(self, vlc_module: Any, parent: Optional[QObject] = None):
        super().__init__(parent)
        from PySide6.QtCore import QTimer

        self._vlc = vlc_module
        self._instance = vlc_module.Instance()
        self._player = self._instance.media_player_new()
        self._volume = 80
        self._muted = False
        self._last_state = "stopped"
        self._last_position = (-1, -1)
        self._ended = False
        self._equalizer = None

        self._timer = QTimer(self)
        self._timer.setInterval(500)
        self._timer.timeout.connect(self._poll)

    def set_source(self, path: str) -> None:
        media = self._instance.media_new_path(str(Path(path)))
        self._player.set_media(media)
        self._ended = False
        self._last_position = (-1, -1)
        self._player.audio_set_volume(self._volume)
        self._player.audio_set_mute(self._muted)
        if self._equalizer is not None:
            self._player.set_equalizer(self._equalizer)

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

    def apply_equalizer(self, enabled: bool, bands: list[int]) -> None:
        if not enabled:
            self._equalizer = None
            try:
                self._player.set_equalizer(None)
            except Exception as exc:
                LOG.warning("Could not clear VLC equalizer: %s", exc)
            return

        try:
            equalizer = self._vlc.AudioEqualizer()
            if equalizer is None:
                raise RuntimeError("VLC did not create an AudioEqualizer instance")
            equalizer.set_preamp(0.0)
            for ui_band, vlc_index in zip(normalize_equalizer_bands(bands), VLC_EQ_BAND_INDEXES, strict=True):
                equalizer.set_amp_at_index(float(ui_band), vlc_index)
            self._player.set_equalizer(equalizer)
            self._equalizer = equalizer
        except Exception as exc:
            self._equalizer = None
            try:
                self._player.set_equalizer(None)
            except Exception:
                pass
            LOG.warning("Could not apply VLC equalizer; continuing with flat playback: %s", exc)

    def _emit_state(self, state: str) -> None:
        if state != self._last_state:
            self._last_state = state
            self.state_changed.emit(state)

    def _poll(self) -> None:
        state = self._player.get_state()
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


def create_playback_backend(parent: Optional[QObject] = None) -> PlaybackBackend:
    """Create the preferred backend, falling back safely to Qt Multimedia."""
    _configure_vlc_runtime_path()
    if importlib.util.find_spec("vlc") is None:
        return QMediaPlaybackBackend(parent)

    try:
        vlc_module = importlib.import_module("vlc")
        return VlcPlaybackBackend(vlc_module, parent)
    except Exception as exc:
        LOG.warning("Falling back to Qt Multimedia because libVLC is unavailable: %s", exc)
        return QMediaPlaybackBackend(parent)

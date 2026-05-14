"""Video player tab using libVLC for full-featured video playback.

Exposes every useful libVLC capability that makes sense in a desktop UI:
- Hardware-accelerated video rendering embedded in a native Qt surface
- Play / pause / stop transport with real-time seek bar
- Per-media volume + mute (independent of the audio player)
- Variable playback rate (0.25× – 2×)
- Multi-track audio selection
- Subtitle track selection + external subtitle/closed-caption file loading
- One-click screenshot (PNG/JPEG) via libVLC's native snapshot API
- Fullscreen mode via a dedicated overlay window (avoids Qt reparenting issues)

Falls back to a friendly error screen when libVLC is not available.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QFrame, QHBoxLayout, QLabel,
    QPushButton, QSizePolicy, QSlider, QToolButton, QVBoxLayout, QWidget,
)

from ..core.playback_backend import _configure_vlc_runtime_path
from .widgets import format_ms

LOG = logging.getLogger(__name__)

VIDEO_EXTENSIONS = (
    ".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm",
    ".m4v", ".ts", ".vob", ".mpg", ".mpeg", ".3gp", ".ogv",
)

_RATE_OPTIONS: list[tuple[str, float]] = [
    ("0.25×", 0.25),
    ("0.5×",  0.50),
    ("0.75×", 0.75),
    ("1×",    1.00),
    ("1.25×", 1.25),
    ("1.5×",  1.50),
    ("2×",    2.00),
]
_DEFAULT_RATE_INDEX = 3  # 1×


def _track_id_and_name(desc: Any) -> tuple[int, str]:
    """Extract (id, name) from a libVLC TrackDescription object."""
    try:
        tid = int(desc.id)
        raw = desc.name
    except AttributeError:
        tid, raw = int(desc[0]), desc[1]
    name = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
    return tid, name


class _VideoSurface(QWidget):
    """Native-windowed widget used as the libVLC rendering surface."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        # WA_NativeWindow ensures winId() returns a real OS window handle that
        # libVLC can embed into rather than a synthetic Qt surface id.
        self.setAttribute(Qt.WA_NativeWindow, True)
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)
        self.setAutoFillBackground(False)
        self.setObjectName("videoSurface")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumSize(320, 180)


class _FullscreenWindow(QWidget):
    """Borderless fullscreen window used for VLC video output during fullscreen mode."""

    def __init__(self, on_exit_cb, on_toggle_play_cb) -> None:
        super().__init__(None, Qt.Window | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_NativeWindow, True)
        self.setStyleSheet("background:#000000;")
        self._on_exit = on_exit_cb
        self._on_toggle_play = on_toggle_play_cb

    def keyPressEvent(self, ev) -> None:
        if ev.key() == Qt.Key_Escape:
            self._on_exit()
            ev.accept()
        elif ev.key() == Qt.Key_Space:
            self._on_toggle_play()
            ev.accept()
        elif ev.key() == Qt.Key_F:
            self._on_exit()
            ev.accept()
        else:
            super().keyPressEvent(ev)

    def mouseDoubleClickEvent(self, ev) -> None:
        self._on_exit()
        super().mouseDoubleClickEvent(ev)


class VideoPlayerView(QWidget):
    """Full-featured libVLC video player tab."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        _configure_vlc_runtime_path()

        self._vlc: Any = None
        self._instance: Any = None
        self._player: Any = None
        self._available = False
        self._user_dragging = False
        self._current_path = ""
        self._fs_window: _FullscreenWindow | None = None

        try:
            import importlib
            vlc = importlib.import_module("vlc")
            self._vlc = vlc
            self._instance = vlc.Instance()
            self._player = self._instance.media_player_new()
            self._available = True
        except Exception as exc:
            LOG.warning("Video player: libVLC unavailable: %s", exc)

        if self._available:
            self._build_player_ui()
        else:
            self._build_unavailable_ui()

    # ---------------------------------------------------------------- UI build

    def _build_unavailable_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)

        title = QLabel("Video playback requires libVLC")
        f = title.font()
        f.setPointSize(14)
        f.setBold(True)
        title.setFont(f)
        title.setStyleSheet("color:#72f4ff;")
        title.setAlignment(Qt.AlignCenter)

        body = QLabel(
            "libVLC (python-vlc) is not available.\n\n"
            "Install VLC Media Player, then add python-vlc to your environment\n"
            "and restart the app."
        )
        body.setAlignment(Qt.AlignCenter)
        body.setStyleSheet("color:#cfd6e2;")

        layout.addStretch(1)
        layout.addWidget(title)
        layout.addWidget(body)
        layout.addStretch(1)

    def _build_player_ui(self) -> None:
        # ---- Toolbar -------------------------------------------------------
        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(10, 8, 10, 6)
        toolbar.setSpacing(8)

        self._open_btn = QPushButton("Open File...")
        self._open_btn.setObjectName("accent")
        self._open_btn.clicked.connect(self._open_file)

        self._info_lbl = QLabel("No file loaded")
        self._info_lbl.setStyleSheet("color:#aab3c0;")
        self._info_lbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        self._screenshot_btn = QPushButton("Screenshot")
        self._screenshot_btn.setEnabled(False)
        self._screenshot_btn.setToolTip("Save a snapshot of the current frame")
        self._screenshot_btn.clicked.connect(self._take_screenshot)

        self._fullscreen_btn = QPushButton("Fullscreen")
        self._fullscreen_btn.setEnabled(False)
        self._fullscreen_btn.setToolTip("Enter fullscreen (double-click video to exit)")
        self._fullscreen_btn.clicked.connect(self._enter_fullscreen)

        toolbar.addWidget(self._open_btn)
        toolbar.addWidget(self._info_lbl, 1)
        toolbar.addWidget(self._screenshot_btn)
        toolbar.addWidget(self._fullscreen_btn)

        # ---- Video surface -------------------------------------------------
        self._surface = _VideoSurface(self)
        self._surface.mouseDoubleClickEvent = lambda ev: self._enter_fullscreen()
        self._attach_vlc_to(self._surface)

        # ---- Controls frame ------------------------------------------------
        controls = QFrame()
        controls.setObjectName("videoControls")
        cl = QVBoxLayout(controls)
        cl.setContentsMargins(12, 6, 12, 8)
        cl.setSpacing(4)

        # Seek row
        self._elapsed_lbl = QLabel("0:00")
        self._elapsed_lbl.setObjectName("timeLabel")
        self._elapsed_lbl.setMinimumWidth(42)
        self._elapsed_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self._total_lbl = QLabel("0:00")
        self._total_lbl.setObjectName("timeLabel")
        self._total_lbl.setMinimumWidth(42)
        self._total_lbl.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        self._seek = QSlider(Qt.Horizontal)
        self._seek.setRange(0, 0)
        self._seek.sliderPressed.connect(lambda: setattr(self, "_user_dragging", True))
        self._seek.sliderReleased.connect(self._on_seek_release)

        seek_row = QHBoxLayout()
        seek_row.setContentsMargins(0, 0, 0, 0)
        seek_row.setSpacing(6)
        seek_row.addWidget(self._elapsed_lbl)
        seek_row.addWidget(self._seek, 1)
        seek_row.addWidget(self._total_lbl)

        # Transport + options row
        self._play_btn = self._make_transport_btn("▶")
        self._play_btn.setToolTip("Play / Pause  [Space]")
        self._play_btn.setCheckable(True)
        self._play_btn.clicked.connect(self._toggle_play)

        self._stop_btn = self._make_transport_btn("■")
        self._stop_btn.setToolTip("Stop")
        self._stop_btn.clicked.connect(self._stop)

        speed_lbl = self._ctrl_label("Speed:")
        self._rate_combo = QComboBox()
        for label, _ in _RATE_OPTIONS:
            self._rate_combo.addItem(label)
        self._rate_combo.setCurrentIndex(_DEFAULT_RATE_INDEX)
        self._rate_combo.setFixedWidth(68)
        self._rate_combo.setToolTip("Playback rate")
        self._rate_combo.currentIndexChanged.connect(self._on_rate_changed)

        audio_lbl = self._ctrl_label("Audio:")
        self._audio_combo = QComboBox()
        self._audio_combo.setMinimumWidth(130)
        self._audio_combo.setToolTip("Audio track")
        self._audio_combo.currentIndexChanged.connect(self._on_audio_track_changed)

        sub_lbl = self._ctrl_label("Subs:")
        self._sub_combo = QComboBox()
        self._sub_combo.setMinimumWidth(130)
        self._sub_combo.setToolTip("Subtitle track")
        self._sub_combo.currentIndexChanged.connect(self._on_sub_changed)

        self._sub_file_btn = QPushButton("Load Sub...")
        self._sub_file_btn.setEnabled(False)
        self._sub_file_btn.setToolTip("Load an external subtitle file (.srt, .ass, ...)")
        self._sub_file_btn.clicked.connect(self._load_sub_file)

        vol_lbl = QLabel("♬")
        vol_lbl.setObjectName("volumeIcon")
        self._vol_slider = QSlider(Qt.Horizontal)
        self._vol_slider.setObjectName("volumeSlider")
        self._vol_slider.setRange(0, 100)
        self._vol_slider.setValue(80)
        self._vol_slider.setFixedWidth(110)
        self._vol_slider.setToolTip("Volume")
        self._vol_slider.valueChanged.connect(self._on_volume_changed)
        self._player.audio_set_volume(80)

        self._mute_btn = self._make_transport_btn("M")
        self._mute_btn.setToolTip("Mute / Unmute")
        self._mute_btn.setCheckable(True)
        self._mute_btn.clicked.connect(self._on_mute_toggled)

        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(0, 0, 0, 0)
        btn_row.setSpacing(6)
        btn_row.addWidget(self._play_btn)
        btn_row.addWidget(self._stop_btn)
        btn_row.addSpacing(6)
        btn_row.addWidget(speed_lbl)
        btn_row.addWidget(self._rate_combo)
        btn_row.addSpacing(8)
        btn_row.addWidget(audio_lbl)
        btn_row.addWidget(self._audio_combo)
        btn_row.addSpacing(8)
        btn_row.addWidget(sub_lbl)
        btn_row.addWidget(self._sub_combo)
        btn_row.addWidget(self._sub_file_btn)
        btn_row.addStretch(1)
        btn_row.addWidget(vol_lbl)
        btn_row.addWidget(self._vol_slider)
        btn_row.addWidget(self._mute_btn)

        cl.addLayout(seek_row)
        cl.addLayout(btn_row)

        # ---- Main layout ---------------------------------------------------
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addLayout(toolbar)
        layout.addWidget(self._surface, 1)
        layout.addWidget(controls)

        # Poll timer – 150 ms keeps seek bar smooth without hammering the CPU
        self._timer = QTimer(self)
        self._timer.setInterval(150)
        self._timer.timeout.connect(self._poll)

        self._set_controls_enabled(False)

    # ---------------------------------------------------------------- helpers

    @staticmethod
    def _ctrl_label(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet("color:#aab3c0;")
        return lbl

    @staticmethod
    def _make_transport_btn(text: str) -> QToolButton:
        btn = QToolButton()
        btn.setText(text)
        btn.setObjectName("transportBtn")
        btn.setFixedSize(42, 40)
        return btn

    def _set_controls_enabled(self, enabled: bool) -> None:
        for w in (
            self._play_btn, self._stop_btn, self._rate_combo,
            self._audio_combo, self._sub_combo, self._sub_file_btn,
            self._screenshot_btn, self._fullscreen_btn,
            self._seek, self._vol_slider, self._mute_btn,
        ):
            w.setEnabled(enabled)

    def _attach_vlc_to(self, widget: QWidget) -> None:
        """Tell libVLC to render video into the given native widget."""
        wid = int(widget.winId())
        if sys.platform == "win32":
            self._player.set_hwnd(wid)
        elif sys.platform.startswith("linux"):
            self._player.set_xwindow(wid)
        else:
            self._player.set_nsobject(wid)

    def _populate_tracks(self) -> None:
        """Refresh audio and subtitle combo boxes from the active media."""
        # Audio tracks
        self._audio_combo.blockSignals(True)
        self._audio_combo.clear()
        try:
            descs = self._player.audio_get_track_description() or []
            current_audio = self._player.audio_get_track()
            for desc in descs:
                tid, name = _track_id_and_name(desc)
                self._audio_combo.addItem(name, tid)
            for i in range(self._audio_combo.count()):
                if self._audio_combo.itemData(i) == current_audio:
                    self._audio_combo.setCurrentIndex(i)
                    break
        except Exception as exc:
            LOG.debug("Could not list audio tracks: %s", exc)
        self._audio_combo.blockSignals(False)

        # Subtitle tracks
        self._sub_combo.blockSignals(True)
        self._sub_combo.clear()
        try:
            spu_descs = self._player.video_get_spu_description() or []
            current_spu = self._player.video_get_spu()
            for desc in spu_descs:
                tid, name = _track_id_and_name(desc)
                self._sub_combo.addItem(name, tid)
            for i in range(self._sub_combo.count()):
                if self._sub_combo.itemData(i) == current_spu:
                    self._sub_combo.setCurrentIndex(i)
                    break
        except Exception as exc:
            LOG.debug("Could not list subtitle tracks: %s", exc)
        self._sub_combo.blockSignals(False)

    def _update_video_info(self) -> None:
        """Append resolution to the info label once the media has been parsed."""
        try:
            w, h = self._player.video_get_size(0)
            if w and h:
                base = self._info_lbl.text().split("  [")[0]
                self._info_lbl.setText(f"{base}  [{w}×{h}]")
        except Exception:
            pass

    # ---------------------------------------------------------------- file open

    def _open_file(self) -> None:
        ext_filter = "Video Files ({});;All Files (*)".format(
            " ".join(f"*{e}" for e in VIDEO_EXTENSIONS)
        )
        path, _ = QFileDialog.getOpenFileName(self, "Open Video File", "", ext_filter)
        if path:
            self._load_path(path)

    def _load_path(self, path: str) -> None:
        self._current_path = path
        media = self._instance.media_new_path(path)
        self._player.set_media(media)
        self._player.audio_set_volume(self._vol_slider.value())
        self._info_lbl.setText(Path(path).name)
        self._set_controls_enabled(True)
        self._player.play()
        self._play_btn.setChecked(True)
        self._play_btn.setText("||")
        self._timer.start()
        # Track lists and resolution are only available after the media parses
        QTimer.singleShot(600, self._populate_tracks)
        QTimer.singleShot(900, self._update_video_info)

    # ---------------------------------------------------------------- transport

    def _toggle_play(self) -> None:
        if not self._current_path:
            self._play_btn.setChecked(False)
            return
        if self._player.is_playing():
            self._player.pause()
            self._play_btn.setText("▶")
            self._play_btn.setChecked(False)
        else:
            self._player.play()
            self._timer.start()
            self._play_btn.setText("||")
            self._play_btn.setChecked(True)

    def _stop(self) -> None:
        self._player.stop()
        self._timer.stop()
        self._play_btn.setText("▶")
        self._play_btn.setChecked(False)
        self._seek.blockSignals(True)
        self._seek.setValue(0)
        self._seek.blockSignals(False)
        self._elapsed_lbl.setText("0:00")

    def _on_seek_release(self) -> None:
        if self._player.get_length() > 0:
            self._player.set_time(self._seek.value())
        self._user_dragging = False

    def _on_volume_changed(self, value: int) -> None:
        self._player.audio_set_volume(value)

    def _on_mute_toggled(self, checked: bool) -> None:
        self._player.audio_set_mute(checked)
        self._mute_btn.setText("--" if checked else "M")

    def _on_rate_changed(self, index: int) -> None:
        _, rate = _RATE_OPTIONS[index]
        try:
            self._player.set_rate(rate)
        except Exception as exc:
            LOG.debug("Could not set playback rate: %s", exc)

    def _on_audio_track_changed(self, index: int) -> None:
        tid = self._audio_combo.itemData(index)
        if tid is not None:
            try:
                self._player.audio_set_track(int(tid))
            except Exception as exc:
                LOG.debug("Could not set audio track: %s", exc)

    def _on_sub_changed(self, index: int) -> None:
        tid = self._sub_combo.itemData(index)
        if tid is not None:
            try:
                self._player.video_set_spu(int(tid))
            except Exception as exc:
                LOG.debug("Could not set subtitle track: %s", exc)

    def _load_sub_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Load Subtitle File", "",
            "Subtitle Files (*.srt *.ass *.ssa *.sub *.vtt *.idx);;All Files (*)",
        )
        if not path:
            return
        try:
            if hasattr(self._player, "add_slave"):
                self._player.add_slave(
                    self._vlc.MediaSlaveType.Subtitle,
                    Path(path).as_uri(),
                    True,
                )
            else:
                self._player.video_set_subtitle_file(path)
            QTimer.singleShot(300, self._populate_tracks)
        except Exception as exc:
            LOG.warning("Could not load subtitle file %s: %s", path, exc)

    # ---------------------------------------------------------------- screenshot

    def _take_screenshot(self) -> None:
        if not self._current_path:
            return
        stem = Path(self._current_path).stem
        default = str(Path.home() / f"{stem}_snapshot.png")
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Screenshot", default, "Images (*.png *.jpg)"
        )
        if not path:
            return
        try:
            # video_take_snapshot(num_video_output, path, width=0, height=0)
            # width=0 / height=0 means "keep original size"
            self._player.video_take_snapshot(0, path, 0, 0)
        except Exception as exc:
            LOG.warning("Screenshot failed: %s", exc)

    # ---------------------------------------------------------------- fullscreen

    def _enter_fullscreen(self) -> None:
        if not self._available or not self._player.get_media():
            return
        if self._fs_window is not None:
            return  # already fullscreen

        self._fs_window = _FullscreenWindow(
            on_exit_cb=self._exit_fullscreen,
            on_toggle_play_cb=self._toggle_play,
        )
        self._fs_window.showFullScreen()
        self._fs_window.raise_()
        self._fs_window.activateWindow()
        # Defer winId capture until the OS window is actually realized
        QTimer.singleShot(50, self._attach_vlc_to_fullscreen_window)
        self._fullscreen_btn.setText("Exit Fullscreen")

    def _attach_vlc_to_fullscreen_window(self) -> None:
        if self._fs_window is None:
            return
        self._attach_vlc_to(self._fs_window)

    def _exit_fullscreen(self) -> None:
        if self._fs_window is None:
            return
        self._fs_window.close()
        self._fs_window = None
        self._fullscreen_btn.setText("Fullscreen")
        # Re-attach rendering to the embedded surface after a tick so the
        # native surface window is front-most in the OS compositor again.
        QTimer.singleShot(50, lambda: self._attach_vlc_to(self._surface))

    # ---------------------------------------------------------------- polling

    def _poll(self) -> None:
        try:
            state = self._player.get_state()
            if state == self._vlc.State.Ended:
                self._on_ended()
                return

            pos = max(0, int(self._player.get_time()))
            dur = max(0, int(self._player.get_length()))

            if not self._user_dragging:
                self._seek.blockSignals(True)
                self._seek.setRange(0, max(0, dur))
                self._seek.setValue(pos)
                self._seek.blockSignals(False)

            self._elapsed_lbl.setText(format_ms(pos))
            self._total_lbl.setText(format_ms(dur))

            is_playing = bool(self._player.is_playing())
            self._play_btn.setChecked(is_playing)
            self._play_btn.setText("||" if is_playing else "▶")
        except Exception as exc:
            LOG.debug("Video poll error: %s", exc)

    def _on_ended(self) -> None:
        self._timer.stop()
        self._play_btn.setText("▶")
        self._play_btn.setChecked(False)
        self._seek.blockSignals(True)
        dur = max(0, int(self._player.get_length()))
        self._seek.setValue(dur)
        self._seek.blockSignals(False)

    # ---------------------------------------------------------------- lifecycle

    def pause_playback(self) -> None:
        """Pause video when the user navigates away from this tab."""
        if self._available and self._player and self._player.is_playing():
            self._player.pause()
            self._play_btn.setText("▶")
            self._play_btn.setChecked(False)

    def keyPressEvent(self, ev) -> None:
        if not self._available:
            super().keyPressEvent(ev)
            return
        if ev.key() == Qt.Key_Space:
            self._toggle_play()
            ev.accept()
        elif ev.key() == Qt.Key_F:
            if self._fs_window:
                self._exit_fullscreen()
            else:
                self._enter_fullscreen()
            ev.accept()
        else:
            super().keyPressEvent(ev)

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
- Collapsible video catalog sidebar with thumbnail cards (toggle with ◀/▶ Library button)

Falls back to a friendly error screen when libVLC is not available.
"""
from __future__ import annotations

import logging
import sqlite3
import sys
from pathlib import Path
from typing import Any

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QApplication, QComboBox, QFileDialog, QFrame, QHBoxLayout, QInputDialog,
    QLabel, QLineEdit, QMessageBox, QPushButton, QScrollArea, QSizePolicy,
    QSlider, QStackedWidget, QVBoxLayout, QWidget,
)

from ..core.playback_backend import _configure_vlc_runtime_path
from ..core.settings import Settings, normalize_stream_urls
from ..core.vlc_equalizer import EQ_FADE_INTERVAL_MS, VlcEqualizerController
from .osd import OSDOverlay
from .transport import PlayPauseSideButton, StopButton, VolumeButton
from .widgets import ElidedLabel, format_duration, format_ms, placeholder_cover

LOG = logging.getLogger(__name__)

_VIDEO_OUTPUT_SETTLE_MS = 80
_VIDEO_OUTPUT_SECOND_SETTLE_MS = 240
_RESUME_PROMPT_MIN_MS = 10_000
_RESUME_CLEAR_REMAINING_MS = 10_000
_SUBTITLE_DELAY_STEP_US = 50_000

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

_SIDEBAR_WIDTH = 234
_CATALOG_BATCH_SIZE = 40
_THUMB_CACHE_MAX = 512
_THUMB_CACHE: dict[tuple[Any, ...], QPixmap] = {}


def _track_id_and_name(desc: Any) -> tuple[int, str]:
    """Extract (id, name) from a libVLC TrackDescription object."""
    try:
        tid = int(desc.id)
        raw = desc.name
    except AttributeError:
        tid, raw = int(desc[0]), desc[1]
    name = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
    return tid, name


def _scale_to_fill(pm: QPixmap, w: int, h: int) -> QPixmap:
    """Scale pixmap to exactly w×h, cropping to centre."""
    pm = pm.scaled(w, h, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
    if pm.width() > w or pm.height() > h:
        x = (pm.width() - w) // 2
        y = (pm.height() - h) // 2
        pm = pm.copy(x, y, w, h)
    return pm


def _thumb_pixmap(artwork_path: str | None, file_path: str = "",
                  w: int = 96, h: int = 54) -> QPixmap:
    """Return a w×h thumbnail, also checking for yt-dlp side-car images."""
    sources: list[str] = []
    if artwork_path:
        sources.append(artwork_path)
    # yt-dlp saves thumbnails as <stem>.jpg / .webp next to the video file
    if file_path:
        stem = Path(file_path).stem
        parent = Path(file_path).parent
        for ext in (".jpg", ".jpeg", ".webp", ".png"):
            p = parent / (stem + ext)
            if p.exists():
                sources.append(str(p))
                break
    cache_key = (
        artwork_path,
        file_path,
        w,
        h,
        tuple(_thumb_source_state(s) for s in sources),
    )
    cached = _THUMB_CACHE.get(cache_key)
    if cached is not None:
        return QPixmap(cached)

    for src in sources:
        pm = QPixmap(src)
        if not pm.isNull():
            out = _scale_to_fill(pm, w, h)
            _cache_thumb(cache_key, out)
            return QPixmap(out)
    pm = placeholder_cover(max(w, h), "▶")
    out = pm.scaled(w, h, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    _cache_thumb(cache_key, out)
    return QPixmap(out)


def _thumb_source_state(src: str) -> tuple[str, int, int]:
    try:
        stat = Path(src).stat()
    except OSError:
        return (src, -1, -1)
    return (src, int(stat.st_mtime_ns), int(stat.st_size))


def _cache_thumb(key: tuple[Any, ...], pixmap: QPixmap) -> None:
    if len(_THUMB_CACHE) >= _THUMB_CACHE_MAX:
        _THUMB_CACHE.pop(next(iter(_THUMB_CACHE)))
    _THUMB_CACHE[key] = QPixmap(pixmap)


# ---------------------------------------------------------------------------
# Catalog sidebar card
# ---------------------------------------------------------------------------

def _video_card_signature(track: Any) -> tuple[Any, ...]:
    sources: list[str] = []
    artwork_path = track.artwork_path or None
    if artwork_path:
        sources.append(artwork_path)
    parent = Path(track.path).parent
    stem = Path(track.path).stem
    for ext in (".jpg", ".jpeg", ".webp", ".png"):
        sidecar = parent / (stem + ext)
        if sidecar.exists():
            sources.append(str(sidecar))
            break
    return (
        track.path,
        track.title or Path(track.path).stem,
        float(track.duration or 0.0),
        track.artwork_path or None,
        tuple(_thumb_source_state(src) for src in sources),
    )


class _VideoCard(QFrame):
    """Clickable thumbnail card representing one catalogued video."""

    load_requested = Signal(str)

    def __init__(self, track: Any, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._path = track.path
        self._signature = _video_card_signature(track)
        self._search_key = (track.title or Path(track.path).stem).lower()
        self.setObjectName("videoCard")
        self.setCursor(Qt.PointingHandCursor)

        title = track.title or Path(track.path).stem
        dur = format_duration(track.duration) if track.duration else ""
        self.setToolTip(f"{title}\n{dur}" if dur else title)

        row = QHBoxLayout(self)
        row.setContentsMargins(6, 4, 6, 4)
        row.setSpacing(8)

        thumb = QLabel()
        thumb.setObjectName("videoCardThumb")
        thumb.setFixedSize(96, 54)
        thumb.setAlignment(Qt.AlignCenter)
        thumb.setPixmap(_thumb_pixmap(track.artwork_path, track.path, 96, 54))
        row.addWidget(thumb)

        info = QVBoxLayout()
        info.setContentsMargins(0, 0, 0, 0)
        info.setSpacing(1)

        title_lbl = ElidedLabel(title)
        title_lbl.setObjectName("videoCardTitle")

        dur_lbl = QLabel(dur or "—")
        dur_lbl.setObjectName("videoCardDuration")

        info.addStretch()
        info.addWidget(title_lbl)
        info.addWidget(dur_lbl)
        info.addStretch()
        row.addLayout(info, 1)

    @property
    def path(self) -> str:
        return self._path

    @property
    def signature(self) -> tuple[Any, ...]:
        return self._signature

    def matches(self, query: str) -> bool:
        return not query or query in self._search_key

    def mousePressEvent(self, ev) -> None:
        if ev.button() == Qt.LeftButton:
            self.load_requested.emit(self._path)
        super().mousePressEvent(ev)


# ---------------------------------------------------------------------------
# VLC surface widgets
# ---------------------------------------------------------------------------

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

    def __init__(
        self,
        on_exit_cb,
        on_toggle_play_cb,
        on_seek_relative_cb=None,
        on_volume_step_cb=None,
        on_mute_toggle_cb=None,
    ) -> None:
        super().__init__(None, Qt.Window | Qt.FramelessWindowHint)
        self.setObjectName("videoFullscreenWindow")
        self._on_exit = on_exit_cb
        self._on_toggle_play = on_toggle_play_cb
        self._on_seek_relative = on_seek_relative_cb
        self._on_volume_step = on_volume_step_cb
        self._on_mute_toggle = on_mute_toggle_cb

        # VLC must render into a *child* native sub-window, not into this
        # top-level window directly.  Qt's backing-store blit targets the
        # top-level X11 window on every repaint and would overwrite VLC's
        # frames.  A WA_NativeWindow child gets its own XID that the backing
        # store never touches, matching how the embedded _VideoSurface works.
        self._vlc_surface = _VideoSurface(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._vlc_surface)

        self._single_click_timer = QTimer(self)
        self._single_click_timer.setSingleShot(True)
        self._single_click_timer.setInterval(QApplication.doubleClickInterval())
        self._single_click_timer.timeout.connect(self._on_toggle_play)

    def keyPressEvent(self, ev) -> None:
        key = ev.key()
        mod = ev.modifiers()
        if key in (Qt.Key_Escape, Qt.Key_F):
            self._on_exit()
        elif key == Qt.Key_Space:
            self._on_toggle_play()
        elif key == Qt.Key_Left and self._on_seek_relative:
            self._on_seek_relative(-30_000 if mod & Qt.ShiftModifier else -5_000)
        elif key == Qt.Key_Right and self._on_seek_relative:
            self._on_seek_relative(30_000 if mod & Qt.ShiftModifier else 5_000)
        elif key == Qt.Key_Up and self._on_volume_step:
            self._on_volume_step(5)
        elif key == Qt.Key_Down and self._on_volume_step:
            self._on_volume_step(-5)
        elif key == Qt.Key_M and self._on_mute_toggle:
            self._on_mute_toggle()
        else:
            super().keyPressEvent(ev)
            return
        ev.accept()

    def mousePressEvent(self, ev) -> None:
        if ev.button() == Qt.LeftButton:
            # Defer the single-click action until Qt's double-click interval has
            # passed so a double-click exits fullscreen without also toggling
            # playback on the first press.
            self._single_click_timer.start()
            ev.accept()
            return
        super().mousePressEvent(ev)

    def mouseDoubleClickEvent(self, ev) -> None:
        if ev.button() == Qt.LeftButton:
            self._single_click_timer.stop()
            self._on_exit()
            ev.accept()
            return
        super().mouseDoubleClickEvent(ev)


# ---------------------------------------------------------------------------
# Splash pane (default background when no video is loaded)
# ---------------------------------------------------------------------------

class _SplashPane(QLabel):
    """Centered Lyon splash shown in the video area when no video is playing."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("videoSplash")
        self.setAlignment(Qt.AlignCenter)
        from .branding import startup_splash_pixmap
        pm = startup_splash_pixmap()
        self._source: QPixmap | None = pm if not pm.isNull() else None

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._source:
            max_w = max(1, int(self.width() * 0.62))
            max_h = max(1, int(self.height() * 0.62))
            pm = self._source.scaled(max_w, max_h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.setPixmap(pm)


# ---------------------------------------------------------------------------
# Main view
# ---------------------------------------------------------------------------

class VideoPlayerView(QWidget):
    """Full-featured libVLC video player tab with collapsible catalog sidebar."""

    request_diagnostics = Signal()
    resume_available = Signal(str, object)  # message, callback

    def __init__(
        self,
        library: Any = None,
        parent: QWidget | None = None,
        initial_volume: int = 80,
        settings: Settings | None = None,
    ):
        super().__init__(parent)
        self._library = library
        self._settings = settings
        self._initial_volume = max(0, min(100, int(initial_volume)))
        _configure_vlc_runtime_path()

        self._vlc: Any = None
        self._instance: Any = None
        self._player: Any = None
        self._available = False
        self._unavailable_reason = ""
        self._user_dragging = False
        self._current_path = ""
        self._fs_window: _FullscreenWindow | None = None
        self._surface_attached = False  # deferred until first showEvent
        self._osd: OSDOverlay | None = None
        self._eq_enabled = False
        self._eq_bands: list[int] = []
        self._eq_preamp: int = 0
        self._eq_controller: VlcEqualizerController | None = None
        self._catalog_pending_tracks: list[Any] = []
        self._catalog_total = 0
        self._catalog_card_by_path: dict[str, _VideoCard] = {}
        self._video_output_generation = 0
        self._current_track_id: int | None = None
        self._current_is_location = False
        self._subtitle_delay_us = 0

        self._eq_fade_timer = QTimer(self)
        self._eq_fade_timer.setInterval(EQ_FADE_INTERVAL_MS)
        self._eq_fade_timer.timeout.connect(self._eq_fade_step)
        self._catalog_build_timer = QTimer(self)
        self._catalog_build_timer.setInterval(0)
        self._catalog_build_timer.timeout.connect(self._append_catalog_batch)

        try:
            import importlib
            vlc = importlib.import_module("vlc")
            self._vlc = vlc
            self._instance = vlc.Instance()
            self._player = self._instance.media_player_new()
            self._eq_controller = VlcEqualizerController(
                vlc,
                self._player,
                context="video VLC equalizer",
            )
            self._available = True
        except Exception as exc:
            self._unavailable_reason = str(exc)
            LOG.warning("Video player: libVLC unavailable: %s", exc)

        if self._available:
            self._build_player_ui()
            self._osd = OSDOverlay()
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
        title.setObjectName("sectionTitle")
        title.setAlignment(Qt.AlignCenter)

        body = QLabel(
            "libVLC (python-vlc) is not available.\n\n"
            "Install VLC Media Player, then add python-vlc to your environment\n"
            "and restart the app."
        )
        body.setAlignment(Qt.AlignCenter)
        body.setObjectName("mutedText")

        diag_btn = QPushButton("Run Diagnostics")
        diag_btn.setToolTip("Open the diagnostics panel to verify your runtime environment")
        diag_btn.clicked.connect(self.request_diagnostics.emit)

        layout.addStretch(1)
        layout.addWidget(title)
        layout.addWidget(body)
        layout.addSpacing(16)
        layout.addWidget(diag_btn, alignment=Qt.AlignCenter)
        layout.addStretch(1)

    def _build_player_ui(self) -> None:
        self.setObjectName("videoPlayerView")
        # ---- Toolbar -------------------------------------------------------
        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(10, 8, 10, 6)
        toolbar.setSpacing(8)

        self._open_btn = QPushButton("Open File...")
        self._open_btn.setObjectName("accent")
        self._open_btn.clicked.connect(self._open_file)

        self._open_url_btn = QPushButton("Open URL...")
        self._open_url_btn.setToolTip("Open a network video stream")
        self._open_url_btn.clicked.connect(self._open_url)

        self._info_lbl = QLabel("No file loaded")
        self._info_lbl.setObjectName("mutedText")
        self._info_lbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        self._screenshot_btn = QPushButton("Screenshot")
        self._screenshot_btn.setEnabled(False)
        self._screenshot_btn.setToolTip("Save a snapshot of the current frame")
        self._screenshot_btn.clicked.connect(self._take_screenshot)

        self._fullscreen_btn = QPushButton("Fullscreen")
        self._fullscreen_btn.setEnabled(False)
        self._fullscreen_btn.setToolTip("Enter fullscreen (double-click video to exit)")
        self._fullscreen_btn.clicked.connect(self._enter_fullscreen)

        self._sidebar_btn = QPushButton("◀ Library")
        self._sidebar_btn.setCheckable(True)
        self._sidebar_btn.setChecked(True)
        self._sidebar_btn.setToolTip("Show / hide video catalog  [Ctrl+B]")
        self._sidebar_btn.setAccessibleName("Toggle video library sidebar")
        self._sidebar_btn.clicked.connect(self._toggle_sidebar)

        toolbar.addWidget(self._open_btn)
        toolbar.addWidget(self._open_url_btn)
        toolbar.addWidget(self._info_lbl, 1)
        toolbar.addWidget(self._screenshot_btn)
        toolbar.addWidget(self._fullscreen_btn)
        toolbar.addWidget(self._sidebar_btn)

        # ---- Video surface + splash stack ----------------------------------
        self._surface = _VideoSurface(self)
        self._surface.mouseDoubleClickEvent = lambda ev: self._enter_fullscreen()

        self._splash_pane = _SplashPane()

        self._video_stack = QStackedWidget()
        self._video_stack.addWidget(self._splash_pane)  # index 0 – no video
        self._video_stack.addWidget(self._surface)       # index 1 – VLC output
        self._video_stack.setCurrentIndex(0)

        # ---- Controls frame ------------------------------------------------
        controls = QFrame()
        controls.setObjectName("videoControls")
        cl = QVBoxLayout(controls)
        cl.setContentsMargins(12, 6, 12, 8)
        cl.setSpacing(8)

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
        self._seek.setAccessibleName("Video seek position")
        self._seek.sliderPressed.connect(lambda: setattr(self, "_user_dragging", True))
        self._seek.sliderReleased.connect(self._on_seek_release)

        seek_row = QHBoxLayout()
        seek_row.setContentsMargins(0, 0, 0, 0)
        seek_row.setSpacing(6)
        seek_row.addWidget(self._elapsed_lbl)
        seek_row.addWidget(self._seek, 1)
        seek_row.addWidget(self._total_lbl)

        # Primary transport row: play / stop / volume
        self._play_btn = PlayPauseSideButton()
        self._play_btn.clicked.connect(self._toggle_play)

        self._stop_btn = StopButton()
        self._stop_btn.clicked.connect(self._stop)

        self._vol_slider = QSlider(Qt.Horizontal)
        self._vol_slider.setObjectName("volumeSlider")
        self._vol_slider.setRange(0, 100)
        self._vol_slider.setValue(self._initial_volume)
        self._vol_slider.setFixedWidth(110)
        self._vol_slider.setAccessibleName("Volume")
        self._vol_slider.setToolTip("Volume")
        self._vol_slider.valueChanged.connect(self._on_volume_changed)
        self._player.audio_set_volume(self._initial_volume)

        self._mute_btn = VolumeButton()
        self._mute_btn.set_state(self._initial_volume, False)
        self._mute_btn.toggled.connect(self._on_mute_toggled)

        transport_row = QHBoxLayout()
        transport_row.setContentsMargins(0, 0, 0, 0)
        transport_row.setSpacing(6)
        transport_row.addWidget(self._play_btn)
        transport_row.addWidget(self._stop_btn)
        transport_row.addStretch(1)
        transport_row.addWidget(self._mute_btn)
        transport_row.addWidget(self._vol_slider)

        # Secondary options row: speed / audio track / subtitle track
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

        self._sub_delay_minus = QPushButton("-50 ms")
        self._sub_delay_minus.setToolTip("Move subtitles earlier")
        self._sub_delay_minus.clicked.connect(lambda: self._step_subtitle_delay(-_SUBTITLE_DELAY_STEP_US))

        self._sub_delay_label = QLabel("0 ms")
        self._sub_delay_label.setObjectName("mutedText")
        self._sub_delay_label.setMinimumWidth(54)
        self._sub_delay_label.setAlignment(Qt.AlignCenter)

        self._sub_delay_plus = QPushButton("+50 ms")
        self._sub_delay_plus.setToolTip("Move subtitles later")
        self._sub_delay_plus.clicked.connect(lambda: self._step_subtitle_delay(_SUBTITLE_DELAY_STEP_US))

        opts_row = QHBoxLayout()
        opts_row.setContentsMargins(0, 2, 0, 0)
        opts_row.setSpacing(6)
        opts_row.addWidget(speed_lbl)
        opts_row.addWidget(self._rate_combo)
        opts_row.addSpacing(12)
        opts_row.addWidget(audio_lbl)
        opts_row.addWidget(self._audio_combo)
        opts_row.addSpacing(12)
        opts_row.addWidget(sub_lbl)
        opts_row.addWidget(self._sub_combo)
        opts_row.addWidget(self._sub_file_btn)
        opts_row.addSpacing(12)
        opts_row.addWidget(self._ctrl_label("Delay:"))
        opts_row.addWidget(self._sub_delay_minus)
        opts_row.addWidget(self._sub_delay_label)
        opts_row.addWidget(self._sub_delay_plus)
        opts_row.addStretch(1)

        cl.addLayout(seek_row)
        cl.addLayout(transport_row)
        cl.addLayout(opts_row)

        # ---- Sidebar + video surface (side by side) -------------------------
        self._sidebar = self._build_sidebar()

        self._sidebar_sep = QFrame()
        self._sidebar_sep.setObjectName("videoSidebarSeparator")
        self._sidebar_sep.setFrameShape(QFrame.VLine)
        self._sidebar_sep.setFixedWidth(1)

        content = QWidget()
        content_row = QHBoxLayout(content)
        content_row.setContentsMargins(0, 0, 0, 0)
        content_row.setSpacing(0)
        content_row.addWidget(self._sidebar)
        content_row.addWidget(self._sidebar_sep)
        content_row.addWidget(self._video_stack, 1)

        # ---- Main layout ---------------------------------------------------
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addLayout(toolbar)
        layout.addWidget(content, 1)
        layout.addWidget(controls)

        # Poll timer – 150 ms keeps seek bar smooth without hammering the CPU
        self._timer = QTimer(self)
        self._timer.setInterval(150)
        self._timer.timeout.connect(self._poll)

        self._set_controls_enabled(False)

        if self._library is not None:
            QTimer.singleShot(0, self.refresh_catalog)

    def _build_sidebar(self) -> QFrame:
        sidebar = QFrame()
        sidebar.setObjectName("videoCatalogSidebar")
        sidebar.setFixedWidth(_SIDEBAR_WIDTH)

        sl = QVBoxLayout(sidebar)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(0)

        # Header
        header = QFrame()
        header.setObjectName("videoCatalogHeader")
        hl = QHBoxLayout(header)
        hl.setContentsMargins(10, 8, 10, 6)
        hl.setSpacing(4)
        lib_lbl = QLabel("Video Library")
        lib_lbl.setObjectName("videoCatalogTitle")
        self._catalog_count_lbl = QLabel("")
        self._catalog_count_lbl.setObjectName("videoCatalogCount")
        hl.addWidget(lib_lbl)
        hl.addStretch()
        hl.addWidget(self._catalog_count_lbl)

        # Search bar
        search_row = QFrame()
        search_row.setObjectName("videoCatalogSearchRow")
        swl = QHBoxLayout(search_row)
        swl.setContentsMargins(8, 5, 8, 4)
        self._catalog_search = QLineEdit()
        self._catalog_search.setPlaceholderText("Search videos…")
        self._catalog_search.setAccessibleName("Video catalog search")
        self._catalog_search.textChanged.connect(self._filter_catalog)
        swl.addWidget(self._catalog_search)

        # Scrollable card list
        scroll = QScrollArea()
        scroll.setObjectName("videoCatalogScroll")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.NoFrame)

        self._catalog_container = QWidget()
        self._catalog_container.setObjectName("videoCatalogContainer")
        self._catalog_layout = QVBoxLayout(self._catalog_container)
        self._catalog_layout.setContentsMargins(6, 6, 6, 6)
        self._catalog_layout.setSpacing(3)
        self._catalog_layout.addStretch()

        self._catalog_cards: list[_VideoCard] = []

        scroll.setWidget(self._catalog_container)

        sl.addWidget(header)
        sl.addWidget(search_row)
        sl.addWidget(scroll, 1)

        return sidebar

    # ---------------------------------------------------------------- catalog

    def refresh_catalog(self) -> None:
        """Reload video catalog from the library database."""
        if self._library is None or not hasattr(self, "_catalog_layout"):
            return
        self._catalog_build_timer.stop()

        try:
            all_videos = list(self._library.all_tracks(media_type="video"))
        except sqlite3.ProgrammingError:
            LOG.debug("Skipping video catalog refresh because the library is closed.")
            return
        missing_ids = {t.id for t in all_videos if not Path(t.path).exists()}
        for track_id in missing_ids:
            self._library.delete_track(track_id)

        desired_tracks = [t for t in all_videos if t.id not in missing_ids]
        desired_by_path = {track.path: track for track in desired_tracks}
        desired_signatures = {
            path: _video_card_signature(track)
            for path, track in desired_by_path.items()
        }

        replacement_paths: set[str] = set()
        for path, card in list(self._catalog_card_by_path.items()):
            if path not in desired_signatures:
                self._catalog_layout.removeWidget(card)
                card.deleteLater()
                self._catalog_card_by_path.pop(path, None)
            elif card.signature != desired_signatures[path]:
                self._catalog_layout.removeWidget(card)
                card.deleteLater()
                self._catalog_card_by_path.pop(path, None)
                replacement_paths.add(path)

        self._catalog_cards = [
            card for card in self._catalog_cards
            if card.path in self._catalog_card_by_path
        ]

        if replacement_paths:
            query = self._catalog_search.text().strip().lower()
            insert_idx = 0
            for track in desired_tracks:
                if track.path in self._catalog_card_by_path:
                    insert_idx += 1
                elif track.path in replacement_paths:
                    card = _VideoCard(track)
                    card.load_requested.connect(self.load_path)
                    self._catalog_layout.insertWidget(insert_idx, card)
                    self._catalog_cards.insert(insert_idx, card)
                    self._catalog_card_by_path[track.path] = card
                    if query and not card.matches(query):
                        card.hide()
                    insert_idx += 1

        self._catalog_pending_tracks = [
            track for track in desired_tracks
            if track.path not in self._catalog_card_by_path
        ]
        self._catalog_total = len(desired_tracks)
        self._update_catalog_count()
        self._append_catalog_batch()
        if self._catalog_pending_tracks:
            self._catalog_build_timer.start()

    def _append_catalog_batch(self) -> None:
        """Append a small batch of video cards to keep large libraries responsive."""
        if not hasattr(self, "_catalog_layout"):
            return
        query = self._catalog_search.text().strip().lower()
        batch = self._catalog_pending_tracks[:_CATALOG_BATCH_SIZE]
        del self._catalog_pending_tracks[:_CATALOG_BATCH_SIZE]

        for track in batch:
            card = _VideoCard(track)
            card.load_requested.connect(self.load_path)
            # Catalog is ordered by tracks.id (see Library.all_tracks); genuinely new
            # videos always have a higher id than existing cards, so appending before
            # the trailing stretch keeps the catalog correctly sorted.
            self._catalog_layout.insertWidget(self._catalog_layout.count() - 1, card)
            self._catalog_cards.append(card)
            self._catalog_card_by_path[track.path] = card
            if query and not card.matches(query):
                card.hide()

        self._update_catalog_count()
        if not self._catalog_pending_tracks:
            self._catalog_build_timer.stop()

    def _filter_catalog(self, text: str) -> None:
        query = text.strip().lower()
        for card in self._catalog_cards:
            show = card.matches(query)
            card.setVisible(show)
        self._update_catalog_count()

    def _update_catalog_count(self) -> None:
        query = self._catalog_search.text().strip().lower()
        visible = sum(1 for c in self._catalog_cards if not c.isHidden())
        total = self._catalog_total
        if query:
            suffix = "…" if self._catalog_pending_tracks else ""
            self._catalog_count_lbl.setText(f"{visible}/{total}{suffix}")
        else:
            suffix = "…" if self._catalog_pending_tracks else ""
            self._catalog_count_lbl.setText(f"{total} video{'s' if total != 1 else ''}{suffix}")

    def _toggle_sidebar(self, checked: bool) -> None:
        self._sidebar.setVisible(checked)
        self._sidebar_sep.setVisible(checked)
        self._sidebar_btn.setText("◀ Library" if checked else "▶ Library")

    # ---------------------------------------------------------------- helpers

    @staticmethod
    def _ctrl_label(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setObjectName("mutedText")
        return lbl

    def _set_controls_enabled(self, enabled: bool) -> None:
        for w in (
            self._play_btn, self._stop_btn, self._rate_combo,
            self._audio_combo, self._sub_combo, self._sub_file_btn,
            self._screenshot_btn, self._fullscreen_btn,
            self._seek, self._vol_slider, self._mute_btn,
            self._sub_delay_minus, self._sub_delay_plus,
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

    def _handoff_vlc_output_to(
        self,
        widget: QWidget,
        resume: bool,
        position_ms: int | None = None,
    ) -> None:
        """Move VLC output to a new native widget and rebuild the video output."""
        if not self._available or self._player is None or not self._player.get_media():
            return

        self._video_output_generation += 1
        generation = self._video_output_generation
        if position_ms is None:
            position_ms = self._safe_player_time()

        rate = _RATE_OPTIONS[self._rate_combo.currentIndex()][1]
        audio_track = self._safe_audio_track()
        subtitle_track = self._safe_subtitle_track()

        try:
            self._player.stop()
        except Exception as exc:
            LOG.debug("Could not stop VLC before video output handoff: %s", exc)

        self._attach_vlc_to(widget)
        self._restore_audio_output_state()

        if self._eq_controller is not None:
            self._eq_controller.attach_to_player()

        self._player.play()
        self._timer.start()
        self._play_btn.set_playing(True)

        QTimer.singleShot(
            _VIDEO_OUTPUT_SETTLE_MS,
            lambda: self._restore_vlc_playback_state(
                generation,
                position_ms or 0,
                rate,
                audio_track,
                subtitle_track,
                resume,
            ),
        )
        QTimer.singleShot(
            _VIDEO_OUTPUT_SECOND_SETTLE_MS,
            lambda: self._restore_vlc_position(generation, position_ms or 0),
        )

    def _safe_player_time(self) -> int:
        try:
            return max(0, int(self._player.get_time()))
        except Exception:
            return 0

    def _safe_audio_track(self) -> int | None:
        try:
            return int(self._player.audio_get_track())
        except Exception:
            return None

    def _safe_subtitle_track(self) -> int | None:
        try:
            return int(self._player.video_get_spu())
        except Exception:
            return None

    def _restore_audio_output_state(self) -> None:
        try:
            self._player.audio_set_volume(self._vol_slider.value())
            self._player.audio_set_mute(self._mute_btn.isChecked())
        except Exception as exc:
            LOG.debug("Could not restore video audio state: %s", exc)

    def _restore_vlc_playback_state(
        self,
        generation: int,
        position_ms: int,
        rate: float,
        audio_track: int | None,
        subtitle_track: int | None,
        resume: bool,
    ) -> None:
        if generation != self._video_output_generation or self._player is None:
            return
        self._restore_vlc_position(generation, position_ms)
        try:
            self._player.set_rate(rate)
        except Exception as exc:
            LOG.debug("Could not restore playback rate after output handoff: %s", exc)
        if audio_track is not None:
            try:
                self._player.audio_set_track(audio_track)
            except Exception as exc:
                LOG.debug("Could not restore audio track after output handoff: %s", exc)
        if subtitle_track is not None:
            try:
                self._player.video_set_spu(subtitle_track)
            except Exception as exc:
                LOG.debug("Could not restore subtitle track after output handoff: %s", exc)
        if not resume:
            try:
                self._player.pause()
            except Exception as exc:
                LOG.debug("Could not pause after output handoff: %s", exc)
            self._play_btn.set_playing(False)
        else:
            self._play_btn.set_playing(True)

    def _restore_vlc_position(self, generation: int, position_ms: int) -> None:
        if generation != self._video_output_generation or self._player is None:
            return
        if position_ms <= 0:
            return
        try:
            self._player.set_time(position_ms)
        except Exception as exc:
            LOG.debug("Could not restore playback position after output handoff: %s", exc)

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
            self.load_path(path)

    def _open_url(self) -> None:
        recent_urls = list(getattr(self._settings, "recent_stream_urls", []))
        url, accepted = QInputDialog.getItem(
            self,
            "Open Network Stream",
            "Stream URL:",
            recent_urls,
            0,
            True,
        )
        if not accepted:
            return
        url = url.strip()
        if not normalize_stream_urls([url]):
            QMessageBox.warning(
                self,
                "Open Network Stream",
                "Enter a valid network stream URL.",
            )
            return
        self.load_location(url, label=url)

    def load_path(self, path: str) -> None:
        """Play a local video file path in the embedded VLC video player."""
        self._load_media_source(path, label=Path(path).name)

    def load_location(
        self,
        uri: str,
        *,
        label: str | None = None,
        options: tuple[str, ...] = (),
    ) -> None:
        """Play a VLC location/MRL such as dvd:///D:/ or vcd:///D:/."""
        self._load_media_source(
            uri,
            is_location=True,
            options=options,
            label=label or uri,
        )

    def playback_available(self) -> bool:
        """Return True when the VLC video player can accept playback sources."""
        return bool(self._available and self._player is not None)

    def unavailable_reason(self) -> str:
        return self._unavailable_reason

    def _load_media_source(
        self,
        source: str,
        *,
        is_location: bool = False,
        options: tuple[str, ...] = (),
        label: str | None = None,
    ) -> None:
        # When the user re-activates the same source while it is still
        # loaded, skip the reload so we don't prompt them to resume the
        # position they're already at.
        reloading_same_source = (
            source == self._current_path
            and is_location == self._current_is_location
            and self._player is not None
            and self._player.get_media() is not None
        )
        if reloading_same_source:
            if not self._player.is_playing():
                self._player.play()
                self._timer.start()
                self._play_btn.set_playing(True)
            return
        self._save_resume_position()
        self._video_output_generation += 1
        self._video_stack.setCurrentIndex(1)
        if not self._surface_attached:
            self._attach_vlc_to(self._surface)
            self._surface_attached = True
        resume_position = 0
        local_track = self._video_track_for_path(source) if not is_location else None
        self._current_track_id = local_track.id if local_track is not None else None
        self._current_is_location = is_location
        self._current_path = source
        if local_track is not None:
            resume_position = max(0, int(getattr(local_track, "resume_position", 0) or 0))
        self._subtitle_delay_us = 0
        self._update_subtitle_delay_label()
        media = (
            self._instance.media_new_location(source)
            if is_location
            else self._instance.media_new_path(source)
        )
        for option in options:
            try:
                media.add_option(option)
            except Exception as exc:
                LOG.debug("Could not add VLC video media option %s: %s", option, exc)
        self._player.set_media(media)
        media.release()  # drop our reference; VLC holds its own via set_media
        self._player.audio_set_volume(self._vol_slider.value())
        if self._eq_controller is not None:
            self._eq_controller.attach_to_player()
        self._info_lbl.setText(label or source)
        self._remember_stream_source(source, is_location)
        self._set_controls_enabled(True)
        self._player.play()
        self._play_btn.set_playing(True)
        self._timer.start()
        # Track lists and resolution are only available after the media parses
        QTimer.singleShot(600, self._populate_tracks)
        QTimer.singleShot(900, self._update_video_info)
        if self._should_prompt_resume(resume_position):
            generation = self._video_output_generation
            QTimer.singleShot(
                350,
                lambda: self._emit_resume_prompt(generation, resume_position),
            )

    def _remember_stream_source(self, source: str, is_location: bool) -> None:
        if not is_location or self._settings is None:
            return
        if not normalize_stream_urls([source]):
            return
        self._settings.remember_stream_url(source)
        try:
            self._settings.save()
        except OSError as exc:
            LOG.warning("Could not save recent stream URL: %s", exc)

    def _video_track_for_path(self, path: str) -> Any | None:
        if self._library is None or not path:
            return None
        finder = getattr(self._library, "tracks_for_paths", None)
        if not callable(finder):
            return None
        try:
            tracks = finder([path])
        except Exception as exc:
            LOG.debug("Could not look up video resume position for %s: %s", path, exc)
            return None
        for track in tracks:
            if getattr(track, "media_type", "") == "video" and getattr(track, "path", "") == path:
                return track
        return None

    @staticmethod
    def _should_prompt_resume(position_ms: int) -> bool:
        return position_ms >= _RESUME_PROMPT_MIN_MS

    def _emit_resume_prompt(self, generation: int, position_ms: int) -> None:
        if generation != self._video_output_generation or not self._current_path:
            return
        message = f"Resume video from {format_ms(position_ms)}?"
        self.resume_available.emit(
            message,
            lambda: self._resume_to_position(generation, position_ms),
        )

    def _resume_to_position(self, generation: int, position_ms: int) -> None:
        if generation != self._video_output_generation or self._player is None:
            return
        try:
            self._player.set_time(max(0, int(position_ms)))
            self._show_osd(f"Resumed {format_ms(position_ms)}")
        except Exception as exc:
            LOG.debug("Could not resume video position: %s", exc)

    def _save_resume_position(self) -> None:
        if self._library is None or self._current_track_id is None or self._current_is_location:
            return
        updater = getattr(self._library, "update_resume_position", None)
        if not callable(updater) or self._player is None:
            return
        try:
            position_ms = max(0, int(self._player.get_time()))
            duration_ms = max(0, int(self._player.get_length()))
        except Exception as exc:
            LOG.debug("Could not read video resume position: %s", exc)
            return
        if position_ms < _RESUME_PROMPT_MIN_MS:
            position_ms = 0
        elif duration_ms > 0 and duration_ms - position_ms <= _RESUME_CLEAR_REMAINING_MS:
            position_ms = 0
        try:
            updater(self._current_track_id, position_ms)
        except Exception as exc:
            LOG.debug("Could not save video resume position: %s", exc)

    # ---------------------------------------------------------------- transport

    def _toggle_play(self) -> None:
        if not self._current_path:
            self._play_btn.set_playing(False)
            return
        if self._player.is_playing():
            self._save_resume_position()
            self._player.pause()
            self._play_btn.set_playing(False)
        else:
            self._video_stack.setCurrentIndex(1)
            self._player.play()
            self._timer.start()
            self._play_btn.set_playing(True)

    def _stop(self) -> None:
        if not self._available or self._player is None:
            return
        self._save_resume_position()
        self._player.stop()
        self._timer.stop()
        self._play_btn.set_playing(False)
        self._seek.blockSignals(True)
        self._seek.setValue(0)
        self._seek.blockSignals(False)
        self._elapsed_lbl.setText("0:00")
        self._video_stack.setCurrentIndex(0)
        self._current_track_id = None

    def _on_seek_release(self) -> None:
        if self._player.get_length() > 0:
            self._player.set_time(self._seek.value())
        self._user_dragging = False

    def _on_volume_changed(self, value: int) -> None:
        self._player.audio_set_volume(value)
        self._mute_btn.set_state(value, bool(self._player.audio_get_mute()))

    def _on_mute_toggled(self, checked: bool) -> None:
        self._player.audio_set_mute(checked)
        self._mute_btn.set_state(self._vol_slider.value(), checked)

    def apply_equalizer(self, enabled: bool, bands: list[int], preamp: int = 0) -> None:
        """Apply or clear the 10-band equalizer on the video player's VLC instance."""
        self._eq_enabled = enabled
        self._eq_bands = list(bands)
        self._eq_preamp = int(preamp)
        if not self._available:
            return
        self._eq_fade_timer.stop()
        if self._eq_controller is not None and self._eq_controller.apply(enabled, bands, preamp):
            self._eq_fade_timer.start()

    def _eq_fade_step(self) -> None:
        if self._eq_controller is None or not self._eq_controller.fade_step():
            self._eq_fade_timer.stop()

    def apply_settings(self, settings: Settings) -> None:
        self._settings = settings

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

    def _step_subtitle_delay(self, delta_us: int) -> None:
        self._subtitle_delay_us = max(
            -10_000_000,
            min(10_000_000, self._subtitle_delay_us + int(delta_us)),
        )
        self._apply_subtitle_delay()

    def _apply_subtitle_delay(self) -> None:
        try:
            setter = getattr(self._player, "video_set_spu_delay")
            setter(int(self._subtitle_delay_us))
        except Exception as exc:
            LOG.debug("Could not set subtitle delay: %s", exc)
        self._update_subtitle_delay_label()
        self._show_osd(f"Subtitle delay {self._subtitle_delay_text()}")

    def _subtitle_delay_text(self) -> str:
        delay_ms = int(round(self._subtitle_delay_us / 1000))
        return f"{delay_ms:+d} ms" if delay_ms else "0 ms"

    def _update_subtitle_delay_label(self) -> None:
        if hasattr(self, "_sub_delay_label"):
            self._sub_delay_label.setText(self._subtitle_delay_text())

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

        was_playing = bool(self._player.is_playing())
        position_ms = self._safe_player_time()
        if was_playing:
            self._player.pause()

        self._fs_window = _FullscreenWindow(
            on_exit_cb=self._exit_fullscreen,
            on_toggle_play_cb=self._toggle_play,
            on_seek_relative_cb=self._seek_relative,
            on_volume_step_cb=self._step_volume,
            on_mute_toggle_cb=self._toggle_mute,
        )
        self._fs_window.showFullScreen()
        self._fs_window.raise_()
        self._fs_window.activateWindow()
        self._fs_window._vlc_surface.winId()
        # Let Qt finish showing the fullscreen native child before rebuilding
        # VLC's video output around that new drawable.
        QTimer.singleShot(
            0,
            lambda: self._attach_vlc_to_fullscreen_window(was_playing, position_ms),
        )
        self._fullscreen_btn.setText("Exit Fullscreen")

    def _attach_vlc_to_fullscreen_window(
        self,
        resume: bool = False,
        position_ms: int | None = None,
        attempt: int = 0,
    ) -> None:
        if self._fs_window is None:
            return
        surface = self._fs_window._vlc_surface
        surface.show()
        surface_is_ready = (
            surface.isVisible() and surface.width() > 1 and surface.height() > 1
        )
        if not surface_is_ready and attempt < 5:
            QTimer.singleShot(
                40,
                lambda: self._attach_vlc_to_fullscreen_window(
                    resume,
                    position_ms,
                    attempt + 1,
                ),
            )
            return
        self._handoff_vlc_output_to(surface, resume, position_ms)

    def _exit_fullscreen(self) -> None:
        if self._fs_window is None:
            return

        was_playing = bool(self._player.is_playing())
        position_ms = self._safe_player_time()
        if was_playing:
            self._player.pause()

        fs_window = self._fs_window
        self._fs_window = None
        fs_window.close()
        fs_window.deleteLater()
        self._fullscreen_btn.setText("Fullscreen")
        self._video_stack.setCurrentIndex(1)

        def _reattach() -> None:
            self._handoff_vlc_output_to(self._surface, was_playing, position_ms)

        # Give the embedded surface a tick to become front-most in the
        # compositor before handing VLC's output back to it.
        QTimer.singleShot(0, _reattach)

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

            self._play_btn.set_playing(bool(self._player.is_playing()))
        except Exception as exc:
            LOG.debug("Video poll error: %s", exc)

    def _on_ended(self) -> None:
        self._clear_resume_position()
        self._timer.stop()
        self._play_btn.set_playing(False)
        self._seek.blockSignals(True)
        dur = max(0, int(self._player.get_length()))
        self._seek.setValue(dur)
        self._seek.blockSignals(False)
        self._video_stack.setCurrentIndex(0)

    def _clear_resume_position(self) -> None:
        """Reset the saved resume position so a fully-watched video does
        not prompt the user to resume on next play."""
        if self._library is None or self._current_track_id is None or self._current_is_location:
            return
        updater = getattr(self._library, "update_resume_position", None)
        if not callable(updater):
            return
        try:
            updater(self._current_track_id, 0)
        except Exception as exc:
            LOG.debug("Could not clear video resume position: %s", exc)

    # ---------------------------------------------------------------- shortcuts / OSD

    def _show_osd(self, text: str) -> None:
        if self._osd is None:
            return
        host = self._fs_window if self._fs_window is not None else self.window()
        self._osd.show_message(text, host)

    def _seek_relative(self, ms_delta: int) -> None:
        """Skip forward/backward by ms_delta milliseconds, showing OSD feedback."""
        if not self._available or self._player is None or not self._player.get_media():
            return
        dur = max(0, int(self._player.get_length()))
        if dur <= 0:
            return
        new_pos = max(0, min(dur, int(self._player.get_time()) + int(ms_delta)))
        self._player.set_time(new_pos)
        seconds = abs(ms_delta) // 1000
        sign = "+" if ms_delta >= 0 else "−"
        self._show_osd(f"{sign}{seconds}s")

    def _step_volume(self, step: int) -> None:
        """Adjust volume by `step` percent; clamps to 0–100 and updates the slider."""
        if not self._available:
            return
        new = max(0, min(100, self._vol_slider.value() + int(step)))
        self._vol_slider.setValue(new)  # triggers _on_volume_changed
        self._show_osd(f"Volume {new}")

    def _toggle_mute(self) -> None:
        if not self._available:
            return
        muted = not self._mute_btn.isChecked()
        self._mute_btn.setChecked(muted)  # triggers _on_mute_toggled
        self._show_osd("Muted" if muted else f"Volume {self._vol_slider.value()}")

    # ---------------------------------------------------------------- lifecycle

    def cleanup(self) -> None:
        """Release native libVLC resources. Called from MainWindow.closeEvent."""
        if not self._available:
            return
        self._save_resume_position()
        self._eq_fade_timer.stop()
        self._catalog_build_timer.stop()
        if hasattr(self, "_timer"):
            self._timer.stop()
        if self._fs_window is not None:
            fs_window = self._fs_window
            self._fs_window = None
            fs_window.close()
            fs_window.deleteLater()
        if self._osd is not None:
            self._osd.hide()
            self._osd.deleteLater()
            self._osd = None
        try:
            self._player.stop()
            self._player.release()
        except Exception as exc:
            LOG.debug("Error releasing video VLC player: %s", exc)
        try:
            self._instance.release()
        except Exception as exc:
            LOG.debug("Error releasing video VLC instance: %s", exc)
        self._player = None  # type: ignore[assignment]
        self._instance = None  # type: ignore[assignment]
        self._available = False

    def pause_playback(self) -> None:
        """Pause video when the user navigates away from this tab."""
        if self._available and self._player and self._player.is_playing():
            self._save_resume_position()
            self._player.pause()
            self._play_btn.set_playing(False)

    def stop_playback(self) -> None:
        """Stop video playback when another playback surface takes over."""
        self._stop()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        # Defer winId() / native-window creation until the widget is fully
        # embedded in the Qt window hierarchy.  Calling it during __init__
        # (before addWidget to QStackedWidget) produced a premature native
        # window that broke QStackedWidget show/hide, causing the previous
        # tab's content to bleed through and the transport bar to duplicate.
        if self._available and not self._surface_attached:
            self._attach_vlc_to(self._surface)
            self._surface_attached = True

    def keyPressEvent(self, ev) -> None:
        if not self._available:
            super().keyPressEvent(ev)
            return
        key = ev.key()
        mod = ev.modifiers()
        if key == Qt.Key_Space:
            self._toggle_play()
        elif key == Qt.Key_F:
            if self._fs_window:
                self._exit_fullscreen()
            else:
                self._enter_fullscreen()
        elif key == Qt.Key_B and mod & Qt.ControlModifier:
            checked = not self._sidebar_btn.isChecked()
            self._sidebar_btn.setChecked(checked)
            self._toggle_sidebar(checked)
        elif key == Qt.Key_Left:
            self._seek_relative(-30_000 if mod & Qt.ShiftModifier else -5_000)
        elif key == Qt.Key_Right:
            self._seek_relative(30_000 if mod & Qt.ShiftModifier else 5_000)
        elif key == Qt.Key_Up:
            self._step_volume(5)
        elif key == Qt.Key_Down:
            self._step_volume(-5)
        elif key == Qt.Key_M:
            self._toggle_mute()
        elif key == Qt.Key_BracketLeft:
            self._step_subtitle_delay(-_SUBTITLE_DELAY_STEP_US)
        elif key == Qt.Key_BracketRight:
            self._step_subtitle_delay(_SUBTITLE_DELAY_STEP_US)
        else:
            super().keyPressEvent(ev)
            return
        ev.accept()

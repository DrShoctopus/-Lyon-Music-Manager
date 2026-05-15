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
import sys
from pathlib import Path
from typing import Any

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QScrollArea, QSizePolicy, QSlider, QStackedWidget,
    QToolButton, QVBoxLayout, QWidget,
)

from ..core.equalizer import normalize_equalizer_bands
from ..core.playback_backend import _configure_vlc_runtime_path
from .widgets import ElidedLabel, format_duration, format_ms, placeholder_cover

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

_SIDEBAR_WIDTH = 234


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
    for src in sources:
        pm = QPixmap(src)
        if not pm.isNull():
            return _scale_to_fill(pm, w, h)
    pm = placeholder_cover(max(w, h), "▶")
    return pm.scaled(w, h, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)


# ---------------------------------------------------------------------------
# Catalog sidebar card
# ---------------------------------------------------------------------------

class _VideoCard(QFrame):
    """Clickable thumbnail card representing one catalogued video."""

    load_requested = Signal(str)

    def __init__(self, track: Any, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._path = track.path
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
        thumb.setFixedSize(96, 54)
        thumb.setAlignment(Qt.AlignCenter)
        thumb.setStyleSheet("background:#0a1520;")
        thumb.setPixmap(_thumb_pixmap(track.artwork_path, track.path, 96, 54))
        row.addWidget(thumb)

        info = QVBoxLayout()
        info.setContentsMargins(0, 0, 0, 0)
        info.setSpacing(1)

        title_lbl = ElidedLabel(title)
        title_lbl.setStyleSheet("color:#dde3ea; font-size:11px; font-weight:600;")

        dur_lbl = QLabel(dur or "—")
        dur_lbl.setStyleSheet("color:#7a8a9a; font-size:10px;")

        info.addStretch()
        info.addWidget(title_lbl)
        info.addWidget(dur_lbl)
        info.addStretch()
        row.addLayout(info, 1)

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

    def __init__(self, on_exit_cb, on_toggle_play_cb) -> None:
        super().__init__(None, Qt.Window | Qt.FramelessWindowHint)
        self.setStyleSheet("background:#000000;")
        self._on_exit = on_exit_cb
        self._on_toggle_play = on_toggle_play_cb

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


# ---------------------------------------------------------------------------
# Splash pane (default background when no video is loaded)
# ---------------------------------------------------------------------------

class _SplashPane(QLabel):
    """Centered Lyon splash shown in the video area when no video is playing."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet("background:#0a1118;")
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

    def __init__(self, library: Any = None, parent: QWidget | None = None):
        super().__init__(parent)
        self._library = library
        _configure_vlc_runtime_path()

        self._vlc: Any = None
        self._instance: Any = None
        self._player: Any = None
        self._available = False
        self._user_dragging = False
        self._current_path = ""
        self._fs_window: _FullscreenWindow | None = None
        self._surface_attached = False  # deferred until first showEvent
        self._eq_enabled = False
        self._eq_bands: list[int] = []
        self._equalizer: Any = None

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
        self.setObjectName("videoPlayerView")
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

        self._sidebar_btn = QPushButton("◀ Library")
        self._sidebar_btn.setCheckable(True)
        self._sidebar_btn.setChecked(True)
        self._sidebar_btn.setToolTip("Show / hide video catalog  [Ctrl+B]")
        self._sidebar_btn.clicked.connect(self._toggle_sidebar)

        toolbar.addWidget(self._open_btn)
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

        # ---- Sidebar + video surface (side by side) -------------------------
        self._sidebar = self._build_sidebar()

        self._sidebar_sep = QFrame()
        self._sidebar_sep.setFrameShape(QFrame.VLine)
        self._sidebar_sep.setFixedWidth(1)
        self._sidebar_sep.setStyleSheet("QFrame { background: #2a3848; }")

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
        sidebar.setStyleSheet("""
            QFrame#videoCatalogSidebar { background: #0d1520; }
            QFrame#videoCard { background: #131e2c; border-radius: 3px; }
            QFrame#videoCard:hover { background: #1e2d40; }
        """)

        sl = QVBoxLayout(sidebar)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(0)

        # Header
        header = QFrame()
        header.setStyleSheet("background: #0a1520;")
        hl = QHBoxLayout(header)
        hl.setContentsMargins(10, 8, 10, 6)
        hl.setSpacing(4)
        lib_lbl = QLabel("Video Library")
        lib_lbl.setStyleSheet("color:#72f4ff; font-weight:600; font-size:12px;")
        self._catalog_count_lbl = QLabel("")
        self._catalog_count_lbl.setStyleSheet("color:#7a8a9a; font-size:10px;")
        hl.addWidget(lib_lbl)
        hl.addStretch()
        hl.addWidget(self._catalog_count_lbl)

        # Search bar
        search_row = QFrame()
        search_row.setStyleSheet("background: #0d1520;")
        swl = QHBoxLayout(search_row)
        swl.setContentsMargins(8, 5, 8, 4)
        self._catalog_search = QLineEdit()
        self._catalog_search.setPlaceholderText("Search videos…")
        self._catalog_search.textChanged.connect(self._filter_catalog)
        swl.addWidget(self._catalog_search)

        # Scrollable card list
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("background: #0d1520;")

        self._catalog_container = QWidget()
        self._catalog_container.setStyleSheet("background: #0d1520;")
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

        for card in self._catalog_cards:
            self._catalog_layout.removeWidget(card)
            card.deleteLater()
        self._catalog_cards.clear()

        videos = list(self._library.all_tracks(media_type="video"))
        query = self._catalog_search.text().strip().lower()

        for track in videos:
            card = _VideoCard(track)
            card.load_requested.connect(self._load_path)
            # Insert before the trailing stretch
            self._catalog_layout.insertWidget(self._catalog_layout.count() - 1, card)
            self._catalog_cards.append(card)
            if query and not card.matches(query):
                card.hide()

        total = len(videos)
        shown = sum(1 for c in self._catalog_cards if not c.isHidden())
        if query:
            self._catalog_count_lbl.setText(f"{shown}/{total}")
        else:
            self._catalog_count_lbl.setText(f"{total} video{'s' if total != 1 else ''}")

    def _filter_catalog(self, text: str) -> None:
        query = text.strip().lower()
        visible = 0
        for card in self._catalog_cards:
            show = card.matches(query)
            card.setVisible(show)
            if show:
                visible += 1
        total = len(self._catalog_cards)
        if query:
            self._catalog_count_lbl.setText(f"{visible}/{total}")
        else:
            self._catalog_count_lbl.setText(f"{total} video{'s' if total != 1 else ''}")

    def _toggle_sidebar(self, checked: bool) -> None:
        self._sidebar.setVisible(checked)
        self._sidebar_sep.setVisible(checked)
        self._sidebar_btn.setText("◀ Library" if checked else "▶ Library")

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
        self._video_stack.setCurrentIndex(1)
        if not self._surface_attached:
            self._attach_vlc_to(self._surface)
            self._surface_attached = True
        self._current_path = path
        media = self._instance.media_new_path(path)
        self._player.set_media(media)
        media.release()  # drop our reference; VLC holds its own via set_media
        self._player.audio_set_volume(self._vol_slider.value())
        if self._equalizer is not None:
            self._player.set_equalizer(self._equalizer)
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
            self._video_stack.setCurrentIndex(1)
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
        self._video_stack.setCurrentIndex(0)

    def _on_seek_release(self) -> None:
        if self._player.get_length() > 0:
            self._player.set_time(self._seek.value())
        self._user_dragging = False

    def _on_volume_changed(self, value: int) -> None:
        self._player.audio_set_volume(value)

    def _on_mute_toggled(self, checked: bool) -> None:
        self._player.audio_set_mute(checked)
        self._mute_btn.setText("--" if checked else "M")

    def apply_equalizer(self, enabled: bool, bands: list[int]) -> None:
        """Apply or clear the 10-band equalizer on the video player's VLC instance."""
        self._eq_enabled = enabled
        self._eq_bands = list(bands)
        if not self._available:
            return
        if not enabled:
            self._equalizer = None
            try:
                self._player.set_equalizer(None)
            except (AttributeError, OSError, RuntimeError) as exc:
                LOG.warning("Could not clear video VLC equalizer: %s", exc)
            return
        try:
            normalized = normalize_equalizer_bands(bands)
            equalizer = self._vlc.AudioEqualizer()
            if equalizer is None:
                raise RuntimeError("VLC did not create an AudioEqualizer instance")
            equalizer.set_preamp(0.0)
            for band_index, band_gain in enumerate(normalized):
                equalizer.set_amp_at_index(float(band_gain), band_index)
            self._player.set_equalizer(equalizer)
            self._equalizer = equalizer
        except (AttributeError, OSError, RuntimeError) as exc:
            self._equalizer = None
            try:
                self._player.set_equalizer(None)
            except (AttributeError, OSError, RuntimeError):
                pass
            LOG.warning("Could not apply video VLC equalizer: %s", exc)

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

        was_playing = bool(self._player.is_playing())
        if was_playing:
            self._player.pause()

        self._fs_window = _FullscreenWindow(
            on_exit_cb=self._exit_fullscreen,
            on_toggle_play_cb=self._toggle_play,
        )
        self._fs_window.showFullScreen()
        self._fs_window.raise_()
        self._fs_window.activateWindow()
        # Defer winId capture until the OS window and its child surface are
        # realized, then resume playback on the new surface.
        QTimer.singleShot(150, lambda: self._attach_vlc_to_fullscreen_window(was_playing))
        self._fullscreen_btn.setText("Exit Fullscreen")

    def _attach_vlc_to_fullscreen_window(self, resume: bool = False) -> None:
        if self._fs_window is None:
            return
        self._attach_vlc_to(self._fs_window._vlc_surface)
        if resume:
            self._player.play()

    def _exit_fullscreen(self) -> None:
        if self._fs_window is None:
            return

        was_playing = bool(self._player.is_playing())
        if was_playing:
            self._player.pause()

        self._fs_window.close()
        self._fs_window = None
        self._fullscreen_btn.setText("Fullscreen")
        self._video_stack.setCurrentIndex(1)

        def _reattach() -> None:
            self._attach_vlc_to(self._surface)
            if was_playing:
                self._player.play()

        # Give the embedded surface a tick to become front-most in the
        # compositor before handing VLC's output back to it.
        QTimer.singleShot(100, _reattach)

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
        self._video_stack.setCurrentIndex(0)

    # ---------------------------------------------------------------- lifecycle

    def cleanup(self) -> None:
        """Release native libVLC resources. Called from MainWindow.closeEvent."""
        if not self._available:
            return
        if hasattr(self, "_timer"):
            self._timer.stop()
        if self._fs_window is not None:
            self._fs_window.close()
            self._fs_window = None
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
            self._player.pause()
            self._play_btn.setText("▶")
            self._play_btn.setChecked(False)

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
        if ev.key() == Qt.Key_Space:
            self._toggle_play()
            ev.accept()
        elif ev.key() == Qt.Key_F:
            if self._fs_window:
                self._exit_fullscreen()
            else:
                self._enter_fullscreen()
            ev.accept()
        elif ev.key() == Qt.Key_B and ev.modifiers() & Qt.ControlModifier:
            checked = not self._sidebar_btn.isChecked()
            self._sidebar_btn.setChecked(checked)
            self._toggle_sidebar(checked)
            ev.accept()
        else:
            super().keyPressEvent(ev)

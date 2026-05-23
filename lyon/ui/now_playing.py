"""Now Playing view + bottom transport bar."""
from __future__ import annotations

import bisect
from decimal import Decimal, InvalidOperation
import json
import re
import threading
import urllib.parse
import urllib.request
from pathlib import Path
from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QFrame, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QPushButton, QScrollArea, QSizePolicy,
    QStackedWidget, QVBoxLayout, QWidget,
)

from ..core import metadata
from ..core.library import Library, Track
from ..core.player import Player
from ..core.settings import Settings
from .artist_panel import ArtistPanel
from .widgets import StarRatingWidget, cover_pixmap, format_duration, format_ms

_PAGE_MARGIN = 8

# ---- LRC parsing -------------------------------------------------------

_LRC_RE = re.compile(r"\[(\d+):(\d+(?:\.\d+)?)\]")
_LRC_OFFSET_RE = re.compile(r"\[offset:\s*([+-]?\d+)\s*\]", re.IGNORECASE)


def _parse_lrc(text: str) -> list[tuple[int, str]]:
    """Return sorted list of (ms, lyric_line) from an LRC string."""
    lines: list[tuple[int, str]] = []
    offset_ms = 0
    for raw in text.splitlines():
        stripped = raw.strip()
        offset_match = _LRC_OFFSET_RE.match(stripped)
        if offset_match:
            offset_ms = int(offset_match.group(1))
            continue
        matches = list(_LRC_RE.finditer(stripped))
        if not matches:
            continue
        lyric_text = stripped[matches[-1].end():].strip()
        for m in matches:
            mins = int(m.group(1))
            try:
                secs = Decimal(m.group(2))
            except InvalidOperation:
                continue
            ms = int((Decimal(mins * 60) + secs) * 1000) - offset_ms
            lines.append((max(0, ms), lyric_text))
    lines.sort(key=lambda x: x[0])
    return lines


def _read_embedded_lyrics(path: str) -> str | None:
    """Try to extract embedded lyrics from an audio file via mutagen."""
    try:
        from mutagen.id3 import ID3

        tags = ID3(path)
        for key in tags.keys():
            if key.startswith("USLT"):
                return tags[key].text
    except Exception:
        pass
    try:
        from mutagen import File as MutagenFile
        f = MutagenFile(path, easy=False)
        if f is None:
            return None
        for field in ("lyrics", "©lyr", "LYRICS"):
            v = f.get(field)
            if v:
                raw = v[0] if isinstance(v, list) else str(v)
                return str(raw)
    except Exception:
        pass
    return None


def _fetch_lrclib(artist: str, title: str, album: str, duration_s: float) -> tuple[str, str]:
    """Query LRCLIB for lyrics. Returns (synced_lrc, plain_text); empty string = not found."""
    params: dict[str, str | int] = {
        "artist_name": artist,
        "track_name": title,
        "album_name": album,
        "duration": int(duration_s),
    }
    url = "https://lrclib.net/api/get?" + urllib.parse.urlencode(params)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Sea-Lyon-Media-Manager"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            if resp.status != 200:
                return "", ""
            data = json.loads(resp.read().decode())
            return data.get("syncedLyrics") or "", data.get("plainLyrics") or ""
    except Exception:
        return "", ""


def _blur_pixmap(pm: QPixmap, target_w: int, target_h: int) -> QPixmap:
    """Scale down → scale up for a fast box-blur approximation, then darken."""
    if pm.isNull():
        return pm
    small = pm.scaled(40, 40, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
    blurred = small.scaled(target_w, target_h, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
    # Crop to exact size (KeepAspectRatioByExpanding can overshoot)
    if blurred.width() > target_w or blurred.height() > target_h:
        x = (blurred.width() - target_w) // 2
        y = (blurred.height() - target_h) // 2
        blurred = blurred.copy(x, y, target_w, target_h)
    # Dark overlay so text remains readable
    result = blurred.copy()
    p = QPainter(result)
    p.fillRect(result.rect(), QColor(0, 0, 0, 160))
    p.end()
    return result


# ---- Lyrics panel ------------------------------------------------------

class _LyricsPanel(QWidget):
    """Scrollable lyrics display; syncs with playback when LRC data is available."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._synced: list[tuple[int, str]] = []   # (ms, text) — empty = not synced
        self._timestamps: list[int] = []
        self._current_line = -1
        self._last_position_ms = 0
        self._labels: list[QLabel] = []

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll_animation = QPropertyAnimation(
            self._scroll.verticalScrollBar(), b"value", self
        )
        self._scroll_animation.setDuration(240)
        self._scroll_animation.setEasingCurve(QEasingCurve.OutCubic)

        self._container = QWidget()
        self._container.setObjectName("lyricsContainer")
        self._vl = QVBoxLayout(self._container)
        self._vl.setAlignment(Qt.AlignTop)
        self._vl.setSpacing(6)
        self._update_center_padding()
        self._scroll.setWidget(self._container)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._scroll)

    def set_lyrics(self, synced: list[tuple[int, str]], plain: str | None = None) -> None:
        """Set synced [(ms, line)] or fall back to plain text."""
        for lbl in self._labels:
            self._vl.removeWidget(lbl)
            lbl.deleteLater()
        self._labels.clear()
        self._current_line = -1
        self._synced = synced
        self._timestamps = [ms for ms, _ in synced]
        self._scroll_animation.stop()

        if synced:
            lines_text = [t for _, t in synced]
        elif plain:
            lines_text = [l for l in plain.splitlines() if l.strip()] or [plain]
        else:
            lines_text = []

        if not lines_text:
            placeholder = QLabel("No lyrics available.")
            placeholder.setObjectName("mutedText")
            placeholder.setAlignment(Qt.AlignCenter)
            self._vl.addWidget(placeholder)
            self._labels.append(placeholder)
            self._scroll.verticalScrollBar().setValue(0)
            return

        for text in lines_text:
            lbl = QLabel(text or " ")  # non-breaking space for blank lines
            lbl.setWordWrap(True)
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setObjectName("lyricsLine")
            self._vl.addWidget(lbl)
            self._labels.append(lbl)
        self._scroll.verticalScrollBar().setValue(0)
        if synced:
            self.update_position(self._last_position_ms)

    def clear(self) -> None:
        self.set_lyrics([], None)

    def update_position(self, pos_ms: int) -> None:
        self._last_position_ms = max(0, int(pos_ms))
        if not self._synced or not self._labels:
            return
        idx = bisect.bisect_right(self._timestamps, self._last_position_ms) - 1
        if idx < 0:
            self._clear_current_line()
            return
        idx = min(idx, len(self._labels) - 1)
        if idx == self._current_line:
            return
        self._clear_current_line()
        self._current_line = idx
        self._labels[idx].setObjectName("lyricsLineCurrent")
        self._repolish_label(self._labels[idx])
        self._center_current_line(self._labels[idx])

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_center_padding()
        if 0 <= self._current_line < len(self._labels):
            QTimer.singleShot(0, self._recenter_current_line)

    def _update_center_padding(self) -> None:
        viewport_height = self._scroll.viewport().height()
        padding = max(0, viewport_height // 2 - 24)
        self._vl.setContentsMargins(0, padding, 0, padding)

    def _center_current_line(self, label: QLabel, *, animate: bool = True) -> None:
        self._vl.activate()
        self._container.adjustSize()
        viewport_height = self._scroll.viewport().height()
        target = label.geometry().center().y() - (viewport_height // 2)
        bar = self._scroll.verticalScrollBar()
        target = max(bar.minimum(), min(target, bar.maximum()))
        self._scroll_animation.stop()
        if animate:
            self._scroll_animation.setStartValue(bar.value())
            self._scroll_animation.setEndValue(target)
            self._scroll_animation.start()
        else:
            bar.setValue(target)

    def _recenter_current_line(self) -> None:
        if 0 <= self._current_line < len(self._labels):
            self._center_current_line(self._labels[self._current_line], animate=False)

    def _clear_current_line(self) -> None:
        if 0 <= self._current_line < len(self._labels):
            self._labels[self._current_line].setObjectName("lyricsLine")
            self._repolish_label(self._labels[self._current_line])
        self._current_line = -1

    @staticmethod
    def _repolish_label(label: QLabel) -> None:
        label.style().unpolish(label)
        label.style().polish(label)
        label.update()


# ---- Info panel --------------------------------------------------------

class _InfoPanel(QWidget):
    """Shows album metadata: year, genre, track count, total duration."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._cover = QLabel()
        self._cover.setFixedSize(100, 100)
        self._cover.setAlignment(Qt.AlignCenter)
        self._cover.setPixmap(cover_pixmap(None, 100, "♪"))

        self._details = QLabel("")
        self._details.setObjectName("mutedText")
        self._details.setWordWrap(True)
        self._details.setAlignment(Qt.AlignTop | Qt.AlignLeft)

        row = QHBoxLayout()
        row.setSpacing(12)
        row.addWidget(self._cover, 0, Qt.AlignTop)
        row.addWidget(self._details, 1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addLayout(row)
        layout.addStretch(1)

    def set_track(self, track: Track | None, library: Library | None) -> None:
        if track is None:
            self._cover.setPixmap(cover_pixmap(None, 100, "♪"))
            self._details.setText("")
            return
        self._cover.setPixmap(cover_pixmap(track.artwork_path, 100, "♪"))
        lines: list[str] = []
        if track.year:
            lines.append(f"Year: {track.year}")
        if track.genre:
            lines.append(f"Genre: {track.genre}")
        if library is not None and track.is_library_item:
            try:
                album_tracks = library.tracks_for_album(
                    track.display_artist, track.album or "", track.media_type
                )
                if album_tracks:
                    total_s = sum(int(t.duration) for t in album_tracks)
                    lines.append(f"Tracks: {len(album_tracks)}")
                    lines.append(f"Duration: {format_duration(total_s)}")
            except Exception:
                pass
        self._details.setText("\n".join(lines) if lines else "No info available.")


# ---- NowPlayingView ----------------------------------------------------

class NowPlayingView(QWidget):
    """Now Playing screen with cinematic background, panel switcher, and interactive queue."""

    # Emitted from the lyrics-fetch worker thread; always delivered on the main thread.
    _lyrics_ready = Signal(int, str, str)   # task_id, synced_lrc, plain_text
    _artist_ready = Signal(str, object, object)  # cache key, ArtistInfo | None, image bytes | None
    request_edit_metadata = Signal(object)  # Track

    # In-memory cap for the lyrics + artist side-panel caches; oldest entries
    # are evicted FIFO when exceeded.
    _PANEL_CACHE_MAX = 256

    def __init__(
        self,
        player: Player,
        library: Library | None = None,
        settings: Settings | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.player = player
        self._library = library
        self._settings = settings
        self._bg_pixmap: QPixmap | None = None
        self._bg_cache: QPixmap | None = None   # blurred result, invalidated on resize/track change
        self._bg_cache_size: tuple[int, int] = (0, 0)
        self._blur_timer = QTimer(self)
        self._blur_timer.setSingleShot(True)
        self._blur_timer.setInterval(80)
        self._blur_timer.timeout.connect(self._rebuild_blur)
        self._current_track: Track | None = None
        self._lyrics_task_id: int = 0   # track.id of the in-flight LRCLIB request; 0 = none
        # track.id → (synced_lrc, plain_text); empty strings mean "we asked LRCLIB and got nothing".
        self._lyrics_cache: dict[int, tuple[str, str]] = {}
        self._artist_task_key = ""
        self._artist_cache: dict[str, tuple[object, bytes | None]] = {}

        # ---- Album cover
        self.cover = QLabel()
        self.cover.setObjectName("nowPlayingCover")
        self.cover.setFixedSize(280, 280)
        self.cover.setAlignment(Qt.AlignCenter)
        self.cover.setPixmap(cover_pixmap(None, 280, "♪"))

        # ---- Track info + rating
        self.title = QLabel("Nothing playing")
        f = self.title.font(); f.setPointSize(20); f.setBold(True)
        self.title.setFont(f)
        self.title.setObjectName("nowPlayingHeroTitle")
        self.title.setWordWrap(True)

        self.artist = QLabel("")
        f2 = self.artist.font(); f2.setPointSize(13)
        self.artist.setFont(f2)
        self.artist.setObjectName("nowPlayingHeroArtist")

        self.album = QLabel("")
        self.album.setObjectName("mutedText")

        self.format_strip = QLabel("")
        self.format_strip.setObjectName("mutedTextSmall")

        self.position_lbl = QLabel("")
        self.position_lbl.setObjectName("mutedText")

        self._rating_widget = StarRatingWidget(0)
        self._rating_widget.rating_changed.connect(self._on_rating_changed)

        info = QVBoxLayout()
        info.setSpacing(4)
        info.addStretch(1)
        info.addWidget(self.title)
        info.addWidget(self.artist)
        info.addWidget(self.album)
        info.addSpacing(8)
        info.addWidget(self._rating_widget)
        info.addSpacing(6)
        info.addWidget(self.format_strip)
        info.addWidget(self.position_lbl)
        info.addStretch(1)

        info_w = QWidget()
        info_w.setLayout(info)
        info_w.setMinimumWidth(260)

        # ---- Right panel: Queue / Lyrics / Info switcher
        queue_btn = QPushButton("Queue")
        queue_btn.setCheckable(True)
        queue_btn.setChecked(True)
        queue_btn.setObjectName("panelTab")
        queue_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        lyrics_btn = QPushButton("Lyrics")
        lyrics_btn.setCheckable(True)
        lyrics_btn.setObjectName("panelTab")
        lyrics_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        info_btn = QPushButton("Info")
        info_btn.setCheckable(True)
        info_btn.setObjectName("panelTab")
        info_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        artist_btn = QPushButton("Artist")
        artist_btn.setCheckable(True)
        artist_btn.setObjectName("panelTab")
        artist_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        tab_row = QHBoxLayout()
        tab_row.setSpacing(4)
        tab_row.addWidget(queue_btn, 1)
        tab_row.addWidget(lyrics_btn, 1)
        tab_row.addWidget(info_btn, 1)
        tab_row.addWidget(artist_btn, 1)

        # Queue panel
        self._queue_list = QListWidget()
        self.queue_list = self._queue_list  # public compatibility for tests and older callers
        self._queue_list.setObjectName("queuePreview")
        self._queue_list.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._queue_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self._queue_list.setUniformItemSizes(True)
        self._queue_list.setDragDropMode(QAbstractItemView.InternalMove)
        self._queue_list.itemDoubleClicked.connect(self._on_queue_double_clicked)
        self._queue_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self._queue_list.customContextMenuRequested.connect(self._on_queue_context_menu)
        # Wire drag-to-reorder
        self._queue_list.model().rowsMoved.connect(self._on_queue_rows_moved)

        # Lyrics panel
        self._lyrics_panel = _LyricsPanel()

        # Info panel
        self._info_panel = _InfoPanel()
        self._artist_panel = ArtistPanel()

        self._panel_stack = QStackedWidget()
        self._panel_stack.addWidget(self._queue_list)   # 0: queue
        self._panel_stack.addWidget(self._lyrics_panel)  # 1: lyrics
        self._panel_stack.addWidget(self._info_panel)    # 2: info
        self._panel_stack.addWidget(self._artist_panel)  # 3: artist

        self._panel_tabs = (queue_btn, lyrics_btn, info_btn, artist_btn)
        for page, btn in enumerate(self._panel_tabs):
            btn.toggled.connect(lambda checked, p=page: self._on_panel_tab_toggled(p, checked))

        right_vl = QVBoxLayout()
        right_vl.setContentsMargins(0, 0, 0, 0)
        right_vl.setSpacing(4)
        right_vl.addLayout(tab_row)
        right_vl.addWidget(self._panel_stack, 1)

        right_w = QWidget()
        right_w.setObjectName("nowPlayingSidePanel")
        right_w.setLayout(right_vl)
        right_w.setMinimumWidth(440)
        right_w.setMaximumWidth(720)
        right_w.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        # ---- Top-level layout
        row = QHBoxLayout()
        row.setSpacing(24)
        row.addWidget(self.cover, 0, Qt.AlignVCenter)
        row.addWidget(info_w, 1)
        row.addWidget(right_w, 1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(_PAGE_MARGIN, _PAGE_MARGIN, _PAGE_MARGIN, _PAGE_MARGIN)
        layout.addLayout(row, 1)

        # ---- Signals
        player.track_changed.connect(self._on_track)
        player.queue_changed.connect(self._refresh_queue)
        player.position_changed.connect(self._on_position)
        self._lyrics_ready.connect(self._on_lyrics_ready)
        self._artist_ready.connect(self._on_artist_ready)
        self._refresh_queue()
        # Sync immediately if a track is already playing when this view is created.
        self._on_track(player.current())

    # ---- Cinematic background ------------------------------------------

    def resizeEvent(self, ev) -> None:
        super().resizeEvent(ev)
        if self._bg_pixmap is not None:
            self._blur_timer.start()
            self.update()

    def paintEvent(self, ev) -> None:
        if self._bg_pixmap is not None and not self._bg_pixmap.isNull():
            size = (self.width(), self.height())
            if self._bg_cache is None:
                self._bg_cache = _blur_pixmap(self._bg_pixmap, size[0], size[1])
                self._bg_cache_size = size
            p = QPainter(self)
            p.drawPixmap(self.rect(), self._bg_cache)
            p.end()
        else:
            super().paintEvent(ev)

    def _rebuild_blur(self) -> None:
        if self._bg_pixmap is None:
            return
        self._bg_cache = None
        self.update()

    def _update_background(self, artwork_path: str | None) -> None:
        self._blur_timer.stop()
        if artwork_path:
            pm = QPixmap(artwork_path)
            self._bg_pixmap = pm if not pm.isNull() else None
        else:
            self._bg_pixmap = None
        self._bg_cache = None  # force rebuild on next paint
        self.update()

    def _on_panel_tab_toggled(self, page: int, checked: bool) -> None:
        if checked:
            for idx, button in enumerate(self._panel_tabs):
                if idx != page:
                    button.setChecked(False)
            self._panel_stack.setCurrentIndex(page)
            return
        if not any(button.isChecked() for button in self._panel_tabs):
            self._panel_tabs[page].setChecked(True)

    # ---- Track change --------------------------------------------------

    def _on_track(self, track: Track | None) -> None:
        self._current_track = track
        if track is None:
            self.title.setText("Nothing playing")
            self.artist.setText("")
            self.album.setText("")
            self.format_strip.setText("")
            self.position_lbl.setText("")
            self.cover.setPixmap(cover_pixmap(None, 280, "♪"))
            self._rating_widget.set_rating(0)
            self._lyrics_panel.clear()
            self._info_panel.set_track(None, self._library)
            self._artist_task_key = ""
            self._artist_panel.set_empty("No artist selected.")
            self._update_background(None)
        else:
            self.title.setText(track.title or "Untitled")
            self.artist.setText(track.display_artist)
            self.album.setText(track.album or "")
            self.format_strip.setText(self._format_strip_text(track))
            self.cover.setPixmap(cover_pixmap(track.artwork_path, 280, "♪"))
            self._rating_widget.set_rating(track.rating)
            self._update_background(track.artwork_path)
            if track.is_library_item:
                self._load_lyrics(track)
                self._load_artist_info(track)
            else:
                self._lyrics_panel.clear()
                self._artist_task_key = ""
                self._artist_panel.set_empty("No artist info for network streams.")
            self._info_panel.set_track(track, self._library)
        self._refresh_queue()

    def _on_position(self, pos_ms: int, dur_ms: int) -> None:
        if dur_ms <= 0 and pos_ms <= 0:
            self.position_lbl.setText("")
        else:
            self.position_lbl.setText(f"{format_ms(pos_ms)} / {format_ms(dur_ms)}")
        # Forward to lyrics panel for sync
        self._lyrics_panel.update_position(pos_ms)

    # ---- Lyrics loading ------------------------------------------------

    def _load_lyrics(self, track: Track) -> None:
        self._lyrics_task_id = 0  # cancel any in-flight LRCLIB request
        path = track.path
        # 1. Try .lrc sidecar file for synced lyrics
        lrc_path = Path(path).with_suffix(".lrc")
        if lrc_path.exists():
            try:
                text = lrc_path.read_text(encoding="utf-8", errors="replace")
                synced = _parse_lrc(text)
                if synced:
                    self._lyrics_panel.set_lyrics(synced)
                    return
                # LRC file exists but no timestamps — treat as plain
                self._lyrics_panel.set_lyrics([], text)
                return
            except OSError:
                pass
        # 2. Try embedded lyrics tags
        plain = _read_embedded_lyrics(path)
        if plain:
            self._lyrics_panel.set_lyrics([], plain)
            return
        # 3. Online lookup, if enabled. Requires Settings (main_window injects it);
        # constructed without Settings (e.g. in unit tests) the network call is skipped.
        if self._settings is None or not self._settings.fetch_lyrics_online:
            self._lyrics_panel.set_lyrics([], None)
            return
        # 3a. Serve from in-memory cache when we've already asked LRCLIB this session.
        cached = self._lyrics_cache.get(track.id)
        if cached is not None:
            self._apply_lyrics_result(*cached)
            return
        # 3b. Otherwise, fetch in a background thread.
        self._lyrics_panel.set_lyrics([], "Searching for lyrics…")
        self._fetch_lyrics_online(track)

    def _fetch_lyrics_online(self, track: Track) -> None:
        task_id = track.id
        self._lyrics_task_id = task_id

        def _worker() -> None:
            synced, plain = _fetch_lrclib(
                track.display_artist,
                track.title or "",
                track.album or "",
                track.duration,
            )
            self._lyrics_ready.emit(task_id, synced, plain)

        threading.Thread(target=_worker, daemon=True).start()

    def _on_lyrics_ready(self, task_id: int, synced_lrc: str, plain: str) -> None:
        # Cache the response unconditionally — even empty results, so we don't
        # re-hit LRCLIB for a track we've already determined has no online lyrics.
        self._lyrics_cache[task_id] = (synced_lrc, plain)
        if len(self._lyrics_cache) > self._PANEL_CACHE_MAX:
            for key in list(self._lyrics_cache.keys())[:-self._PANEL_CACHE_MAX]:
                del self._lyrics_cache[key]
        if task_id != self._lyrics_task_id:
            return  # stale result — track changed while fetch was in flight
        self._apply_lyrics_result(synced_lrc, plain)

    def _apply_lyrics_result(self, synced_lrc: str, plain: str) -> None:
        if synced_lrc:
            parsed = _parse_lrc(synced_lrc)
            if parsed:
                self._lyrics_panel.set_lyrics(parsed)
                return
        self._lyrics_panel.set_lyrics([], plain or None)

    # ---- Artist info ---------------------------------------------------

    def _load_artist_info(self, track: Track) -> None:
        artist = (track.artist or track.display_artist or "").strip()
        key = artist.casefold()
        self._artist_task_key = ""
        if not artist or key == "unknown artist":
            self._artist_panel.set_empty()
            return
        cached = self._artist_cache.get(key)
        if cached is not None:
            info, image_bytes = cached
            self._artist_panel.set_artist(info, image_bytes)
            return
        if self._settings is None or not self._settings.auto_lookup_metadata:
            self._artist_panel.set_empty()
            return
        self._artist_task_key = key
        self._artist_panel.set_loading(artist)

        def _worker() -> None:
            info = metadata.lookup_artist_info(artist)
            image_bytes = metadata.fetch_artist_image(info) if info and info.image_url else None
            self._artist_ready.emit(key, info, image_bytes)

        threading.Thread(target=_worker, daemon=True).start()

    def _on_artist_ready(self, key: str, info: object, image_bytes: object) -> None:
        image = image_bytes if isinstance(image_bytes, bytes) else None
        if info is not None:
            self._artist_cache[key] = (info, image)
            if len(self._artist_cache) > self._PANEL_CACHE_MAX:
                for cache_key in list(self._artist_cache.keys())[:-self._PANEL_CACHE_MAX]:
                    del self._artist_cache[cache_key]
        if key != self._artist_task_key:
            return
        self._artist_panel.set_artist(info, image)

    # ---- Rating --------------------------------------------------------

    def _on_rating_changed(self, rating: int) -> None:
        if (
            self._current_track is not None
            and self._current_track.is_library_item
            and self._library is not None
        ):
            self._library.update_rating(self._current_track.id, rating)
            self._current_track.rating = rating

    # ---- Queue panel ---------------------------------------------------

    def _refresh_queue(self) -> None:
        self._queue_list.blockSignals(True)
        self._queue_list.clear()
        queue = self.player.queue()
        current = self.player.current_index()
        upcoming = queue[current + 1:current + 1 + 12] if current >= 0 else queue[:12]
        if not upcoming:
            placeholder = QListWidgetItem("Queue is empty.")
            placeholder.setFlags(Qt.NoItemFlags)
            self._queue_list.addItem(placeholder)
            self._queue_list.blockSignals(False)
            return
        base = current + 1 if current >= 0 else 0
        for offset, track in enumerate(upcoming):
            item = QListWidgetItem(f"{track.title}  —  {track.display_artist}")
            item.setData(Qt.UserRole, base + offset)
            self._queue_list.addItem(item)
        self._queue_list.blockSignals(False)

    def _on_queue_double_clicked(self, item: QListWidgetItem) -> None:
        idx = item.data(Qt.UserRole)
        if isinstance(idx, int):
            self.player.play_index(idx)

    def _on_queue_context_menu(self, pos) -> None:
        item = self._queue_list.itemAt(pos)
        if item is None:
            return
        idx = item.data(Qt.UserRole)
        if not isinstance(idx, int):
            return
        queue = self.player.queue()
        track = queue[idx] if 0 <= idx < len(queue) else None
        from PySide6.QtWidgets import QMenu
        menu = QMenu(self)
        play_act = menu.addAction("Play Now")
        remove_act = menu.addAction("Remove from Queue")
        edit_act = None
        if track is not None and getattr(track, "is_library_item", False):
            menu.addSeparator()
            edit_act = menu.addAction("Edit Metadata…")
        try:
            action = menu.exec(self._queue_list.mapToGlobal(pos))
        finally:
            menu.deleteLater()
        if action == play_act:
            self.player.play_index(idx)
        elif action == remove_act:
            self.player.remove_queue_index(idx)
        elif edit_act is not None and action == edit_act:
            self.request_edit_metadata.emit(track)

    def _on_queue_rows_moved(
        self, _parent, src_first: int, src_last: int, _dest, dest_row: int
    ) -> None:
        # QListWidget drag-drop fires rowsMoved; sync to player queue
        # dest_row is the row *before* which items are inserted after the move
        current = self.player.current_index()
        base = current + 1 if current >= 0 else 0
        dst = dest_row if dest_row < src_first else dest_row - 1
        self.player.move_queue_item(base + src_first, base + dst)

    # ---- Helpers -------------------------------------------------------

    @staticmethod
    def _format_strip_text(track: Track) -> str:
        bits: list[str] = []
        ext = Path(track.path).suffix.lstrip(".").upper()
        if ext:
            bits.append(ext)
        elif not track.is_library_item and track.playback_is_location:
            uri = (track.playback_uri or track.path or "").casefold()
            bits.append("Audio CD" if uri.startswith("cdda://") else "Stream")
        if getattr(track, "bitrate", 0):
            kbps = round(track.bitrate / 1000)
            if kbps > 0:
                bits.append(f"{kbps} kbps")
        if getattr(track, "samplerate", 0):
            sr = track.samplerate
            bits.append(f"{sr // 1000} kHz" if sr % 1000 == 0 else f"{sr / 1000:g} kHz")
        return "  ·  ".join(bits)

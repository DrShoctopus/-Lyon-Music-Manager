"""Now Playing view + bottom transport bar."""
from __future__ import annotations

import bisect
import json
import re
import threading
import urllib.parse
import urllib.request
from pathlib import Path
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QFrame, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QPushButton, QScrollArea, QSizePolicy, QSlider,
    QStackedWidget, QVBoxLayout, QWidget,
)

from ..core.library import Library, Track
from ..core.player import Player, RepeatMode
from .transport import (
    HeartButton, NextButton, PlayPauseButton, PrevButton, RepeatButton,
    ShuffleButton, StopButton, VolumeButton,
)
from .widgets import ElidedLabel, StarRatingWidget, cover_pixmap, format_duration, format_ms

# ---- LRC parsing -------------------------------------------------------

_LRC_RE = re.compile(r"\[(\d+):(\d+(?:\.\d+)?)\](.*)")


def _parse_lrc(text: str) -> list[tuple[int, str]]:
    """Return sorted list of (ms, lyric_line) from an LRC string."""
    lines: list[tuple[int, str]] = []
    for raw in text.splitlines():
        m = _LRC_RE.match(raw.strip())
        if m:
            mins = int(m.group(1))
            secs = float(m.group(2))
            ms = int((mins * 60 + secs) * 1000)
            lines.append((ms, m.group(3).strip()))
    lines.sort(key=lambda x: x[0])
    return lines


def _read_embedded_lyrics(path: str) -> str | None:
    """Try to extract embedded lyrics from an audio file via mutagen."""
    try:
        from mutagen.id3 import ID3, USLT

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
        with urllib.request.urlopen(req, timeout=8) as resp:
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
        self._labels: list[QLabel] = []

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self._container = QWidget()
        self._container.setObjectName("lyricsContainer")
        self._vl = QVBoxLayout(self._container)
        self._vl.setAlignment(Qt.AlignTop)
        self._vl.setSpacing(6)
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
            return

        for text in lines_text:
            lbl = QLabel(text or " ")  # non-breaking space for blank lines
            lbl.setWordWrap(True)
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setObjectName("lyricsLine")
            self._vl.addWidget(lbl)
            self._labels.append(lbl)

    def clear(self) -> None:
        self.set_lyrics([], None)

    def update_position(self, pos_ms: int) -> None:
        if not self._synced or not self._labels:
            return
        idx = bisect.bisect_right(self._timestamps, pos_ms) - 1
        idx = max(0, min(idx, len(self._labels) - 1))
        if idx == self._current_line:
            return
        if 0 <= self._current_line < len(self._labels):
            self._labels[self._current_line].setObjectName("lyricsLine")
            self._repolish_label(self._labels[self._current_line])
        self._current_line = idx
        self._labels[idx].setObjectName("lyricsLineCurrent")
        self._repolish_label(self._labels[idx])
        self._scroll.ensureWidgetVisible(self._labels[idx])

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
        if library is not None:
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


# ---- Clickable QLabel --------------------------------------------------

class _ClickableLabel(QLabel):
    clicked = Signal()

    def mousePressEvent(self, ev) -> None:
        if ev.button() == Qt.LeftButton:
            self.clicked.emit()
            ev.accept()
            return
        super().mousePressEvent(ev)


# ---- NowPlayingView ----------------------------------------------------

class NowPlayingView(QWidget):
    """Now Playing screen with cinematic background, panel switcher, and interactive queue."""

    # Emitted from the lyrics-fetch worker thread; always delivered on the main thread.
    _lyrics_ready = Signal(int, str, str)   # task_id, synced_lrc, plain_text

    def __init__(
        self,
        player: Player,
        library: Library | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.player = player
        self._library = library
        self._bg_pixmap: QPixmap | None = None
        self._bg_cache: QPixmap | None = None   # blurred result, invalidated on resize/track change
        self._bg_cache_size: tuple[int, int] = (0, 0)
        self._current_track: Track | None = None
        self._lyrics_task_id: int = 0   # track.id of the in-flight LRCLIB request; 0 = none

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
        info.addStretch(2)
        info.addWidget(self.title)
        info.addWidget(self.artist)
        info.addWidget(self.album)
        info.addSpacing(8)
        info.addWidget(self._rating_widget)
        info.addSpacing(6)
        info.addWidget(self.format_strip)
        info.addWidget(self.position_lbl)
        info.addStretch(3)

        info_w = QWidget()
        info_w.setLayout(info)
        info_w.setMinimumWidth(260)

        # ---- Right panel: Queue / Lyrics / Info switcher
        queue_btn = QPushButton("Queue")
        queue_btn.setCheckable(True)
        queue_btn.setChecked(True)
        queue_btn.setObjectName("panelTab")
        lyrics_btn = QPushButton("Lyrics")
        lyrics_btn.setCheckable(True)
        lyrics_btn.setObjectName("panelTab")
        info_btn = QPushButton("Info")
        info_btn.setCheckable(True)
        info_btn.setObjectName("panelTab")

        tab_row = QHBoxLayout()
        tab_row.setSpacing(4)
        tab_row.addWidget(queue_btn)
        tab_row.addWidget(lyrics_btn)
        tab_row.addWidget(info_btn)
        tab_row.addStretch(1)

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

        self._panel_stack = QStackedWidget()
        self._panel_stack.addWidget(self._queue_list)   # 0: queue
        self._panel_stack.addWidget(self._lyrics_panel)  # 1: lyrics
        self._panel_stack.addWidget(self._info_panel)    # 2: info

        def _make_tab_switch(btn, other1, other2, page):
            def _switch(checked):
                if checked:
                    other1.setChecked(False)
                    other2.setChecked(False)
                    self._panel_stack.setCurrentIndex(page)
                elif not other1.isChecked() and not other2.isChecked():
                    btn.setChecked(True)  # prevent all-unchecked state
            return _switch

        queue_btn.toggled.connect(_make_tab_switch(queue_btn, lyrics_btn, info_btn, 0))
        lyrics_btn.toggled.connect(_make_tab_switch(lyrics_btn, queue_btn, info_btn, 1))
        info_btn.toggled.connect(_make_tab_switch(info_btn, queue_btn, lyrics_btn, 2))

        right_vl = QVBoxLayout()
        right_vl.setSpacing(4)
        right_vl.addLayout(tab_row)
        right_vl.addWidget(self._panel_stack, 1)

        right_w = QWidget()
        right_w.setLayout(right_vl)
        right_w.setMinimumWidth(220)
        right_w.setMaximumWidth(360)

        # ---- Top-level layout
        row = QHBoxLayout()
        row.setSpacing(24)
        row.addWidget(self.cover, 0, Qt.AlignTop)
        row.addWidget(info_w, 1)
        row.addWidget(right_w, 0)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 28, 28, 28)
        layout.addLayout(row, 1)

        # ---- Signals
        player.track_changed.connect(self._on_track)
        player.queue_changed.connect(self._refresh_queue)
        player.position_changed.connect(self._on_position)
        self._lyrics_ready.connect(self._on_lyrics_ready)
        self._refresh_queue()
        # Sync immediately if a track is already playing when this view is created.
        self._on_track(player.current())

    # ---- Cinematic background ------------------------------------------

    def resizeEvent(self, ev) -> None:
        super().resizeEvent(ev)
        if self._bg_pixmap is not None:
            self._bg_cache = None  # invalidate so paintEvent rebuilds at new size
            self.update()

    def paintEvent(self, ev) -> None:
        if self._bg_pixmap is not None and not self._bg_pixmap.isNull():
            size = (self.width(), self.height())
            if self._bg_cache is None or self._bg_cache_size != size:
                self._bg_cache = _blur_pixmap(self._bg_pixmap, size[0], size[1])
                self._bg_cache_size = size
            p = QPainter(self)
            p.drawPixmap(0, 0, self._bg_cache)
            p.end()
        else:
            super().paintEvent(ev)

    def _update_background(self, artwork_path: str | None) -> None:
        if artwork_path:
            pm = QPixmap(artwork_path)
            self._bg_pixmap = pm if not pm.isNull() else None
        else:
            self._bg_pixmap = None
        self._bg_cache = None  # force rebuild on next paint
        self.update()

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
            self._update_background(None)
        else:
            self.title.setText(track.title or "Untitled")
            self.artist.setText(track.display_artist)
            self.album.setText(track.album or "")
            self.format_strip.setText(self._format_strip_text(track))
            self.cover.setPixmap(cover_pixmap(track.artwork_path, 280, "♪"))
            self._rating_widget.set_rating(track.rating)
            self._update_background(track.artwork_path)
            self._load_lyrics(track)
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
        # 3. Fetch from LRCLIB in a background thread
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
        if task_id != self._lyrics_task_id:
            return  # stale result — track changed while fetch was in flight
        if synced_lrc:
            parsed = _parse_lrc(synced_lrc)
            if parsed:
                self._lyrics_panel.set_lyrics(parsed)
                return
        self._lyrics_panel.set_lyrics([], plain or None)

    # ---- Rating --------------------------------------------------------

    def _on_rating_changed(self, rating: int) -> None:
        if self._current_track is not None and self._library is not None:
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
        from PySide6.QtWidgets import QMenu
        menu = QMenu(self)
        play_act = menu.addAction("Play Now")
        remove_act = menu.addAction("Remove from Queue")
        action = menu.exec(self._queue_list.mapToGlobal(pos))
        if action == play_act:
            self.player.play_index(idx)
        elif action == remove_act:
            self.player.remove_queue_index(idx)

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
        if getattr(track, "bitrate", 0):
            kbps = round(track.bitrate / 1000)
            if kbps > 0:
                bits.append(f"{kbps} kbps")
        if getattr(track, "samplerate", 0):
            sr = track.samplerate
            bits.append(f"{sr // 1000} kHz" if sr % 1000 == 0 else f"{sr / 1000:g} kHz")
        return "  ·  ".join(bits)


# ---- TransportBar -------------------------------------------------------

class TransportBar(QWidget):
    """Persistent bottom transport bar."""

    open_now_playing = Signal()
    play_requested = Signal()

    def __init__(
        self,
        player: Player,
        library: Library | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.player = player
        self._library = library
        self._user_dragging = False

        self.bar = QFrame(self)
        self.bar.setObjectName("transport")

        self.thumb = _ClickableLabel()
        self.thumb.setObjectName("transportThumb")
        self.thumb.setFixedSize(68, 68)
        self.thumb.setPixmap(cover_pixmap(None, 68, "♪"))
        self.thumb.setCursor(Qt.PointingHandCursor)
        self.thumb.setAccessibleName("Open Now Playing")
        self.thumb.clicked.connect(self.open_now_playing.emit)

        self.title_lbl = ElidedLabel("Nothing playing")
        self.title_lbl.setObjectName("nowPlayingTitle")
        self.artist_lbl = ElidedLabel("")
        self.artist_lbl.setObjectName("nowPlayingArtist")

        meta = QVBoxLayout()
        meta.setSpacing(0)
        meta.addStretch(1)
        meta.addWidget(self.title_lbl)
        meta.addWidget(self.artist_lbl)
        meta.addStretch(1)

        meta_w = QWidget()
        meta_w.setLayout(meta)
        meta_w.setMinimumWidth(180)
        meta_w.setMaximumWidth(340)
        meta_w.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)

        self.heart_btn = HeartButton()
        self.heart_btn.setEnabled(False)
        self.heart_btn.toggled.connect(self._on_heart_toggled)

        self.shuffle_btn = ShuffleButton()
        self.repeat_btn = RepeatButton()
        self.stop_btn = StopButton()
        self.prev_btn = PrevButton()
        self.next_btn = NextButton()
        self.play_btn = PlayPauseButton()
        self.vol_btn = VolumeButton()
        self.vol_btn.set_state(player.volume(), player.is_muted())

        self.play_btn.clicked.connect(self.play_requested.emit)
        self.prev_btn.clicked.connect(player.previous)
        self.next_btn.clicked.connect(player.next)
        self.stop_btn.clicked.connect(player.stop)
        self.shuffle_btn.toggled.connect(player.set_shuffle)
        self.shuffle_btn.setChecked(player.shuffle())
        self.repeat_btn.set_state(self._repeat_to_int(player.repeat()))
        self.repeat_btn.state_changed.connect(self._on_repeat_clicked)
        self.vol_btn.toggled.connect(self._on_mute_toggled)

        controls = QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(6)
        controls.addWidget(self.shuffle_btn)
        controls.addWidget(self.repeat_btn)
        controls.addWidget(self.stop_btn)
        controls.addSpacing(6)
        controls.addWidget(self.prev_btn)
        controls.addWidget(self.play_btn)
        controls.addWidget(self.next_btn)
        controls.setAlignment(Qt.AlignCenter)

        self.elapsed_lbl = QLabel("0:00")
        self.elapsed_lbl.setObjectName("timeLabel")
        self.elapsed_lbl.setMinimumWidth(42)
        self.elapsed_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.total_lbl = QLabel("0:00")
        self.total_lbl.setObjectName("timeLabel")
        self.total_lbl.setMinimumWidth(42)
        self.total_lbl.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.seek = QSlider(Qt.Horizontal)
        self.seek.setRange(0, 0)
        self.seek.setAccessibleName("Seek position")
        self.seek.sliderPressed.connect(lambda: setattr(self, "_user_dragging", True))
        self.seek.sliderReleased.connect(self._on_seek_release)

        seek_row = QHBoxLayout()
        seek_row.setContentsMargins(0, 0, 0, 0)
        seek_row.setSpacing(6)
        seek_row.addWidget(self.elapsed_lbl)
        seek_row.addWidget(self.seek, 1)
        seek_row.addWidget(self.total_lbl)

        center = QVBoxLayout()
        center.setContentsMargins(0, 0, 0, 0)
        center.setSpacing(6)
        center.addLayout(controls)
        center.addLayout(seek_row)

        center_w = QWidget()
        center_w.setLayout(center)
        center_w.setMinimumWidth(330)
        center_w.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        self.vol = QSlider(Qt.Horizontal)
        self.vol.setRange(0, 100)
        self.vol.setValue(player.volume())
        self.vol.setObjectName("volumeSlider")
        self.vol.setMinimumWidth(100)
        self.vol.setMaximumWidth(150)
        self.vol.setAccessibleName("Volume")
        self.vol.valueChanged.connect(self._on_volume_slider)

        vol_row = QHBoxLayout()
        vol_row.setContentsMargins(0, 0, 0, 0)
        vol_row.setSpacing(4)
        vol_row.addWidget(self.vol_btn)
        vol_row.addWidget(self.vol)

        bar_layout = QHBoxLayout(self.bar)
        bar_layout.setContentsMargins(18, 8, 18, 8)
        bar_layout.setSpacing(12)
        bar_layout.addWidget(self.thumb)
        bar_layout.addWidget(meta_w)
        bar_layout.addWidget(self.heart_btn)
        bar_layout.addStretch(1)
        bar_layout.addWidget(center_w, 3)
        bar_layout.addStretch(1)
        bar_layout.addLayout(vol_row)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self.bar)

        player.track_changed.connect(self._on_track)
        player.position_changed.connect(self._on_position)
        player.state_changed.connect(self._on_state)

    @staticmethod
    def _repeat_to_int(mode: RepeatMode) -> int:
        return {RepeatMode.OFF: 0, RepeatMode.ALL: 1, RepeatMode.ONE: 2}[mode]

    def _on_repeat_clicked(self, _state: int) -> None:
        mode = self.player.cycle_repeat()
        self.repeat_btn.set_state(self._repeat_to_int(mode))

    def _on_volume_slider(self, value: int) -> None:
        self.player.set_volume(value)
        self.vol_btn.set_state(value, self.player.is_muted())

    def _on_track(self, track: Track | None) -> None:
        if track is None:
            self.title_lbl.setText("Nothing playing")
            self.artist_lbl.setText("")
            self.thumb.setPixmap(cover_pixmap(None, 68, "♪"))
            self.heart_btn.blockSignals(True)
            self.heart_btn.setChecked(False)
            self.heart_btn.blockSignals(False)
            self.heart_btn.setEnabled(False)
        else:
            self.title_lbl.setText(track.title)
            self.artist_lbl.setText(f"{track.display_artist} - {track.album}")
            self.thumb.setPixmap(cover_pixmap(track.artwork_path, 68, "♪"))
            self.heart_btn.blockSignals(True)
            self.heart_btn.setChecked(track.liked)
            self.heart_btn.blockSignals(False)
            self.heart_btn.setEnabled(self._library is not None)

    def _on_position(self, pos_ms: int, dur_ms: int) -> None:
        if not self._user_dragging:
            self.seek.blockSignals(True)
            self.seek.setRange(0, max(0, dur_ms))
            self.seek.setValue(pos_ms)
            self.seek.blockSignals(False)
        self.elapsed_lbl.setText(format_ms(pos_ms))
        self.total_lbl.setText(format_ms(dur_ms))

    def _on_mute_toggled(self, muted: bool) -> None:
        self.player.set_muted(muted)
        self.vol_btn.set_state(self.vol.value(), muted)

    def _on_heart_toggled(self, liked: bool) -> None:
        track = self.player.current()
        if track is not None and self._library is not None:
            track.liked = liked
            self._library.update_liked(track.id, liked)

    def _on_state(self, state: str) -> None:
        self.play_btn.set_playing(state == "playing")
        self.vol_btn.set_state(self.vol.value(), self.player.is_muted())

    def _on_seek_release(self) -> None:
        self.player.seek(self.seek.value())
        self._user_dragging = False

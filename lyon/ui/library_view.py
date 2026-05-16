"""Library browser: artists -> albums -> tracks, plus search."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEvent, QModelIndex, QRect, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QColor, QDesktopServices, QIcon, QKeySequence, QPainter, QPixmap, QShortcut,
    QStandardItem, QStandardItemModel,
)
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QDialog, QDialogButtonBox, QFormLayout,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListView, QMenu, QPushButton,
    QSpinBox, QSplitter, QStackedWidget, QStyledItemDelegate, QStyleOptionViewItem,
    QTableView, QVBoxLayout, QWidget,
)

from ..core.library import Library, Track
from .widgets import StarRatingWidget, format_duration


# Sentinel stored in Qt.UserRole on the synthetic "All Albums" album row.
_ALL_ALBUMS_KEY = "__all_albums__"
_ALL_GENRES_KEY = "__all_genres__"

# Sentinels for virtual collections shown at the top of the artist list.
_RECENTLY_ADDED_KEY = "__recently_added__"
_RECENTLY_PLAYED_KEY = "__recently_played__"
_MOST_PLAYED_KEY = "__most_played__"
_TOP_RATED_KEY = "__top_rated__"

_VIRTUAL_COLLECTIONS: list[tuple[str, str]] = [
    (_RECENTLY_ADDED_KEY, "Recently Added"),
    (_RECENTLY_PLAYED_KEY, "Recently Played"),
    (_MOST_PLAYED_KEY, "Most Played"),
    (_TOP_RATED_KEY, "Top Rated ★★★★+"),
]

# Roles used on the tracks model:
#   Qt.UserRole         -> per-column sort key (int for #/Time/Rating, lowercase str otherwise)
#   _TRACK_REF_ROLE     -> Track reference stored on column 0 only
_TRACK_REF_ROLE = Qt.UserRole + 1

_PLAYING_GLYPH = "▶"

# Track table column indices — single source of truth.
_COL_NUM = 0
_COL_TITLE = 1
_COL_ARTIST = 2
_COL_ALBUM = 3
_COL_TIME = 4
_COL_RATING = 5
_COL_FORMAT = 6
_NUM_COLS = 7

# Format badge colors (file extension → background hex)
_FORMAT_COLORS: dict[str, str] = {
    "FLAC": "#2e7d32", "ALAC": "#2e7d32",
    "MP3": "#546e7a",
    "AAC": "#1565c0", "M4A": "#1565c0",
    "OGG": "#00695c", "OPUS": "#00695c",
    "WAV": "#e65100", "AIFF": "#e65100",
    "WMA": "#4527a0",
}


class _StarDelegate(QStyledItemDelegate):
    """Paints 5-star ratings in the Rating column and handles in-place editing."""

    _FILLED = "★"
    _EMPTY = "☆"
    _GAP = 2

    def __init__(self, library: Library, parent=None) -> None:
        super().__init__(parent)
        self._library = library

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        self.initStyleOption(option, index)
        rating = int(index.data(Qt.UserRole) or 0)
        painter.save()
        painter.setRenderHint(QPainter.TextAntialiasing)
        fm = painter.fontMetrics()
        sw = fm.horizontalAdvance(self._FILLED)
        total_w = sw * 5 + self._GAP * 4
        x = option.rect.x() + (option.rect.width() - total_w) // 2
        y = option.rect.y() + (option.rect.height() - fm.height()) // 2 + fm.ascent()
        for i in range(5):
            painter.setPen(QColor("#f5a623") if i < rating else QColor("#555e70"))
            painter.drawText(x, y, self._FILLED if i < rating else self._EMPTY)
            x += sw + self._GAP
        painter.restore()

    def editorEvent(
        self,
        event: QEvent,
        model: QStandardItemModel,
        option: QStyleOptionViewItem,
        index: QModelIndex,
    ) -> bool:
        if event.type() != QEvent.MouseButtonPress:
            return False
        track_item = model.item(index.row(), _COL_NUM)
        if track_item is None:
            return False
        track = track_item.data(_TRACK_REF_ROLE)
        if not isinstance(track, Track):
            return False
        fm = self.parent().fontMetrics() if self.parent() else option.widget.fontMetrics()
        sw = fm.horizontalAdvance(self._FILLED)
        total_w = sw * 5 + self._GAP * 4
        star_x = option.rect.x() + (option.rect.width() - total_w) // 2
        click_x = event.position().x()
        clicked_star = -1
        for i in range(5):
            if star_x <= click_x < star_x + sw:
                clicked_star = i
                break
            star_x += sw + self._GAP
        if clicked_star < 0:
            return False
        current = index.data(Qt.UserRole) or 0
        new_rating = clicked_star + 1 if clicked_star + 1 != current else 0
        self._library.update_rating(track.id, new_rating)
        # Update track reference so subsequent sorts work without a full refresh
        track.rating = new_rating
        model.setData(index, new_rating, Qt.UserRole)
        return True


class _FormatDelegate(QStyledItemDelegate):
    """Renders a coloured rounded-rectangle chip showing the audio format."""

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        fmt = (index.data(Qt.DisplayRole) or "").upper()
        if not fmt:
            return
        color = QColor(_FORMAT_COLORS.get(fmt, "#546e7a"))
        rect = option.rect.adjusted(5, 3, -5, -3)
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(color)
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(rect, 3, 3)
        painter.setPen(QColor("#ffffff"))
        f = painter.font()
        f.setPointSize(max(6, f.pointSize() - 1))
        painter.setFont(f)
        painter.drawText(rect, Qt.AlignCenter, fmt)
        painter.restore()

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        return QSize(60, option.rect.height())


class LibraryView(QWidget):
    play_tracks = Signal(list, int)        # (tracks, start_index)
    enqueue_tracks = Signal(list)
    status_message = Signal(str)
    request_rescan = Signal()
    request_add_folder = Signal()
    request_youtube_search = Signal(str)
    request_open_settings = Signal()
    request_diagnostics = Signal()

    def __init__(self, library: Library, parent: QWidget | None = None):
        super().__init__(parent)
        self.library = library
        self._current_tracks: list[Track] = []
        self._currently_playing: Track | None = None
        self._show_videos: bool = False

        # ---- Top toolbar
        top = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search artist, album, or track...")
        self.search.setAccessibleName("Library search")
        self.search.setClearButtonEnabled(True)
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(150)
        self._search_timer.timeout.connect(self._do_search)
        self.search.textChanged.connect(self._on_search)

        self.play_btn = QPushButton("Play")
        self.play_btn.clicked.connect(self._play_selected)
        self.enqueue_btn = QPushButton("Enqueue")
        self.enqueue_btn.clicked.connect(self._enqueue_selected)
        rescan_btn = QPushButton("Rescan")
        rescan_btn.clicked.connect(self.request_rescan.emit)
        self._show_videos_cb = QCheckBox("Show Videos")
        self._show_videos_cb.setChecked(False)
        self._show_videos_cb.toggled.connect(self._on_show_videos_toggled)
        self._grid_mode_btn = QPushButton("⊞")
        self._grid_mode_btn.setCheckable(True)
        self._grid_mode_btn.setToolTip("Album grid view")
        self._grid_mode_btn.setFixedWidth(32)
        self._grid_mode_btn.toggled.connect(self._on_view_mode_toggled)
        top.addWidget(self.search, 1)
        top.addWidget(self.play_btn)
        top.addWidget(self.enqueue_btn)
        top.addWidget(rescan_btn)
        top.addWidget(self._show_videos_cb)
        top.addWidget(self._grid_mode_btn)

        # ---- Genres / Artists / Albums lists
        self.genres = QListView()
        self.genres.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.genres_model = QStandardItemModel()
        self.genres.setModel(self.genres_model)

        self.artists = QListView()
        self.artists.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.artists_model = QStandardItemModel()
        self.artists.setModel(self.artists_model)

        self.albums = QListView()
        self.albums.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.albums.setIconSize(QSize(48, 48))
        self.albums_model = QStandardItemModel()
        self.albums.setModel(self.albums_model)

        # ---- Tracks table (sortable)
        self.tracks = QTableView()
        self.tracks.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tracks.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tracks.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tracks.setAlternatingRowColors(True)
        self.tracks.setMouseTracking(True)
        self.tracks.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tracks.customContextMenuRequested.connect(self._show_track_context_menu)
        self.tracks.verticalHeader().setVisible(False)

        self.tracks_model = QStandardItemModel(0, _NUM_COLS)
        self.tracks_model.setHorizontalHeaderLabels(
            ["#", "Title", "Artist", "Album", "Time", "Rating", "Format"]
        )
        # Sort using a dedicated UserRole key so # / Time / Rating sort numerically and
        # text columns collate case-insensitively.
        self.tracks_model.setSortRole(Qt.UserRole)
        self.tracks.setModel(self.tracks_model)
        self.tracks.setSortingEnabled(True)
        self.tracks.sortByColumn(0, Qt.AscendingOrder)

        self._star_delegate = _StarDelegate(self.library, self.tracks)
        self.tracks.setItemDelegateForColumn(_COL_RATING, self._star_delegate)
        self._format_delegate = _FormatDelegate(self.tracks)
        self.tracks.setItemDelegateForColumn(_COL_FORMAT, self._format_delegate)

        header = self.tracks.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(_COL_NUM,    QHeaderView.Fixed)
        header.setSectionResizeMode(_COL_TITLE,  QHeaderView.Stretch)
        header.setSectionResizeMode(_COL_ARTIST, QHeaderView.Interactive)
        header.setSectionResizeMode(_COL_ALBUM,  QHeaderView.Interactive)
        header.setSectionResizeMode(_COL_TIME,   QHeaderView.Fixed)
        header.setSectionResizeMode(_COL_RATING, QHeaderView.Fixed)
        header.setSectionResizeMode(_COL_FORMAT, QHeaderView.Fixed)
        self.tracks.setColumnWidth(_COL_NUM,    50)
        self.tracks.setColumnWidth(_COL_ARTIST, 180)
        self.tracks.setColumnWidth(_COL_ALBUM,  200)
        self.tracks.setColumnWidth(_COL_TIME,   70)
        self.tracks.setColumnWidth(_COL_RATING, 90)
        self.tracks.setColumnWidth(_COL_FORMAT, 62)
        header.setContextMenuPolicy(Qt.CustomContextMenu)
        header.customContextMenuRequested.connect(self._show_header_context_menu)

        # Keyboard shortcuts scoped to the tracks table
        QShortcut(QKeySequence(Qt.Key_Return), self.tracks,
                  activated=self._play_selected, context=Qt.WidgetShortcut)
        QShortcut(QKeySequence(Qt.Key_Enter), self.tracks,
                  activated=self._play_selected, context=Qt.WidgetShortcut)
        QShortcut(QKeySequence("Ctrl+E"), self.tracks,
                  activated=self._enqueue_selected, context=Qt.WidgetShortcut)

        # ---- List-mode browser: 4-pane splitter (Genres | Artists | Albums | Tracks)
        splitter = QSplitter(Qt.Horizontal)
        for w, label in (
            (self.genres,  "Genres"),
            (self.artists, "Artists"),
            (self.albums,  "Albums"),
        ):
            box = QWidget()
            v = QVBoxLayout(box)
            v.setContentsMargins(0, 0, 0, 0)
            heading = QLabel(label)
            heading.setObjectName("sectionHeading")
            v.addWidget(heading)
            v.addWidget(w)
            splitter.addWidget(box)
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rh = QLabel("Tracks")
        rh.setObjectName("sectionHeading")
        rv.addWidget(rh)
        rv.addWidget(self.tracks)
        splitter.addWidget(right)
        splitter.setSizes([130, 170, 210, 590])

        # ---- Grid-mode browser (shared genres model + album art grid)
        self._grid_genres = QListView()
        self._grid_genres.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._grid_genres.setModel(self.genres_model)

        self._grid_albums_model = QStandardItemModel()
        self._grid_albums_view = QListView()
        self._grid_albums_view.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._grid_albums_view.setModel(self._grid_albums_model)
        self._grid_albums_view.setViewMode(QListView.IconMode)
        self._grid_albums_view.setIconSize(QSize(160, 160))
        self._grid_albums_view.setGridSize(QSize(190, 215))
        self._grid_albums_view.setResizeMode(QListView.Adjust)
        self._grid_albums_view.setUniformItemSizes(True)
        self._grid_albums_view.setWordWrap(True)
        self._grid_albums_view.setSpacing(6)
        self._grid_albums_view.setMovement(QListView.Static)

        gg_box = QWidget()
        gg_vl = QVBoxLayout(gg_box)
        gg_vl.setContentsMargins(0, 0, 0, 0)
        gg_lbl = QLabel("Genres")
        gg_lbl.setObjectName("sectionHeading")
        gg_vl.addWidget(gg_lbl)
        gg_vl.addWidget(self._grid_genres)

        ga_box = QWidget()
        ga_vl = QVBoxLayout(ga_box)
        ga_vl.setContentsMargins(0, 0, 0, 0)
        ga_lbl = QLabel("Albums")
        ga_lbl.setObjectName("sectionHeading")
        ga_vl.addWidget(ga_lbl)
        ga_vl.addWidget(self._grid_albums_view)

        grid_inner = QSplitter(Qt.Horizontal)
        grid_inner.addWidget(gg_box)
        grid_inner.addWidget(ga_box)
        grid_inner.setSizes([150, 850])

        grid_widget = QWidget()
        grid_vl = QVBoxLayout(grid_widget)
        grid_vl.setContentsMargins(0, 0, 0, 0)
        grid_vl.addWidget(grid_inner)

        # ---- Empty-state (library has no tracks at all)
        empty_widget = QWidget()
        empty_layout = QVBoxLayout(empty_widget)
        empty_layout.setAlignment(Qt.AlignCenter)
        empty_layout.setSpacing(16)

        empty_text = QLabel("No music found.\nAdd a folder to start building your library.")
        empty_text.setAlignment(Qt.AlignCenter)
        empty_text.setObjectName("emptyStateText")
        empty_layout.addWidget(empty_text)

        empty_btns = QHBoxLayout()
        empty_btns.setSpacing(8)
        empty_btns.setAlignment(Qt.AlignCenter)
        _add_btn = QPushButton("Add Folder")
        _add_btn.setObjectName("accent")
        _add_btn.clicked.connect(self.request_add_folder.emit)
        _settings_btn = QPushButton("Open Settings")
        _settings_btn.clicked.connect(self.request_open_settings.emit)
        _diag_btn = QPushButton("Run Diagnostics")
        _diag_btn.clicked.connect(self.request_diagnostics.emit)
        empty_btns.addWidget(_add_btn)
        empty_btns.addWidget(_settings_btn)
        empty_btns.addWidget(_diag_btn)
        empty_layout.addLayout(empty_btns)

        self._browser_stack = QStackedWidget()
        self._browser_stack.addWidget(empty_widget)  # 0: empty
        self._browser_stack.addWidget(splitter)       # 1: list browser
        self._browser_stack.addWidget(grid_widget)    # 2: grid browser

        # ---- Footer
        self._footer_label = QLabel("")
        self._footer_label.setObjectName("footerText")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addLayout(top)
        layout.addWidget(self._browser_stack, 1)
        layout.addWidget(self._footer_label)

        self.genres.selectionModel().currentChanged.connect(lambda *_: self._refresh_artists())
        self.artists.selectionModel().currentChanged.connect(lambda *_: self._refresh_albums())
        self.albums.selectionModel().currentChanged.connect(lambda *_: self._refresh_tracks())
        self.tracks.doubleClicked.connect(self._on_track_double)
        self._grid_genres.selectionModel().currentChanged.connect(
            lambda *_: self._refresh_grid_albums()
        )
        self._grid_albums_view.doubleClicked.connect(self._on_grid_album_activated)

        self.refresh()

    # ------------------------------------------------------------------ data
    @property
    def _media_type_filter(self) -> str | None:
        return None if self._show_videos else "audio"

    def _on_show_videos_toggled(self, checked: bool) -> None:
        self._show_videos = checked
        self.refresh()

    def refresh(self) -> None:
        has_tracks = bool(self.library.all_artists())

        # Populate genres pane (both list and grid share genres_model)
        self.genres_model.clear()
        ag_item = QStandardItem("All Genres")
        ag_item.setData(_ALL_GENRES_KEY, Qt.UserRole)
        f = ag_item.font(); f.setItalic(True); ag_item.setFont(f)
        self.genres_model.appendRow(ag_item)
        for g in self.library.all_genres(self._media_type_filter):
            it = QStandardItem(g); it.setData(g, Qt.UserRole)
            self.genres_model.appendRow(it)

        # Reset genre selection to "All Genres" without firing signal
        self.genres.blockSignals(True)
        self.genres.setCurrentIndex(self.genres_model.index(0, 0))
        self.genres.blockSignals(False)

        if has_tracks:
            # Preserve view mode across refresh
            current_page = self._browser_stack.currentIndex()
            self._browser_stack.setCurrentIndex(max(1, current_page))
            self._refresh_artists()
            if self._browser_stack.currentIndex() == 2:
                self._refresh_grid_albums()
        else:
            self._browser_stack.setCurrentIndex(0)
            self.artists_model.clear()
            self.albums_model.clear()
            self.tracks_model.removeRows(0, self.tracks_model.rowCount())
            self._current_tracks = []
            self._update_footer()

    def _refresh_artists(self) -> None:
        """Repopulate artist list filtered by current genre selection."""
        genre_idx = self.genres.currentIndex()
        genre_key = genre_idx.data(Qt.UserRole) if genre_idx.isValid() else _ALL_GENRES_KEY
        genre = None if genre_key == _ALL_GENRES_KEY else genre_key

        self.artists_model.clear()
        for key, label in _VIRTUAL_COLLECTIONS:
            item = QStandardItem(label)
            item.setData(key, Qt.UserRole)
            fnt = item.font(); fnt.setItalic(True); item.setFont(fnt)
            self.artists_model.appendRow(item)
        real_artists = self.library.all_artists(self._media_type_filter, genre=genre)
        for a in real_artists:
            it = QStandardItem(a); it.setData(a, Qt.UserRole)
            self.artists_model.appendRow(it)

        if real_artists:
            self.artists.setCurrentIndex(
                self.artists_model.index(len(_VIRTUAL_COLLECTIONS), 0)
            )
        else:
            self.artists.setCurrentIndex(self.artists_model.index(0, 0))

    _VIRTUAL_KEYS = frozenset(k for k, _ in _VIRTUAL_COLLECTIONS)

    def _refresh_albums(self) -> None:
        self.albums_model.clear()
        idx = self.artists.currentIndex()
        if not idx.isValid():
            self._current_tracks = []
            self.tracks_model.removeRows(0, self.tracks_model.rowCount())
            self._update_footer()
            return
        artist_key = idx.data(Qt.UserRole)
        # Virtual collection selected — clear album pane and populate tracks directly
        if artist_key in self._VIRTUAL_KEYS:
            self.albums_model.clear()
            self._populate_virtual_collection(artist_key)
            return
        artist = idx.data(Qt.DisplayRole)
        albums = list(self.library.albums_for_artist(artist, self._media_type_filter))
        # When the artist has multiple albums, offer an "All Albums" view.
        if len(albums) >= 2:
            all_item = QStandardItem("All Albums")
            all_item.setData(_ALL_ALBUMS_KEY, Qt.UserRole)
            font = all_item.font()
            font.setItalic(True)
            all_item.setFont(font)
            self.albums_model.appendRow(all_item)
        for album, _art in albums:
            it = QStandardItem(album)
            it.setData(album, Qt.UserRole)
            if _art:
                pm = QPixmap(_art)
                if not pm.isNull():
                    it.setIcon(QIcon(pm.scaled(48, 48, Qt.KeepAspectRatio, Qt.SmoothTransformation)))
                else:
                    it.setForeground(QColor("#888888"))
            else:
                it.setForeground(QColor("#888888"))
            self.albums_model.appendRow(it)
        if self.albums_model.rowCount():
            self.albums.setCurrentIndex(self.albums_model.index(0, 0))
        else:
            self._current_tracks = []
            self.tracks_model.removeRows(0, self.tracks_model.rowCount())
            self._update_footer()

    def _populate_virtual_collection(self, key: str) -> None:
        mt = self._media_type_filter
        if key == _RECENTLY_ADDED_KEY:
            tracks = self.library.recently_added(50, mt)
        elif key == _RECENTLY_PLAYED_KEY:
            tracks = self.library.recently_played(50, mt)
        elif key == _MOST_PLAYED_KEY:
            tracks = self.library.most_played(50, mt)
        elif key == _TOP_RATED_KEY:
            tracks = self.library.top_rated(4, 100, mt)
        else:
            return
        self._current_tracks = tracks
        self._populate_tracks(tracks)

    # ------------------------------------------------------------------ grid view
    def _on_view_mode_toggled(self, checked: bool) -> None:
        if checked:
            if self._browser_stack.currentIndex() == 0:
                # Empty library — revert toggle
                self._grid_mode_btn.blockSignals(True)
                self._grid_mode_btn.setChecked(False)
                self._grid_mode_btn.blockSignals(False)
                return
            self._browser_stack.setCurrentIndex(2)
            self._refresh_grid_albums()
        else:
            has_tracks = bool(self.library.all_artists())
            self._browser_stack.setCurrentIndex(1 if has_tracks else 0)

    def _refresh_grid_albums(self) -> None:
        """Populate the album art grid for the selected genre."""
        self._grid_albums_model.clear()
        genre_idx = self._grid_genres.currentIndex()
        genre_key = genre_idx.data(Qt.UserRole) if genre_idx.isValid() else _ALL_GENRES_KEY
        genre = None if genre_key == _ALL_GENRES_KEY else genre_key

        if genre is None:
            albums = self.library.all_albums()
        else:
            tracks = self.library.tracks_for_genre(genre, self._media_type_filter)
            seen: set[tuple[str, str]] = set()
            albums = []
            for t in tracks:
                key_t = (t.display_artist, t.album or "Unknown Album")
                if key_t not in seen:
                    seen.add(key_t)
                    albums.append((t.display_artist, t.album or "Unknown Album", t.artwork_path))

        for artist, album, art in albums:
            pm = QPixmap(art) if art else None
            if pm and pm.isNull():
                pm = None
            icon = (
                QIcon(pm.scaled(160, 160, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                if pm else QIcon()
            )
            it = QStandardItem(icon, f"{album}\n{artist}")
            it.setData((artist, album), Qt.UserRole)
            it.setTextAlignment(Qt.AlignHCenter | Qt.AlignTop)
            self._grid_albums_model.appendRow(it)

    def _on_grid_album_activated(self, index: QModelIndex) -> None:
        data = index.data(Qt.UserRole)
        if not isinstance(data, tuple) or len(data) != 2:
            return
        artist, album = data
        # Switch back to list mode and navigate to the album
        self._grid_mode_btn.blockSignals(True)
        self._grid_mode_btn.setChecked(False)
        self._grid_mode_btn.blockSignals(False)
        self._browser_stack.setCurrentIndex(1)
        self._navigate_to_album(artist, album)

    def _navigate_to_album(self, artist: str, album: str) -> None:
        # Reset genre to "All Genres" so the artist is always visible
        if self.genres_model.rowCount():
            self.genres.blockSignals(True)
            self.genres.setCurrentIndex(self.genres_model.index(0, 0))
            self.genres.blockSignals(False)
        self._refresh_artists()
        # Find and select the artist row
        for row in range(self.artists_model.rowCount()):
            idx = self.artists_model.index(row, 0)
            if idx.data(Qt.UserRole) not in self._VIRTUAL_KEYS:
                if idx.data(Qt.DisplayRole) == artist:
                    self.artists.setCurrentIndex(idx)
                    break
        # Find and select the album row (after _refresh_albums fires via signal)
        album_row = self._find_model_row(self.albums_model, album)
        if album_row >= 0:
            self.albums.setCurrentIndex(self.albums_model.index(album_row, 0))

    def _show_header_context_menu(self, pos) -> None:
        menu = QMenu(self)
        rating_act = menu.addAction("Rating")
        rating_act.setCheckable(True)
        rating_act.setChecked(not self.tracks.isColumnHidden(_COL_RATING))
        format_act = menu.addAction("Format")
        format_act.setCheckable(True)
        format_act.setChecked(not self.tracks.isColumnHidden(_COL_FORMAT))
        action = menu.exec(self.tracks.horizontalHeader().mapToGlobal(pos))
        if action == rating_act:
            self.tracks.setColumnHidden(_COL_RATING, not rating_act.isChecked())
        elif action == format_act:
            self.tracks.setColumnHidden(_COL_FORMAT, not format_act.isChecked())

    def _refresh_tracks(self) -> None:
        ai = self.artists.currentIndex()
        # Virtual collection already populated tracks in _refresh_albums; nothing to do here.
        if ai.isValid() and ai.data(Qt.UserRole) in self._VIRTUAL_KEYS:
            return
        bi = self.albums.currentIndex()
        if not ai.isValid() or not bi.isValid():
            self._current_tracks = []
            self.tracks_model.removeRows(0, self.tracks_model.rowCount())
            self._update_footer()
            return
        artist = ai.data(Qt.DisplayRole)
        album_key = bi.data(Qt.UserRole)
        if album_key == _ALL_ALBUMS_KEY:
            self._current_tracks = self.library.tracks_for_artist(artist, self._media_type_filter)
        else:
            album = album_key if isinstance(album_key, str) else bi.data(Qt.DisplayRole)
            self._current_tracks = self.library.tracks_for_album(artist, album, self._media_type_filter)
        self._populate_tracks(self._current_tracks)

    def _populate_tracks(self, tracks: list[Track]) -> None:
        # Disable sorting while filling so the view doesn't re-sort per insert.
        self.tracks.setSortingEnabled(False)
        self.tracks_model.removeRows(0, self.tracks_model.rowCount())
        for tr in tracks:
            duration = format_duration(tr.duration)
            tooltip = self._track_tooltip(tr, duration)

            n_item = QStandardItem(str(tr.track_no or ""))
            n_item.setData(int(tr.track_no or 0), Qt.UserRole)
            n_item.setData(tr, _TRACK_REF_ROLE)
            n_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)

            title_item = QStandardItem(tr.title)
            title_item.setData((tr.title or "").lower(), Qt.UserRole)

            artist_item = QStandardItem(tr.artist)
            artist_item.setData((tr.artist or "").lower(), Qt.UserRole)

            album_item = QStandardItem(tr.album)
            album_item.setData((tr.album or "").lower(), Qt.UserRole)

            time_item = QStandardItem(duration)
            time_item.setData(int(tr.duration or 0), Qt.UserRole)
            time_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)

            rating_item = QStandardItem("")
            rating_item.setData(int(tr.rating or 0), Qt.UserRole)

            fmt = Path(tr.path).suffix.lstrip(".").upper() or ""
            format_item = QStandardItem(fmt)
            format_item.setData(fmt.lower(), Qt.UserRole)

            for it in (n_item, title_item, artist_item, album_item, time_item, rating_item, format_item):
                it.setEditable(False)
                it.setToolTip(tooltip)
            self.tracks_model.appendRow(
                [n_item, title_item, artist_item, album_item, time_item, rating_item, format_item]
            )
        self.tracks.setSortingEnabled(True)
        self._refresh_playing_indicator()
        self._update_footer()

    def _update_footer(self) -> None:
        count = len(self._current_tracks)
        if count == 0:
            q = self.search.text().strip()
            self._footer_label.setText(f'No tracks match "{q}"' if q else "")
            return
        total_s = sum(int(t.duration) for t in self._current_tracks)
        h, remainder = divmod(total_s, 3600)
        m, s = divmod(remainder, 60)
        if h:
            duration_str = f"{h} hr {m} min"
        else:
            duration_str = f"{m} min {s} sec"
        plural = "track" if count == 1 else "tracks"
        self._footer_label.setText(f"{count} {plural} — {duration_str}")

    # ------------------------------------------------------------------ row lookup
    def _track_at_row(self, row: int) -> Track | None:
        item = self.tracks_model.item(row, 0)
        if item is None:
            return None
        track = item.data(_TRACK_REF_ROLE)
        return track if isinstance(track, Track) else None

    def _displayed_tracks(self) -> list[Track]:
        out: list[Track] = []
        for r in range(self.tracks_model.rowCount()):
            t = self._track_at_row(r)
            if t is not None:
                out.append(t)
        return out

    # ------------------------------------------------------------------ details / tooltip
    @staticmethod
    def _track_details(track: Track, duration: str) -> list[tuple[str, str]]:
        file_type = Path(track.path).suffix.lstrip(".").upper() or "Unknown"
        artist = track.display_artist
        album = track.album or "Unknown Album"
        bitrate = LibraryView._format_bitrate(track.bitrate)
        sample_rate = LibraryView._format_sample_rate(track.samplerate)
        return [
            ("Title", track.title),
            ("Artist", artist),
            ("Album", album),
            ("Time", duration),
            ("Bitrate", bitrate),
            ("Sample rate", sample_rate),
            ("File type", file_type),
            ("File location", track.path),
        ]

    @staticmethod
    def _track_tooltip(track: Track, duration: str) -> str:
        return "\n".join(
            f"{label}: {value}"
            for label, value in LibraryView._track_details(track, duration)
        )

    @staticmethod
    def _format_bitrate(bitrate: int) -> str:
        if bitrate <= 0:
            return "Unknown"
        kbps = round(bitrate / 1000)
        if kbps <= 0:
            return f"{bitrate} bps"
        return f"{kbps} kbps"

    @staticmethod
    def _format_sample_rate(sample_rate: int) -> str:
        if sample_rate <= 0:
            return "Unknown"
        if sample_rate % 1000 == 0:
            return f"{sample_rate // 1000} kHz"
        return f"{sample_rate / 1000:g} kHz"

    # ------------------------------------------------------------------ context menu
    def _show_track_context_menu(self, pos) -> None:
        idx = self.tracks.indexAt(pos)
        if not idx.isValid():
            return
        track = self._track_at_row(idx.row())
        if track is None:
            return
        self.tracks.selectRow(idx.row())
        self.tracks.setCurrentIndex(idx)

        menu = QMenu(self)
        play_now = menu.addAction("Play")
        enqueue = menu.addAction("Enqueue")
        menu.addSeparator()
        open_folder = menu.addAction("Open Containing Folder")
        edit_metadata = menu.addAction("Edit Metadata")
        youtube_search = menu.addAction("Search YouTube for Artist, Album, and Track")
        properties = menu.addAction("Properties")
        action = menu.exec(self.tracks.viewport().mapToGlobal(pos))

        if action == play_now:
            self._play_selected()
        elif action == enqueue:
            self._enqueue_selected()
        elif action == open_folder:
            self._open_containing_folder(track)
        elif action == edit_metadata:
            self._show_edit_metadata_dialog(track)
        elif action == properties:
            self._show_track_properties(track)
        elif action == youtube_search:
            self.request_youtube_search.emit(self._youtube_query_for_track(track))

    def _open_containing_folder(self, track: Track) -> None:
        folder = Path(track.path).expanduser().parent
        if not folder.is_absolute():
            folder = folder.resolve(strict=False)
        if not folder.exists():
            self.status_message.emit(f"Folder not found: {folder}")
            return
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder))):
            self.status_message.emit(f"Could not open folder: {folder}")

    def _show_track_properties(self, track: Track) -> None:
        duration = format_duration(track.duration)
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Properties - {track.title}")
        layout = QVBoxLayout(dialog)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        for label, value in self._track_details(track, duration):
            value_label = QLabel(value)
            value_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            value_label.setWordWrap(True)
            form.addRow(f"{label}:", value_label)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(dialog.reject)
        layout.addLayout(form)
        layout.addWidget(buttons)
        dialog.resize(520, 260)
        dialog.exec()

    def _show_edit_metadata_dialog(self, track: Track) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Edit Metadata - {track.title}")
        layout = QVBoxLayout(dialog)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)

        title_edit = QLineEdit(track.title)
        artist_edit = QLineEdit(track.artist)
        album_artist_edit = QLineEdit(track.album_artist)
        album_edit = QLineEdit(track.album)
        genre_edit = QLineEdit(track.genre)

        track_no_spin = QSpinBox()
        track_no_spin.setRange(0, 9999)
        track_no_spin.setValue(track.track_no or 0)

        disc_no_spin = QSpinBox()
        disc_no_spin.setRange(0, 999)
        disc_no_spin.setValue(track.disc_no or 0)

        year_spin = QSpinBox()
        year_spin.setRange(0, 9999)
        year_spin.setValue(track.year or 0)

        form.addRow("Title:", title_edit)
        form.addRow("Artist:", artist_edit)
        form.addRow("Album Artist:", album_artist_edit)
        form.addRow("Album:", album_edit)
        form.addRow("Track #:", track_no_spin)
        form.addRow("Disc #:", disc_no_spin)
        form.addRow("Year:", year_spin)
        form.addRow("Genre:", genre_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)

        layout.addLayout(form)
        layout.addWidget(buttons)
        dialog.resize(480, 320)

        if dialog.exec() != QDialog.Accepted:
            return

        self.library.update_track(track.id, {
            "title": title_edit.text().strip(),
            "artist": artist_edit.text().strip(),
            "album_artist": album_artist_edit.text().strip(),
            "album": album_edit.text().strip(),
            "track_no": track_no_spin.value(),
            "disc_no": disc_no_spin.value(),
            "year": year_spin.value(),
            "genre": genre_edit.text().strip(),
        })
        self.status_message.emit(f"Metadata saved for \"{title_edit.text().strip()}\"")
        self.refresh()

    @staticmethod
    def _youtube_query_for_track(track: Track) -> str:
        parts = (track.display_artist, track.album, track.title)
        return " ".join(
            part.strip()
            for part in parts
            if part and part.strip() not in {"Unknown Artist", "Unknown Album"}
        )

    # ------------------------------------------------------------------ search
    def _on_search(self, _text: str) -> None:
        self._search_timer.start()

    def _do_search(self) -> None:
        q = self.search.text().strip()
        if not q:
            self._refresh_tracks()
            return
        self._current_tracks = self.library.search(q, self._media_type_filter)
        self._populate_tracks(self._current_tracks)
        self._browser_stack.setCurrentIndex(1)

    # ------------------------------------------------------------------ playback
    def _selected_rows(self) -> list[int]:
        rows = {idx.row() for idx in self.tracks.selectionModel().selectedRows()}
        if rows:
            return sorted(rows)
        idx = self.tracks.currentIndex()
        return [idx.row()] if idx.isValid() else []

    def _selected_tracks(self) -> list[Track]:
        out: list[Track] = []
        for r in self._selected_rows():
            t = self._track_at_row(r)
            if t is not None:
                out.append(t)
        return out

    def highlighted_playback(self) -> tuple[list[Track], int] | None:
        """Visible track list (in current sort order) and highlighted row."""
        idx = self.tracks.currentIndex()
        if not idx.isValid():
            return None
        tracks = self._displayed_tracks()
        row = idx.row()
        if not tracks or row < 0 or row >= len(tracks):
            return None
        return tracks, row

    def _play_selected(self) -> None:
        displayed = self._displayed_tracks()
        if not displayed:
            return
        selected = self._selected_tracks()
        if selected:
            self.play_tracks.emit(selected, 0)
            return
        self.play_tracks.emit(displayed, 0)

    def _enqueue_selected(self) -> None:
        tracks = self._selected_tracks() or self._displayed_tracks()
        if tracks:
            self.enqueue_tracks.emit(tracks)
        else:
            self.status_message.emit("No tracks selected to enqueue.")

    def _on_track_double(self, index) -> None:
        if not index.isValid():
            return
        track = self._track_at_row(index.row())
        if track is None:
            return
        if track.is_video:
            QDesktopServices.openUrl(QUrl.fromLocalFile(track.path))
            return
        self.play_tracks.emit(self._displayed_tracks(), index.row())

    # ------------------------------------------------------------------ playing indicator / selection sync
    def highlight_track(self, track: Track | None) -> None:
        self._currently_playing = track
        self._refresh_playing_indicator()
        if track is None:
            return
        row = self._row_for_track(track)
        if row < 0 and not self.search.text().strip():
            self._show_track_album(track)
            row = self._row_for_track(track)
            self._refresh_playing_indicator()
        if row >= 0:
            self._select_track_row(row)

    def _row_for_track(self, track: Track) -> int:
        for row in range(self.tracks_model.rowCount()):
            current = self._track_at_row(row)
            if current and self._same_track(current, track):
                return row
        return -1

    def _refresh_playing_indicator(self) -> None:
        target_row = (
            self._row_for_track(self._currently_playing)
            if self._currently_playing is not None
            else -1
        )
        for r in range(self.tracks_model.rowCount()):
            item = self.tracks_model.item(r, 0)
            track = self._track_at_row(r)
            if item is None or track is None:
                continue
            new_text = _PLAYING_GLYPH if r == target_row else str(track.track_no or "")
            if item.text() != new_text:
                item.setText(new_text)

    def _same_track(self, a: Track, b: Track) -> bool:
        return (a.id and b.id and a.id == b.id) or a.path == b.path

    def _select_track_row(self, row: int) -> None:
        idx = self.tracks_model.index(row, 0)
        self.tracks.selectRow(row)
        self.tracks.setCurrentIndex(idx)
        self.tracks.scrollTo(idx, QAbstractItemView.PositionAtCenter)

    def _show_track_album(self, track: Track) -> None:
        artist = track.display_artist
        album = track.album or "Unknown Album"
        # Search only real artist rows (skip virtual collection sentinels)
        artist_row = -1
        for row in range(self.artists_model.rowCount()):
            idx = self.artists_model.index(row, 0)
            if idx.data(Qt.UserRole) not in self._VIRTUAL_KEYS:
                if idx.data(Qt.DisplayRole) == artist:
                    artist_row = row
                    break
        if artist_row < 0:
            return
        self.artists.setCurrentIndex(self.artists_model.index(artist_row, 0))
        album_row = self._find_model_row(self.albums_model, album)
        if album_row >= 0:
            self.albums.setCurrentIndex(self.albums_model.index(album_row, 0))

    def _find_model_row(self, model: QStandardItemModel, value: str) -> int:
        for row in range(model.rowCount()):
            if model.index(row, 0).data(Qt.DisplayRole) == value:
                return row
        return -1

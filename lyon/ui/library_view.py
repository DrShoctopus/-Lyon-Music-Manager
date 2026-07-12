"""Library browser: artists -> albums -> tracks, plus search."""
from __future__ import annotations

import logging
from collections import OrderedDict, deque
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from PySide6.QtCore import (
    QAbstractTableModel,
    QEvent,
    QMimeData,
    QModelIndex,
    QObject,
    QRunnable,
    QSize,
    QSortFilterProxyModel,
    Qt,
    QThreadPool,
    QTimer,
    QUrl,
    Signal,
)
from PySide6.QtGui import (
    QAction,
    QColor,
    QDesktopServices,
    QIcon,
    QImageReader,
    QKeySequence,
    QPainter,
    QPixmap,
    QShortcut,
    QStandardItem,
    QStandardItemModel,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListView,
    QMenu,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableView,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..core.library import Library, Track
from ..core.smart_playlist import spec_to_json
from ..core.tagger import write_partial_tags
from .metadata_fetch_dialog import MetadataFetchDialog
from .smart_playlist_dialog import SmartPlaylistDialog
from .widgets import format_duration

LOG = logging.getLogger(__name__)


# Sentinel stored in Qt.UserRole on the synthetic "All Albums" album row.
_ALL_ALBUMS_KEY = "__all_albums__"
_ALL_GENRES_KEY = "__all_genres__"
_LOAD_MORE_ALBUMS_KEY = "__load_more_albums__"

# Sentinels for virtual collections shown at the top of the artist list.
_RECENTLY_ADDED_KEY = "__recently_added__"
_RECENTLY_PLAYED_KEY = "__recently_played__"
_MOST_PLAYED_KEY = "__most_played__"
_TOP_RATED_KEY = "__top_rated__"
_LIKED_KEY = "__liked__"

_SV_ALL_ALBUMS = "__sv_all_albums__"

_VIRTUAL_COLLECTIONS: list[tuple[str, str]] = [
    (_LIKED_KEY, "Liked ♥"),
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
_COL_GROUPING = 7
_NUM_COLS = 8

_TRACK_COLUMN_DEFAULT_WIDTHS = {
    _COL_NUM: 46,
    _COL_TITLE: 340,
    _COL_ARTIST: 210,
    _COL_ALBUM: 220,
    _COL_TIME: 72,
    _COL_RATING: 90,
    _COL_FORMAT: 78,
    _COL_GROUPING: 150,
}

# Format badge colors (file extension → background hex)
_FORMAT_COLORS: dict[str, str] = {
    "FLAC": "#2e7d32", "ALAC": "#2e7d32",
    "MP3": "#546e7a",
    "AAC": "#1565c0", "M4A": "#1565c0",
    "OGG": "#00695c", "OPUS": "#00695c",
    "WAV": "#e65100", "AIFF": "#e65100",
    "WMA": "#4527a0",
}


_TRACK_MIME_TYPE = "application/x-lyon-track-ids"


def _exec_menu(menu: QMenu, global_pos):
    try:
        return menu.exec(global_pos)
    finally:
        menu.deleteLater()


def _exec_dialog(dialog: QDialog) -> int:
    try:
        return dialog.exec()
    finally:
        dialog.deleteLater()


@contextmanager
def _blocked_selection_signals(*views) -> Iterator[None]:
    blocked = []
    for view in views:
        selection_model = view.selectionModel()
        if selection_model is not None:
            blocked.append((selection_model, selection_model.blockSignals(True)))
    try:
        yield
    finally:
        for selection_model, previous in reversed(blocked):
            selection_model.blockSignals(previous)


class _TrackTableModel(QAbstractTableModel):
    """Lightweight QAbstractTableModel for the tracks table.

    Stores tracks in a plain ``list[Track]``; no per-cell ``QStandardItem``
    overhead.  The ▶ playing indicator is rendered via ``data()`` rather than
    mutating item text.  Sorting is delegated to a ``QSortFilterProxyModel``
    (sortRole = Qt.UserRole).

    Column 0, role ``_TRACK_REF_ROLE`` returns the ``Track`` reference.
    """

    _HEADERS = ["#", "Title", "Artist", "Album", "Time", "Rating", "Format", "Group"]

    def __init__(self, tooltip_fn=None, parent=None) -> None:
        super().__init__(parent)
        self._tracks: list[Track] = []
        self._playing_row: int = -1          # source-model row that shows ▶
        self._tooltip_fn = tooltip_fn        # Optional[Callable[[Track], str]]

    # -- QAbstractTableModel interface ----------------------------------------

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # type: ignore[override]
        return 0 if parent.isValid() else len(self._tracks)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # type: ignore[override]
        return 0 if parent.isValid() else _NUM_COLS

    def headerData(self, section: int, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            if 0 <= section < len(self._HEADERS):
                return self._HEADERS[section]
        return None

    def data(self, index: QModelIndex, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        row, col = index.row(), index.column()
        if row < 0 or row >= len(self._tracks):
            return None
        tr = self._tracks[row]

        if role == _TRACK_REF_ROLE:
            return tr if col == _COL_NUM else None

        if role == Qt.DisplayRole:
            return self._display(tr, row, col)

        if role == Qt.UserRole:
            return self._sort_key(tr, col)

        if role == Qt.ToolTipRole and self._tooltip_fn:
            return self._tooltip_fn(tr)

        if role == Qt.TextAlignmentRole and col in (_COL_NUM, _COL_TIME):
            return int(Qt.AlignRight | Qt.AlignVCenter)

        return None

    def setData(self, index: QModelIndex, value, role=Qt.EditRole) -> bool:  # type: ignore[override]
        """Support in-place rating updates from _StarDelegate."""
        if not index.isValid():
            return False
        if role == Qt.UserRole and index.column() == _COL_RATING:
            row = index.row()
            if 0 <= row < len(self._tracks):
                self._tracks[row].rating = value
                self.dataChanged.emit(index, index, [Qt.UserRole])
                return True
        return False

    def flags(self, index: QModelIndex):
        if not index.isValid():
            return Qt.NoItemFlags
        return Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsDragEnabled

    # -- Internal helpers -------------------------------------------------------

    def _display(self, tr: "Track", row: int, col: int):
        if col == _COL_NUM:
            return _PLAYING_GLYPH if row == self._playing_row else str(tr.track_no or "")
        if col == _COL_TITLE:
            return tr.title
        if col == _COL_ARTIST:
            return tr.artist
        if col == _COL_ALBUM:
            return tr.album
        if col == _COL_TIME:
            return format_duration(tr.duration)
        if col == _COL_RATING:
            return ""
        if col == _COL_FORMAT:
            return Path(tr.path).suffix.lstrip(".").upper() or ""
        if col == _COL_GROUPING:
            return tr.grouping or ""
        return None

    def _sort_key(self, tr: "Track", col: int):
        if col == _COL_NUM:
            return int(tr.track_no or 0)
        if col == _COL_TITLE:
            return (tr.title or "").lower()
        if col == _COL_ARTIST:
            return (tr.artist or "").lower()
        if col == _COL_ALBUM:
            return (tr.album or "").lower()
        if col == _COL_TIME:
            return int(tr.duration or 0)
        if col == _COL_RATING:
            return int(tr.rating or 0)
        if col == _COL_FORMAT:
            return Path(tr.path).suffix.lstrip(".").lower()
        if col == _COL_GROUPING:
            return (tr.grouping or "").lower()
        return None

    # -- Public mutation API ---------------------------------------------------

    def reset_tracks(self, tracks: list["Track"]) -> None:
        """Replace the entire track list atomically."""
        self.beginResetModel()
        self._tracks = list(tracks)
        self._playing_row = -1
        self.endResetModel()

    def set_playing_row(self, row: int) -> None:
        """Mark which source-model row shows the ▶ glyph; pass -1 to clear."""
        old = self._playing_row
        self._playing_row = row
        for r in (old, row):
            if 0 <= r < len(self._tracks):
                idx = self.index(r, _COL_NUM)
                self.dataChanged.emit(idx, idx, [Qt.DisplayRole])

    def track_at(self, row: int) -> "Track | None":
        """Return the Track at the given source-model row, or None."""
        if 0 <= row < len(self._tracks):
            return self._tracks[row]
        return None

    def track_count(self) -> int:
        return len(self._tracks)

    # -- Drag-and-drop ---------------------------------------------------------

    def mimeTypes(self) -> list[str]:
        return [_TRACK_MIME_TYPE]

    def mimeData(self, indexes) -> QMimeData:
        mime = QMimeData()
        seen: set[int] = set()
        ids: list[str] = []
        for idx in indexes:
            if idx.column() == _COL_NUM and idx.row() not in seen:
                seen.add(idx.row())
                tr = self.track_at(idx.row())
                if isinstance(tr, Track):
                    ids.append(str(tr.id))
        if ids:
            mime.setData(_TRACK_MIME_TYPE, ",".join(ids).encode())
        return mime

    def supportedDragActions(self):
        return Qt.CopyAction


class _PlaylistListView(QListView):
    """QListView that accepts track-ID drops to add tracks to a playlist."""

    tracks_dropped = Signal(int, list)  # (playlist_id, [track_id, ...])

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)

    def dragEnterEvent(self, ev) -> None:
        if ev.mimeData().hasFormat(_TRACK_MIME_TYPE):
            ev.acceptProposedAction()
        else:
            super().dragEnterEvent(ev)

    def dragMoveEvent(self, ev) -> None:
        if ev.mimeData().hasFormat(_TRACK_MIME_TYPE):
            ev.acceptProposedAction()
        else:
            super().dragMoveEvent(ev)

    def dropEvent(self, ev) -> None:
        if not ev.mimeData().hasFormat(_TRACK_MIME_TYPE):
            super().dropEvent(ev)
            return
        idx = self.indexAt(ev.position().toPoint())
        if not idx.isValid():
            ev.ignore()
            return
        playlist_id = idx.data(Qt.UserRole)
        if not isinstance(playlist_id, int):
            ev.ignore()
            return
        raw = bytes(ev.mimeData().data(_TRACK_MIME_TYPE)).decode()
        track_ids = [int(x) for x in raw.split(",") if x.strip().isdigit()]
        if track_ids:
            self.tracks_dropped.emit(playlist_id, track_ids)
            ev.acceptProposedAction()
        else:
            ev.ignore()


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
        model,
        option: QStyleOptionViewItem,
        index: QModelIndex,
    ) -> bool:
        if event.type() != QEvent.MouseButtonPress:
            return False
        col0 = index.sibling(index.row(), _COL_NUM)
        if not col0.isValid():
            return False
        track = col0.data(_TRACK_REF_ROLE)
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


class _FingerprintSignals(QObject):
    done = Signal(list)   # list[dict] candidates
    error = Signal(str)   # error message


class _IdentifyTrackDialog(QDialog):
    """Shows AcoustID fingerprint candidates and lets the user apply one."""

    def __init__(self, track: "Track", parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Identify Track — {track.title or track.path}")
        self.resize(680, 380)
        self.selected_candidate: dict | None = None

        layout = QVBoxLayout(self)

        self._status = QLabel("Fingerprinting… (this may take a moment)")
        self._status.setObjectName("dialogSubtitle")
        layout.addWidget(self._status)

        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(["Score", "Artist", "Title", "Release"])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.setAlternatingRowColors(True)
        self._table.itemSelectionChanged.connect(self._on_selection)
        layout.addWidget(self._table, 1)

        bb = QDialogButtonBox()
        self._apply_btn = bb.addButton("Apply Selected", QDialogButtonBox.AcceptRole)
        self._apply_btn.setEnabled(False)
        bb.addButton(QDialogButtonBox.Cancel)
        bb.accepted.connect(self._on_apply)
        bb.rejected.connect(self.reject)
        layout.addWidget(bb)

        self._candidates: list[dict] = []

    def on_candidates(self, candidates: list) -> None:
        self._candidates = candidates
        self._table.setRowCount(0)
        if not candidates:
            self._status.setText("No matches found.")
            return
        self._status.setText(f"Found {len(candidates)} candidate(s). Select one to apply.")
        for c in candidates:
            row = self._table.rowCount()
            self._table.insertRow(row)
            self._table.setItem(row, 0, QTableWidgetItem(f"{c['score']:.0%}"))
            self._table.setItem(row, 1, QTableWidgetItem(c.get("artist", "")))
            self._table.setItem(row, 2, QTableWidgetItem(c.get("title", "")))
            self._table.setItem(row, 3, QTableWidgetItem(c.get("album", "")))

    def on_error(self, message: str) -> None:
        self._status.setText(f"Error: {message}")

    def _on_selection(self) -> None:
        self._apply_btn.setEnabled(bool(self._table.selectedItems()))

    def _on_apply(self) -> None:
        rows = {i.row() for i in self._table.selectedItems()}
        if rows:
            row = next(iter(rows))
            if 0 <= row < len(self._candidates):
                self.selected_candidate = self._candidates[row]
        self.accept()


_GRID_ICON_SIZE = 180
_ART_CACHE_MAX = 200
_MAX_ARTWORK_FILE_BYTES = 64 * 1024 * 1024
_MAX_ARTWORK_PIXELS = 64_000_000
_LARGE_LIBRARY_THRESHOLD = 10_000
_UI_POPULATE_CHUNK = 500
_GRID_ALBUM_PAGE_SIZE = 500


def _read_scaled_artwork(art_path: str):
    """Decode one bounded thumbnail on the Qt GUI thread."""
    try:
        if Path(art_path).stat().st_size > _MAX_ARTWORK_FILE_BYTES:
            return None
    except OSError:
        return None
    reader = QImageReader(art_path)
    source_size = reader.size()
    if (
        source_size.isValid()
        and source_size.width() * source_size.height() > _MAX_ARTWORK_PIXELS
    ):
        return None
    if source_size.isValid():
        reader.setScaledSize(
            source_size.scaled(
                _GRID_ICON_SIZE,
                _GRID_ICON_SIZE,
                Qt.KeepAspectRatio,
            )
        )
    image = reader.read()
    if image.isNull():
        return None
    return image.scaled(
        _GRID_ICON_SIZE,
        _GRID_ICON_SIZE,
        Qt.KeepAspectRatio,
        Qt.SmoothTransformation,
    )


class LibraryView(QWidget):
    play_tracks = Signal(list, int)        # (tracks, start_index)
    enqueue_tracks = Signal(list)
    play_video = Signal(Track)
    status_message = Signal(str)
    request_add_folder = Signal()
    request_youtube_search = Signal(str)
    request_open_settings = Signal()
    request_diagnostics = Signal()
    request_scan_replaygain = Signal(list)  # list[Track]
    tracks_metadata_changed = Signal(list)  # track ids changed by a known library edit

    def __init__(self, library: Library, parent: QWidget | None = None):
        super().__init__(parent)
        self.library = library
        self._current_tracks: list[Track] = []
        self._currently_playing: Track | None = None
        self._show_videos: bool = False
        self._active_playlist_id: int | None = None
        # Album art grid async loading
        self._art_cache: OrderedDict[str, QPixmap] = OrderedDict()
        self._grid_gen: int = 0
        self._grid_art_map: dict[str, list[QStandardItem]] = {}
        self._grid_album_offset = 0
        self._grid_album_genre: str | None = None
        self._grid_album_has_more = False
        self._art_pending: deque[tuple[int, str]] = deque()
        self._art_load_timer = QTimer(self)
        self._art_load_timer.setSingleShot(True)
        self._art_load_timer.timeout.connect(self._load_next_artwork)
        self._populate_gen = 0
        self._populate_timer = QTimer(self)
        self._populate_timer.timeout.connect(self._populate_next_chunk)
        self._populate_state: dict | None = None

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

        self.enqueue_btn = QPushButton("Enqueue")
        self.enqueue_btn.clicked.connect(self._enqueue_selected)
        self._show_videos_cb = QCheckBox("Show Videos")
        self._show_videos_cb.setChecked(False)
        self._show_videos_cb.toggled.connect(self._on_show_videos_toggled)
        self._list_mode_btn = QPushButton("▤ List")
        self._list_mode_btn.setObjectName("viewModeBtn")
        self._list_mode_btn.setCheckable(True)
        self._list_mode_btn.setChecked(True)
        self._list_mode_btn.setToolTip("Default 4-column library view")
        self._list_mode_btn.toggled.connect(self._on_list_mode_toggled)
        self._grid_mode_btn = QPushButton("⊞ Grid")
        self._grid_mode_btn.setObjectName("viewModeBtn")
        self._grid_mode_btn.setCheckable(True)
        self._grid_mode_btn.setToolTip("Album grid view")
        self._grid_mode_btn.toggled.connect(self._on_view_mode_toggled)
        self._simple_mode_btn = QPushButton("≡ Simple")
        self._simple_mode_btn.setObjectName("viewModeBtn")
        self._simple_mode_btn.setCheckable(True)
        self._simple_mode_btn.setToolTip("Simplified 3-column view")
        self._simple_mode_btn.toggled.connect(self._on_simple_mode_toggled)
        top.addWidget(self.search, 1)
        top.addWidget(self._show_videos_cb)
        top.addWidget(self.enqueue_btn)
        top.addWidget(self._list_mode_btn)
        top.addWidget(self._grid_mode_btn)
        top.addWidget(self._simple_mode_btn)

        # ---- Genres / Artists / Albums lists
        self.genres = QListView()
        self.genres.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.genres_model = QStandardItemModel()
        self.genres.setModel(self.genres_model)

        self.playlists_model = QStandardItemModel()
        self.playlists_view = _PlaylistListView()
        self.playlists_view.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.playlists_view.setModel(self.playlists_model)
        self.playlists_view.setContextMenuPolicy(Qt.CustomContextMenu)

        self.artists = QListView()
        self.artists.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.artists_model = QStandardItemModel()
        self.artists.setModel(self.artists_model)

        self.albums = QListView()
        self.albums.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.albums.setIconSize(QSize(48, 48))
        self.albums_model = QStandardItemModel()
        self.albums.setModel(self.albums_model)
        self.albums.setContextMenuPolicy(Qt.CustomContextMenu)
        self.albums.customContextMenuRequested.connect(self._show_album_context_menu)

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

        self.tracks_model = _TrackTableModel(
            tooltip_fn=lambda tr: LibraryView._track_tooltip(tr, format_duration(tr.duration)),
            parent=self,
        )
        # Sort via a proxy so # / Time / Rating sort numerically and text columns
        # collate case-insensitively (Qt.UserRole carries the sort key).
        self._tracks_proxy = QSortFilterProxyModel(self)
        self._tracks_proxy.setSourceModel(self.tracks_model)
        self._tracks_proxy.setSortRole(Qt.UserRole)
        self.tracks.setModel(self._tracks_proxy)
        self.tracks.setSortingEnabled(True)
        self.tracks.sortByColumn(0, Qt.AscendingOrder)

        self._star_delegate = _StarDelegate(self.library, self.tracks)
        self.tracks.setItemDelegateForColumn(_COL_RATING, self._star_delegate)
        self._format_delegate = _FormatDelegate(self.tracks)
        self.tracks.setItemDelegateForColumn(_COL_FORMAT, self._format_delegate)

        header = self.tracks.horizontalHeader()
        header.setStretchLastSection(False)
        header.setMinimumSectionSize(38)
        for col in range(_NUM_COLS):
            header.setSectionResizeMode(col, QHeaderView.Interactive)
        for col, width in _TRACK_COLUMN_DEFAULT_WIDTHS.items():
            self.tracks.setColumnWidth(col, width)
        header.setContextMenuPolicy(Qt.CustomContextMenu)
        header.customContextMenuRequested.connect(self._show_header_context_menu)
        self.tracks.setDragEnabled(True)
        self.tracks.setDragDropMode(QAbstractItemView.DragOnly)

        # Keyboard shortcuts scoped to the tracks table
        QShortcut(QKeySequence(Qt.Key_Return), self.tracks,
                  activated=self._play_selected, context=Qt.WidgetShortcut)
        QShortcut(QKeySequence(Qt.Key_Enter), self.tracks,
                  activated=self._play_selected, context=Qt.WidgetShortcut)
        QShortcut(QKeySequence("Ctrl+E"), self.tracks,
                  activated=self._enqueue_selected, context=Qt.WidgetShortcut)

        # ---- List-mode browser: 4-pane splitter (Genres+Playlists | Artists | Albums | Tracks)
        splitter = QSplitter(Qt.Horizontal)

        # Left column: Genres (top) + Playlists (bottom) in a vertical sub-splitter
        genres_box = QWidget()
        gb_vl = QVBoxLayout(genres_box)
        gb_vl.setContentsMargins(0, 0, 0, 0)
        gb_lbl = QLabel("Genres")
        gb_lbl.setObjectName("sectionHeading")
        gb_vl.addWidget(gb_lbl)
        gb_vl.addWidget(self.genres)

        playlists_box = QWidget()
        pb_vl = QVBoxLayout(playlists_box)
        pb_vl.setContentsMargins(0, 0, 0, 0)
        pb_lbl = QLabel("Playlists")
        pb_lbl.setObjectName("sectionHeading")
        pb_vl.addWidget(pb_lbl)
        pb_vl.addWidget(self.playlists_view)

        left_vsplit = QSplitter(Qt.Vertical)
        left_vsplit.addWidget(genres_box)
        left_vsplit.addWidget(playlists_box)
        left_vsplit.setSizes([200, 200])
        splitter.addWidget(left_vsplit)

        for w, label in (
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
        self._grid_albums_view.setIconSize(QSize(_GRID_ICON_SIZE, _GRID_ICON_SIZE))
        self._grid_albums_view.setGridSize(QSize(210, 240))
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

        # ---- Simple-mode browser: 3-pane (Artists | Albums | Tracks)
        self._sv_artists_model = QStandardItemModel()
        self._sv_artists = QListView()
        self._sv_artists.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._sv_artists.setModel(self._sv_artists_model)

        self._sv_albums_model = QStandardItemModel()
        self._sv_albums = QListView()
        self._sv_albums.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._sv_albums.setModel(self._sv_albums_model)

        self._sv_tracks_model = QStandardItemModel()
        self._sv_tracks = QListView()
        self._sv_tracks.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._sv_tracks.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self._sv_tracks.setContextMenuPolicy(Qt.CustomContextMenu)
        self._sv_tracks.customContextMenuRequested.connect(self._sv_show_track_context_menu)
        self._sv_tracks.setModel(self._sv_tracks_model)
        self._sv_current_tracks: list[Track] = []

        QShortcut(QKeySequence(Qt.Key_Return), self._sv_tracks,
                  activated=self._sv_play_selected, context=Qt.WidgetShortcut)
        QShortcut(QKeySequence(Qt.Key_Enter), self._sv_tracks,
                  activated=self._sv_play_selected, context=Qt.WidgetShortcut)
        QShortcut(QKeySequence("Ctrl+E"), self._sv_tracks,
                  activated=self._sv_enqueue_selected, context=Qt.WidgetShortcut)

        sv_splitter = QSplitter(Qt.Horizontal)
        for _sv_widget, _sv_label in (
            (self._sv_artists, "Artists"),
            (self._sv_albums, "Albums"),
            (self._sv_tracks, "Tracks"),
        ):
            _sv_box = QWidget()
            _sv_vbox = QVBoxLayout(_sv_box)
            _sv_vbox.setContentsMargins(0, 0, 0, 0)
            _sv_heading = QLabel(_sv_label)
            _sv_heading.setObjectName("sectionHeading")
            _sv_vbox.addWidget(_sv_heading)
            _sv_vbox.addWidget(_sv_widget)
            sv_splitter.addWidget(_sv_box)
        sv_splitter.setSizes([300, 300, 400])

        simple_widget = QWidget()
        simple_vl = QVBoxLayout(simple_widget)
        simple_vl.setContentsMargins(0, 0, 0, 0)
        simple_vl.addWidget(sv_splitter)

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
        self._browser_stack.addWidget(empty_widget)   # 0: empty
        self._browser_stack.addWidget(splitter)       # 1: list browser
        self._browser_stack.addWidget(grid_widget)    # 2: grid browser
        self._browser_stack.addWidget(simple_widget)  # 3: simple browser

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
        self._sv_artists.selectionModel().currentChanged.connect(
            lambda *_: self._sv_refresh_albums()
        )
        self._sv_albums.selectionModel().currentChanged.connect(
            lambda *_: self._sv_refresh_tracks()
        )
        self._sv_tracks.doubleClicked.connect(self._sv_on_track_double)
        self.playlists_view.selectionModel().currentChanged.connect(self._on_playlist_selected)
        self.playlists_view.tracks_dropped.connect(self._on_playlist_tracks_dropped)
        self.playlists_view.customContextMenuRequested.connect(self._on_playlist_context_menu)

        # A populated database is hydrated here only on startup.  Use the same
        # bounded model-building path as a completed scan so restarting with a
        # large library cannot allocate every artist item in one GUI-thread burst.
        self.refresh(chunked=self._is_large_library())

    # ------------------------------------------------------------------ data
    @property
    def _media_type_filter(self) -> str | None:
        return None if self._show_videos else "audio"

    def _library_all_artists(
        self,
        media_type: str | None = None,
        *,
        genre: str | None = None,
    ) -> list[str]:
        fn = getattr(self.library, "all_artists", None)
        if not callable(fn):
            return []
        try:
            return list(fn(media_type, genre=genre))
        except TypeError:
            return list(fn(media_type))

    def _library_all_genres(self, media_type: str | None = None) -> list[str]:
        fn = getattr(self.library, "all_genres", None)
        if not callable(fn):
            return []
        try:
            return list(fn(media_type))
        except TypeError:
            return list(fn())

    def _library_all_albums(
        self, media_type: str | None = None
    ) -> list[tuple[str, str, str | None]]:
        fn = getattr(self.library, "all_albums", None)
        if not callable(fn):
            return []
        try:
            return list(fn(media_type))
        except TypeError:
            return list(fn())

    def _library_all_playlists(self) -> list:
        fn = getattr(self.library, "all_playlists", None)
        return list(fn()) if callable(fn) else []

    def _available_virtual_collections(self) -> list[tuple[str, str]]:
        required = {
            _LIKED_KEY: "liked",
            _RECENTLY_ADDED_KEY: "recently_added",
            _RECENTLY_PLAYED_KEY: "recently_played",
            _MOST_PLAYED_KEY: "most_played",
            _TOP_RATED_KEY: "top_rated",
        }
        return [
            (key, label)
            for key, label in _VIRTUAL_COLLECTIONS
            if callable(getattr(self.library, required[key], None))
        ]

    def _on_show_videos_toggled(self, checked: bool) -> None:
        self._show_videos = checked
        self.refresh()

    def _library_has_tracks(self) -> bool:
        fn = getattr(self.library, "count_tracks", None)
        if callable(fn):
            try:
                return fn(self._media_type_filter) > 0
            except TypeError:
                return fn() > 0
        return bool(self._library_all_artists(self._media_type_filter))

    def _is_large_library(self) -> bool:
        fn = getattr(self.library, "count_tracks", None)
        if not callable(fn):
            return False
        try:
            return fn(self._media_type_filter) >= _LARGE_LIBRARY_THRESHOLD
        except TypeError:
            return fn() >= _LARGE_LIBRARY_THRESHOLD

    def refresh_after_scan(self) -> None:
        """Refresh models without one huge GUI-thread allocation burst."""
        self.refresh(chunked=self._is_large_library())

    def refresh(self, *, chunked: bool = False) -> None:
        self._cancel_populate()
        has_tracks = self._library_has_tracks()
        active_pl = self._active_playlist_id
        self._refresh_playlists()

        # Populate genres pane (both list and grid share genres_model)
        with _blocked_selection_signals(self.genres, self._grid_genres):
            self.genres_model.clear()
            ag_item = QStandardItem("All Genres")
            ag_item.setData(_ALL_GENRES_KEY, Qt.UserRole)
            f = ag_item.font()
            f.setItalic(True)
            ag_item.setFont(f)
            self.genres_model.appendRow(ag_item)
            for g in self._library_all_genres(self._media_type_filter):
                it = QStandardItem(g)
                it.setData(g, Qt.UserRole)
                self.genres_model.appendRow(it)

            # Reset genre selections to "All Genres" without firing selection signals.
            all_genres_idx = self.genres_model.index(0, 0)
            self.genres.setCurrentIndex(all_genres_idx)
            self._grid_genres.setCurrentIndex(all_genres_idx)

        if has_tracks:
            # Preserve view mode across refresh
            current_page = self._browser_stack.currentIndex()
            self._browser_stack.setCurrentIndex(max(1, current_page))
            if self._browser_stack.currentIndex() == 1:
                self._refresh_artists(chunked=chunked)
            elif self._browser_stack.currentIndex() == 2:
                self._refresh_grid_albums()
            elif self._browser_stack.currentIndex() == 3:
                self._sv_refresh_artists(chunked=chunked)
        else:
            self._browser_stack.setCurrentIndex(0)
            self.artists_model.clear()
            self.albums_model.clear()
            self._clear_tracks_model()
            self._current_tracks = []
            self._update_footer()

        # Re-run active playlist query after library changes.
        if active_pl is not None:
            if not self._restore_active_playlist(active_pl):
                # Playlist was deleted — clear stale state
                self._active_playlist_id = None
                self._current_tracks = []
                self._clear_tracks_model()
                self._update_footer()

    def _cancel_populate(self) -> None:
        self._populate_gen += 1
        self._populate_timer.stop()
        self._populate_state = None

    def _start_artist_populate(
        self,
        list_view: QListView,
        model: QStandardItemModel,
        virtual_count: int,
        artists: list[str],
    ) -> None:
        self._cancel_populate()
        self._populate_gen += 1
        self._populate_state = {
            "gen": self._populate_gen,
            "list_view": list_view,
            "model": model,
            "virtual_count": virtual_count,
            "artists": artists,
            "offset": 0,
        }
        self._populate_timer.start(0)

    def _populate_next_chunk(self) -> None:
        state = self._populate_state
        if state is None or state["gen"] != self._populate_gen:
            self._populate_timer.stop()
            return
        artists: list[str] = state["artists"]
        offset: int = state["offset"]
        end = min(offset + _UI_POPULATE_CHUNK, len(artists))
        model: QStandardItemModel = state["model"]
        for name in artists[offset:end]:
            item = QStandardItem(name)
            item.setData(name, Qt.UserRole)
            model.appendRow(item)
        state["offset"] = end
        if end < len(artists):
            self._populate_timer.start(0)
            return
        self._populate_timer.stop()
        self._populate_state = None
        list_view: QListView = state["list_view"]
        virtual_count: int = state["virtual_count"]
        if artists:
            list_view.setCurrentIndex(model.index(virtual_count, 0))
        elif model.rowCount():
            list_view.setCurrentIndex(model.index(0, 0))

    def _refresh_artists(self, *, chunked: bool = False) -> None:
        """Repopulate artist list filtered by current genre selection."""
        genre_idx = self.genres.currentIndex()
        genre_key = genre_idx.data(Qt.UserRole) if genre_idx.isValid() else _ALL_GENRES_KEY
        genre = None if genre_key == _ALL_GENRES_KEY else genre_key

        with _blocked_selection_signals(self.artists):
            self.artists_model.clear()
            virtual_collections = self._available_virtual_collections()
            for key, label in virtual_collections:
                item = QStandardItem(label)
                item.setData(key, Qt.UserRole)
                fnt = item.font()
                fnt.setItalic(True)
                item.setFont(fnt)
                self.artists_model.appendRow(item)
            real_artists = self._library_all_artists(self._media_type_filter, genre=genre)
            if chunked and len(real_artists) > _UI_POPULATE_CHUNK:
                self._start_artist_populate(
                    self.artists,
                    self.artists_model,
                    len(virtual_collections),
                    real_artists,
                )
                return
            for a in real_artists:
                it = QStandardItem(a)
                it.setData(a, Qt.UserRole)
                self.artists_model.appendRow(it)

            if real_artists:
                self.artists.setCurrentIndex(
                    self.artists_model.index(len(virtual_collections), 0)
                )
            elif self.artists_model.rowCount():
                self.artists.setCurrentIndex(self.artists_model.index(0, 0))
            else:
                self.artists.setCurrentIndex(QModelIndex())

        if self.artists.currentIndex().isValid():
            self._refresh_albums()
        else:
            self.albums_model.clear()
            self._current_tracks = []
            self._clear_tracks_model()
            self._update_footer()

    _VIRTUAL_KEYS = frozenset(k for k, _ in _VIRTUAL_COLLECTIONS)

    def _refresh_albums(self) -> None:
        self._clear_playlist_selection()
        self._grid_gen += 1
        gen = self._grid_gen
        self._art_load_timer.stop()
        self._art_pending.clear()
        self._grid_art_map = {}
        virtual_key = None
        should_refresh_tracks = False

        with _blocked_selection_signals(self.albums):
            self.albums_model.clear()
            idx = self.artists.currentIndex()
            if not idx.isValid():
                self._current_tracks = []
                self._clear_tracks_model()
                self._update_footer()
                return
            artist_key = idx.data(Qt.UserRole)
            # Virtual collection selected — clear album pane and populate tracks directly
            if artist_key in self._VIRTUAL_KEYS:
                virtual_key = artist_key
            else:
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
                    if not _art:
                        it.setForeground(QColor("#888888"))
                    self.albums_model.appendRow(it)
                    if not _art:
                        continue
                    if _art in self._art_cache:
                        self._art_cache.move_to_end(_art)
                        it.setIcon(QIcon(self._art_cache[_art]))
                    else:
                        first = _art not in self._grid_art_map
                        self._grid_art_map.setdefault(_art, []).append(it)
                        if first:
                            self._art_pending.append((gen, _art))
                if self.albums_model.rowCount():
                    self.albums.setCurrentIndex(self.albums_model.index(0, 0))
                    should_refresh_tracks = True
                else:
                    self._current_tracks = []
                    self._clear_tracks_model()
                    self._update_footer()

        self._pump_artwork_loads()

        if virtual_key is not None:
            self._populate_virtual_collection(virtual_key)
            return
        if should_refresh_tracks:
            self._refresh_tracks()

    def _populate_virtual_collection(self, key: str) -> None:
        mt = self._media_type_filter
        if key == _LIKED_KEY and callable(getattr(self.library, "liked", None)):
            tracks = self.library.liked(mt)
        elif key == _RECENTLY_ADDED_KEY and callable(getattr(self.library, "recently_added", None)):
            tracks = self.library.recently_added(50, mt)
        elif key == _RECENTLY_PLAYED_KEY and callable(getattr(self.library, "recently_played", None)):
            tracks = self.library.recently_played(50, mt)
        elif key == _MOST_PLAYED_KEY and callable(getattr(self.library, "most_played", None)):
            tracks = self.library.most_played(50, mt)
        elif key == _TOP_RATED_KEY and callable(getattr(self.library, "top_rated", None)):
            tracks = self.library.top_rated(4, 100, mt)
        else:
            return
        self._current_tracks = tracks
        self._populate_tracks(tracks)

    # ------------------------------------------------------------------ view modes
    def _set_view_mode_checked(self, active: QPushButton) -> None:
        """Make the three view-mode buttons act like a radio group."""
        for btn in (self._list_mode_btn, self._grid_mode_btn, self._simple_mode_btn):
            if btn is active:
                continue
            btn.blockSignals(True)
            btn.setChecked(False)
            btn.blockSignals(False)
        if not active.isChecked():
            active.blockSignals(True)
            active.setChecked(True)
            active.blockSignals(False)

    def _on_list_mode_toggled(self, checked: bool) -> None:
        if not checked:
            # Don't allow toggling off via re-click — only switching to another view does that.
            if not (self._grid_mode_btn.isChecked() or self._simple_mode_btn.isChecked()):
                self._list_mode_btn.blockSignals(True)
                self._list_mode_btn.setChecked(True)
                self._list_mode_btn.blockSignals(False)
            return
        self._set_view_mode_checked(self._list_mode_btn)
        has_tracks = self._library_has_tracks()
        self._browser_stack.setCurrentIndex(1 if has_tracks else 0)
        if has_tracks:
            self._refresh_artists(chunked=self._is_large_library())

    def _on_view_mode_toggled(self, checked: bool) -> None:
        if not checked:
            if not (self._list_mode_btn.isChecked() or self._simple_mode_btn.isChecked()):
                self._grid_mode_btn.blockSignals(True)
                self._grid_mode_btn.setChecked(True)
                self._grid_mode_btn.blockSignals(False)
            return
        if self._browser_stack.currentIndex() == 0:
            # Empty library — revert toggle back to list
            self._set_view_mode_checked(self._list_mode_btn)
            return
        self._set_view_mode_checked(self._grid_mode_btn)
        self._browser_stack.setCurrentIndex(2)
        self._refresh_grid_albums()

    def _on_simple_mode_toggled(self, checked: bool) -> None:
        if not checked:
            if not (self._list_mode_btn.isChecked() or self._grid_mode_btn.isChecked()):
                self._simple_mode_btn.blockSignals(True)
                self._simple_mode_btn.setChecked(True)
                self._simple_mode_btn.blockSignals(False)
            return
        if self._browser_stack.currentIndex() == 0:
            # Empty library — revert toggle back to list
            self._set_view_mode_checked(self._list_mode_btn)
            return
        self._set_view_mode_checked(self._simple_mode_btn)
        self._browser_stack.setCurrentIndex(3)
        self._sv_refresh_artists(chunked=self._is_large_library())

    def _refresh_grid_albums(self) -> None:
        """Populate the album art grid for the selected genre (artwork loads asynchronously)."""
        self._grid_gen += 1
        gen = self._grid_gen
        self._art_load_timer.stop()
        self._art_pending.clear()
        self._grid_art_map = {}
        self._grid_albums_model.clear()

        genre_idx = self._grid_genres.currentIndex()
        genre_key = genre_idx.data(Qt.UserRole) if genre_idx.isValid() else _ALL_GENRES_KEY
        genre = None if genre_key == _ALL_GENRES_KEY else genre_key
        self._grid_album_offset = 0
        self._grid_album_genre = genre
        self._grid_album_has_more = False

        if self._is_large_library() and callable(
            getattr(self.library, "album_summaries_page", None)
        ):
            self._load_next_grid_album_page()
            return
        if genre is None:
            albums = self._library_all_albums(self._media_type_filter)
        else:
            albums_fn = getattr(self.library, "albums_for_genre", None)
            if callable(albums_fn):
                albums = albums_fn(genre, self._media_type_filter)
            else:
                tracks = self.library.tracks_for_genre(genre, self._media_type_filter)
                seen: set[tuple[str, str]] = set()
                albums = []
                for track in tracks:
                    key_t = (track.display_artist, track.display_album)
                    if key_t not in seen:
                        seen.add(key_t)
                        albums.append(
                            (track.display_artist, track.display_album, track.artwork_path)
                        )

        self._append_grid_album_items(gen, albums)
        self._pump_artwork_loads()

    def _append_grid_album_items(
        self,
        gen: int,
        albums: list[tuple[str, str, str | None]],
    ) -> None:
        for artist, album, art in albums:
            it = QStandardItem(QIcon(), f"{album}\n{artist}")
            it.setData((artist, album), Qt.UserRole)
            it.setTextAlignment(Qt.AlignHCenter | Qt.AlignTop)
            self._grid_albums_model.appendRow(it)
            if not art:
                continue
            if art in self._art_cache:
                self._art_cache.move_to_end(art)
                it.setIcon(QIcon(self._art_cache[art]))
            else:
                first = art not in self._grid_art_map
                self._grid_art_map.setdefault(art, []).append(it)
                if first:
                    self._art_pending.append((gen, art))

    def _load_next_grid_album_page(self) -> None:
        page_fn = getattr(self.library, "album_summaries_page", None)
        if not callable(page_fn):
            return
        if self._grid_albums_model.rowCount():
            last_row = self._grid_albums_model.rowCount() - 1
            last = self._grid_albums_model.item(last_row)
            if last is not None and last.data(Qt.UserRole) == _LOAD_MORE_ALBUMS_KEY:
                self._grid_albums_model.removeRow(last_row)
        page = page_fn(
            limit=_GRID_ALBUM_PAGE_SIZE + 1,
            offset=self._grid_album_offset,
            media_type=self._media_type_filter,
            genre=self._grid_album_genre,
        )
        albums = list(page[:_GRID_ALBUM_PAGE_SIZE])
        self._grid_album_offset += len(albums)
        self._grid_album_has_more = len(page) > _GRID_ALBUM_PAGE_SIZE
        self._append_grid_album_items(self._grid_gen, albums)
        if self._grid_album_has_more:
            more = QStandardItem("Load more albums…")
            more.setData(_LOAD_MORE_ALBUMS_KEY, Qt.UserRole)
            more.setTextAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
            self._grid_albums_model.appendRow(more)
        self._pump_artwork_loads()

    def _pump_artwork_loads(self) -> None:
        if self._art_pending and not self._art_load_timer.isActive():
            self._art_load_timer.start(0)

    def _load_next_artwork(self) -> None:
        if not self._art_pending:
            return
        gen, art_path = self._art_pending.popleft()
        image = None
        if gen == self._grid_gen:
            try:
                image = _read_scaled_artwork(art_path)
            except Exception as exc:  # noqa: BLE001 — one bad image must not break the grid
                LOG.debug("Could not load grid artwork %s: %s", art_path, exc)
        self._on_artwork_loaded(gen, art_path, image)
        self._pump_artwork_loads()

    def _on_artwork_loaded(self, gen: int, art_path: str, img: object) -> None:
        if gen != self._grid_gen:
            return
        pm: QPixmap | None = None
        if img is not None:
            pm = QPixmap.fromImage(img)
            if pm.isNull():
                pm = None
        if pm is not None:
            if len(self._art_cache) >= _ART_CACHE_MAX:
                self._art_cache.popitem(last=False)
            self._art_cache[art_path] = pm
        icon = QIcon(pm) if pm else QIcon()
        for item in self._grid_art_map.get(art_path, []):
            item.setIcon(icon)
            if pm is None:
                item.setForeground(QColor("#888888"))

    def _on_grid_album_activated(self, index: QModelIndex) -> None:
        data = index.data(Qt.UserRole)
        if data == _LOAD_MORE_ALBUMS_KEY:
            self._load_next_grid_album_page()
            return
        if not isinstance(data, tuple) or len(data) != 2:
            return
        artist, album = data
        # Switch back to list mode and navigate to the album
        self._set_view_mode_checked(self._list_mode_btn)
        self._browser_stack.setCurrentIndex(1)
        self._navigate_to_album(artist, album)

    # ------------------------------------------------------------------ simple view
    def _sv_refresh_artists(self, *, chunked: bool = False) -> None:
        with _blocked_selection_signals(self._sv_artists):
            self._sv_artists_model.clear()
            artists = self._library_all_artists(self._media_type_filter)
            if chunked and len(artists) > _UI_POPULATE_CHUNK:
                self._start_artist_populate(
                    self._sv_artists,
                    self._sv_artists_model,
                    0,
                    artists,
                )
                return
            for a in artists:
                it = QStandardItem(a)
                it.setData(a, Qt.UserRole)
                self._sv_artists_model.appendRow(it)
            if self._sv_artists_model.rowCount():
                self._sv_artists.setCurrentIndex(self._sv_artists_model.index(0, 0))
            else:
                self._sv_artists.setCurrentIndex(QModelIndex())
        self._sv_refresh_albums()

    def _sv_refresh_albums(self) -> None:
        # Block the album selection signal while we rebuild the model: model.clear()
        # invalidates the current index (1st currentChanged) and setCurrentIndex(row 0)
        # would fire a 2nd. We call _sv_refresh_tracks() exactly once at the end.
        sel = self._sv_albums.selectionModel()
        sel.blockSignals(True)
        try:
            self._sv_albums_model.clear()
            idx = self._sv_artists.currentIndex()
            if not idx.isValid():
                self._sv_tracks_model.clear()
                self._sv_current_tracks = []
                return
            artist = idx.data(Qt.DisplayRole)
            albums = list(self.library.albums_for_artist(artist, self._media_type_filter))
            if len(albums) >= 2:
                all_item = QStandardItem("All Albums")
                all_item.setData(_SV_ALL_ALBUMS, Qt.UserRole)
                f = all_item.font()
                f.setItalic(True)
                all_item.setFont(f)
                self._sv_albums_model.appendRow(all_item)
            for album, _ in albums:
                it = QStandardItem(album)
                it.setData(album, Qt.UserRole)
                self._sv_albums_model.appendRow(it)
            if self._sv_albums_model.rowCount():
                self._sv_albums.setCurrentIndex(self._sv_albums_model.index(0, 0))
        finally:
            sel.blockSignals(False)
        self._sv_refresh_tracks()

    def _sv_refresh_tracks(self) -> None:
        self._sv_tracks_model.clear()
        self._sv_current_tracks = []
        artist_idx = self._sv_artists.currentIndex()
        album_idx = self._sv_albums.currentIndex()
        if not artist_idx.isValid():
            return
        artist = artist_idx.data(Qt.DisplayRole)
        album_key = album_idx.data(Qt.UserRole) if album_idx.isValid() else _SV_ALL_ALBUMS
        if album_key == _SV_ALL_ALBUMS:
            tracks = self.library.tracks_for_artist(artist, self._media_type_filter)
        else:
            album = album_idx.data(Qt.DisplayRole)
            tracks = self.library.tracks_for_album(artist, album, self._media_type_filter)
        self._sv_current_tracks = tracks
        for tr in tracks:
            duration = format_duration(tr.duration)
            num_prefix = f"{tr.track_no}. " if tr.track_no else ""
            it = QStandardItem(f"{num_prefix}{tr.title}  [{duration}]")
            it.setData(tr, _TRACK_REF_ROLE)
            it.setEditable(False)
            it.setToolTip(self._track_tooltip(tr, duration))
            self._sv_tracks_model.appendRow(it)

    def _sv_on_track_double(self, index: QModelIndex) -> None:
        if not index.isValid():
            return
        item = self._sv_tracks_model.item(index.row(), 0)
        if item is None:
            return
        track = item.data(_TRACK_REF_ROLE)
        if not isinstance(track, Track):
            return
        if track.is_video:
            self.play_video.emit(track)
            return
        self.play_tracks.emit(self._sv_current_tracks, index.row())

    def _sv_track_at_row(self, row: int) -> Track | None:
        item = self._sv_tracks_model.item(row, 0)
        if item is None:
            return None
        track = item.data(_TRACK_REF_ROLE)
        return track if isinstance(track, Track) else None

    def _sv_selected_rows(self) -> list[int]:
        rows = {idx.row() for idx in self._sv_tracks.selectionModel().selectedRows()}
        if rows:
            return sorted(rows)
        idx = self._sv_tracks.currentIndex()
        return [idx.row()] if idx.isValid() else []

    def _sv_selected_tracks(self) -> list[Track]:
        out: list[Track] = []
        for r in self._sv_selected_rows():
            t = self._sv_track_at_row(r)
            if t is not None:
                out.append(t)
        return out

    def _sv_play_selected(self) -> None:
        if not self._sv_current_tracks:
            return
        selected = self._sv_selected_tracks()
        if selected:
            if len(selected) == 1 and selected[0].is_video:
                self.play_video.emit(selected[0])
                return
            self.play_tracks.emit(selected, 0)
            return
        current = self._sv_track_at_row(self._sv_tracks.currentIndex().row())
        if current is not None and current.is_video:
            self.play_video.emit(current)
            return
        self.play_tracks.emit(self._sv_current_tracks, 0)

    def _sv_enqueue_selected(self) -> None:
        tracks = self._sv_selected_tracks() or self._sv_current_tracks
        if tracks:
            self.enqueue_tracks.emit(tracks)
        else:
            self.status_message.emit("No tracks selected to enqueue.")

    def _sv_show_track_context_menu(self, pos) -> None:
        idx = self._sv_tracks.indexAt(pos)
        if not idx.isValid():
            return
        track = self._sv_track_at_row(idx.row())
        if track is None:
            return
        selected = self._sv_selected_tracks()
        if not any(t.id == track.id or t.path == track.path for t in selected):
            self._sv_tracks.setCurrentIndex(idx)
            selected = [track]
        self._show_track_actions_menu(
            self._sv_tracks.viewport().mapToGlobal(pos),
            primary_track=track,
            selected=selected,
            play_fn=self._sv_play_selected,
            enqueue_fn=self._sv_enqueue_selected,
            show_go_to_album=False,
        )

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
        # All toggleable columns (Title is always visible — it's the row identifier).
        toggleable = [
            (_COL_NUM,      "#"),
            (_COL_ARTIST,   "Artist"),
            (_COL_ALBUM,    "Album"),
            (_COL_TIME,     "Time"),
            (_COL_RATING,   "Rating"),
            (_COL_FORMAT,   "Format"),
            (_COL_GROUPING, "Group"),
        ]
        col_actions: list[tuple[int, QAction]] = []
        for col, label in toggleable:
            act = menu.addAction(label)
            act.setCheckable(True)
            act.setChecked(not self.tracks.isColumnHidden(col))
            col_actions.append((col, act))
        menu.addSeparator()
        show_all_act = menu.addAction("Show All Columns")
        action = _exec_menu(menu, self.tracks.horizontalHeader().mapToGlobal(pos))
        if action is None:
            return
        if action is show_all_act:
            for col, _ in toggleable:
                self.tracks.setColumnHidden(col, False)
            self.tracks.setColumnHidden(_COL_TITLE, False)
            return
        for col, act in col_actions:
            if action is act:
                self.tracks.setColumnHidden(col, not act.isChecked())
                return

    def _refresh_tracks(self) -> None:
        ai = self.artists.currentIndex()
        # Virtual collection already populated tracks in _refresh_albums; nothing to do here.
        if ai.isValid() and ai.data(Qt.UserRole) in self._VIRTUAL_KEYS:
            return
        bi = self.albums.currentIndex()
        if not ai.isValid() or not bi.isValid():
            self._current_tracks = []
            self._clear_tracks_model()
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

    def _clear_tracks_model(self) -> None:
        """Clear the tracks table atomically (no rows, no selection)."""
        self.tracks_model.reset_tracks([])

    def _populate_tracks(self, tracks: list[Track]) -> None:
        # reset_tracks uses beginResetModel/endResetModel — no need to toggle sorting.
        self.tracks_model.reset_tracks(tracks)
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
    def _track_at_row(self, proxy_row: int) -> Track | None:
        """Return the Track visible at *proxy_row* (accounts for current sort order)."""
        proxy_idx = self._tracks_proxy.index(proxy_row, _COL_NUM)
        if not proxy_idx.isValid():
            return None
        src_idx = self._tracks_proxy.mapToSource(proxy_idx)
        track = self.tracks_model.track_at(src_idx.row())
        return track if isinstance(track, Track) else None

    def _displayed_tracks(self) -> list[Track]:
        """All visible tracks in the current (possibly sorted) display order."""
        out: list[Track] = []
        for r in range(self._tracks_proxy.rowCount()):
            t = self._track_at_row(r)
            if t is not None:
                out.append(t)
        return out

    # ------------------------------------------------------------------ details / tooltip
    @staticmethod
    def _track_details(track: Track, duration: str) -> list[tuple[str, str]]:
        file_type = Path(track.path).suffix.lstrip(".").upper() or "Unknown"
        artist = track.display_artist
        album = track.display_album
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

    # ------------------------------------------------------------------ album context menu
    def _show_album_context_menu(self, pos) -> None:
        idx = self.albums.indexAt(pos)
        if not idx.isValid():
            return
        album_key = idx.data(Qt.UserRole)
        if album_key == _ALL_ALBUMS_KEY or album_key in self._VIRTUAL_KEYS:
            return

        ai = self.artists.currentIndex()
        if not ai.isValid():
            return
        artist = str(ai.data(Qt.DisplayRole) or "").strip()
        album = str(idx.data(Qt.DisplayRole) or "").strip()
        if not artist or not album:
            return

        menu = QMenu(self)
        fetch_act = menu.addAction("Fetch Metadata…")
        action = _exec_menu(menu, self.albums.viewport().mapToGlobal(pos))

        if action == fetch_act:
            self._fetch_album_metadata(artist, album)

    def _fetch_album_metadata(self, artist: str, album: str) -> None:
        try:
            tracks = self.library.tracks_for_album(artist, album, "audio")
        except Exception:
            self.status_message.emit("Could not load tracks for metadata fetch.")
            return
        if not tracks:
            self.status_message.emit("No audio tracks found for this album.")
            return
        try:
            dlg = MetadataFetchDialog(tracks, artist, album, self.library, self)
            result = _exec_dialog(dlg)
        except Exception:
            self.status_message.emit("Metadata fetch could not be started.")
            return
        if result == QDialog.Accepted:
            self.status_message.emit(f"Metadata updated for \"{album}\".")
            self.refresh()
            self.tracks_metadata_changed.emit([track.id for track in tracks])

    # ------------------------------------------------------------------ context menu
    def _show_track_context_menu(self, pos) -> None:
        idx = self.tracks.indexAt(pos)
        if not idx.isValid():
            return
        track = self._track_at_row(idx.row())
        if track is None:
            return
        # If the right-clicked row isn't in the current selection, narrow to just that row.
        selected = self._selected_tracks()
        if not any(t.id == track.id or t.path == track.path for t in selected):
            self.tracks.selectRow(idx.row())
            self.tracks.setCurrentIndex(idx)
            selected = [track]

        self._show_track_actions_menu(
            self.tracks.viewport().mapToGlobal(pos),
            primary_track=track,
            selected=selected,
            play_fn=self._play_selected,
            enqueue_fn=self._enqueue_selected,
            show_go_to_album=bool(self.search.text().strip()),
        )

    def _show_track_actions_menu(
        self,
        global_pos,
        primary_track: Track,
        selected: list[Track],
        play_fn,
        enqueue_fn,
        show_go_to_album: bool = False,
    ) -> None:
        """Build and execute the shared right-click action menu for a track row."""
        menu = QMenu(self)
        play_now = menu.addAction("Play")
        enqueue = menu.addAction("Enqueue")
        menu.addSeparator()

        # "Add to Playlist" submenu
        playlists = self._library_all_playlists()
        add_pl_menu = menu.addMenu("Add to Playlist")
        pl_act_map: dict = {}
        for pl in playlists:
            if not pl.is_smart:
                act = add_pl_menu.addAction(pl.name)
                pl_act_map[act] = pl.id
        if playlists:
            add_pl_menu.addSeparator()
        new_pl_act = add_pl_menu.addAction("New Playlist…")

        go_to_album = None
        if show_go_to_album:
            menu.addSeparator()
            go_to_album = menu.addAction("Go to Album in Library")

        menu.addSeparator()
        open_folder = menu.addAction("Open Containing Folder")
        edit_metadata = menu.addAction("Edit Metadata")
        identify_act = None
        if len(selected) == 1:
            from ..core.fingerprint import (
                is_available as _fp_available,
            )
            from ..core.fingerprint import (
                is_lookup_configured as _fp_configured,
            )
            identify_act = menu.addAction("Identify Track…")
            if not _fp_available():
                identify_act.setEnabled(False)
                identify_act.setToolTip("Install pyacoustid and fpcalc to enable")
            elif not _fp_configured():
                identify_act.setEnabled(False)
                identify_act.setToolTip("Set LYON_ACOUSTID_API_KEY to enable AcoustID lookup")
        scan_rg = menu.addAction("Scan ReplayGain…")
        youtube_search = menu.addAction("Search YouTube for Artist, Album, and Track")
        properties = menu.addAction("Properties")
        action = _exec_menu(menu, global_pos)

        if action is None:
            return
        if action == play_now:
            play_fn()
        elif action == enqueue:
            enqueue_fn()
        elif action == new_pl_act:
            self._add_to_new_playlist([t.id for t in selected])
        elif action in pl_act_map:
            self._add_tracks_to_playlist([t.id for t in selected], pl_act_map[action])
        elif action == open_folder:
            self._open_containing_folder(primary_track)
        elif action == edit_metadata:
            if len(selected) >= 2:
                self._show_batch_metadata_dialog(selected)
            else:
                self._show_edit_metadata_dialog(primary_track)
        elif identify_act is not None and action == identify_act:
            self._identify_track(primary_track)
        elif action == scan_rg:
            self.request_scan_replaygain.emit(list(selected))
        elif action == properties:
            self._show_track_properties(primary_track)
        elif action == youtube_search:
            self.request_youtube_search.emit(self._youtube_query_for_track(primary_track))
        elif go_to_album is not None and action == go_to_album:
            self.reveal_track(primary_track)

    # ------------------------------------------------------------------ identify track (AcoustID)

    def _identify_track(self, track: Track) -> None:
        """Launch the AcoustID lookup workflow for a single track."""
        from ..core.fingerprint import is_available, is_lookup_configured, lookup_candidates

        if not is_available():
            QMessageBox.warning(
                self,
                "Fingerprinting Not Available",
                "Install pyacoustid and fpcalc to identify tracks.",
            )
            return
        if not is_lookup_configured():
            QMessageBox.warning(
                self,
                "AcoustID API Key Required",
                "Set LYON_ACOUSTID_API_KEY to enable AcoustID lookup.",
            )
            return

        dlg = _IdentifyTrackDialog(track, self)
        dlg.show()
        dlg.raise_()

        signals = _FingerprintSignals(self)
        signals.done.connect(dlg.on_candidates)
        signals.error.connect(dlg.on_error)

        class _Worker(QRunnable):
            def __init__(self, path, sigs):
                super().__init__()
                self.setAutoDelete(True)
                self._path = path
                self._sigs = sigs
            def run(self):
                try:
                    candidates = lookup_candidates(self._path)
                    self._sigs.done.emit(candidates)
                except Exception as exc:
                    self._sigs.error.emit(str(exc))

        QThreadPool.globalInstance().start(_Worker(track.path, signals))

        if dlg.exec() == QDialog.Accepted and dlg.selected_candidate:
            c = dlg.selected_candidate
            fields: dict = {}
            if c.get("title"):
                fields["title"] = c["title"]
            if c.get("artist"):
                fields["artist"] = c["artist"]
            if c.get("album"):
                fields["album"] = c["album"]
            if fields:
                self.library.update_track(track.id, fields)
                track_path = Path(track.path)
                if track_path.is_file():
                    write_partial_tags(track_path, fields)
            if c.get("acoustid"):
                self.library.update_acoustid(track.id, c["acoustid"])
            self.status_message.emit(f"Applied: {c.get('artist', '')} — {c.get('title', '')}")
            self.refresh()
            if fields:
                self.tracks_metadata_changed.emit([track.id])

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
        _exec_dialog(dialog)

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
        grouping_edit = QLineEdit(getattr(track, "grouping", "") or "")

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
        form.addRow("Grouping:", grouping_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)

        layout.addLayout(form)
        layout.addWidget(buttons)
        dialog.resize(480, 340)

        if _exec_dialog(dialog) != QDialog.Accepted:
            return

        fields = {
            "title": title_edit.text().strip(),
            "artist": artist_edit.text().strip(),
            "album_artist": album_artist_edit.text().strip(),
            "album": album_edit.text().strip(),
            "track_no": track_no_spin.value(),
            "disc_no": disc_no_spin.value(),
            "year": year_spin.value(),
            "genre": genre_edit.text().strip(),
            "grouping": grouping_edit.text().strip(),
        }
        self.library.update_track(track.id, fields)
        track_path = Path(track.path)
        write_failed = track_path.is_file() and not write_partial_tags(track_path, fields)
        msg = f"Metadata saved for \"{fields['title']}\""
        if write_failed:
            msg += " (file tags could not be written to disk.)"
        self.status_message.emit(msg)
        self.refresh()
        self.tracks_metadata_changed.emit([track.id])

    def edit_track_metadata(self, track: Track) -> None:
        self._show_edit_metadata_dialog(track)

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
        if self._browser_stack.currentIndex() != 1:
            self._set_view_mode_checked(self._list_mode_btn)
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
            if len(selected) == 1 and selected[0].is_video:
                self.play_video.emit(selected[0])
                return
            self.play_tracks.emit(selected, 0)
            return
        current = self._track_at_row(self.tracks.currentIndex().row())
        if current is not None and current.is_video:
            self.play_video.emit(current)
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
            self.play_video.emit(track)
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
        """Return the source-model row for *track*, or -1 if not visible."""
        for row in range(self.tracks_model.track_count()):
            current = self.tracks_model.track_at(row)
            if current and self._same_track(current, track):
                return row
        return -1

    def _refresh_playing_indicator(self) -> None:
        target_row = (
            self._row_for_track(self._currently_playing)
            if self._currently_playing is not None
            else -1
        )
        self.tracks_model.set_playing_row(target_row)

    def _same_track(self, a: Track, b: Track) -> bool:
        return (a.id and b.id and a.id == b.id) or a.path == b.path

    def _select_track_row(self, row: int) -> None:
        """Select *row* (source-model coordinate) in the tracks view."""
        src_idx = self.tracks_model.index(row, 0)
        proxy_idx = self._tracks_proxy.mapFromSource(src_idx)
        if not proxy_idx.isValid():
            return
        self.tracks.selectRow(proxy_idx.row())
        self.tracks.setCurrentIndex(proxy_idx)
        self.tracks.scrollTo(proxy_idx, QAbstractItemView.PositionAtCenter)

    def _show_track_album(self, track: Track) -> None:
        artist = track.display_artist
        album = track.display_album
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

    # ------------------------------------------------------------------ P6 tools
    def reveal_track(self, track: Track | None) -> None:
        """Navigate library panes to show and select the given track."""
        if track is None:
            return
        if self.search.text().strip():
            self.search.blockSignals(True)
            self.search.clear()
            self.search.blockSignals(False)
        # Ensure list mode is active
        if self._browser_stack.currentIndex() != 1:
            self._set_view_mode_checked(self._list_mode_btn)
            has_tracks = bool(self._library_all_artists(self._media_type_filter))
            self._browser_stack.setCurrentIndex(1 if has_tracks else 0)
        self._navigate_to_album(track.display_artist, track.display_album)
        row = self._row_for_track(track)
        if row >= 0:
            self._select_track_row(row)

    def _show_batch_metadata_dialog(self, tracks: list[Track]) -> None:
        _MIXED = "(multiple values)"

        def _common(field: str) -> str:
            vals = {getattr(t, field, "") or "" for t in tracks}
            return next(iter(vals)) if len(vals) == 1 else ""

        def _common_int(field: str) -> int | None:
            vals = {getattr(t, field, 0) or 0 for t in tracks}
            return next(iter(vals)) if len(vals) == 1 else None

        dialog = QDialog(self)
        dialog.setWindowTitle(f"Edit Metadata for {len(tracks)} Tracks")
        layout = QVBoxLayout(dialog)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)

        artist_edit = QLineEdit()
        artist_edit.setPlaceholderText(_MIXED)
        if v := _common("artist"):
            artist_edit.setText(v)

        album_artist_edit = QLineEdit()
        album_artist_edit.setPlaceholderText(_MIXED)
        if v := _common("album_artist"):
            album_artist_edit.setText(v)

        album_edit = QLineEdit()
        album_edit.setPlaceholderText(_MIXED)
        if v := _common("album"):
            album_edit.setText(v)

        genre_edit = QLineEdit()
        genre_edit.setPlaceholderText(_MIXED)
        if v := _common("genre"):
            genre_edit.setText(v)

        year_spin = QSpinBox()
        year_spin.setRange(0, 9999)
        year_spin.setSpecialValueText(_MIXED)
        if v_int := _common_int("year"):
            year_spin.setValue(v_int)

        form.addRow("Artist:", artist_edit)
        form.addRow("Album Artist:", album_artist_edit)
        form.addRow("Album:", album_edit)
        form.addRow("Year:", year_spin)
        form.addRow("Genre:", genre_edit)

        note = QLabel(f"Empty fields are not changed. Applies to {len(tracks)} tracks.")
        note.setObjectName("mutedText")
        note.setWordWrap(True)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addLayout(form)
        layout.addWidget(note)
        layout.addWidget(buttons)
        dialog.resize(480, 300)

        if _exec_dialog(dialog) != QDialog.Accepted:
            return

        fields: dict = {}
        if artist_edit.text().strip():
            fields["artist"] = artist_edit.text().strip()
        if album_artist_edit.text().strip():
            fields["album_artist"] = album_artist_edit.text().strip()
        if album_edit.text().strip():
            fields["album"] = album_edit.text().strip()
        if genre_edit.text().strip():
            fields["genre"] = genre_edit.text().strip()
        if year_spin.value() > 0:
            fields["year"] = year_spin.value()

        if not fields:
            return
        failed = 0
        for t in tracks:
            self.library.update_track(t.id, fields)
            if Path(t.path).is_file():
                if not write_partial_tags(Path(t.path), fields):
                    failed += 1
        n = len(tracks)
        msg = f"Updated metadata for {n} track{'s' if n != 1 else ''}."
        if failed:
            msg += f" ({failed} file{'s' if failed != 1 else ''} could not be written to disk.)"
        self.status_message.emit(msg)
        self.refresh()
        self.tracks_metadata_changed.emit([track.id for track in tracks])

    # ------------------------------------------------------------------ playlists
    def refresh_playlists(self) -> None:
        self._refresh_playlists()

    _PL_IS_SMART_ROLE = Qt.UserRole + 1
    _PL_RULES_ROLE    = Qt.UserRole + 2

    def _refresh_playlists(self) -> None:
        self.playlists_model.clear()
        for pl in self._library_all_playlists():
            prefix = "⚡ " if pl.is_smart else ""
            it = QStandardItem(f"{prefix}{pl.name}")
            it.setData(pl.id, Qt.UserRole)
            it.setData(pl.is_smart, self._PL_IS_SMART_ROLE)
            it.setData(pl.rules, self._PL_RULES_ROLE)
            self.playlists_model.appendRow(it)

    @staticmethod
    def _playlist_display_name(name: str | None) -> str:
        return (name or "").removeprefix("⚡ ")

    def _playlist_row_for_id(self, playlist_id: int) -> int:
        for row in range(self.playlists_model.rowCount()):
            if self.playlists_model.index(row, 0).data(Qt.UserRole) == playlist_id:
                return row
        return -1

    def _tracks_for_playlist_index(self, idx: QModelIndex) -> list[Track]:
        playlist_id = idx.data(Qt.UserRole)
        if not isinstance(playlist_id, int):
            return []
        is_smart = bool(idx.data(self._PL_IS_SMART_ROLE))
        rules_json = idx.data(self._PL_RULES_ROLE)
        if is_smart and rules_json:
            return self.library.smart_playlist_tracks(rules_json)
        return self.library.playlist_tracks(playlist_id)

    def _restore_active_playlist(self, playlist_id: int) -> bool:
        row = self._playlist_row_for_id(playlist_id)
        if row < 0:
            return False
        idx = self.playlists_model.index(row, 0)
        tracks = self._tracks_for_playlist_index(idx)
        self.playlists_view.blockSignals(True)
        self.playlists_view.setCurrentIndex(idx)
        self.playlists_view.blockSignals(False)
        self._active_playlist_id = playlist_id
        self._current_tracks = tracks
        self._populate_tracks(tracks)
        if self._browser_stack.currentIndex() in (2, 3):
            self._set_view_mode_checked(self._list_mode_btn)
            self._browser_stack.setCurrentIndex(1)
        return True

    def _clear_playlist_selection(self) -> None:
        self._active_playlist_id = None
        self.playlists_view.blockSignals(True)
        self.playlists_view.selectionModel().clearSelection()
        self.playlists_view.blockSignals(False)

    def _on_playlist_selected(self, idx: QModelIndex, _prev: QModelIndex) -> None:
        if not idx.isValid():
            return
        playlist_id = idx.data(Qt.UserRole)
        if not isinstance(playlist_id, int):
            return
        self._active_playlist_id = playlist_id
        tracks = self._tracks_for_playlist_index(idx)
        self._current_tracks = tracks
        self._populate_tracks(tracks)
        # Ensure list-mode browser is showing
        if self._browser_stack.currentIndex() in (2, 3):
            self._set_view_mode_checked(self._list_mode_btn)
            self._browser_stack.setCurrentIndex(1)

    def _on_playlist_tracks_dropped(self, playlist_id: int, track_ids: list) -> None:
        for row in range(self.playlists_model.rowCount()):
            idx = self.playlists_model.index(row, 0)
            if idx.data(Qt.UserRole) == playlist_id and idx.data(self._PL_IS_SMART_ROLE):
                self.status_message.emit("Cannot add tracks to a smart playlist.")
                return
        self._add_tracks_to_playlist(track_ids, playlist_id)

    def _on_playlist_context_menu(self, pos) -> None:
        menu = QMenu(self)
        new_act = menu.addAction("New Playlist…")
        new_smart_act = menu.addAction("New Smart Playlist…")
        import_act = menu.addAction("Import Playlist…")
        rename_act = edit_rules_act = remove_act = export_act = None
        playlist_id: int | None = None
        is_smart = False
        idx = self.playlists_view.indexAt(pos)
        if idx.isValid():
            playlist_id = idx.data(Qt.UserRole)
            is_smart = bool(idx.data(self._PL_IS_SMART_ROLE))
            if isinstance(playlist_id, int):
                rename_act = menu.addAction("Rename…")
                if is_smart:
                    edit_rules_act = menu.addAction("Edit Rules…")
                export_act = menu.addAction("Export as M3U…")
                menu.addSeparator()
                remove_act = menu.addAction("Delete Playlist")
        action = _exec_menu(menu, self.playlists_view.mapToGlobal(pos))
        if action is None:
            return
        if action == new_act:
            self._new_playlist_dialog()
        elif action == new_smart_act:
            self._new_smart_playlist_dialog()
        elif action == import_act:
            self._import_playlist_dialog()
        elif action == rename_act and playlist_id is not None:
            self._rename_playlist_dialog(
                playlist_id,
                self._playlist_display_name(idx.data(Qt.DisplayRole)),
            )
        elif action == edit_rules_act and playlist_id is not None:
            raw_name = idx.data(Qt.DisplayRole) or ""
            pl_name = raw_name.removeprefix("⚡ ")
            rules_json = idx.data(self._PL_RULES_ROLE) or ""
            self._edit_smart_playlist_rules(playlist_id, pl_name, rules_json)
        elif action == export_act and playlist_id is not None:
            self._export_playlist_m3u(playlist_id)
        elif action == remove_act and playlist_id is not None:
            self._delete_playlist_confirm(
                playlist_id,
                self._playlist_display_name(idx.data(Qt.DisplayRole)),
            )

    def _new_playlist_dialog(self, initial_track_ids: list[int] | None = None) -> None:
        name, ok = QInputDialog.getText(self, "New Playlist", "Playlist name:")
        if not ok or not name.strip():
            return
        try:
            pl_id = self.library.create_playlist(name.strip())
        except Exception as exc:
            self.status_message.emit(f"Could not create playlist: {exc}")
            return
        if initial_track_ids:
            self.library.add_to_playlist(pl_id, initial_track_ids)
        self._refresh_playlists()
        for row in range(self.playlists_model.rowCount()):
            if self.playlists_model.index(row, 0).data(Qt.UserRole) == pl_id:
                self.playlists_view.setCurrentIndex(self.playlists_model.index(row, 0))
                break

    def _new_smart_playlist_dialog(self) -> None:
        dlg = SmartPlaylistDialog(parent=self)
        if not _exec_dialog(dlg) or dlg.spec is None:
            return
        try:
            pl_id = self.library.create_smart_playlist(dlg.playlist_name, spec_to_json(dlg.spec))
        except Exception as exc:
            self.status_message.emit(f"Could not create smart playlist: {exc}")
            return
        self._refresh_playlists()
        for row in range(self.playlists_model.rowCount()):
            if self.playlists_model.index(row, 0).data(Qt.UserRole) == pl_id:
                self.playlists_view.setCurrentIndex(self.playlists_model.index(row, 0))
                break

    def _edit_smart_playlist_rules(
        self, playlist_id: int, pl_name: str, rules_json: str
    ) -> None:
        dlg = SmartPlaylistDialog(name=pl_name, rules_json=rules_json, parent=self)
        if not _exec_dialog(dlg) or dlg.spec is None:
            return
        new_rules = spec_to_json(dlg.spec)
        try:
            # Update rules first; if it fails, the name is untouched.
            self.library.update_playlist_rules(playlist_id, new_rules)
            if dlg.playlist_name != pl_name:
                self.library.rename_playlist(playlist_id, dlg.playlist_name)
        except Exception as exc:
            self.status_message.emit(f"Could not update smart playlist: {exc}")
            return
        self._refresh_playlists()
        # Re-select and re-run the query
        for row in range(self.playlists_model.rowCount()):
            idx = self.playlists_model.index(row, 0)
            if idx.data(Qt.UserRole) == playlist_id:
                self.playlists_view.setCurrentIndex(idx)
                break

    def _add_to_new_playlist(self, track_ids: list[int]) -> None:
        self._new_playlist_dialog(initial_track_ids=track_ids)

    def _add_tracks_to_playlist(self, track_ids: list[int], playlist_id: int) -> None:
        self.library.add_to_playlist(playlist_id, track_ids)
        n = len(track_ids)
        self.status_message.emit(f"Added {n} track{'s' if n != 1 else ''} to playlist.")
        if self._active_playlist_id == playlist_id:
            tracks = self.library.playlist_tracks(playlist_id)
            self._current_tracks = tracks
            self._populate_tracks(tracks)

    def _rename_playlist_dialog(self, playlist_id: int, current_name: str) -> None:
        current_name = self._playlist_display_name(current_name)
        name, ok = QInputDialog.getText(
            self, "Rename Playlist", "New name:", text=current_name or ""
        )
        if not ok or not name.strip():
            return
        try:
            self.library.rename_playlist(playlist_id, name.strip())
        except Exception as exc:
            self.status_message.emit(f"Rename failed: {exc}")
            return
        self._refresh_playlists()
        for row in range(self.playlists_model.rowCount()):
            if self.playlists_model.index(row, 0).data(Qt.UserRole) == playlist_id:
                self.playlists_view.setCurrentIndex(self.playlists_model.index(row, 0))
                break

    def _delete_playlist_confirm(self, playlist_id: int, name: str) -> None:
        r = QMessageBox.question(
            self, "Delete Playlist",
            f'Delete playlist "{name}"? This cannot be undone.',
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if r != QMessageBox.Yes:
            return
        self.library.delete_playlist(playlist_id)
        if self._active_playlist_id == playlist_id:
            self._active_playlist_id = None
            self._current_tracks = []
            self._clear_tracks_model()
            self._update_footer()
        self._refresh_playlists()

    def _export_playlist_m3u(self, playlist_id: int) -> None:
        tracks = self.library.playlist_tracks(playlist_id)
        if not tracks:
            self.status_message.emit("Playlist is empty — nothing to export.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Playlist", "", "M3U Playlist (*.m3u8 *.m3u)"
        )
        if not path:
            return
        try:
            lines = ["#EXTM3U"]
            for t in tracks:
                dur = int(t.duration or -1)
                lines.append(f"#EXTINF:{dur},{t.display_artist} - {t.title}")
                lines.append(t.path)
            Path(path).write_text("\n".join(lines), encoding="utf-8")
            self.status_message.emit(
                f"Exported {len(tracks)} tracks to {Path(path).name}"
            )
        except OSError as exc:
            self.status_message.emit(f"Export failed: {exc}")

    def _import_playlist_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Import Playlist", "", "Playlists (*.m3u *.m3u8 *.pls)"
        )
        if not path:
            return
        from ..core.playlist_import import import_playlist
        try:
            result = import_playlist(self.library, Path(path))
        except Exception as exc:
            self.status_message.emit(f"Import failed: {exc}")
            return
        self._refresh_playlists()
        for row in range(self.playlists_model.rowCount()):
            if self.playlists_model.index(row, 0).data(Qt.UserRole) == result.playlist_id:
                self.playlists_view.setCurrentIndex(self.playlists_model.index(row, 0))
                break
        msg = f"Imported {result.matched} track{'s' if result.matched != 1 else ''} from {Path(path).name}"
        if result.matched == 0 and result.unmatched:
            QMessageBox.warning(
                self,
                "Empty Playlist Imported",
                f"None of the {len(result.unmatched)} path"
                f"{'s' if len(result.unmatched) != 1 else ''} in this playlist were "
                "found in the library. The playlist was created but is empty — "
                "add the referenced files to your library and try again, or delete it.",
            )
        elif result.unmatched:
            n = len(result.unmatched)
            detail = "\n".join(result.unmatched[:10])
            if n > 10:
                detail += f"\n…and {n - 10} more"
            QMessageBox.warning(
                self,
                "Unmatched Paths",
                f"{n} path{'s' if n != 1 else ''} from the playlist were not found in the library:\n\n{detail}",
            )
        self.status_message.emit(msg)

"""Library browser: artists -> albums -> tracks, plus search."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QAbstractItemView, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QListView, QPushButton, QSplitter, QTableView, QVBoxLayout, QWidget,
)

from ..core.library import Library, Track
from .widgets import format_duration


class LibraryView(QWidget):
    play_tracks = Signal(list, int)        # (tracks, start_index)
    enqueue_tracks = Signal(list)
    status_message = Signal(str)
    request_rescan = Signal()
    request_add_folder = Signal()

    def __init__(self, library: Library, parent: QWidget | None = None):
        super().__init__(parent)
        self.library = library

        # Top toolbar
        top = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search artist, album, or track...")
        self.search.textChanged.connect(self._on_search)
        self.play_btn = QPushButton("Play")
        self.play_btn.clicked.connect(self._play_selected)
        self.enqueue_btn = QPushButton("Enqueue")
        self.enqueue_btn.clicked.connect(self._enqueue_selected)
        add_btn = QPushButton("Add Folder")
        add_btn.clicked.connect(self.request_add_folder.emit)
        rescan_btn = QPushButton("Rescan")
        rescan_btn.clicked.connect(self.request_rescan.emit)
        top.addWidget(self.search, 1)
        top.addWidget(self.play_btn)
        top.addWidget(self.enqueue_btn)
        top.addWidget(add_btn)
        top.addWidget(rescan_btn)

        # Splitter: artists | albums | tracks
        self.artists = QListView()
        self.artists.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.artists_model = QStandardItemModel()
        self.artists.setModel(self.artists_model)

        self.albums = QListView()
        self.albums.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.albums_model = QStandardItemModel()
        self.albums.setModel(self.albums_model)

        self.tracks = QTableView()
        self.tracks.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tracks.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tracks.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tracks.setAlternatingRowColors(True)
        self.tracks.setMouseTracking(True)
        self.tracks.verticalHeader().setVisible(False)
        self.tracks_model = QStandardItemModel(0, 5)
        self.tracks_model.setHorizontalHeaderLabels(["#", "Title", "Artist", "Album", "Time"])
        self.tracks.setModel(self.tracks_model)
        self.tracks.horizontalHeader().setStretchLastSection(False)
        self.tracks.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)

        splitter = QSplitter(Qt.Horizontal)
        for w, label in ((self.artists, "Artists"), (self.albums, "Albums")):
            box = QWidget()
            v = QVBoxLayout(box)
            v.setContentsMargins(0, 0, 0, 0)
            heading = QLabel(label)
            heading.setStyleSheet("color:#ffb24d;font-weight:600;padding:4px 6px;")
            v.addWidget(heading)
            v.addWidget(w)
            splitter.addWidget(box)
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rh = QLabel("Tracks")
        rh.setStyleSheet("color:#ffb24d;font-weight:600;padding:4px 6px;")
        rv.addWidget(rh)
        rv.addWidget(self.tracks)
        splitter.addWidget(right)
        splitter.setSizes([180, 220, 600])

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addLayout(top)
        layout.addWidget(splitter, 1)

        self.artists.selectionModel().currentChanged.connect(lambda *_: self._refresh_albums())
        self.albums.selectionModel().currentChanged.connect(lambda *_: self._refresh_tracks())
        self.tracks.doubleClicked.connect(self._on_track_double)

        self._current_tracks: list[Track] = []
        self.refresh()

    # ------------------------------------------------------------------ data
    def refresh(self) -> None:
        self.artists_model.clear()
        for a in self.library.all_artists():
            self.artists_model.appendRow(QStandardItem(a))
        if self.artists_model.rowCount():
            self.artists.setCurrentIndex(self.artists_model.index(0, 0))
        else:
            self.albums_model.clear()
            self.tracks_model.removeRows(0, self.tracks_model.rowCount())
            self._current_tracks = []

    def _refresh_albums(self) -> None:
        self.albums_model.clear()
        idx = self.artists.currentIndex()
        if not idx.isValid():
            self._current_tracks = []
            self.tracks_model.removeRows(0, self.tracks_model.rowCount())
            return
        artist = idx.data(Qt.DisplayRole)
        for album, _art in self.library.albums_for_artist(artist):
            it = QStandardItem(album)
            it.setData(album, Qt.UserRole)
            self.albums_model.appendRow(it)
        if self.albums_model.rowCount():
            self.albums.setCurrentIndex(self.albums_model.index(0, 0))
        else:
            self._current_tracks = []
            self.tracks_model.removeRows(0, self.tracks_model.rowCount())

    def _refresh_tracks(self) -> None:
        self.tracks_model.removeRows(0, self.tracks_model.rowCount())
        ai = self.artists.currentIndex()
        bi = self.albums.currentIndex()
        if not ai.isValid() or not bi.isValid():
            self._current_tracks = []
            return
        artist = ai.data(Qt.DisplayRole)
        album = bi.data(Qt.DisplayRole)
        self._current_tracks = self.library.tracks_for_album(artist, album)
        self._populate_tracks(self._current_tracks)

    def _populate_tracks(self, tracks: list[Track]) -> None:
        for tr in tracks:
            duration = format_duration(tr.duration)
            tooltip = self._track_tooltip(tr, duration)
            row = [
                QStandardItem(str(tr.track_no or "")),
                QStandardItem(tr.title),
                QStandardItem(tr.artist),
                QStandardItem(tr.album),
                QStandardItem(duration),
            ]
            for it in row:
                it.setEditable(False)
                it.setToolTip(tooltip)
            self.tracks_model.appendRow(row)

    def _track_tooltip(self, track: Track, duration: str) -> str:
        file_type = Path(track.path).suffix.lstrip(".").upper() or "Unknown"
        artist = track.display_artist
        album = track.album or "Unknown Album"
        return f"Artist: {artist}\nAlbum: {album}\nTime: {duration}\nFile type: {file_type}"

    # ------------------------------------------------------------------ search
    def _on_search(self, q: str) -> None:
        q = q.strip()
        self.tracks_model.removeRows(0, self.tracks_model.rowCount())
        if not q:
            self._refresh_tracks()
            return
        self._current_tracks = self.library.search(q)
        self._populate_tracks(self._current_tracks)

    # ------------------------------------------------------------------ playback
    def _selected_rows(self) -> list[int]:
        rows = {idx.row() for idx in self.tracks.selectionModel().selectedRows()}
        if rows:
            return sorted(rows)
        idx = self.tracks.currentIndex()
        return [idx.row()] if idx.isValid() else []

    def _selected_tracks(self) -> list[Track]:
        return [self._current_tracks[i] for i in self._selected_rows() if i < len(self._current_tracks)]

    def _play_selected(self) -> None:
        if not self._current_tracks:
            return
        rows = self._selected_rows()
        if rows:
            tracks = [self._current_tracks[i] for i in rows if i < len(self._current_tracks)]
            if tracks:
                self.play_tracks.emit(tracks, 0)
            return
        self.play_tracks.emit(self._current_tracks, 0)

    def _enqueue_selected(self) -> None:
        tracks = self._selected_tracks() or list(self._current_tracks)
        if tracks:
            self.enqueue_tracks.emit(tracks)
        else:
            self.status_message.emit("No tracks selected to enqueue.")

    def _on_track_double(self, index) -> None:
        if not index.isValid() or not self._current_tracks:
            return
        self.play_tracks.emit(self._current_tracks, index.row())

    def highlight_track(self, track: Track | None) -> None:
        if track is None:
            return
        row = self._row_for_track(track)
        if row < 0 and not self.search.text().strip():
            self._show_track_album(track)
            row = self._row_for_track(track)
        if row >= 0:
            self._select_track_row(row)

    def _row_for_track(self, track: Track) -> int:
        for row, current in enumerate(self._current_tracks):
            if self._same_track(current, track):
                return row
        return -1

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
        artist_row = self._find_model_row(self.artists_model, artist)
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

"""Library browser: artists -> albums -> tracks, all-tracks view, and filters."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
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
        self._current_tracks: list[Track] = []
        self._filtering = False

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

        filters = QHBoxLayout()
        self.view_mode = QComboBox()
        self.view_mode.addItem("Artist / Album Browser", "browser")
        self.view_mode.addItem("All Tracks", "all")
        self.view_mode.currentIndexChanged.connect(self._on_filter_changed)
        self.genre_filter = QComboBox()
        self.genre_filter.currentIndexChanged.connect(self._on_filter_changed)
        self.year_filter = QComboBox()
        self.year_filter.currentIndexChanged.connect(self._on_filter_changed)
        self.sort_filter = QComboBox()
        self.sort_filter.addItem("Sort: Artist", "artist")
        self.sort_filter.addItem("Sort: Album", "album")
        self.sort_filter.addItem("Sort: Title", "title")
        self.sort_filter.addItem("Sort: Year", "year")
        self.sort_filter.addItem("Sort: Recently Added", "added")
        self.sort_filter.currentIndexChanged.connect(self._on_filter_changed)
        filters.addWidget(QLabel("View:"))
        filters.addWidget(self.view_mode)
        filters.addWidget(QLabel("Genre:"))
        filters.addWidget(self.genre_filter)
        filters.addWidget(QLabel("Year:"))
        filters.addWidget(self.year_filter)
        filters.addWidget(self.sort_filter)
        filters.addStretch(1)

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
        self.tracks_model = QStandardItemModel(0, 9)
        self.tracks_model.setHorizontalHeaderLabels(
            ["#", "Title", "Artist", "Album", "Year", "Genre", "Bitrate", "Type", "Time"]
        )
        self.tracks.setModel(self.tracks_model)
        header = self.tracks.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        for column in (0, 4, 6, 7, 8):
            header.setSectionResizeMode(column, QHeaderView.ResizeToContents)

        splitter = QSplitter(Qt.Horizontal)
        self.artist_box = self._labeled_box(self.artists, "Artists")
        self.album_box = self._labeled_box(self.albums, "Albums")
        splitter.addWidget(self.artist_box)
        splitter.addWidget(self.album_box)
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rh = QLabel("Tracks")
        rh.setStyleSheet("color:#72f4ff;font-weight:600;padding:4px 6px;")
        rv.addWidget(rh)
        rv.addWidget(self.tracks)
        splitter.addWidget(right)
        splitter.setSizes([180, 220, 600])

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addLayout(top)
        layout.addLayout(filters)
        layout.addWidget(splitter, 1)

        self.artists.selectionModel().currentChanged.connect(lambda *_: self._refresh_albums())
        self.albums.selectionModel().currentChanged.connect(lambda *_: self._refresh_tracks())
        self.tracks.doubleClicked.connect(self._on_track_double)

        self.refresh()

    def _labeled_box(self, view: QListView, label: str) -> QWidget:
        box = QWidget()
        v = QVBoxLayout(box)
        v.setContentsMargins(0, 0, 0, 0)
        heading = QLabel(label)
        heading.setStyleSheet("color:#72f4ff;font-weight:600;padding:4px 6px;")
        v.addWidget(heading)
        v.addWidget(view)
        return box

    # ------------------------------------------------------------------ data
    def refresh(self) -> None:
        self._refresh_facets()
        self.artist_box.setEnabled(True)
        self.album_box.setEnabled(True)
        self.artists_model.clear()
        for a in self.library.all_artists():
            self.artists_model.appendRow(QStandardItem(a))
        if self._all_tracks_mode() or self._has_active_filters():
            self._apply_track_filters()
            return
        if self.artists_model.rowCount():
            self.artists.setCurrentIndex(self.artists_model.index(0, 0))
        else:
            self.albums_model.clear()
            self.tracks_model.removeRows(0, self.tracks_model.rowCount())
            self._current_tracks = []

    def _refresh_facets(self) -> None:
        self._filtering = True
        current_genre = self.genre_filter.currentData() or ""
        current_year = self.year_filter.currentData()
        self.genre_filter.clear()
        self.genre_filter.addItem("All Genres", "")
        for genre in self.library.all_genres():
            self.genre_filter.addItem(genre, genre)
        genre_idx = self.genre_filter.findData(current_genre)
        self.genre_filter.setCurrentIndex(max(0, genre_idx))

        self.year_filter.clear()
        self.year_filter.addItem("All Years", None)
        for year in self.library.all_years():
            self.year_filter.addItem(str(year), year)
        year_idx = self.year_filter.findData(current_year)
        self.year_filter.setCurrentIndex(max(0, year_idx))
        self._filtering = False

    def _refresh_albums(self) -> None:
        if self._all_tracks_mode() or self._has_active_filters():
            return
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
        if self._all_tracks_mode() or self._has_active_filters():
            return
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
        self.tracks_model.removeRows(0, self.tracks_model.rowCount())
        details = self._track_details([track.id for track in tracks])
        for tr in tracks:
            duration = format_duration(tr.duration)
            bitrate, samplerate = details.get(tr.id, (0, 0))
            tooltip = self._track_tooltip(tr, duration, bitrate, samplerate)
            row = [
                QStandardItem(str(tr.track_no or "")),
                QStandardItem(tr.title),
                QStandardItem(tr.display_artist),
                QStandardItem(tr.album or "Unknown Album"),
                QStandardItem(str(tr.year or "")),
                QStandardItem(tr.genre),
                QStandardItem(self._format_bitrate(bitrate)),
                QStandardItem(Path(tr.path).suffix.lstrip(".").upper() or "Unknown"),
                QStandardItem(duration),
            ]
            for it in row:
                it.setEditable(False)
                it.setToolTip(tooltip)
            self.tracks_model.appendRow(row)
        self.status_message.emit(f"Showing {len(tracks)} track{'s' if len(tracks) != 1 else ''}.")

    def _track_tooltip(self, track: Track, duration: str, bitrate: int, samplerate: int) -> str:
        file_type = Path(track.path).suffix.lstrip(".").upper() or "Unknown"
        artist = track.display_artist
        album = track.album or "Unknown Album"
        sample = f"{samplerate:,} Hz" if samplerate else "Unknown"
        return (
            f"Artist: {artist}\n"
            f"Album: {album}\n"
            f"Year: {track.year or 'Unknown'}\n"
            f"Genre: {track.genre or 'Unknown'}\n"
            f"Time: {duration}\n"
            f"Bitrate: {self._format_bitrate(bitrate)}\n"
            f"Sample rate: {sample}\n"
            f"File type: {file_type}\n"
            f"File location: {track.path}"
        )

    @staticmethod
    def _format_bitrate(bitrate: int) -> str:
        if bitrate <= 0:
            return "Unknown"
        kbps = round(bitrate / 1000)
        if kbps <= 0:
            return f"{bitrate} bps"
        return f"{kbps} kbps"

    def _track_details(self, ids: list[int]) -> dict[int, tuple[int, int]]:
        ids = [track_id for track_id in ids if track_id]
        if not ids:
            return {}
        placeholders = ",".join("?" for _ in ids)
        with self.library._lock:
            rows = self.library.conn.execute(
                f"SELECT id, bitrate, samplerate FROM tracks WHERE id IN ({placeholders})",
                tuple(ids),
            ).fetchall()
        return {int(row["id"]): (int(row["bitrate"] or 0), int(row["samplerate"] or 0)) for row in rows}

    # ------------------------------------------------------------------ search / filters
    def _all_tracks_mode(self) -> bool:
        return self.view_mode.currentData() == "all"

    def _has_active_filters(self) -> bool:
        return bool(self.search.text().strip() or self.genre_filter.currentData() or self.year_filter.currentData() is not None)

    def _on_filter_changed(self, *_args) -> None:
        if self._filtering:
            return
        self._apply_track_filters() if self._all_tracks_mode() or self._has_active_filters() else self.refresh()

    def _on_search(self, _q: str) -> None:
        self._apply_track_filters() if self._all_tracks_mode() or self._has_active_filters() else self._refresh_tracks()

    def _apply_track_filters(self) -> None:
        self.artist_box.setEnabled(not self._all_tracks_mode() and not self._has_active_filters())
        self.album_box.setEnabled(not self._all_tracks_mode() and not self._has_active_filters())
        self._current_tracks = self.library.filtered_tracks(
            self.search.text(),
            genre=self.genre_filter.currentData() or "",
            year=self.year_filter.currentData(),
            sort=self.sort_filter.currentData() or "artist",
        )
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
        if row < 0 and not self.search.text().strip() and not self._all_tracks_mode():
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

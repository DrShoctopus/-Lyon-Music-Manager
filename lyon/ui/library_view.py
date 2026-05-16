"""Library browser: artists -> albums -> tracks, plus search."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QDesktopServices, QKeySequence, QShortcut, QStandardItem, QStandardItemModel,
)
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QDialog, QDialogButtonBox, QFormLayout,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListView, QMenu, QPushButton,
    QSpinBox, QSplitter, QStackedWidget, QTableView, QVBoxLayout, QWidget,
)

from ..core.library import Library, Track
from .widgets import format_duration


# Sentinel stored in Qt.UserRole on the synthetic "All Albums" album row.
_ALL_ALBUMS_KEY = "__all_albums__"
# Roles used on the tracks model:
#   Qt.UserRole         -> per-column sort key (int for #/Time, lowercase str otherwise)
#   _TRACK_REF_ROLE     -> Track reference stored on column 0 only
_TRACK_REF_ROLE = Qt.UserRole + 1

_PLAYING_GLYPH = "▶"


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
        top.addWidget(self.search, 1)
        top.addWidget(self.play_btn)
        top.addWidget(self.enqueue_btn)
        top.addWidget(rescan_btn)
        top.addWidget(self._show_videos_cb)

        # ---- Artists / Albums lists
        self.artists = QListView()
        self.artists.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.artists_model = QStandardItemModel()
        self.artists.setModel(self.artists_model)

        self.albums = QListView()
        self.albums.setEditTriggers(QAbstractItemView.NoEditTriggers)
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

        self.tracks_model = QStandardItemModel(0, 5)
        self.tracks_model.setHorizontalHeaderLabels(["#", "Title", "Artist", "Album", "Time"])
        # Sort using a dedicated UserRole key so # / Time sort numerically and
        # text columns collate case-insensitively.
        self.tracks_model.setSortRole(Qt.UserRole)
        self.tracks.setModel(self.tracks_model)
        self.tracks.setSortingEnabled(True)
        self.tracks.sortByColumn(0, Qt.AscendingOrder)

        header = self.tracks.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.Fixed)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.Interactive)
        header.setSectionResizeMode(3, QHeaderView.Interactive)
        header.setSectionResizeMode(4, QHeaderView.Fixed)
        self.tracks.setColumnWidth(0, 50)
        self.tracks.setColumnWidth(2, 180)
        self.tracks.setColumnWidth(3, 200)
        self.tracks.setColumnWidth(4, 70)

        # Keyboard shortcuts scoped to the tracks table
        QShortcut(QKeySequence(Qt.Key_Return), self.tracks,
                  activated=self._play_selected, context=Qt.WidgetShortcut)
        QShortcut(QKeySequence(Qt.Key_Enter), self.tracks,
                  activated=self._play_selected, context=Qt.WidgetShortcut)
        QShortcut(QKeySequence("Ctrl+E"), self.tracks,
                  activated=self._enqueue_selected, context=Qt.WidgetShortcut)

        # ---- Splitter
        splitter = QSplitter(Qt.Horizontal)
        for w, label in ((self.artists, "Artists"), (self.albums, "Albums")):
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
        splitter.setSizes([180, 220, 600])

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
        self._browser_stack.addWidget(splitter)       # 1: browser

        # ---- Footer
        self._footer_label = QLabel("")
        self._footer_label.setObjectName("footerText")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addLayout(top)
        layout.addWidget(self._browser_stack, 1)
        layout.addWidget(self._footer_label)

        self.artists.selectionModel().currentChanged.connect(lambda *_: self._refresh_albums())
        self.albums.selectionModel().currentChanged.connect(lambda *_: self._refresh_tracks())
        self.tracks.doubleClicked.connect(self._on_track_double)

        self.refresh()

    # ------------------------------------------------------------------ data
    @property
    def _media_type_filter(self) -> str | None:
        return None if self._show_videos else "audio"

    def _on_show_videos_toggled(self, checked: bool) -> None:
        self._show_videos = checked
        self.refresh()

    def refresh(self) -> None:
        self.artists_model.clear()
        for a in self.library.all_artists(self._media_type_filter):
            self.artists_model.appendRow(QStandardItem(a))
        if self.artists_model.rowCount():
            self._browser_stack.setCurrentIndex(1)
            self.artists.setCurrentIndex(self.artists_model.index(0, 0))
        else:
            self._browser_stack.setCurrentIndex(0)
            self.albums_model.clear()
            self.tracks_model.removeRows(0, self.tracks_model.rowCount())
            self._current_tracks = []
            self._update_footer()

    def _refresh_albums(self) -> None:
        self.albums_model.clear()
        idx = self.artists.currentIndex()
        if not idx.isValid():
            self._current_tracks = []
            self.tracks_model.removeRows(0, self.tracks_model.rowCount())
            self._update_footer()
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
            self.albums_model.appendRow(it)
        if self.albums_model.rowCount():
            self.albums.setCurrentIndex(self.albums_model.index(0, 0))
        else:
            self._current_tracks = []
            self.tracks_model.removeRows(0, self.tracks_model.rowCount())
            self._update_footer()

    def _refresh_tracks(self) -> None:
        ai = self.artists.currentIndex()
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

            for it in (n_item, title_item, artist_item, album_item, time_item):
                it.setEditable(False)
                it.setToolTip(tooltip)
            self.tracks_model.appendRow([n_item, title_item, artist_item, album_item, time_item])
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

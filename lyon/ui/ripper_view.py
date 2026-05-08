"""Rip-from-CD view: detect disc, look up metadata, kick off rip."""
from __future__ import annotations

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QPixmap, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QMessageBox, QProgressBar, QPushButton, QTableView, QVBoxLayout, QWidget,
)

from ..core import cd_detect
from ..core.library import Library
from ..core.metadata import AlbumInfo, TrackInfo, fetch_artwork, lookup_disc, search_album
from ..core.ripper import RipRequest, Ripper, target_folder
from ..core.settings import Settings
from .widgets import cover_pixmap


def _row_track_no(text: str | None) -> int:
    """Parse a track-number cell. Returns 0 for empty/non-numeric."""
    if not text:
        return 0
    try:
        return int(text.strip())
    except ValueError:
        return 0


class _LookupThread(QThread):
    finished_with = Signal(object, object)   # (AlbumInfo|None, bytes|None)

    def __init__(self, toc: cd_detect.DiscToc, settings: Settings, parent=None):
        super().__init__(parent)
        self.toc = toc
        self.settings = settings

    def run(self) -> None:
        info = lookup_disc(self.toc.discid, self.toc.toc_string)
        art = None
        if info and self.settings.download_artwork:
            art = fetch_artwork(info)
        self.finished_with.emit(info, art)


class RipperView(QWidget):
    rip_completed = Signal()
    log = Signal(str)

    def __init__(self, settings: Settings, library: Library, parent: QWidget | None = None):
        super().__init__(parent)
        self.settings = settings
        self.library = library
        self.ripper = Ripper(settings, self)
        self._album: AlbumInfo | None = None
        self._toc: cd_detect.DiscToc | None = None
        self._lookup: _LookupThread | None = None

        # Drive selector + actions
        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("CD Drive:"))
        self.drive_combo = QComboBox()
        self.drive_combo.setMinimumWidth(80)
        toolbar.addWidget(self.drive_combo)
        self.refresh_btn = QPushButton("Refresh Drives")
        self.refresh_btn.clicked.connect(self.refresh_drives)
        toolbar.addWidget(self.refresh_btn)
        self.detect_btn = QPushButton("Read Disc")
        self.detect_btn.clicked.connect(self.detect_disc)
        toolbar.addWidget(self.detect_btn)
        toolbar.addStretch(1)
        self.start_btn = QPushButton("Rip CD")
        self.start_btn.setObjectName("accent")
        self.start_btn.setEnabled(False)
        self.start_btn.clicked.connect(self.start_rip)
        toolbar.addWidget(self.start_btn)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self.cancel_rip)
        toolbar.addWidget(self.cancel_btn)

        # Album header (cover + editable artist/album)
        header = QHBoxLayout()
        self.cover = QLabel()
        self.cover.setFixedSize(140, 140)
        self.cover.setAlignment(Qt.AlignCenter)
        self.cover.setStyleSheet("background:#0c0f14;border:1px solid #2a3340;")
        self.cover.setPixmap(cover_pixmap(None, 140, "CD"))
        header.addWidget(self.cover)

        meta = QVBoxLayout()
        self.album_edit = QLineEdit()
        self.album_edit.setPlaceholderText("Album title")
        f = self.album_edit.font(); f.setPointSize(14); f.setBold(True)
        self.album_edit.setFont(f)
        meta.addWidget(self.album_edit)
        self.artist_edit = QLineEdit()
        self.artist_edit.setPlaceholderText("Album artist")
        meta.addWidget(self.artist_edit)
        year_row = QHBoxLayout()
        self.year_edit = QLineEdit()
        self.year_edit.setPlaceholderText("Year")
        self.year_edit.setMaximumWidth(80)
        year_row.addWidget(QLabel("Year:"))
        year_row.addWidget(self.year_edit)
        self.relookup_btn = QPushButton("Search Online")
        self.relookup_btn.clicked.connect(self.search_online)
        year_row.addWidget(self.relookup_btn)
        year_row.addStretch(1)
        meta.addLayout(year_row)
        self.dest_label = QLabel("")
        self.dest_label.setStyleSheet("color:#8a93a0;")
        meta.addWidget(self.dest_label)
        meta.addStretch(1)
        header.addLayout(meta, 1)

        # Track table
        self.tracks_model = QStandardItemModel(0, 3)
        self.tracks_model.setHorizontalHeaderLabels(["#", "Title", "Status"])
        self.tracks = QTableView()
        self.tracks.setModel(self.tracks_model)
        self.tracks.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.SelectedClicked)
        self.tracks.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tracks.setAlternatingRowColors(True)
        self.tracks.verticalHeader().setVisible(False)
        self.tracks.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.tracks.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.tracks.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)

        # Status bar
        status_row = QHBoxLayout()
        self.status_label = QLabel("Insert a CD and click Read Disc.")
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        status_row.addWidget(self.status_label, 1)
        status_row.addWidget(self.progress, 2)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.addLayout(toolbar)
        layout.addLayout(header)
        layout.addWidget(self.tracks, 1)
        layout.addLayout(status_row)

        # Wire ripper signals
        self.ripper.track_started.connect(self._on_track_started)
        self.ripper.track_progress.connect(self._on_track_progress)
        self.ripper.track_finished.connect(self._on_track_finished)
        self.ripper.finished.connect(self._on_rip_finished)
        self.ripper.log.connect(self.log)

        for w in (self.album_edit, self.artist_edit, self.year_edit):
            w.textChanged.connect(self._update_dest)

        self.refresh_drives()

    # ------------------------------------------------------------------ drives
    def refresh_drives(self) -> None:
        self.drive_combo.clear()
        drives = cd_detect.list_cd_drives()
        if not drives:
            self.drive_combo.addItem("(no CD drive found)")
            self.drive_combo.setEnabled(False)
            self.detect_btn.setEnabled(False)
            return
        self.drive_combo.setEnabled(True)
        self.detect_btn.setEnabled(True)
        for d in drives:
            self.drive_combo.addItem(d)
        if self.settings.cd_drive in drives:
            self.drive_combo.setCurrentText(self.settings.cd_drive)

    # ------------------------------------------------------------------ detect
    def detect_disc(self) -> None:
        drive = self.drive_combo.currentText()
        if not drive or "no CD" in drive:
            return
        self.settings.cd_drive = drive
        self.settings.save()
        self.status_label.setText(f"Reading disc in {drive}...")
        toc = cd_detect.read_disc(drive)
        if toc is None:
            QMessageBox.warning(
                self, "No disc",
                "Couldn't read a disc in that drive. Make sure an audio CD is inserted, "
                "and that libdiscid.dll is bundled in the application's bin/ folder.",
            )
            self.status_label.setText("No audio disc detected.")
            return
        self._toc = toc
        self.status_label.setText(
            f"Disc found in {drive} ({toc.track_count} tracks). Looking up metadata..."
        )
        self._populate_default_tracks(toc.track_count)
        if self.settings.auto_lookup_metadata:
            # Abandon any in-flight lookup so its stale result can't overwrite
            # the metadata for this newly inserted disc.
            if self._lookup is not None and self._lookup.isRunning():
                try:
                    self._lookup.finished_with.disconnect(self._on_lookup_done)
                except (RuntimeError, TypeError):
                    pass
            self._lookup = _LookupThread(toc, self.settings, self)
            self._lookup.finished_with.connect(self._on_lookup_done)
            self._lookup.start()

    def _populate_default_tracks(self, n: int) -> None:
        self.tracks_model.removeRows(0, self.tracks_model.rowCount())
        for i in range(1, n + 1):
            row = [
                QStandardItem(str(i)),
                QStandardItem(f"Track {i:02d}"),
                QStandardItem(""),
            ]
            row[0].setEditable(False)
            row[2].setEditable(False)
            self.tracks_model.appendRow(row)
        self._update_dest()

    def _on_lookup_done(self, info: AlbumInfo | None, art: bytes | None) -> None:
        if info is None:
            self.status_label.setText(
                "Disc not found in MusicBrainz. Edit titles manually or click Search Online."
            )
            self.start_btn.setEnabled(True)
            return
        if art is not None:
            info.artwork = art
        self._apply_album(info)

    def _apply_album(self, info: AlbumInfo) -> None:
        self._album = info
        self.album_edit.setText(info.album)
        self.artist_edit.setText(info.artist)
        self.year_edit.setText(str(info.year) if info.year else "")
        self.tracks_model.removeRows(0, self.tracks_model.rowCount())
        for tr in info.tracks:
            row = [
                QStandardItem(str(tr.number)),
                QStandardItem(tr.title),
                QStandardItem(""),
            ]
            row[0].setEditable(False)
            row[2].setEditable(False)
            self.tracks_model.appendRow(row)
        if info.artwork:
            pm = QPixmap()
            pm.loadFromData(info.artwork)
            if not pm.isNull():
                self.cover.setPixmap(pm.scaled(140, 140, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            self.cover.setPixmap(cover_pixmap(None, 140, "CD"))
        self.status_label.setText(f"Found: {info.artist} - {info.album}")
        self.start_btn.setEnabled(True)
        self._update_dest()

    def search_online(self) -> None:
        artist = self.artist_edit.text().strip()
        album = self.album_edit.text().strip()
        if not (artist and album):
            QMessageBox.information(self, "Search Online",
                                    "Enter an artist and album to search.")
            return
        self.status_label.setText("Searching MusicBrainz...")
        info = search_album(artist, album)
        if not info:
            self.status_label.setText("No matching release found.")
            return
        if self.settings.download_artwork:
            info.artwork = fetch_artwork(info)
        self._apply_album(info)

    def _update_dest(self, *_) -> None:
        album = AlbumInfo(
            artist=self.artist_edit.text().strip() or "Unknown Artist",
            album=self.album_edit.text().strip() or "Unknown Album",
            date=self.year_edit.text().strip(),
        )
        folder = target_folder(self.settings, album)
        self.dest_label.setText(f"Will save to: {folder}")

    # ------------------------------------------------------------------ ripping
    def start_rip(self) -> None:
        if self.ripper.is_running():
            return
        if not self._toc:
            QMessageBox.information(self, "No Disc", "Read a disc first.")
            return

        # Build album from current edits + table
        album = AlbumInfo(
            artist=self.artist_edit.text().strip() or "Unknown Artist",
            album=self.album_edit.text().strip() or "Unknown Album",
            date=self.year_edit.text().strip(),
            musicbrainz_albumid=(self._album.musicbrainz_albumid if self._album else ""),
            artwork=(self._album.artwork if self._album else None),
        )
        for r in range(self.tracks_model.rowCount()):
            raw = (self.tracks_model.item(r, 0).text() or "").strip()
            try:
                num = int(raw) if raw else r + 1
            except ValueError:
                num = r + 1
            title = self.tracks_model.item(r, 1).text().strip() or f"Track {num:02d}"
            album.tracks.append(TrackInfo(number=num, title=title, artist=album.artist))

        folder = target_folder(self.settings, album, create=True)
        self.start_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.detect_btn.setEnabled(False)
        self.progress.setRange(0, len(album.tracks))
        self.progress.setValue(0)

        req = RipRequest(drive=self._toc.drive, album=album, target_dir=folder)
        self.ripper.start(req)

    def cancel_rip(self) -> None:
        self.ripper.cancel()
        self.status_label.setText("Cancelling...")

    # ------------------------------------------------------------------ progress
    def _on_track_started(self, n: int, title: str) -> None:
        self.status_label.setText(f"Ripping {n:02d}: {title}")
        for r in range(self.tracks_model.rowCount()):
            if _row_track_no(self.tracks_model.item(r, 0).text()) == n:
                self.tracks_model.item(r, 2).setText("Ripping...")
                break

    def _on_track_progress(self, n: int, pct: int) -> None:
        # Per-track percentage isn't exposed by ffmpeg easily; ignore.
        pass

    def _on_track_finished(self, n: int, path: str) -> None:
        for r in range(self.tracks_model.rowCount()):
            if _row_track_no(self.tracks_model.item(r, 0).text()) == n:
                self.tracks_model.item(r, 2).setText("Done")
                break
        self.progress.setValue(self.progress.value() + 1)
        self.library.add_file(path)
        self.library.conn.commit()

    def _on_rip_finished(self, ok: bool, msg: str) -> None:
        self.status_label.setText(msg)
        self.start_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.detect_btn.setEnabled(True)
        if ok and self.settings.eject_after_rip and self._toc:
            cd_detect.eject(self._toc.drive)
        self.rip_completed.emit()

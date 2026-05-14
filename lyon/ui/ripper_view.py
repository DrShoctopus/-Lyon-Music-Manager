"""Rip-from-CD view: detect disc, look up metadata, kick off rip."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtGui import QPixmap, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QMessageBox, QProgressBar, QPushButton, QStyle, QStyleOptionProgressBar,
    QStyledItemDelegate, QTableView, QVBoxLayout, QWidget,
)

from ..core import cd_detect
from ..core.library import Library
from ..core.metadata import (
    AlbumInfo,
    TrackInfo,
    fetch_artwork,
    lookup_disc,
    metadata_diagnostics_log_path,
    search_album,
)
from ..core.ripper import RipRequest, Ripper, target_file, unique_target_folder
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


class _ProgressDelegate(QStyledItemDelegate):
    """Paint the Status column as an inline percent-complete bar."""

    def paint(self, painter, option, index) -> None:  # noqa: D102
        pct = index.data(Qt.UserRole)
        if pct is None:
            super().paint(painter, option, index)
            return

        try:
            pct = max(0, min(100, int(pct)))
        except (TypeError, ValueError):
            super().paint(painter, option, index)
            return

        progress = QStyleOptionProgressBar()
        progress.rect = option.rect.adjusted(4, 4, -4, -4)
        progress.minimum = 0
        progress.maximum = 100
        progress.progress = pct
        progress.text = f"{pct}%"
        progress.textAlignment = Qt.AlignCenter
        progress.textVisible = True

        widget = option.widget
        style = widget.style() if widget is not None else self.parent().style()
        style.drawControl(QStyle.CE_ProgressBar, progress, painter, widget)


class _DiscReadThread(QThread):
    finished_with = Signal(object)  # DiscToc|None

    def __init__(self, drive: str, parent=None):
        super().__init__(parent)
        self.drive = drive
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        toc = cd_detect.read_disc(self.drive)
        if self._cancelled:
            return
        self.finished_with.emit(toc)


class _LookupThread(QThread):
    finished_with = Signal(object, object)   # (AlbumInfo|None, bytes|None)

    def __init__(self, toc: cd_detect.DiscToc, settings: Settings, parent=None):
        super().__init__(parent)
        self.toc = toc
        self.settings = settings
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        info = lookup_disc(
            self.toc.discid,
            self.toc.toc_string,
            ctdb_toc=self.toc.ctdb_toc_string,
            use_cuetools_db=self.settings.cuetools_db_metadata_enabled,
        )
        if self._cancelled:
            return
        art = None
        if info and self.settings.download_artwork:
            art = fetch_artwork(info)
        if self._cancelled:
            return
        self.finished_with.emit(info, art)


class _AlbumSearchThread(QThread):
    finished_with = Signal(object, object)   # (AlbumInfo|None, bytes|None)

    def __init__(self, artist: str, album: str, settings: Settings, parent=None):
        super().__init__(parent)
        self.artist = artist
        self.album = album
        self.settings = settings
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        info = search_album(self.artist, self.album)
        if self._cancelled:
            return
        art = None
        if info and self.settings.download_artwork:
            art = fetch_artwork(info)
        if self._cancelled:
            return
        self.finished_with.emit(info, art)


def _rip_request_from_toc(
    toc: cd_detect.DiscToc,
    album: AlbumInfo,
    folder: Path,
) -> RipRequest:
    """Build a rip request using the already-read disc TOC.

    Reusing the cached offsets avoids a second libdiscid read at rip time, which
    can fail independently of the initial disc detection and leave ffmpeg without
    the timing data it needs to split tracks.
    """
    return RipRequest(
        drive=toc.drive,
        album=album,
        target_dir=folder,
        track_offsets=tuple(toc.track_offsets),
        leadout_sector=toc.sectors,
        ctdb_toc=toc.ctdb_toc_string,
    )


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
        self._disc_reader: _DiscReadThread | None = None
        self._lookup: _LookupThread | None = None
        self._search: _AlbumSearchThread | None = None

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
        self.tracks.setItemDelegateForColumn(2, _ProgressDelegate(self.tracks))
        header_view = self.tracks.horizontalHeader()
        header_view.setSectionResizeMode(1, QHeaderView.Stretch)
        header_view.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header_view.setSectionResizeMode(2, QHeaderView.Fixed)
        self._status_column_width = int(header_view.defaultSectionSize() * 1.5)
        header_view.resizeSection(2, self._status_column_width)

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
        self.ripper.log.connect(self.status_label.setText)

        self._dest_timer = QTimer(self)
        self._dest_timer.setSingleShot(True)
        self._dest_timer.setInterval(200)
        self._dest_timer.timeout.connect(self._update_dest)
        self.album_edit.textChanged.connect(self._dest_timer.start)
        self.artist_edit.textChanged.connect(self._dest_timer.start)
        self.year_edit.textChanged.connect(self._dest_timer.start)

        self.refresh_drives()
        self._update_dest()

    def apply_settings(self, settings: Settings) -> None:
        self.settings = settings
        self.ripper.settings = settings
        self._update_dest()
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
        if self._disc_reader is not None and self._disc_reader.isRunning():
            return
        self.settings.cd_drive = drive
        self.settings.save()
        self.status_label.setText(f"Reading disc in {drive}...")
        self.detect_btn.setEnabled(False)
        self.refresh_btn.setEnabled(False)
        self.start_btn.setEnabled(False)
        self._disc_reader = _DiscReadThread(drive, self)
        self._disc_reader.finished_with.connect(self._on_disc_read)
        self._disc_reader.finished.connect(self._disc_reader.deleteLater)
        self._disc_reader.start()

    def _on_disc_read(self, toc: cd_detect.DiscToc | None) -> None:
        self.detect_btn.setEnabled(True)
        self.refresh_btn.setEnabled(True)
        self._disc_reader = None
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
            f"Disc found in {toc.drive} ({toc.track_count} tracks). Looking up metadata..."
        )
        self._populate_default_tracks(toc.track_count)
        if self.settings.auto_lookup_metadata:
            self._start_lookup(toc)
        else:
            self.start_btn.setEnabled(True)

    def _start_lookup(self, toc: cd_detect.DiscToc) -> None:
        self._lookup = _LookupThread(toc, self.settings, self)
        self._lookup.finished_with.connect(self._on_lookup_done)
        self._lookup.finished.connect(self._lookup.deleteLater)
        self._lookup.start()

    def _populate_default_tracks(self, n: int) -> None:
        self.tracks_model.removeRows(0, self.tracks_model.rowCount())
        for i in range(1, n + 1):
            self._add_track_row(i, f"Track {i:02d}")
        self._update_dest()

    def _add_track_row(self, number: int, title: str) -> None:
        row = [
            QStandardItem(str(number)),
            QStandardItem(title),
            QStandardItem("0%"),
        ]
        row[0].setEditable(False)
        row[2].setEditable(False)
        row[2].setData(0, Qt.UserRole)
        self.tracks_model.appendRow(row)
        self.tracks.horizontalHeader().resizeSection(2, self._status_column_width)

    def _set_track_progress(self, number: int, pct: int) -> None:
        pct = max(0, min(100, int(pct)))
        for r in range(self.tracks_model.rowCount()):
            if _row_track_no(self.tracks_model.item(r, 0).text()) == number:
                status = self.tracks_model.item(r, 2)
                status.setText(f"{pct}%")
                status.setData(pct, Qt.UserRole)
                break

    def _on_lookup_done(self, info: AlbumInfo | None, art: bytes | None) -> None:
        if self.sender() is not self._lookup:
            return
        self._lookup = None
        if info is None:
            message = (
                "Disc not found in CUETools DB, MusicBrainz, or TheAudioDB. "
                "Edit titles manually or click Search Online."
            )
            if self.settings.metadata_diagnostics_enabled:
                message += f" Detailed lookup log: {metadata_diagnostics_log_path()}"
            self.status_label.setText(message)
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
            self._add_track_row(tr.number, tr.title)
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
        if self._search is not None and self._search.isRunning():
            return
        self.status_label.setText("Searching MusicBrainz and TheAudioDB...")
        self.relookup_btn.setEnabled(False)
        self._search = _AlbumSearchThread(artist, album, self.settings, self)
        self._search.finished_with.connect(self._on_search_done)
        self._search.finished.connect(self._search.deleteLater)
        self._search.start()

    def _on_search_done(self, info: AlbumInfo | None, art: bytes | None) -> None:
        if self.sender() is not self._search:
            return
        self._search = None
        self.relookup_btn.setEnabled(True)
        if not info:
            message = "No matching release found."
            if self.settings.metadata_diagnostics_enabled:
                message += f" Detailed lookup log: {metadata_diagnostics_log_path()}"
            self.status_label.setText(message)
            return
        if art is not None:
            info.artwork = art
        self._apply_album(info)

    def _update_dest(self, *_) -> None:
        album = AlbumInfo(
            artist=self.artist_edit.text().strip() or "Unknown Artist",
            album=self.album_edit.text().strip() or "Unknown Album",
            date=self.year_edit.text().strip(),
        )
        folder = unique_target_folder(self.settings, album)
        self.dest_label.setText(f"Will save to: {folder}")

    # ------------------------------------------------------------------ ripping
    def start_rip(self) -> None:
        if self.ripper.is_running():
            return
        if not self._toc:
            QMessageBox.information(self, "No Disc", "Read a disc first.")
            return

        album = self._album_from_edits()
        if not album.tracks:
            QMessageBox.information(self, "No Tracks", "No tracks are available to rip.")
            return

        folder = unique_target_folder(self.settings, album)
        existing = [target_file(folder, tr, len(album.tracks)) for tr in album.tracks]
        existing = [p for p in existing if p.exists()]
        if existing:
            shown = "\n".join(str(p.name) for p in existing[:8])
            if len(existing) > 8:
                shown += f"\n...and {len(existing) - 8} more"
            answer = QMessageBox.question(
                self,
                "Overwrite existing files?",
                "The destination already contains files that will be overwritten:\n\n"
                f"{shown}\n\nContinue and overwrite them?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                self.status_label.setText("Rip cancelled before overwriting existing files.")
                return

        folder = unique_target_folder(self.settings, album, create=True)
        self.start_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.detect_btn.setEnabled(False)
        self.progress.setRange(0, len(album.tracks))
        self.progress.setValue(0)
        for tr in album.tracks:
            self._set_track_progress(tr.number, 0)

        req = _rip_request_from_toc(self._toc, album, folder)
        self.ripper.start(req)

    def _album_from_edits(self) -> AlbumInfo:
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
        return album

    def cancel_rip(self) -> None:
        self.ripper.cancel()
        self.status_label.setText("Cancelling...")

    def shutdown(self) -> None:
        """Stop ripper + worker threads. Called from MainWindow.closeEvent.

        The libdiscid read and MusicBrainz / CTDB / TheAudioDB HTTP calls
        these threads make have no cancellation primitive, so we (1) disconnect
        the result signals to keep stale emits from reaching the about-to-be-
        destroyed widget, (2) flag the thread so any post-network work is
        skipped, and (3) cap the per-thread wait to keep app close responsive.
        terminate() is the last-resort fallback so Qt does not abort with
        "Destroyed while thread is still running" when the process is exiting.
        """
        self.ripper.shutdown()
        for thread_attr in ("_disc_reader", "_lookup", "_search"):
            t = getattr(self, thread_attr, None)
            if t is None:
                continue
            try:
                t.finished_with.disconnect()
            except (TypeError, RuntimeError):
                pass
            try:
                t.cancel()
            except AttributeError:
                pass
            if t.isRunning() and not t.wait(1500):
                t.terminate()
                t.wait(500)

    # ------------------------------------------------------------------ progress
    def _on_track_started(self, n: int, title: str) -> None:
        self.status_label.setText(f"Ripping {n:02d}: {title}")
        self._set_track_progress(n, 0)

    def _on_track_progress(self, n: int, pct: int) -> None:
        self._set_track_progress(n, pct)

    def _on_track_finished(self, n: int, path: str) -> None:
        self._set_track_progress(n, 100)
        self.progress.setValue(self.progress.value() + 1)
        self.library.add_file(path)
        self.library.commit()

    def _on_rip_finished(self, ok: bool, msg: str) -> None:
        self.status_label.setText(msg)
        self.start_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.detect_btn.setEnabled(True)
        if ok and self.settings.eject_after_rip and self._toc:
            cd_detect.eject(self._toc.drive)
        self.rip_completed.emit()

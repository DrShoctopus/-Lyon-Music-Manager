"""Rip-from-CD view: detect disc, look up metadata, kick off rip."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QRectF, QThread, QTimer, Signal
from PySide6.QtGui import (
    QColor, QFont, QLinearGradient, QPainter, QPainterPath,
    QPixmap, QStandardItem, QStandardItemModel,
)
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QMessageBox, QProgressBar, QPushButton,
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
from ..core.ripper import (
    RipRequest,
    Ripper,
    format_extension,
    track_output_files,
    unique_target_folder,
)
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


# Sentinel values stored in Qt.UserRole for the Status column.
_STATUS_WAITING   = None   # not yet started
_STATUS_DONE      = 100    # completed successfully
_STATUS_FAILED    = -1     # failed / not completed
_STATUS_CANCELLED = -2     # cancelled mid-rip


def _draw_app_progress_bar(painter: QPainter, rect, pct: int, label: str) -> None:
    """Draw an app-styled progress bar with split-colour label text.

    Matches the QProgressBar QSS (dark bg, blue-cyan gradient chunk).
    Text is dark-grey over the filled chunk and light over the empty background.
    pct: 0-100.
    """
    r = QRectF(rect)
    chunk_w = r.width() * max(0, min(100, pct)) / 100.0

    painter.save()

    # Background
    bg_path = QPainterPath()
    bg_path.addRoundedRect(r, 5.0, 5.0)
    painter.setPen(QColor("#27313b"))
    painter.fillPath(bg_path, QColor("#070a0f"))
    painter.drawPath(bg_path)

    # Chunk
    if chunk_w > 0.5:
        grad = QLinearGradient(r.left(), 0.0, r.right(), 0.0)
        grad.setColorAt(0.00, QColor("#0f3c9c"))
        grad.setColorAt(0.55, QColor("#1b8dff"))
        grad.setColorAt(1.00, QColor("#68f3ff"))
        chunk_path = QPainterPath()
        chunk_path.addRoundedRect(QRectF(r.left(), r.top(), chunk_w, r.height()), 4.0, 4.0)
        chunk_path = chunk_path.intersected(bg_path)
        painter.fillPath(chunk_path, grad)

    # Label – bold dark text over the filled area, light text over the empty area.
    # Bold + near-black gives strong contrast against the blue gradient when the
    # bar has overtaken the percentage/label text.
    normal_font = painter.font()
    bold_font = QFont(normal_font)
    bold_font.setBold(True)

    painter.setClipping(True)
    if chunk_w > 0.5:
        painter.setClipRect(QRectF(r.left(), r.top(), chunk_w, r.height()))
        painter.setFont(bold_font)
        painter.setPen(QColor("#0d0d0d"))
        painter.drawText(rect, Qt.AlignCenter, label)
        painter.setFont(normal_font)
    rest_w = r.width() - chunk_w
    if rest_w > 0.5:
        painter.setClipRect(QRectF(r.left() + chunk_w, r.top(), rest_w, r.height()))
        painter.setPen(QColor("#f0fbff"))
        painter.drawText(rect, Qt.AlignCenter, label)
    painter.setClipping(False)

    painter.restore()


class _AppProgressBar(QProgressBar):
    """QProgressBar painted with the app's custom bar style and split-colour text."""

    def paintEvent(self, event) -> None:
        mn, mx, val = self.minimum(), self.maximum(), self.value()
        pct = int(100 * (val - mn) / (mx - mn)) if mx > mn else 0
        p = QPainter(self)
        _draw_app_progress_bar(p, self.rect(), pct, f"{pct}%")
        p.end()


class _ProgressDelegate(QStyledItemDelegate):
    """Paint the Status column.

    Qt.UserRole semantics:
      None           → "Waiting"  (gray text)
      0 – 99 (int)   → progress bar at that percent
      100            → "Done"     (full bar, "Done" label)
      -1             → "Failed"   (red text)
      -2             → "Cancelled"(gray text)
    """

    def paint(self, painter, option, index) -> None:  # noqa: D102
        val = index.data(Qt.UserRole)

        # Named terminal states — paint as coloured text.
        if val is None or val in (_STATUS_FAILED, _STATUS_CANCELLED):
            labels  = {None: "Waiting", _STATUS_FAILED: "Failed", _STATUS_CANCELLED: "Cancelled"}
            colors  = {None: "#8a93a0", _STATUS_FAILED: "#e85050", _STATUS_CANCELLED: "#8a93a0"}
            painter.save()
            painter.setPen(QColor(colors[val]))
            painter.drawText(option.rect, Qt.AlignCenter, labels[val])
            painter.restore()
            return

        try:
            pct = max(0, min(100, int(val)))
        except (TypeError, ValueError):
            super().paint(painter, option, index)
            return

        label = "Done" if pct == _STATUS_DONE else f"{pct}%"
        _draw_app_progress_bar(painter, option.rect.adjusted(4, 4, -4, -4), pct, label)


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
    track_numbers: tuple[int, ...] = (),
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
        track_numbers=track_numbers,
    )


def _existing_target_files(settings: Settings, album: AlbumInfo, folder: Path) -> list[Path]:
    ext = format_extension(settings.rip_format)
    return [path for path in track_output_files(folder, album.tracks, len(album.tracks), ext) if path.exists()]


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
        self._active_track_nums: set[int] = set()
        self._done_track_nums: set[int] = set()
        self._last_rip_folder: Path | None = None

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
        self.cover.setObjectName("ripperCover")
        self.cover.setFixedSize(140, 140)
        self.cover.setAlignment(Qt.AlignCenter)
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
        self.clear_meta_btn = QPushButton("Clear Metadata")
        self.clear_meta_btn.clicked.connect(self._clear_metadata)
        year_row.addWidget(self.clear_meta_btn)
        year_row.addStretch(1)
        meta.addLayout(year_row)
        self.dest_label = QLabel("")
        self.dest_label.setObjectName("mutedTextSmall")
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
        self.progress = _AppProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        status_row.addWidget(self.status_label, 1)
        status_row.addWidget(self.progress, 2)

        self.retry_btn = QPushButton("Retry Failed Tracks")
        self.retry_btn.setObjectName("accent")
        self.retry_btn.setToolTip("Re-rip only the tracks that failed in the previous attempt")
        self.retry_btn.clicked.connect(self._retry_failed)
        self.retry_btn.setVisible(False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.addLayout(toolbar)
        layout.addLayout(header)
        layout.addWidget(self.tracks, 1)
        layout.addLayout(status_row)
        layout.addWidget(self.retry_btn)

        # Wire ripper signals
        self.ripper.track_started.connect(self._on_track_started)
        self.ripper.track_progress.connect(self._on_track_progress)
        self.ripper.track_finished.connect(self._on_track_finished)
        self.ripper.track_failed.connect(self._on_track_failed)
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

        if toc.discid and self.library.has_disc(toc.discid, toc.track_count):
            album_info = self.library.album_for_disc(toc.discid)
            label = f"{album_info[0]} – {album_info[1]}" if album_info else "this disc"
            self._reset_disc_state()
            self.status_label.setText("Already in library — disc ejected.")
            cd_detect.eject(toc.drive)
            QMessageBox.information(
                self,
                "Already in Library",
                f"“{label}” is already in your library.\nThe disc has been ejected.",
            )
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

    def _reset_disc_state(self) -> None:
        """Clear cached TOC + album info and wipe the disc-specific UI fields."""
        self._toc = None
        self._album = None
        self.tracks_model.removeRows(0, self.tracks_model.rowCount())
        self.album_edit.clear()
        self.artist_edit.clear()
        self.year_edit.clear()
        self.cover.setPixmap(cover_pixmap(None, 140, "CD"))
        self.progress.setValue(0)
        self.retry_btn.setVisible(False)
        self._active_track_nums = set()
        self._done_track_nums = set()
        self._last_rip_folder = None

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
            QStandardItem("Waiting"),
        ]
        row[0].setEditable(False)
        row[2].setEditable(False)
        row[2].setData(_STATUS_WAITING, Qt.UserRole)
        self.tracks_model.appendRow(row)
        self.tracks.horizontalHeader().resizeSection(2, self._status_column_width)

    def _set_track_progress(self, number: int, pct: int) -> None:
        pct = max(0, min(100, int(pct)))
        for r in range(self.tracks_model.rowCount()):
            if _row_track_no(self.tracks_model.item(r, 0).text()) == number:
                status = self.tracks_model.item(r, 2)
                if pct == _STATUS_DONE:
                    status.setText("Done")
                else:
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

    def _clear_metadata(self) -> None:
        self.tracks_model.removeRows(0, self.tracks_model.rowCount())
        self.album_edit.clear()
        self.artist_edit.clear()
        self.year_edit.clear()
        self.cover.setPixmap(cover_pixmap(None, 140, "CD"))

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
        existing = _existing_target_files(self.settings, album, folder)
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
        self._last_rip_folder = folder
        self.start_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.detect_btn.setEnabled(False)
        self.retry_btn.setVisible(False)
        self.progress.setRange(0, len(album.tracks))
        self.progress.setValue(0)
        self._active_track_nums = {tr.number for tr in album.tracks}
        self._done_track_nums = set()
        for tr in album.tracks:
            self._set_track_status_sentinel(tr.number, _STATUS_WAITING)

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
            setattr(self, thread_attr, None)

    # ------------------------------------------------------------------ progress
    def _on_track_started(self, n: int, title: str) -> None:
        self.status_label.setText(f"Ripping track {n:02d}: {title}")
        self._set_track_progress(n, 1)

    def _on_track_progress(self, n: int, pct: int) -> None:
        self._set_track_progress(n, max(1, pct))

    def _on_track_finished(self, n: int, path: str) -> None:
        self._set_track_progress(n, _STATUS_DONE)
        self._done_track_nums.add(n)
        self.progress.setValue(self.progress.value() + 1)
        self.library.add_file(path, disc_id=self._toc.discid if self._toc else None)
        self.library.commit()

    def _on_track_failed(self, n: int, _reason: str) -> None:
        self._set_track_status_sentinel(n, _STATUS_FAILED)

    def _on_rip_finished(self, ok: bool, msg: str) -> None:
        self.status_label.setText(msg)
        self.start_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.detect_btn.setEnabled(True)

        if not ok:
            # Mark any track that wasn't completed as Failed (or Cancelled).
            cancelled = "cancel" in msg.lower()
            sentinel = _STATUS_CANCELLED if cancelled else _STATUS_FAILED
            for n in self._active_track_nums - self._done_track_nums:
                if self._track_status(n) != _STATUS_FAILED:
                    self._set_track_status_sentinel(n, sentinel)
            if not cancelled and self._track_nums_with_status(_STATUS_FAILED):
                self.retry_btn.setVisible(True)

        if ok and self.settings.eject_after_rip and self._toc:
            cd_detect.eject(self._toc.drive)
        self.rip_completed.emit()

    def _set_track_status_sentinel(self, number: int, sentinel) -> None:
        labels = {
            _STATUS_WAITING: "Waiting",
            _STATUS_FAILED: "Failed",
            _STATUS_CANCELLED: "Cancelled",
        }
        for r in range(self.tracks_model.rowCount()):
            if _row_track_no(self.tracks_model.item(r, 0).text()) == number:
                status_item = self.tracks_model.item(r, 2)
                status_item.setText(labels.get(sentinel, ""))
                status_item.setData(sentinel, Qt.UserRole)
                break

    def _track_status(self, number: int):
        for r in range(self.tracks_model.rowCount()):
            if _row_track_no(self.tracks_model.item(r, 0).text()) == number:
                return self.tracks_model.item(r, 2).data(Qt.UserRole)
        return None

    def _track_nums_with_status(self, sentinel) -> set[int]:
        nums: set[int] = set()
        for r in range(self.tracks_model.rowCount()):
            number = _row_track_no(self.tracks_model.item(r, 0).text())
            if number and self.tracks_model.item(r, 2).data(Qt.UserRole) == sentinel:
                nums.add(number)
        return nums

    def _retry_failed(self) -> None:
        """Re-rip only the tracks that are currently marked Failed."""
        if not self._toc:
            return
        album = self._album_from_edits()
        failed_nums = self._track_nums_with_status(_STATUS_FAILED)
        if not failed_nums:
            return

        folder = self._last_rip_folder or unique_target_folder(self.settings, album, create=True)

        self.start_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.detect_btn.setEnabled(False)
        self.retry_btn.setVisible(False)
        self.progress.setRange(0, len(failed_nums))
        self.progress.setValue(0)
        self._active_track_nums = set(failed_nums)
        self._done_track_nums = set()
        for n in sorted(failed_nums):
            self._set_track_status_sentinel(n, _STATUS_WAITING)

        req = _rip_request_from_toc(
            self._toc,
            album,
            folder,
            track_numbers=tuple(sorted(failed_nums)),
        )
        self.ripper.start(req)

"""Optical disc playback view."""
from __future__ import annotations

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QFrame, QHBoxLayout, QHeaderView, QLabel, QPushButton,
    QStackedWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..core import cd_detect
from ..core.disc_playback import DiscKind, VideoDiscSource, probe_video_disc, tracks_from_audio_cd
from ..core.library import Track
from ..core.metadata import AlbumInfo, lookup_disc
from ..core.settings import Settings
from .widgets import format_duration


class _DiscReadThread(QThread):
    finished_with = Signal(object, object)  # DiscToc|None, AlbumInfo|None

    def __init__(self, drive: str, settings: Settings, parent=None):
        super().__init__(parent)
        self.drive = drive
        self.settings = settings
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        toc = cd_detect.read_disc(self.drive)
        if self._cancelled:
            return
        album = None
        if toc is not None:
            album = lookup_disc(
                toc.discid,
                toc.toc_string,
                ctdb_toc=toc.ctdb_toc_string,
                use_cuetools_db=self.settings.cuetools_db_metadata_enabled,
            )
        if self._cancelled:
            return
        self.finished_with.emit(toc, album)


class DiscView(QWidget):
    """Drive selector and controls for Audio CD, DVD, and VCD/SVCD playback."""

    play_audio_tracks = Signal(object, int)   # list[Track], start index
    enqueue_audio_tracks = Signal(object)     # list[Track]
    play_video_disc = Signal(object)          # VideoDiscSource
    stop_video_disc = Signal()
    rip_drive_requested = Signal(str)
    status_message = Signal(str)

    def __init__(self, settings: Settings, parent: QWidget | None = None):
        super().__init__(parent)
        self.settings = settings
        self._audio_tracks: list[Track] = []
        self._reader: _DiscReadThread | None = None
        self._video_source: VideoDiscSource | None = None

        self.setObjectName("discView")
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 14, 18, 14)
        root.setSpacing(12)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        toolbar.addWidget(QLabel("Drive:"))
        self.drive_combo = QComboBox()
        self.drive_combo.setMinimumWidth(92)
        toolbar.addWidget(self.drive_combo)

        toolbar.addWidget(QLabel("Type:"))
        self.kind_combo = QComboBox()
        self.kind_combo.addItem("Auto", None)
        self.kind_combo.addItem("Audio CD", DiscKind.AUDIO_CD)
        self.kind_combo.addItem("DVD", DiscKind.DVD)
        self.kind_combo.addItem("VCD/SVCD", DiscKind.VCD)
        toolbar.addWidget(self.kind_combo)

        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self.refresh_drives)
        toolbar.addWidget(self.refresh_btn)
        self.probe_btn = QPushButton("Read Disc")
        self.probe_btn.setObjectName("accent")
        self.probe_btn.clicked.connect(self.probe_disc)
        toolbar.addWidget(self.probe_btn)
        self.eject_btn = QPushButton("Eject")
        self.eject_btn.clicked.connect(self._eject)
        toolbar.addWidget(self.eject_btn)
        toolbar.addStretch(1)
        root.addLayout(toolbar)

        self.status_label = QLabel("Insert a disc and click Read Disc.")
        self.status_label.setObjectName("mutedText")
        root.addWidget(self.status_label)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_empty_page())
        self.stack.addWidget(self._build_audio_page())
        self.stack.addWidget(self._build_video_page())
        root.addWidget(self.stack, 1)

        self.refresh_drives()

    def _build_empty_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setAlignment(Qt.AlignCenter)
        label = QLabel("No disc loaded.")
        label.setObjectName("mutedText")
        layout.addWidget(label)
        return page

    def _build_audio_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(8)

        self.album_label = QLabel("Audio CD")
        self.album_label.setObjectName("sectionTitle")
        layout.addWidget(self.album_label)

        self.track_table = QTableWidget(0, 4)
        self.track_table.setHorizontalHeaderLabels(["#", "Title", "Artist", "Time"])
        self.track_table.verticalHeader().setVisible(False)
        self.track_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.track_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.track_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.track_table.doubleClicked.connect(lambda idx: self._play_audio_index(idx.row()))
        header = self.track_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        layout.addWidget(self.track_table, 1)

        controls = QHBoxLayout()
        self.play_disc_btn = QPushButton("Play Disc")
        self.play_disc_btn.clicked.connect(lambda: self._play_audio_index(0))
        self.play_track_btn = QPushButton("Play Selected")
        self.play_track_btn.clicked.connect(self._play_selected_audio)
        self.enqueue_btn = QPushButton("Enqueue Selected")
        self.enqueue_btn.clicked.connect(self._enqueue_selected_audio)
        self.rip_btn = QPushButton("Rip this CD")
        self.rip_btn.clicked.connect(lambda: self.rip_drive_requested.emit(self._selected_drive()))
        for btn in (self.play_disc_btn, self.play_track_btn, self.enqueue_btn, self.rip_btn):
            controls.addWidget(btn)
        controls.addStretch(1)
        layout.addLayout(controls)
        return page

    def _build_video_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setAlignment(Qt.AlignTop)
        layout.setSpacing(10)

        box = QFrame()
        box.setObjectName("videoControls")
        box_layout = QVBoxLayout(box)
        box_layout.setContentsMargins(14, 12, 14, 12)
        self.video_title = QLabel("Video disc")
        self.video_title.setObjectName("sectionTitle")
        self.video_body = QLabel("Use Play Disc to open the selected optical disc with VLC.")
        self.video_body.setObjectName("mutedText")
        self.video_body.setWordWrap(True)
        row = QHBoxLayout()
        self.play_video_btn = QPushButton("Play Disc")
        self.play_video_btn.setObjectName("accent")
        self.play_video_btn.clicked.connect(self._play_video)
        self.play_no_menu_btn = QPushButton("Play Without Menus")
        self.play_no_menu_btn.clicked.connect(self._play_video_fallback)
        self.play_no_menu_btn.setVisible(False)
        self.stop_video_btn = QPushButton("Stop")
        self.stop_video_btn.clicked.connect(self.stop_video_disc.emit)
        row.addWidget(self.play_video_btn)
        row.addWidget(self.play_no_menu_btn)
        row.addWidget(self.stop_video_btn)
        row.addStretch(1)
        box_layout.addWidget(self.video_title)
        box_layout.addWidget(self.video_body)
        box_layout.addLayout(row)
        layout.addWidget(box)
        layout.addStretch(1)
        return page

    def refresh_drives(self) -> None:
        current = self.drive_combo.currentText()
        self.drive_combo.clear()
        drives = cd_detect.list_cd_drives()
        if not drives:
            self.drive_combo.addItem("(no optical drive found)")
            self.drive_combo.setEnabled(False)
            self.probe_btn.setEnabled(False)
            self.eject_btn.setEnabled(False)
            return
        self.drive_combo.setEnabled(True)
        self.probe_btn.setEnabled(True)
        self.eject_btn.setEnabled(True)
        for drive in drives:
            self.drive_combo.addItem(drive)
        if current in drives:
            self.drive_combo.setCurrentText(current)
        elif self.settings.cd_drive in drives:
            self.drive_combo.setCurrentText(self.settings.cd_drive)

    def probe_disc(self) -> None:
        drive = self._selected_drive()
        if not drive:
            return
        self.settings.cd_drive = drive
        self._audio_tracks = []
        self._video_source = None
        self._set_busy(True)
        requested = self.kind_combo.currentData()
        if requested in (DiscKind.DVD, DiscKind.VCD):
            self._show_video_source(probe_video_disc(drive, requested))
            self._set_busy(False)
            return
        self.status_label.setText(f"Reading disc in {drive}...")
        self._reader = _DiscReadThread(drive, self.settings, self)
        self._reader.finished_with.connect(self._on_audio_read)
        self._reader.finished.connect(self._clear_reader)
        self._reader.start()

    def _on_audio_read(self, toc, album: AlbumInfo | None) -> None:
        requested = self.kind_combo.currentData()
        if toc is None:
            if requested == DiscKind.AUDIO_CD:
                self.status_label.setText("No readable Audio CD was found.")
                self.stack.setCurrentIndex(0)
                return
            source = probe_video_disc(self._selected_drive())
            self._show_video_source(source)
            return
        self._audio_tracks = tracks_from_audio_cd(toc, album)
        title = album.album if album else "Audio CD"
        artist = album.artist if album else ""
        self.album_label.setText(f"{artist} - {title}" if artist else title)
        self._populate_audio_table()
        self.status_label.setText(f"Audio CD ready: {len(self._audio_tracks)} tracks.")
        self.stack.setCurrentIndex(1)

    def _clear_reader(self) -> None:
        self._reader = None
        self._set_busy(False)

    def _show_video_source(self, source: VideoDiscSource) -> None:
        self._video_source = source
        fallback = " A no-menu fallback is available if VLC cannot open the disc." if source.fallback_uri else ""
        self.video_title.setText(source.label)
        self.video_body.setText(f"Ready to open {source.uri}.{fallback}")
        self.play_no_menu_btn.setVisible(bool(source.fallback_uri))
        self.status_label.setText(f"{source.label} source ready.")
        self.stack.setCurrentIndex(2)

    def _populate_audio_table(self) -> None:
        self.track_table.setRowCount(len(self._audio_tracks))
        for row, track in enumerate(self._audio_tracks):
            values = [
                str(track.track_no or row + 1),
                track.title,
                track.display_artist,
                format_duration(track.duration),
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.track_table.setItem(row, col, item)
        if self._audio_tracks:
            self.track_table.selectRow(0)
        self.track_table.resizeColumnToContents(0)
        self.track_table.resizeColumnToContents(2)
        self.track_table.resizeColumnToContents(3)

    def _selected_audio_rows(self) -> list[int]:
        rows = sorted({idx.row() for idx in self.track_table.selectionModel().selectedRows()})
        return [row for row in rows if 0 <= row < len(self._audio_tracks)]

    def _play_selected_audio(self) -> None:
        rows = self._selected_audio_rows()
        self._play_audio_index(rows[0] if rows else 0)

    def _play_audio_index(self, index: int) -> None:
        if not self._audio_tracks:
            return
        index = max(0, min(index, len(self._audio_tracks) - 1))
        self.play_audio_tracks.emit(list(self._audio_tracks), index)

    def _enqueue_selected_audio(self) -> None:
        rows = self._selected_audio_rows()
        tracks = [self._audio_tracks[row] for row in rows] if rows else list(self._audio_tracks)
        if tracks:
            self.enqueue_audio_tracks.emit(tracks)

    def _play_video(self) -> None:
        if self._video_source is None:
            self._show_video_source(probe_video_disc(self._selected_drive(), self.kind_combo.currentData()))
        if self._video_source is not None:
            self.play_video_disc.emit(self._video_source)

    def _play_video_fallback(self) -> None:
        if self._video_source is None or not self._video_source.fallback_uri:
            return
        self.play_video_disc.emit(
            VideoDiscSource(
                self._video_source.drive,
                self._video_source.kind,
                self._video_source.fallback_uri,
                label=f"{self._video_source.label} (no menus)",
            )
        )

    def _eject(self) -> None:
        drive = self._selected_drive()
        if drive:
            cd_detect.eject(drive)
            self.status_label.setText(f"Ejected {drive}.")

    def _selected_drive(self) -> str:
        text = self.drive_combo.currentText()
        return "" if not text or "no optical" in text else text

    def _set_busy(self, busy: bool) -> None:
        self.probe_btn.setEnabled(not busy and self.drive_combo.isEnabled())
        self.refresh_btn.setEnabled(not busy)
        self.kind_combo.setEnabled(not busy)

    def shutdown(self) -> None:
        if self._reader is not None:
            reader = self._reader
            reader.cancel()
            reader.requestInterruption()
            reader.quit()
            if not reader.wait(3000):
                reader.terminate()
                reader.wait(2000)
            self._reader = None

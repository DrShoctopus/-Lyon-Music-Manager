"""Internet radio browser and station manager."""
from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QFrame, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..core.radio import RadioStation, parse_playlist_file, station_from_settings, station_from_url
from ..core.settings import Settings, normalize_radio_stations

LOG = logging.getLogger(__name__)

_COL_NAME = 0
_COL_GENRE = 1
_COL_BITRATE = 2
_COL_URL = 3


class _StationDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Add Radio Station")
        self.resize(420, 180)

        form = QFormLayout()
        form.setContentsMargins(12, 12, 12, 12)
        form.setVerticalSpacing(8)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Station name")
        form.addRow("Name:", self.name_edit)

        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("https://example.com/stream")
        form.addRow("URL:", self.url_edit)

        self.genre_edit = QLineEdit()
        self.genre_edit.setPlaceholderText("Optional")
        form.addRow("Genre:", self.genre_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def station(self) -> RadioStation | None:
        return station_from_url(
            self.url_edit.text(),
            name=self.name_edit.text(),
            genre=self.genre_edit.text(),
        )


class RadioView(QWidget):
    play_requested = Signal(str, str)  # url, title
    status_message = Signal(str)

    def __init__(self, settings: Settings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._settings = settings
        self.setObjectName("radioView")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)

        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(0, 0, 0, 0)
        toolbar.setSpacing(6)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search stations...")
        self.search.setClearButtonEnabled(True)
        self.search.setAccessibleName("Radio station search")
        self.search.textChanged.connect(self._filter)
        toolbar.addWidget(self.search, 1)

        self.play_btn = QPushButton("Play")
        self.play_btn.setObjectName("accent")
        self.play_btn.clicked.connect(self._play_selected)
        toolbar.addWidget(self.play_btn)

        self.add_btn = QPushButton("Add...")
        self.add_btn.clicked.connect(self._add_station)
        toolbar.addWidget(self.add_btn)

        self.import_btn = QPushButton("Import Playlist...")
        self.import_btn.clicked.connect(self._import_playlist)
        toolbar.addWidget(self.import_btn)

        self.remove_btn = QPushButton("Remove")
        self.remove_btn.clicked.connect(self._remove_selected)
        toolbar.addWidget(self.remove_btn)

        layout.addLayout(toolbar)

        self.table = QTableWidget(0, 4)
        self.table.setObjectName("radioStationTable")
        self.table.setHorizontalHeaderLabels(["Station", "Genre", "Bitrate", "URL"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.itemDoubleClicked.connect(lambda _item: self._play_selected())
        self.table.itemSelectionChanged.connect(self._update_buttons)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(_COL_NAME, QHeaderView.Stretch)
        header.setSectionResizeMode(_COL_GENRE, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(_COL_BITRATE, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(_COL_URL, QHeaderView.Stretch)
        layout.addWidget(self.table, 1)

        footer = QFrame()
        footer.setObjectName("radioFooter")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(0, 0, 0, 0)
        self.footer_label = QLabel("")
        self.footer_label.setObjectName("mutedText")
        footer_layout.addWidget(self.footer_label)
        footer_layout.addStretch(1)
        layout.addWidget(footer)

        self.refresh()

    def apply_settings(self, settings: Settings) -> None:
        self._settings = settings
        self.refresh()

    def refresh(self) -> None:
        self.table.setRowCount(0)
        for raw_station in self._settings.radio_stations:
            station = station_from_settings(raw_station)
            if station is not None:
                self._append_station_row(station)
        self._filter(self.search.text())
        self._update_buttons()

    def _append_station_row(self, station: RadioStation) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)

        name_item = QTableWidgetItem(station.name)
        name_item.setData(Qt.UserRole, station.as_settings_dict())
        self.table.setItem(row, _COL_NAME, name_item)
        self.table.setItem(row, _COL_GENRE, QTableWidgetItem(station.genre))
        bitrate_text = f"{station.bitrate} kbps" if station.bitrate else ""
        self.table.setItem(row, _COL_BITRATE, QTableWidgetItem(bitrate_text))
        self.table.setItem(row, _COL_URL, QTableWidgetItem(station.url))

    def _current_station(self) -> RadioStation | None:
        row = self.table.currentRow()
        if row < 0 or self.table.isRowHidden(row):
            return None
        item = self.table.item(row, _COL_NAME)
        if item is None:
            return None
        return station_from_settings(item.data(Qt.UserRole))

    def _play_selected(self) -> None:
        station = self._current_station()
        if station is None:
            return
        self._settings.remember_stream_url(station.url)
        self._save_settings()
        self.play_requested.emit(station.url, station.name)

    def _add_station(self) -> None:
        dialog = _StationDialog(self)
        try:
            if dialog.exec() != QDialog.Accepted:
                return
            station = dialog.station()
        finally:
            dialog.deleteLater()
        if station is None:
            QMessageBox.warning(self, "Add Radio Station", "Enter a valid network stream URL.")
            return
        self._settings.add_radio_stations([station.as_settings_dict()])
        self._save_settings()
        self.refresh()
        self._select_station_url(station.url)
        self.status_message.emit(f'Added radio station "{station.name}".')

    def _import_playlist(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Import Radio Playlist",
            "",
            "Playlist Files (*.m3u *.m3u8 *.pls);;All Files (*)",
        )
        if not path:
            return
        try:
            stations = parse_playlist_file(path)
        except OSError as exc:
            LOG.warning("Could not import radio playlist %s: %s", path, exc)
            QMessageBox.warning(self, "Import Radio Playlist", f"Could not read {Path(path).name}.")
            return
        if not stations:
            QMessageBox.warning(self, "Import Radio Playlist", "No stream URLs were found.")
            return
        self._settings.add_radio_stations([station.as_settings_dict() for station in stations])
        self._save_settings()
        self.refresh()
        self._select_station_url(stations[0].url)
        count = len(stations)
        self.status_message.emit(f"Imported {count} radio station{'' if count == 1 else 's'}.")

    def _remove_selected(self) -> None:
        station = self._current_station()
        if station is None:
            return
        remaining = [
            raw
            for raw in self._settings.radio_stations
            if str(raw.get("url", "")).casefold() != station.url.casefold()
        ]
        self._settings.radio_stations = normalize_radio_stations(remaining)
        self._save_settings()
        self.refresh()
        self.status_message.emit(f'Removed radio station "{station.name}".')

    def _filter(self, text: str) -> None:
        query = text.strip().casefold()
        visible = 0
        for row in range(self.table.rowCount()):
            station = station_from_settings(self.table.item(row, _COL_NAME).data(Qt.UserRole))
            haystack = " ".join((
                station.name,
                station.genre,
                station.url,
                str(station.bitrate or ""),
            )).casefold() if station else ""
            show = not query or query in haystack
            self.table.setRowHidden(row, not show)
            if show:
                visible += 1
        total = self.table.rowCount()
        self.footer_label.setText(f"{visible}/{total} stations" if query else f"{total} stations")
        self._update_buttons()

    def _select_station_url(self, url: str) -> None:
        for row in range(self.table.rowCount()):
            station = station_from_settings(self.table.item(row, _COL_NAME).data(Qt.UserRole))
            if station and station.url.casefold() == url.casefold():
                self.table.selectRow(row)
                return

    def _save_settings(self) -> None:
        try:
            self._settings.save()
        except OSError as exc:
            LOG.warning("Could not save radio settings: %s", exc)

    def _update_buttons(self) -> None:
        has_station = self._current_station() is not None
        self.play_btn.setEnabled(has_station)
        self.remove_btn.setEnabled(has_station)

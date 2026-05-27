"""Browse panel backed by the radio-browser.info directory."""
from __future__ import annotations

import logging

from PySide6.QtCore import QRunnable, Qt, QThreadPool, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
    QWidget,
)

from ..core.radio import RadioStation
from ..core.radio_browser import BrowseResult, RadioBrowserClient

LOG = logging.getLogger(__name__)

_COL_NAME = 0
_COL_TAGS = 1
_COL_COUNTRY = 2
_COL_BITRATE = 3
_COL_VOTES = 4

_ANY_TAG = "(any tag)"
_ANY_COUNTRY = "(any country)"


class RadioBrowserPanel(QWidget):
    """Browse and search the radio-browser.info public station directory."""

    play_requested = Signal(str, str)        # url, title
    station_add_requested = Signal(object)   # RadioStation

    # Private signals marshal worker-thread results onto the GUI thread.
    _results_ready = Signal(list)            # list[BrowseResult]
    _meta_ready = Signal(list, list)         # (tags: list[str], countries: list[str])
    _error_occurred = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._searching = False
        self._meta_loaded = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)

        # ---- search row
        search_row = QHBoxLayout()
        search_row.setSpacing(6)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Station name…")
        self.name_edit.setClearButtonEnabled(True)
        self.name_edit.returnPressed.connect(self._do_search)
        search_row.addWidget(self.name_edit, 2)

        self.tag_combo = QComboBox()
        self.tag_combo.setMinimumWidth(120)
        self.tag_combo.addItem(_ANY_TAG)
        self.tag_combo.setToolTip("Filter by tag / genre")
        search_row.addWidget(self.tag_combo, 1)

        self.country_combo = QComboBox()
        self.country_combo.setMinimumWidth(120)
        self.country_combo.addItem(_ANY_COUNTRY)
        self.country_combo.setToolTip("Filter by country code")
        search_row.addWidget(self.country_combo, 1)

        self.search_btn = QPushButton("Search")
        self.search_btn.setObjectName("accent")
        self.search_btn.clicked.connect(self._do_search)
        search_row.addWidget(self.search_btn)

        layout.addLayout(search_row)

        # ---- inline status / spinner
        self.status_label = QLabel("")
        self.status_label.setObjectName("mutedText")
        self.status_label.setVisible(False)
        layout.addWidget(self.status_label)

        # ---- results table
        self.table = QTableWidget(0, 5)
        self.table.setObjectName("radioBrowseTable")
        self.table.setHorizontalHeaderLabels(["Station", "Tags", "Country", "Bitrate", "Votes"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.itemDoubleClicked.connect(lambda _: self._play_selected())
        self.table.itemSelectionChanged.connect(self._update_buttons)

        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(_COL_NAME, QHeaderView.Stretch)
        hdr.setSectionResizeMode(_COL_TAGS, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(_COL_COUNTRY, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(_COL_BITRATE, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(_COL_VOTES, QHeaderView.ResizeToContents)
        layout.addWidget(self.table, 1)

        # ---- action row
        action_row = QHBoxLayout()
        action_row.setSpacing(6)
        action_row.addStretch(1)

        self.play_btn = QPushButton("Play")
        self.play_btn.setObjectName("accent")
        self.play_btn.setEnabled(False)
        self.play_btn.clicked.connect(self._play_selected)
        action_row.addWidget(self.play_btn)

        self.add_btn = QPushButton("Add to My Stations")
        self.add_btn.setEnabled(False)
        self.add_btn.clicked.connect(self._add_selected)
        action_row.addWidget(self.add_btn)

        layout.addLayout(action_row)

        # ---- signal wiring
        self._results_ready.connect(self._on_results_ready)
        self._meta_ready.connect(self._on_meta_ready)
        self._error_occurred.connect(self._on_error)

    # ------------------------------------------------------------------ events

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._meta_loaded:
            self._load_meta()

    # ------------------------------------------------------------------ public slots

    def _do_search(self) -> None:
        if self._searching:
            return
        self._set_searching(True)
        name = self.name_edit.text().strip()
        tag = self.tag_combo.currentText()
        country = self.country_combo.currentText()
        tag = "" if tag == _ANY_TAG else tag
        country = "" if country == _ANY_COUNTRY else country

        client = RadioBrowserClient.get()
        results_signal = self._results_ready
        error_signal = self._error_occurred

        class _SearchTask(QRunnable):
            def __init__(self):
                super().__init__()
                self.setAutoDelete(True)

            def run(self):
                try:
                    results = client.search(name=name, tag=tag, country=country, limit=100)
                    results_signal.emit(results)
                except Exception as exc:
                    LOG.debug("radio-browser.info search failed: %s", exc)
                    error_signal.emit(str(exc))

        QThreadPool.globalInstance().start(_SearchTask())

    def _load_meta(self) -> None:
        client = RadioBrowserClient.get()
        meta_signal = self._meta_ready
        error_signal = self._error_occurred

        class _MetaTask(QRunnable):
            def __init__(self):
                super().__init__()
                self.setAutoDelete(True)

            def run(self):
                try:
                    tags = client.list_tags(200)
                    countries = client.list_country_codes()
                    meta_signal.emit(tags, countries)
                except Exception as exc:
                    LOG.debug("radio-browser.info meta load failed: %s", exc)
                    error_signal.emit(str(exc))

        QThreadPool.globalInstance().start(_MetaTask())

    # ------------------------------------------------------------------ private slots

    def _on_results_ready(self, results: list) -> None:
        self._set_searching(False)
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        for result in results:
            if isinstance(result, BrowseResult):
                self._append_row(result)
        self.table.setSortingEnabled(True)
        if not results:
            self.status_label.setText("No stations found. Try a different search.")
            self.status_label.setVisible(True)
        self._update_buttons()

    def _on_meta_ready(self, tags: list, countries: list) -> None:
        self._meta_loaded = True
        self.tag_combo.blockSignals(True)
        self.country_combo.blockSignals(True)
        for tag in tags:
            self.tag_combo.addItem(str(tag))
        for code in countries:
            self.country_combo.addItem(str(code))
        self.tag_combo.blockSignals(False)
        self.country_combo.blockSignals(False)

    def _on_error(self, message: str) -> None:
        self._set_searching(False)
        self._meta_loaded = True
        self.status_label.setText("Could not reach radio-browser.info. Check your connection.")
        self.status_label.setVisible(True)

    def _play_selected(self) -> None:
        station = self._current_station()
        if station is None:
            return
        self.play_requested.emit(station.url, station.name)

    def _add_selected(self) -> None:
        station = self._current_station()
        if station is None:
            return
        self.station_add_requested.emit(station)

    def _update_buttons(self) -> None:
        has = self._current_station() is not None
        self.play_btn.setEnabled(has)
        self.add_btn.setEnabled(has)

    # ------------------------------------------------------------------ helpers

    def _set_searching(self, searching: bool) -> None:
        self._searching = searching
        self.search_btn.setEnabled(not searching)
        if searching:
            self.status_label.setText("Searching…")
            self.status_label.setVisible(True)
        else:
            self.status_label.setVisible(False)

    def _append_row(self, result: BrowseResult) -> None:
        station = result.station
        row = self.table.rowCount()
        self.table.insertRow(row)

        name_item = QTableWidgetItem(station.name)
        name_item.setData(Qt.UserRole, station)
        self.table.setItem(row, _COL_NAME, name_item)
        self.table.setItem(row, _COL_TAGS, QTableWidgetItem(station.genre))
        self.table.setItem(row, _COL_COUNTRY, QTableWidgetItem(result.country))
        self.table.setItem(row, _COL_BITRATE, QTableWidgetItem(
            f"{station.bitrate}" if station.bitrate else ""
        ))
        votes_item = QTableWidgetItem()
        votes_item.setData(Qt.DisplayRole, result.votes)
        self.table.setItem(row, _COL_VOTES, votes_item)

    def _current_station(self) -> RadioStation | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, _COL_NAME)
        if item is None:
            return None
        station = item.data(Qt.UserRole)
        return station if isinstance(station, RadioStation) else None

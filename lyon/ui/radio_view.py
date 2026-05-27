"""Internet radio browser and station manager."""
from __future__ import annotations

import datetime
import logging
import time
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QRunnable, QStringListModel, Qt, QThreadPool, Signal
from PySide6.QtGui import QAction, QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCompleter, QDialog, QFileDialog,
    QFrame, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMenu, QMessageBox,
    QPushButton, QTabWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..core.radio import (
    RadioStation, check_station_health, parse_playlist_file,
    station_from_settings, station_from_url,
    stations_to_m3u, stations_to_pls,
)
from ..core.settings import Settings, normalize_radio_stations
from .radio_browser_panel import RadioBrowserPanel
from .radio_station_dialog import RadioStationDialog

LOG = logging.getLogger(__name__)

_COL_FAVORITE = 0
_COL_NAME = 1
_COL_GENRE = 2
_COL_BITRATE = 3
_COL_URL = 4
_COL_STATUS = 5

_STAR = "★"
_NO_STAR = "☆"

_STATUS_UNKNOWN = "?"
_STATUS_OK = "●"
_STATUS_FAIL = "●"

_COLOR_OK = QColor("#4caf50")    # green
_COLOR_FAIL = QColor("#f44336")  # red

# Minimum seconds between successive health checks for the same URL.
_CHECK_INTERVAL = 300.0


class RadioView(QWidget):
    play_requested = Signal(str, str)   # url, title
    status_message = Signal(str)

    # Marshals health-check worker results back to the GUI thread.
    _health_result = Signal(str, bool, int)   # url, ok, http_status_code

    def __init__(self, settings: Settings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._settings = settings
        self.setObjectName("radioView")

        # Per-URL health state: url → (ok, status_code, monotonic_time)
        self._health_cache: dict[str, tuple[bool, int, float]] = {}
        # URLs whose health check is currently in-flight.
        self._checking: set[str] = set()
        # Station most recently played via the quick-play bar (for the toast).
        self._toast_station: RadioStation | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ---- Quick-play bar (above tabs) -------------------------------------
        qp_frame = QFrame()
        qp_frame.setObjectName("quickPlayBar")
        qp_layout = QHBoxLayout(qp_frame)
        qp_layout.setContentsMargins(12, 8, 12, 4)
        qp_layout.setSpacing(6)

        qp_label = QLabel("Stream URL:")
        qp_layout.addWidget(qp_label)

        self._url_input = QLineEdit()
        self._url_input.setPlaceholderText("https://example.com/stream  — paste a URL to play directly")
        self._url_input.setClearButtonEnabled(True)
        self._url_input.returnPressed.connect(self._on_quick_play)
        self._url_input.textChanged.connect(self._on_url_input_changed)
        qp_layout.addWidget(self._url_input, 1)

        self._quick_play_btn = QPushButton("Play Stream")
        self._quick_play_btn.clicked.connect(self._on_quick_play)
        qp_layout.addWidget(self._quick_play_btn)

        outer.addWidget(qp_frame)

        # ---- Quick-play status: inline error + "Add to My Stations?" toast ---
        self._qp_error = QLabel()
        self._qp_error.setObjectName("errorText")
        self._qp_error.setContentsMargins(12, 0, 12, 2)
        self._qp_error.setVisible(False)
        outer.addWidget(self._qp_error)

        self._toast_frame = QFrame()
        self._toast_frame.setObjectName("quickPlayToast")
        toast_layout = QHBoxLayout(self._toast_frame)
        toast_layout.setContentsMargins(12, 4, 12, 4)
        toast_layout.setSpacing(8)
        self._toast_label = QLabel()
        toast_layout.addWidget(self._toast_label, 1)
        self._toast_add_btn = QPushButton("Add to My Stations")
        self._toast_add_btn.clicked.connect(self._on_toast_add)
        toast_layout.addWidget(self._toast_add_btn)
        toast_dismiss = QPushButton("✕")
        toast_dismiss.setMaximumWidth(28)
        toast_dismiss.setToolTip("Dismiss")
        toast_dismiss.clicked.connect(self._dismiss_toast)
        toast_layout.addWidget(toast_dismiss)
        self._toast_frame.setVisible(False)
        outer.addWidget(self._toast_frame)

        # ---- History-backed completer ----------------------------------------
        self._history_model = QStringListModel(
            list(self._settings.radio_quick_play_history or []), self
        )
        completer = QCompleter(self._history_model, self)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        completer.setFilterMode(Qt.MatchContains)
        self._url_input.setCompleter(completer)

        # ---- Tab widget -------------------------------------------------------
        self._tabs = QTabWidget(self)
        outer.addWidget(self._tabs)

        # ---- My Stations tab --------------------------------------------------
        my_stations = QWidget()
        ms_layout = QVBoxLayout(my_stations)
        ms_layout.setContentsMargins(12, 10, 12, 10)
        ms_layout.setSpacing(8)

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

        self.edit_btn = QPushButton("Edit...")
        self.edit_btn.clicked.connect(self._edit_station)
        toolbar.addWidget(self.edit_btn)

        self.import_btn = QPushButton("Import Playlist...")
        self.import_btn.clicked.connect(self._import_playlist)
        toolbar.addWidget(self.import_btn)

        self.export_btn = QPushButton("Export...")
        self.export_btn.clicked.connect(self._export_stations)
        toolbar.addWidget(self.export_btn)

        self.remove_btn = QPushButton("Remove")
        self.remove_btn.clicked.connect(self._remove_selected)
        toolbar.addWidget(self.remove_btn)

        ms_layout.addLayout(toolbar)

        self.table = QTableWidget(0, 6)
        self.table.setObjectName("radioStationTable")
        self.table.setHorizontalHeaderLabels(
            ["", "Station", "Genre", "Bitrate", "URL", "Status"]
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.itemDoubleClicked.connect(lambda _item: self._play_selected())
        self.table.itemSelectionChanged.connect(self._update_buttons)
        self.table.cellClicked.connect(self._on_cell_clicked)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_context_menu)
        self.table.installEventFilter(self)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(_COL_FAVORITE, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(_COL_NAME, QHeaderView.Stretch)
        header.setSectionResizeMode(_COL_GENRE, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(_COL_BITRATE, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(_COL_URL, QHeaderView.Stretch)
        header.setSectionResizeMode(_COL_STATUS, QHeaderView.ResizeToContents)
        ms_layout.addWidget(self.table, 1)

        footer = QFrame()
        footer.setObjectName("radioFooter")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(0, 0, 0, 0)
        self.footer_label = QLabel("")
        self.footer_label.setObjectName("mutedText")
        footer_layout.addWidget(self.footer_label)
        footer_layout.addStretch(1)
        ms_layout.addWidget(footer)

        self._tabs.addTab(my_stations, "My Stations")

        # ---- Browse tab -------------------------------------------------------
        self._browse_panel = RadioBrowserPanel()
        self._browse_panel.play_requested.connect(self.play_requested)
        self._browse_panel.station_add_requested.connect(self._on_browse_station_add)
        self._tabs.addTab(self._browse_panel, "Browse")

        # Wire health-check results back to GUI thread.
        self._health_result.connect(self._on_health_result)
        self._tabs.currentChanged.connect(self._on_tab_changed)

        self.refresh()

    # ------------------------------------------------------------------ QObject

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if obj is self.table and event.type() == QEvent.KeyPress:
            key = event.key()
            if key in (Qt.Key_Return, Qt.Key_Enter):
                self._play_selected()
                return True
            if key in (Qt.Key_Delete, Qt.Key_Backspace):
                self._remove_selected()
                return True
        return super().eventFilter(obj, event)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._tabs.currentIndex() == 0:
            self._schedule_health_checks()

    # ------------------------------------------------------------------ public

    def apply_settings(self, settings: Settings) -> None:
        self._settings = settings
        self._history_model.setStringList(list(settings.radio_quick_play_history or []))
        self.refresh()

    def _on_browse_station_add(self, station: RadioStation) -> None:
        self._settings.add_radio_stations([station.as_settings_dict()])
        self._save_settings()
        self.refresh()
        self._tabs.setCurrentIndex(0)
        self._select_station_url(station.url)
        self.status_message.emit(f'Added "{station.name}" to My Stations.')

    def refresh(self) -> None:
        selected_url = ""
        station = self._current_station()
        if station is not None:
            selected_url = station.url

        header = self.table.horizontalHeader()
        if self.table.isSortingEnabled():
            sort_col = header.sortIndicatorSection()
            sort_order = header.sortIndicatorOrder()
        else:
            sort_col = _COL_FAVORITE
            sort_order = Qt.AscendingOrder

        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        for raw_station in self._settings.radio_stations:
            s = station_from_settings(raw_station)
            if s is not None:
                self._append_station_row(s)

        # Pre-sort before re-enabling so the header indicator is already set to
        # our intended column/order; this prevents setSortingEnabled from applying
        # the Qt default (column 0, descending) over the actual desired sort.
        self.table.sortItems(sort_col, sort_order)
        self.table.setSortingEnabled(True)

        self._filter(self.search.text())
        if selected_url:
            self._select_station_url(selected_url)
        self._update_buttons()

        # Repopulate status cells from cache and queue any new/stale checks.
        self._update_health_cells()
        if self.isVisible() and self._tabs.currentIndex() == 0:
            self._schedule_health_checks()

    # ------------------------------------------------------------------ quick-play bar

    def _on_url_input_changed(self, _text: str) -> None:
        self._qp_error.setVisible(False)

    def _on_quick_play(self) -> None:
        url = self._url_input.text().strip()
        if not url:
            return
        station = station_from_url(url)
        if station is None:
            self._qp_error.setText(
                "Not a valid stream URL — must begin with http:// or https://."
            )
            self._qp_error.setVisible(True)
            return

        self._qp_error.setVisible(False)

        # Record in history.
        self._settings.add_quick_play_url(station.url)
        self._save_settings()
        self._history_model.setStringList(
            list(self._settings.radio_quick_play_history)
        )

        # Play.
        self.play_requested.emit(station.url, station.name)

        # Show "Add to My Stations?" toast unless this URL is already saved.
        already_saved = any(
            str(raw.get("url", "")).casefold() == station.url.casefold()
            for raw in self._settings.radio_stations
        )
        if already_saved:
            self._dismiss_toast()
        else:
            self._toast_station = station
            self._toast_label.setText(
                f'Now playing "{station.name}". Add to My Stations?'
            )
            self._toast_frame.setVisible(True)

    def _on_toast_add(self) -> None:
        station = self._toast_station
        if station is None:
            return
        self._settings.add_radio_stations([station.as_settings_dict()])
        self._save_settings()
        self.refresh()
        self._tabs.setCurrentIndex(0)
        self._select_station_url(station.url)
        self.status_message.emit(f'Added "{station.name}" to My Stations.')
        self._dismiss_toast()

    def _dismiss_toast(self) -> None:
        self._toast_station = None
        self._toast_frame.setVisible(False)

    # ------------------------------------------------------------------ station table

    def _append_station_row(self, station: RadioStation) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)

        # Favorite column — sort key: 0 for favorites (appear first), 1 for others.
        fav_item = QTableWidgetItem(_STAR if station.favorite else _NO_STAR)
        fav_item.setData(Qt.UserRole, 0 if station.favorite else 1)
        fav_item.setTextAlignment(Qt.AlignCenter)
        fav_item.setToolTip("Click to toggle favourite")
        self.table.setItem(row, _COL_FAVORITE, fav_item)

        name_item = QTableWidgetItem(station.name)
        name_item.setData(Qt.UserRole, station.as_settings_dict())
        self.table.setItem(row, _COL_NAME, name_item)
        self.table.setItem(row, _COL_GENRE, QTableWidgetItem(station.genre))
        bitrate_text = f"{station.bitrate} kbps" if station.bitrate else ""
        self.table.setItem(row, _COL_BITRATE, QTableWidgetItem(bitrate_text))
        self.table.setItem(row, _COL_URL, QTableWidgetItem(station.url))

        # Status cell — populated from cache immediately, checked async if stale.
        self._populate_health_cell(row, station.url)

    def _current_station(self) -> RadioStation | None:
        row = self.table.currentRow()
        if row < 0 or self.table.isRowHidden(row):
            return None
        item = self.table.item(row, _COL_NAME)
        if item is None:
            return None
        return station_from_settings(item.data(Qt.UserRole))

    # ------------------------------------------------------------------ health check

    def _schedule_health_checks(self) -> None:
        """Queue a background health check for every stale or unchecked station."""
        now = time.monotonic()
        health_signal = self._health_result

        for row in range(self.table.rowCount()):
            url_item = self.table.item(row, _COL_URL)
            if url_item is None:
                continue
            url = url_item.text()
            if url in self._checking:
                continue
            cached = self._health_cache.get(url)
            if cached is not None and now - cached[2] < _CHECK_INTERVAL:
                continue  # still fresh

            self._checking.add(url)

            class _HealthTask(QRunnable):
                def __init__(self, task_url: str) -> None:
                    super().__init__()
                    self.setAutoDelete(True)
                    self._url = task_url

                def run(self) -> None:
                    ok, code = check_station_health(self._url)
                    health_signal.emit(self._url, ok, code)

            QThreadPool.globalInstance().start(_HealthTask(url))

    def _on_health_result(self, url: str, ok: bool, code: int) -> None:
        """Receive a health-check result on the GUI thread and update the table."""
        self._checking.discard(url)
        self._health_cache[url] = (ok, code, time.monotonic())
        for row in range(self.table.rowCount()):
            url_item = self.table.item(row, _COL_URL)
            if url_item is not None and url_item.text().casefold() == url.casefold():
                self._set_health_cell(row, ok, code)

    def _on_tab_changed(self, index: int) -> None:
        if index == 0:
            self._schedule_health_checks()

    def _update_health_cells(self) -> None:
        """Re-apply cached health state to every row after a table rebuild."""
        for row in range(self.table.rowCount()):
            url_item = self.table.item(row, _COL_URL)
            if url_item is not None:
                self._populate_health_cell(row, url_item.text())

    def _populate_health_cell(self, row: int, url: str) -> None:
        cached = self._health_cache.get(url)
        if cached is not None:
            self._set_health_cell(row, cached[0], cached[1])
        else:
            item = QTableWidgetItem(_STATUS_UNKNOWN)
            item.setTextAlignment(Qt.AlignCenter)
            item.setToolTip("Status not yet checked")
            self.table.setItem(row, _COL_STATUS, item)

    def _set_health_cell(self, row: int, ok: bool, code: int) -> None:
        item = self.table.item(row, _COL_STATUS)
        if item is None:
            item = QTableWidgetItem()
            self.table.setItem(row, _COL_STATUS, item)
        item.setText(_STATUS_OK if ok else _STATUS_FAIL)
        item.setForeground(QBrush(_COLOR_OK if ok else _COLOR_FAIL))
        item.setTextAlignment(Qt.AlignCenter)
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        status_text = f"HTTP {code}" if code else "Connection failed"
        item.setToolTip(f"Checked {timestamp} — {status_text}")

    # ------------------------------------------------------------------ favourite toggle

    def _on_cell_clicked(self, row: int, col: int) -> None:
        """Toggle favourite when the star cell is clicked."""
        if col != _COL_FAVORITE or self.table.isRowHidden(row):
            return
        name_item = self.table.item(row, _COL_NAME)
        if name_item is None:
            return
        station = station_from_settings(name_item.data(Qt.UserRole))
        if station is None:
            return
        self._toggle_favorite(station)

    def _toggle_favorite(self, station: RadioStation) -> None:
        new_favorite = not station.favorite
        updated = station_from_url(
            station.url,
            name=station.name,
            genre=station.genre,
            bitrate=station.bitrate,
            tags=station.tags,
            favorite=new_favorite,
        )
        if updated is None:
            return
        self._settings.radio_stations = [
            updated.as_settings_dict()
            if str(raw.get("url", "")).casefold() == station.url.casefold()
            else raw
            for raw in self._settings.radio_stations
        ]
        self._save_settings()
        self.refresh()
        self._select_station_url(station.url)

    # ------------------------------------------------------------------ actions

    def _play_selected(self) -> None:
        station = self._current_station()
        if station is None:
            return
        self._settings.remember_stream_url(station.url)
        self._save_settings()
        self.play_requested.emit(station.url, station.name)

    def _add_station(self) -> None:
        dialog = RadioStationDialog(parent=self)
        try:
            if dialog.exec() != QDialog.Accepted:
                return
            station = dialog.station()
        finally:
            dialog.deleteLater()
        if station is None:
            return
        self._settings.add_radio_stations([station.as_settings_dict()])
        self._save_settings()
        self.refresh()
        self._select_station_url(station.url)
        self.status_message.emit(f'Added radio station "{station.name}".')

    def _edit_station(self) -> None:
        station = self._current_station()
        if station is None:
            return
        dialog = RadioStationDialog(station=station, parent=self)
        try:
            if dialog.exec() != QDialog.Accepted:
                return
            updated = dialog.station()
        finally:
            dialog.deleteLater()
        if updated is None:
            return
        duplicate = next(
            (
                raw for raw in self._settings.radio_stations
                if str(raw.get("url", "")).casefold() == updated.url.casefold()
                and str(raw.get("url", "")).casefold() != station.url.casefold()
            ),
            None,
        )
        if duplicate is not None:
            QMessageBox.warning(
                self,
                "Edit Radio Station",
                "A station with that URL already exists.",
            )
            return
        remaining = [
            raw for raw in self._settings.radio_stations
            if str(raw.get("url", "")).casefold() != station.url.casefold()
        ]
        self._settings.radio_stations = normalize_radio_stations([
            *remaining,
            updated.as_settings_dict(),
        ])
        self._save_settings()
        self.refresh()
        self._select_station_url(updated.url)
        self.status_message.emit(f'Updated radio station "{updated.name}".')

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

    def _export_stations(self) -> None:
        stations = [
            s for raw in self._settings.radio_stations
            if (s := station_from_settings(raw)) is not None
        ]
        if not stations:
            QMessageBox.information(self, "Export Stations", "No stations to export.")
            return
        path, selected_filter = QFileDialog.getSaveFileName(
            self,
            "Export Radio Stations",
            "stations.m3u",
            "M3U Playlist (*.m3u);;PLS Playlist (*.pls)",
        )
        if not path:
            return
        try:
            suffix = Path(path).suffix.lower()
            if suffix == ".pls" or "PLS" in selected_filter:
                text = stations_to_pls(stations)
            else:
                text = stations_to_m3u(stations)
            Path(path).write_text(text, encoding="utf-8")
        except OSError as exc:
            LOG.warning("Could not export radio stations to %s: %s", path, exc)
            QMessageBox.warning(self, "Export Stations", f"Could not write {Path(path).name}.")
            return
        self.status_message.emit(f"Exported {len(stations)} station{'' if len(stations) == 1 else 's'}.")

    def _remove_selected(self) -> None:
        station = self._current_station()
        if station is None:
            return
        answer = QMessageBox.question(
            self,
            "Remove Station",
            f'Remove "{station.name}" from your stations?',
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
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

    def _show_context_menu(self, pos: object) -> None:
        item = self.table.itemAt(pos)  # type: ignore[arg-type]
        if item is not None:
            self.table.setCurrentItem(item)
        station = self._current_station()
        if station is None:
            return

        menu = QMenu(self)
        menu.addAction("Play Now", self._play_selected)
        menu.addAction("Edit...", self._edit_station)
        menu.addSeparator()
        fav_label = "Remove from Favourites" if station.favorite else "Add to Favourites"
        fav_action = QAction(fav_label, self)
        fav_action.triggered.connect(lambda: self._toggle_favorite(station))
        menu.addAction(fav_action)
        check_action = QAction("Check Status Now", self)
        check_action.triggered.connect(lambda: self._force_health_check(station.url))
        menu.addAction(check_action)
        menu.addSeparator()
        copy_action = QAction("Copy URL", self)
        copy_action.triggered.connect(lambda: QApplication.clipboard().setText(station.url))
        menu.addAction(copy_action)
        menu.addSeparator()
        menu.addAction("Remove", self._remove_selected)
        menu.exec(self.table.viewport().mapToGlobal(pos))  # type: ignore[arg-type]

    def _force_health_check(self, url: str) -> None:
        """Evict cache entry for *url* and immediately queue a fresh check."""
        self._health_cache.pop(url, None)
        self._checking.discard(url)
        health_signal = self._health_result

        class _HealthTask(QRunnable):
            def __init__(self, task_url: str) -> None:
                super().__init__()
                self.setAutoDelete(True)
                self._url = task_url

            def run(self) -> None:
                ok, code = check_station_health(self._url)
                health_signal.emit(self._url, ok, code)

        self._checking.add(url)
        QThreadPool.globalInstance().start(_HealthTask(url))

    # ------------------------------------------------------------------ filter / navigation

    def _filter(self, text: str) -> None:
        query = text.strip().casefold()
        visible = 0
        for row in range(self.table.rowCount()):
            item = self.table.item(row, _COL_NAME)
            station = station_from_settings(item.data(Qt.UserRole)) if item else None
            haystack = " ".join((
                station.name,
                station.genre,
                station.url,
                str(station.bitrate or ""),
                " ".join(station.tags),
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
            item = self.table.item(row, _COL_NAME)
            station = station_from_settings(item.data(Qt.UserRole)) if item else None
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
        self.edit_btn.setEnabled(has_station)
        self.remove_btn.setEnabled(has_station)
        self.export_btn.setEnabled(bool(self._settings.radio_stations))

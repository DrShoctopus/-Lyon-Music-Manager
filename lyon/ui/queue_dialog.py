"""Playback queue editor dialog."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QDialogButtonBox, QHBoxLayout, QHeaderView, QLabel,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..core.library import Track
from ..core.player import Player
from .widgets import format_duration


class QueueDialog(QDialog):
    """Show and edit the player's active queue."""

    def __init__(self, player: Player, parent: QWidget | None = None):
        super().__init__(parent)
        self.player = player
        self.setWindowTitle("Playback Queue")
        self.resize(720, 420)

        self.summary = QLabel("")
        self.summary.setStyleSheet("color:#cfd6e2;font-weight:600;")

        self.table = QTableWidget(0, 4, self)
        self.table.setHorizontalHeaderLabels(["#", "Title", "Artist", "Time"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.doubleClicked.connect(lambda idx: self.player.play_index(idx.row()))
        header = self.table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)

        controls = QHBoxLayout()
        play_btn = QPushButton("Play Selected")
        up_btn = QPushButton("Move Up")
        down_btn = QPushButton("Move Down")
        remove_btn = QPushButton("Remove")
        clear_btn = QPushButton("Clear Queue")
        play_btn.clicked.connect(self._play_selected)
        up_btn.clicked.connect(lambda: self._move_selected(-1))
        down_btn.clicked.connect(lambda: self._move_selected(1))
        remove_btn.clicked.connect(self._remove_selected)
        clear_btn.clicked.connect(self.player.clear_queue)
        for btn in (play_btn, up_btn, down_btn, remove_btn, clear_btn):
            controls.addWidget(btn)
        controls.addStretch(1)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(self.summary)
        layout.addWidget(self.table, 1)
        layout.addLayout(controls)
        layout.addWidget(buttons)

        self.player.queue_changed.connect(self.refresh)
        self.player.track_changed.connect(lambda _track: self.refresh())
        self.refresh()

    def refresh(self) -> None:
        queue = self.player.queue()
        current = self.player.current_index()
        self.summary.setText(self._summary_text(queue, current))
        self.table.setRowCount(len(queue))
        for row, track in enumerate(queue):
            values = [
                "▶" if row == current else str(row + 1),
                track.title,
                track.display_artist,
                format_duration(track.duration),
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                if row == current:
                    item.setForeground(QColor("#72f4ff"))
                self.table.setItem(row, col, item)
        if 0 <= current < self.table.rowCount():
            self.table.selectRow(current)
            self.table.scrollToItem(self.table.item(current, 0), QAbstractItemView.PositionAtCenter)
        self.table.resizeColumnToContents(0)
        self.table.resizeColumnToContents(2)
        self.table.resizeColumnToContents(3)

    @staticmethod
    def _summary_text(queue: list[Track], current: int) -> str:
        if not queue:
            return "Queue is empty."
        total = format_duration(sum(track.duration for track in queue))
        if 0 <= current < len(queue):
            return f"{len(queue)} tracks • {total} total • Now playing {current + 1} of {len(queue)}"
        return f"{len(queue)} tracks • {total} total"

    def _selected_row(self) -> int:
        rows = self.table.selectionModel().selectedRows()
        if rows:
            return rows[0].row()
        idx = self.table.currentIndex()
        return idx.row() if idx.isValid() else -1

    def _play_selected(self) -> None:
        row = self._selected_row()
        if row >= 0:
            self.player.play_index(row)

    def _remove_selected(self) -> None:
        row = self._selected_row()
        if row >= 0:
            self.player.remove_queue_index(row)

    def _move_selected(self, delta: int) -> None:
        row = self._selected_row()
        if row < 0:
            return
        new_row = row + delta
        self.player.move_queue_item(row, new_row)
        if 0 <= new_row < self.table.rowCount():
            self.table.selectRow(new_row)

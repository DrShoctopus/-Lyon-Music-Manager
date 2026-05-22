"""Library statistics dialog."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QDialogButtonBox, QHeaderView, QLabel,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..core.library import Library


def _fmt_duration(seconds: float) -> str:
    total = int(seconds)
    d, rem = divmod(total, 86400)
    h, rem = divmod(rem, 3600)
    m = rem // 60
    parts = []
    if d:
        parts.append(f"{d} day{'s' if d != 1 else ''}")
    if h:
        parts.append(f"{h} hour{'s' if h != 1 else ''}")
    parts.append(f"{m} minute{'s' if m != 1 else ''}")
    return ", ".join(parts)


def _fmt_size(n_bytes: int) -> str:
    for unit, threshold in (("GB", 1 << 30), ("MB", 1 << 20), ("KB", 1 << 10)):
        if n_bytes >= threshold:
            return f"{n_bytes / threshold:.1f} {unit}"
    return f"{n_bytes} B"


_ROWS = [
    ("Artists", "artist_count"),
    ("Albums", "album_count"),
    ("Tracks", "track_count"),
    ("Total Time", "total_duration"),
    ("Disk Space", "total_file_size"),
]


class LibraryStatsDialog(QDialog):
    """Modal dialog showing aggregate library statistics."""

    def __init__(self, library: Library, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Library Statistics")
        self.resize(420, 240)

        stats = library.library_stats()

        summary = QLabel(
            f"Your library contains {stats['track_count']:,} track"
            f"{'s' if stats['track_count'] != 1 else ''} across "
            f"{stats['artist_count']:,} artist"
            f"{'s' if stats['artist_count'] != 1 else ''} and "
            f"{stats['album_count']:,} album"
            f"{'s' if stats['album_count'] != 1 else ''}."
        )
        summary.setWordWrap(True)
        summary.setObjectName("dialogSummary")

        table = QTableWidget(len(_ROWS), 2, self)
        table.setHorizontalHeaderLabels(["Statistic", "Value"])
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionMode(QAbstractItemView.NoSelection)
        table.setFocusPolicy(Qt.NoFocus)
        table.setAlternatingRowColors(True)

        values = {
            "artist_count": f"{stats['artist_count']:,}",
            "album_count": f"{stats['album_count']:,}",
            "track_count": f"{stats['track_count']:,}",
            "total_duration": _fmt_duration(stats["total_duration"]),
            "total_file_size": _fmt_size(stats["total_file_size"]),
        }

        for row, (label, key) in enumerate(_ROWS):
            label_item = QTableWidgetItem(label)
            label_item.setFlags(label_item.flags() & ~Qt.ItemIsEditable)
            value_item = QTableWidgetItem(values[key])
            value_item.setFlags(value_item.flags() & ~Qt.ItemIsEditable)
            value_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            table.setItem(row, 0, label_item)
            table.setItem(row, 1, value_item)

        header = table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        table.resizeRowsToContents()

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(summary)
        layout.addWidget(table, 1)
        layout.addWidget(buttons)

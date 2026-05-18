"""Dialog for finding and removing duplicate tracks."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QDesktopServices, QStandardItem
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QDialogButtonBox, QHBoxLayout,
    QHeaderView, QLabel, QMessageBox, QPushButton, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget,
)
from PySide6.QtCore import QUrl

from ..core.library import Library, Track


class DuplicateDialog(QDialog):
    """Shows groups of duplicate tracks and lets the user keep only the best copy."""

    _MODE_TITLE = "title"
    _MODE_HASH  = "hash"

    def __init__(self, library: Library, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.library = library
        self.setWindowTitle("Find Duplicates")
        self.resize(860, 540)
        self._groups: list[list[Track]] = []
        self._build_ui()
        self._refresh_groups()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        # Mode selector row
        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("Find duplicates:"))
        self._mode_combo = QComboBox()
        self._mode_combo.addItem("By Title + Artist", self._MODE_TITLE)
        self._mode_combo.addItem("By File Hash (exact copies)", self._MODE_HASH)
        fp_idx = self._mode_combo.count()
        self._mode_combo.addItem("By Fingerprint (coming in v0.8)", "fingerprint")
        fp_item = self._mode_combo.model().item(fp_idx)
        fp_item.setEnabled(False)
        self._mode_combo.setToolTip(
            "Title+Artist: matches tracks with identical tags\n"
            "File Hash: matches byte-identical files regardless of tags"
        )
        self._mode_combo.currentIndexChanged.connect(self._refresh_groups)
        mode_row.addWidget(self._mode_combo)
        mode_row.addStretch(1)
        layout.addLayout(mode_row)

        # Summary label (updated by _refresh_groups)
        self._summary_label = QLabel("")
        self._summary_label.setObjectName("dialogSummary")
        layout.addWidget(self._summary_label)

        self._tree = QTreeWidget()
        self._tree.setColumnCount(4)
        self._tree.setHeaderLabels(["Title / Path", "Format", "Bitrate", "Size"])
        self._tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self._tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self._tree.header().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self._tree.header().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self._tree.setAlternatingRowColors(True)
        self._tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self._tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._show_context_menu)
        layout.addWidget(self._tree, 1)

        controls = QHBoxLayout()
        keep_best_btn = QPushButton("Keep Highest Quality (Remove Others)")
        keep_best_btn.clicked.connect(self._keep_best)
        keep_all_btn = QPushButton("Keep All")
        keep_all_btn.setToolTip("Close without making any changes")
        keep_all_btn.clicked.connect(self.accept)
        controls.addWidget(keep_best_btn)
        controls.addWidget(keep_all_btn)
        controls.addStretch(1)
        layout.addLayout(controls)

        close_box = QDialogButtonBox(QDialogButtonBox.Close)
        close_box.rejected.connect(self.reject)
        layout.addWidget(close_box)

    def _refresh_groups(self) -> None:
        mode = self._mode_combo.currentData()
        if mode == self._MODE_HASH:
            self._groups = self.library.find_duplicates_by_hash()
        else:
            self._groups = self.library.find_duplicates()
        self._update_summary()
        self._populate_tree()

    def _update_summary(self) -> None:
        if not self._groups:
            self._summary_label.setText("No duplicate tracks found.")
        else:
            extras = sum(len(g) - 1 for g in self._groups)
            self._summary_label.setText(
                f"Found {len(self._groups)} group(s) of duplicates "
                f"({extras} extra {'copy' if extras == 1 else 'copies'})."
            )

    def _populate_tree(self) -> None:
        self._tree.clear()
        for group in self._groups:
            artist = group[0].display_artist
            title = group[0].title or "Untitled"
            parent_item = QTreeWidgetItem(self._tree, [f"{artist} — {title}"])
            f = parent_item.font(0)
            f.setBold(True)
            parent_item.setFont(0, f)
            parent_item.setExpanded(True)
            for track in group:
                fmt = Path(track.path).suffix.lstrip(".").upper()
                kbps = (
                    f"{round(track.bitrate / 1000)} kbps"
                    if track.bitrate > 0
                    else "?"
                )
                # Avoid touching every duplicate path during dialog population;
                # those paths may live on slow or offline network volumes.
                size = "—"
                child = QTreeWidgetItem(parent_item, [track.path, fmt, kbps, size])
                child.setData(0, Qt.UserRole, track)

    def _show_context_menu(self, pos) -> None:
        from PySide6.QtWidgets import QMenu
        item = self._tree.itemAt(pos)
        if item is None:
            return
        track: Track | None = item.data(0, Qt.UserRole)
        if not isinstance(track, Track):
            return
        menu = QMenu(self)
        open_act = menu.addAction("Open Containing Folder")
        remove_act = menu.addAction("Remove from Library")
        try:
            action = menu.exec(self._tree.mapToGlobal(pos))
        finally:
            menu.deleteLater()
        if action == open_act:
            folder = Path(track.path).parent
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
        elif action == remove_act:
            r = QMessageBox.question(
                self,
                "Remove Track",
                f"Remove\n{track.path}\nfrom the library? (file not deleted)",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if r == QMessageBox.Yes:
                self.library.delete_track(track.id)
                self._refresh_groups()

    def _keep_best(self) -> None:
        to_remove = sum(len(g) - 1 for g in self._groups)
        if to_remove == 0:
            return
        r = QMessageBox.question(
            self,
            "Keep Highest Quality",
            f"Remove {to_remove} lower-quality duplicate(s) from the library?\n"
            f"Files on disk are NOT deleted.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if r != QMessageBox.Yes:
            return
        # find_duplicates*() orders each group by bitrate DESC — group[0] is best.
        for group in self._groups:
            for track in group[1:]:
                self.library.delete_track(track.id)
        self._refresh_groups()
        if not self._groups:
            QMessageBox.information(self, "Done", "All duplicates removed.")
            self.accept()

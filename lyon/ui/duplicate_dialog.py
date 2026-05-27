"""Dialog for finding and removing duplicate tracks."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QRunnable, QThreadPool, Signal, QObject
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QDialogButtonBox, QHBoxLayout,
    QHeaderView, QLabel, QMessageBox, QProgressBar, QPushButton, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget,
)
from PySide6.QtCore import QUrl

from ..core.library import Library, Track


class DuplicateDialog(QDialog):
    """Shows groups of duplicate tracks and lets the user keep only the best copy."""

    _MODE_TITLE       = "title"
    _MODE_HASH        = "hash"
    _MODE_FINGERPRINT = "fingerprint"

    def __init__(self, library: Library, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.library = library
        self.setWindowTitle("Find Duplicates")
        self.resize(860, 560)
        self._groups: list[list[Track]] = []
        self._hash_scan_token = 0
        self._pending_keep_best_check = False
        self._build_ui()
        self._refresh_groups()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        # Mode selector row
        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("Find duplicates:"))
        self._mode_combo = QComboBox()
        self._mode_combo.addItem("By Title + Artist", self._MODE_TITLE)
        self._mode_combo.addItem("By File Hash (content sample)", self._MODE_HASH)
        self._mode_combo.addItem("By AcoustID Fingerprint", self._MODE_FINGERPRINT)
        self._mode_combo.setToolTip(
            "Title+Artist: matches tracks with identical tags\n"
            "File Hash: matches files with identical header/middle/tail samples\n"
            "  (catches re-encodes and renamed copies; not a full byte compare)\n"
            "AcoustID Fingerprint: matches by acoustic content regardless of tags or format\n"
            "  (requires fpcalc + AcoustID API key; tracks must be scanned first)"
        )
        self._mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        mode_row.addWidget(self._mode_combo)
        mode_row.addStretch(1)

        self._scan_fp_btn = QPushButton("Scan Missing Fingerprints…")
        self._scan_fp_btn.setToolTip("Compute AcoustID fingerprints for library tracks that haven't been identified yet")
        self._scan_fp_btn.clicked.connect(self._scan_fingerprints)
        self._scan_fp_btn.setVisible(False)
        mode_row.addWidget(self._scan_fp_btn)
        layout.addLayout(mode_row)

        # Fingerprint availability warning
        self._fp_warn = QLabel("")
        self._fp_warn.setObjectName("warningLabel")
        self._fp_warn.setWordWrap(True)
        self._fp_warn.setVisible(False)
        layout.addWidget(self._fp_warn)

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
        self._keep_best_btn = QPushButton("Keep Highest Quality (Remove Others)")
        self._keep_best_btn.clicked.connect(self._keep_best)
        keep_all_btn = QPushButton("Keep All")
        keep_all_btn.setToolTip("Close without making any changes")
        keep_all_btn.clicked.connect(self.accept)
        controls.addWidget(self._keep_best_btn)
        controls.addWidget(keep_all_btn)
        controls.addStretch(1)
        layout.addLayout(controls)

        close_box = QDialogButtonBox(QDialogButtonBox.Close)
        close_box.rejected.connect(self.reject)
        layout.addWidget(close_box)

    def _on_mode_changed(self) -> None:
        is_fp = self._mode_combo.currentData() == self._MODE_FINGERPRINT
        self._scan_fp_btn.setVisible(is_fp)
        if is_fp:
            from ..core.fingerprint import is_available, is_lookup_configured
            if not is_available():
                self._fp_warn.setText(
                    "fpcalc (Chromaprint) is not installed. "
                    "Download fpcalc and place it in the bin/ folder to enable fingerprint matching."
                )
                self._fp_warn.setVisible(True)
            elif not is_lookup_configured():
                self._fp_warn.setText(
                    "AcoustID API key not configured. Set LYON_ACOUSTID_API_KEY "
                    "to enable fingerprint lookup."
                )
                self._fp_warn.setVisible(True)
            else:
                self._fp_warn.setVisible(False)
        else:
            self._fp_warn.setVisible(False)
        self._refresh_groups()

    def _refresh_groups(self) -> None:
        mode = self._mode_combo.currentData()
        if mode == self._MODE_HASH:
            self._refresh_groups_hash_async()
            return
        if mode == self._MODE_FINGERPRINT:
            self._groups = self.library.find_duplicates_by_fingerprint()
        else:
            self._groups = self.library.find_duplicates()
        self._update_summary()
        self._populate_tree()

    def _refresh_groups_hash_async(self) -> None:
        """Run the hash backfill + duplicate scan off the UI thread (disk I/O)."""
        self._hash_scan_token += 1
        token = self._hash_scan_token
        self._groups = []
        self._set_hash_scan_busy(True)
        library = self.library
        signals = _HashScanSignals(self)
        signals.finished.connect(self._on_hash_scan_finished)
        signals.failed.connect(self._on_hash_scan_failed)

        class _HashTask(QRunnable):
            def __init__(self) -> None:
                super().__init__()
                self.setAutoDelete(True)

            def run(self) -> None:
                try:
                    groups = library.find_duplicates_by_hash()
                except Exception as exc:
                    signals.failed.emit(token, str(exc))
                    return
                signals.finished.emit(token, groups)

        QThreadPool.globalInstance().start(_HashTask())

    def _set_hash_scan_busy(self, busy: bool) -> None:
        self._mode_combo.setEnabled(not busy)
        self._keep_best_btn.setEnabled(not busy)
        if busy:
            self._tree.clear()
            self._summary_label.setText("Computing file hashes — this may take a moment…")

    def _on_hash_scan_finished(self, token: object, groups: object) -> None:
        if token != self._hash_scan_token:
            return  # superseded by a later mode switch
        self._groups = groups if isinstance(groups, list) else []
        self._set_hash_scan_busy(False)
        self._update_summary()
        self._populate_tree()
        if self._pending_keep_best_check and not self._groups:
            self._pending_keep_best_check = False
            QMessageBox.information(self, "Done", "All duplicates removed.")
            self.accept()

    def _on_hash_scan_failed(self, token: object, message: str) -> None:
        if token != self._hash_scan_token:
            return
        self._groups = []
        self._set_hash_scan_busy(False)
        self._summary_label.setText(f"Hash scan failed: {message}")
        self._populate_tree()

    def _update_summary(self) -> None:
        mode = self._mode_combo.currentData()
        if not self._groups:
            if mode == self._MODE_FINGERPRINT:
                pending = self.library.count_tracks_without_acoustid()
                total_audio = self.library.count_tracks(media_type="audio")
                if pending == total_audio:
                    self._summary_label.setText(
                        "No fingerprints computed yet. Click 'Scan Missing Fingerprints…' to begin."
                    )
                else:
                    self._summary_label.setText("No duplicate tracks found by fingerprint.")
            else:
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
                try:
                    size_bytes = Path(track.path).stat().st_size
                    size = f"{size_bytes / (1 << 20):.1f} MB"
                except OSError:
                    size = "?"
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
        mode = self._mode_combo.currentData()
        if mode == self._MODE_HASH:
            # The refresh is async; defer the "all removed" check to _on_hash_scan_finished.
            self._pending_keep_best_check = True
            self._refresh_groups()
        else:
            self._refresh_groups()
            if not self._groups:
                QMessageBox.information(self, "Done", "All duplicates removed.")
                self.accept()

    # ------------------------------------------------------------------ fingerprint scan

    def _scan_fingerprints(self) -> None:
        from ..core.fingerprint import is_available, is_lookup_configured
        if not is_available():
            QMessageBox.warning(self, "Not Available", "fpcalc is not installed.")
            return
        if not is_lookup_configured():
            QMessageBox.warning(
                self, "API Key Required",
                "Set LYON_ACOUSTID_API_KEY first."
            )
            return

        tracks = self.library.tracks_without_acoustid()
        if not tracks:
            QMessageBox.information(self, "Up to Date", "All tracks already have fingerprints.")
            return

        dlg = _FingerprintScanDialog(tracks, self.library, self)
        dlg.exec()
        self._refresh_groups()


class _HashScanSignals(QObject):
    finished = Signal(object, object)  # (token, list[list[Track]])
    failed = Signal(object, str)       # (token, message)


class _ScanSignals(QObject):
    progress = Signal(int, str)   # (index, track_title)
    finished = Signal()


class _FingerprintScanDialog(QDialog):
    """Modal progress dialog that fingerprints a batch of tracks."""

    def __init__(self, tracks: list[Track], library: Library, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Scanning Fingerprints")
        self.setModal(True)
        self.resize(500, 130)
        self._tracks = tracks
        self._library = library
        self._cancelled = False

        layout = QVBoxLayout(self)
        self._label = QLabel(f"Fingerprinting 0 of {len(tracks)} tracks…")
        layout.addWidget(self._label)
        self._bar = QProgressBar()
        self._bar.setRange(0, len(tracks))
        self._bar.setValue(0)
        layout.addWidget(self._bar)

        bb = QDialogButtonBox(QDialogButtonBox.Cancel)
        bb.rejected.connect(self._cancel)
        layout.addWidget(bb)

        self._signals = _ScanSignals(self)
        self._signals.progress.connect(self._on_progress)
        self._signals.finished.connect(self._on_finished)

        self._start_scan()

    def _start_scan(self) -> None:
        tracks = self._tracks
        library = self._library
        signals = self._signals

        class _ScanTask(QRunnable):
            def __init__(self, dlg_ref):
                super().__init__()
                self.setAutoDelete(True)
                self._dlg = dlg_ref

            def run(self) -> None:
                from ..core.fingerprint import lookup_candidates
                for i, track in enumerate(tracks):
                    if self._dlg._cancelled:
                        break
                    signals.progress.emit(i, track.title or track.path)
                    try:
                        candidates = lookup_candidates(track.path)
                        if candidates and candidates[0].get("acoustid"):
                            library.update_acoustid(track.id, candidates[0]["acoustid"])
                    except Exception:
                        pass
                signals.finished.emit()

        QThreadPool.globalInstance().start(_ScanTask(self))

    def _on_progress(self, index: int, title: str) -> None:
        self._bar.setValue(index)
        self._label.setText(f"Fingerprinting {index + 1} of {len(self._tracks)}: {title}")

    def _on_finished(self) -> None:
        self.accept()

    def _cancel(self) -> None:
        self._cancelled = True
        self.reject()

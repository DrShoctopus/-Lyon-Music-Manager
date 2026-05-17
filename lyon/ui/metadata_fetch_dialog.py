"""MusicBrainz metadata fetch dialog for library albums (P7)."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QFrame, QHBoxLayout, QLabel,
    QListWidget, QListWidgetItem, QMessageBox, QPushButton, QScrollArea, QSizePolicy,
    QStackedWidget, QVBoxLayout, QWidget,
)

from ..core.library import Library, Track
from ..core.metadata import (
    AlbumInfo, TrackInfo,
    download_cover_art, fetch_musicbrainz_release,
    lookup_musicbrainz_disc, search_musicbrainz_releases,
)
from ..core.tagger import write_tags

# Stacked page indices
_PAGE_LOADING = 0
_PAGE_NOT_FOUND = 1
_PAGE_DIFF = 2


class _SearchWorker(QThread):
    disc_found = Signal(object)   # AlbumInfo — exact disc-ID match (has full track list)
    candidates = Signal(list)     # list[AlbumInfo] — text search results
    not_found = Signal()
    error = Signal(str)

    def __init__(self, disc_id: Optional[str], artist: str, album: str, parent=None) -> None:
        super().__init__(parent)
        self._disc_id = disc_id
        self._artist = artist
        self._album = album

    def run(self) -> None:
        if self._disc_id:
            try:
                info = lookup_musicbrainz_disc(self._disc_id)
                if info:
                    self.disc_found.emit(info)
                    return
            except Exception:
                pass

        try:
            results = search_musicbrainz_releases(self._artist, self._album, limit=5)
        except Exception as exc:
            self.error.emit(str(exc))
            return

        if results:
            self.candidates.emit(results)
        else:
            self.not_found.emit()


class _DetailWorker(QThread):
    """Fetches full release detail and/or cover art by MusicBrainz release ID."""

    detail_ready = Signal(object)  # AlbumInfo with full track listing
    artwork_ready = Signal(bytes)
    error = Signal(str)

    def __init__(
        self,
        mbid: str,
        fallback: AlbumInfo,
        fetch_details: bool = True,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._mbid = mbid
        self._fallback = fallback
        self._fetch_details = fetch_details

    def run(self) -> None:
        if self._fetch_details and self._mbid:
            try:
                info = fetch_musicbrainz_release(self._mbid)
            except Exception as exc:
                self.error.emit(str(exc))
                info = None
            self.detail_ready.emit(info if info else self._fallback)
        elif not self._fetch_details:
            # Disc path — emit fallback immediately so diff can show right away
            self.detail_ready.emit(self._fallback)

        if self._mbid:
            try:
                art = download_cover_art(self._mbid)
                if art:
                    self.artwork_ready.emit(art)
            except Exception:
                pass


class _PickerDialog(QDialog):
    """Select one release from a list of MusicBrainz candidates."""

    def __init__(self, candidates: list[AlbumInfo], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Select Album")
        self.setMinimumWidth(500)
        self._selected: AlbumInfo | None = None

        vl = QVBoxLayout(self)
        vl.addWidget(QLabel("Multiple albums found. Select the correct one:"))

        self._list = QListWidget()
        for info in candidates:
            year = f" ({info.date[:4]})" if info.date and len(info.date) >= 4 else ""
            item = QListWidgetItem(f"{info.artist} — {info.album}{year}")
            item.setData(Qt.UserRole, info)
            self._list.addItem(item)
        if self._list.count():
            self._list.setCurrentRow(0)
        self._list.itemDoubleClicked.connect(lambda _: self._on_ok())
        vl.addWidget(self._list)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self._on_ok)
        btns.rejected.connect(self.reject)
        vl.addWidget(btns)

    def _on_ok(self) -> None:
        item = self._list.currentItem()
        if item:
            self._selected = item.data(Qt.UserRole)
            self.accept()

    @property
    def selected(self) -> AlbumInfo | None:
        return self._selected


class MetadataFetchDialog(QDialog):
    """Fetch MusicBrainz metadata for an album, review changes, then apply."""

    def __init__(
        self,
        tracks: list[Track],
        artist: str,
        album: str,
        library: Library,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Fetch Metadata — {album}")
        self.setMinimumWidth(660)
        self.setMinimumHeight(500)

        self._tracks = tracks
        self._library = library
        self._proposed: AlbumInfo | None = None
        self._artwork_bytes: bytes | None = None
        self._is_disc_path = False
        self._field_rows: list[tuple[str, str, str, QCheckBox]] = []
        self._track_rows: list[tuple[Track, str, QCheckBox]] = []
        self._artwork_cb: QCheckBox | None = None
        self._artwork_row_w: QWidget | None = None
        self._search_worker: _SearchWorker | None = None
        self._detail_worker: _DetailWorker | None = None

        outer = QVBoxLayout(self)
        outer.setSpacing(8)

        # Source banner (shown after search resolves)
        self._banner = QLabel()
        self._banner.setWordWrap(True)
        self._banner.setVisible(False)
        outer.addWidget(self._banner)

        # Stacked pages
        self._stack = QStackedWidget()
        outer.addWidget(self._stack, 1)

        # Page 0: Loading
        loading_w = QWidget()
        loading_vl = QVBoxLayout(loading_w)
        loading_vl.setAlignment(Qt.AlignCenter)
        self._loading_label = QLabel("Searching MusicBrainz…")
        self._loading_label.setAlignment(Qt.AlignCenter)
        loading_vl.addWidget(self._loading_label)
        self._stack.addWidget(loading_w)

        # Page 1: Not found / error
        nf_w = QWidget()
        nf_vl = QVBoxLayout(nf_w)
        nf_vl.setAlignment(Qt.AlignCenter)
        self._not_found_label = QLabel("No matching releases found on MusicBrainz.")
        self._not_found_label.setAlignment(Qt.AlignCenter)
        nf_vl.addWidget(self._not_found_label)
        self._stack.addWidget(nf_w)

        # Page 2: Diff view
        diff_w = QWidget()
        diff_vl = QVBoxLayout(diff_w)
        diff_vl.setSpacing(6)

        self._only_empty_cb = QCheckBox("Only fill empty fields")
        self._only_empty_cb.setChecked(True)
        self._only_empty_cb.toggled.connect(self._on_only_empty_toggled)
        diff_vl.addWidget(self._only_empty_cb)

        self._warn_label = QLabel(
            "Warning: This album was identified by Disc ID (exact match). "
            "Filling all fields may overwrite data previously fetched by CTDB."
        )
        self._warn_label.setWordWrap(True)
        self._warn_label.setObjectName("warningLabel")
        self._warn_label.setVisible(False)
        diff_vl.addWidget(self._warn_label)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        self._diff_container = QWidget()
        self._diff_vl = QVBoxLayout(self._diff_container)
        self._diff_vl.setSpacing(4)
        self._diff_vl.setContentsMargins(4, 4, 4, 4)
        scroll.setWidget(self._diff_container)
        diff_vl.addWidget(scroll, 1)

        self._stack.addWidget(diff_w)

        # Dialog buttons
        self._btns = QDialogButtonBox(QDialogButtonBox.Cancel)
        self._apply_btn = self._btns.addButton("Apply", QDialogButtonBox.AcceptRole)
        self._apply_btn.setVisible(False)
        self._btns.rejected.connect(self.reject)
        self._btns.accepted.connect(self._on_apply)
        outer.addWidget(self._btns)

        # Start search
        disc_id = next((t.disc_id for t in tracks if t.disc_id), None)
        self._search_worker = _SearchWorker(disc_id, artist, album, self)
        self._search_worker.disc_found.connect(self._on_disc_found)
        self._search_worker.candidates.connect(self._on_candidates)
        self._search_worker.not_found.connect(self._on_not_found)
        self._search_worker.error.connect(self._on_search_error)
        self._search_worker.finished.connect(self._on_search_worker_finished)
        self._search_worker.finished.connect(self._search_worker.deleteLater)
        self._search_worker.start()

    # ------------------------------------------------------------------ search slots

    def _on_disc_found(self, info: AlbumInfo) -> None:
        self._is_disc_path = True
        self._banner.setText(
            "Matched by Disc ID (exact match). "
            "Data from MusicBrainz is highly reliable for this album."
        )
        self._banner.setVisible(True)
        # Disc lookup already includes track list; show diff immediately.
        # Run detail worker with fetch_details=False to only grab artwork.
        self._start_detail_worker(info, fetch_details=False)

    def _on_candidates(self, candidates: list[AlbumInfo]) -> None:
        self._is_disc_path = False
        if len(candidates) == 1:
            selected = candidates[0]
        else:
            picker = _PickerDialog(candidates, self)
            try:
                accepted = picker.exec()
                selected = picker.selected
            finally:
                picker.deleteLater()
            if accepted != QDialog.Accepted or selected is None:
                self.reject()
                return

        self._banner.setText(
            "Matched by text search — please review all fields carefully before applying."
        )
        self._banner.setVisible(True)
        self._loading_label.setText("Fetching release details…")
        self._stack.setCurrentIndex(_PAGE_LOADING)
        self._start_detail_worker(selected, fetch_details=True)

    def _on_not_found(self) -> None:
        self._not_found_label.setText("No matching releases found on MusicBrainz.")
        self._stack.setCurrentIndex(_PAGE_NOT_FOUND)

    def _on_search_error(self, msg: str) -> None:
        self._not_found_label.setText(f"Search failed: {msg}")
        self._stack.setCurrentIndex(_PAGE_NOT_FOUND)

    def _start_detail_worker(self, info: AlbumInfo, fetch_details: bool) -> None:
        self._detail_worker = _DetailWorker(
            info.musicbrainz_albumid, info,
            fetch_details=fetch_details, parent=self,
        )
        self._detail_worker.detail_ready.connect(self._show_diff)
        self._detail_worker.artwork_ready.connect(self._on_artwork_ready)
        self._detail_worker.error.connect(self._on_detail_error)
        self._detail_worker.finished.connect(self._on_detail_worker_finished)
        self._detail_worker.finished.connect(self._detail_worker.deleteLater)
        self._detail_worker.start()

    def _on_search_worker_finished(self) -> None:
        if self.sender() is self._search_worker:
            self._search_worker = None

    def _on_detail_worker_finished(self) -> None:
        if self.sender() is self._detail_worker:
            self._detail_worker = None

    def _on_detail_error(self, msg: str) -> None:
        # Don't block the user; if detail fails we already emitted fallback in _DetailWorker
        pass

    # ------------------------------------------------------------------ diff display

    def _show_diff(self, info: AlbumInfo) -> None:
        self._proposed = info
        self._build_diff_table(info)
        self._stack.setCurrentIndex(_PAGE_DIFF)
        self._apply_btn.setVisible(True)
        self._apply_only_empty(self._only_empty_cb.isChecked())

    def _build_diff_table(self, info: AlbumInfo) -> None:
        while self._diff_vl.count():
            item = self._diff_vl.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self._field_rows.clear()
        self._track_rows.clear()
        self._artwork_cb = None
        self._artwork_row_w = None

        t0 = self._tracks[0] if self._tracks else None
        current_album = t0.album if t0 else ""
        current_artist = t0.display_artist if t0 else ""
        current_year = str(t0.year) if t0 and t0.year else ""
        current_genre = t0.genre if t0 else ""

        proposed_year = str(info.year) if info.year else ""

        album_fields = [
            ("album",  "Album",  current_album,  info.album),
            ("artist", "Artist", current_artist, info.artist),
            ("year",   "Year",   current_year,   proposed_year),
            ("genre",  "Genre",  current_genre,  info.genre),
        ]

        # Column header row
        hdr = QHBoxLayout()
        hdr.setSpacing(8)
        for text, stretch in (("Field", 0), ("Current", 1), ("Proposed", 1), ("", 0)):
            lbl = QLabel(f"<b>{text}</b>")
            if stretch:
                lbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
                hdr.addWidget(lbl, 1)
            elif text == "Field":
                lbl.setFixedWidth(90)
                hdr.addWidget(lbl)
            else:
                lbl.setFixedWidth(32)
                hdr.addWidget(lbl)
        hdr_w = QWidget()
        hdr_w.setLayout(hdr)
        self._diff_vl.addWidget(hdr_w)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        self._diff_vl.addWidget(sep)

        for field_key, field_label, cur, prop in album_fields:
            cb = QCheckBox()
            self._add_diff_row(field_label, cur, prop, cb)
            self._field_rows.append((field_key, cur, prop, cb))

        if info.tracks:
            sep2 = QFrame()
            sep2.setFrameShape(QFrame.HLine)
            self._diff_vl.addWidget(sep2)

            track_section = QLabel("<b>Track Titles</b>")
            self._diff_vl.addWidget(track_section)

            proposed_by_num = {ti.number: ti for ti in info.tracks}
            for tr in sorted(self._tracks, key=lambda t: t.track_no or 0):
                pti = proposed_by_num.get(tr.track_no or 0)
                if pti is None:
                    continue
                cb = QCheckBox()
                self._add_diff_row(f"#{tr.track_no}", tr.title, pti.title, cb)
                self._track_rows.append((tr, pti.title, cb))

        self._diff_vl.addStretch(1)

    def _add_diff_row(self, label: str, current: str, proposed: str, cb: QCheckBox) -> None:
        row = QHBoxLayout()
        row.setSpacing(8)

        lbl_w = QLabel(label)
        lbl_w.setFixedWidth(90)
        lbl_w.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        row.addWidget(lbl_w)

        cur_w = QLabel(current if current else "(empty)")
        cur_w.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        cur_w.setTextFormat(Qt.PlainText)
        cur_w.setWordWrap(True)
        row.addWidget(cur_w, 1)

        prop_w = QLabel(proposed if proposed else "(empty)")
        prop_w.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        prop_w.setTextFormat(Qt.PlainText)
        prop_w.setWordWrap(True)
        row.addWidget(prop_w, 1)

        cb.setEnabled(bool(proposed))
        cb.setFixedWidth(32)
        row.addWidget(cb)

        row_w = QWidget()
        row_w.setLayout(row)
        self._diff_vl.addWidget(row_w)

    def _on_artwork_ready(self, art: bytes) -> None:
        if self._artwork_row_w is not None:
            return
        self._artwork_bytes = art

        pix = QPixmap()
        pix.loadFromData(art)
        if pix.isNull():
            return
        thumb = pix.scaled(80, 80, Qt.KeepAspectRatio, Qt.SmoothTransformation)

        self._artwork_cb = QCheckBox()
        self._artwork_cb.setFixedWidth(32)
        self._artwork_cb.setChecked(True)

        row = QHBoxLayout()
        row.setSpacing(8)

        lbl_w = QLabel("Art")
        lbl_w.setFixedWidth(90)
        lbl_w.setAlignment(Qt.AlignRight | Qt.AlignTop)
        row.addWidget(lbl_w)

        cur_art = QLabel()
        cur_art.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        if self._tracks and self._tracks[0].artwork_path:
            cur_pix = QPixmap(self._tracks[0].artwork_path)
            if not cur_pix.isNull():
                cur_art.setPixmap(cur_pix.scaled(80, 80, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            else:
                cur_art.setText("(none)")
        else:
            cur_art.setText("(none)")
        row.addWidget(cur_art, 1)

        prop_art = QLabel()
        prop_art.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        prop_art.setPixmap(thumb)
        row.addWidget(prop_art, 1)

        row.addWidget(self._artwork_cb)

        row_w = QWidget()
        row_w.setLayout(row)
        self._artwork_row_w = row_w

        # Insert before the trailing stretch
        stretch_idx = self._diff_vl.count() - 1
        self._diff_vl.insertWidget(stretch_idx, row_w)

        # Apply current "only empty" setting
        has_current_art = bool(self._tracks and self._tracks[0].artwork_path)
        if self._only_empty_cb.isChecked() and has_current_art:
            self._artwork_cb.setChecked(False)

    # ------------------------------------------------------------------ checkbox logic

    def _on_only_empty_toggled(self, checked: bool) -> None:
        self._apply_only_empty(checked)
        if self._is_disc_path:
            self._warn_label.setVisible(not checked)

    def _apply_only_empty(self, only_empty: bool) -> None:
        for _fk, cur, prop, cb in self._field_rows:
            if not prop:
                cb.setChecked(False)
                continue
            cb.setChecked((not cur) if only_empty else True)

        for tr, prop_title, cb in self._track_rows:
            if not prop_title:
                cb.setChecked(False)
                continue
            cb.setChecked((not tr.title) if only_empty else True)

        if self._artwork_cb is not None:
            has_current = bool(self._tracks and self._tracks[0].artwork_path)
            self._artwork_cb.setChecked((not has_current) if only_empty else True)

    # ------------------------------------------------------------------ apply

    def _on_apply(self) -> None:
        if self._proposed is None:
            self.accept()
            return

        # Merge album-level values
        merged: dict[str, str] = {}
        for field_key, cur, prop, cb in self._field_rows:
            merged[field_key] = prop if (cb.isChecked() and prop) else cur

        # Build AlbumInfo for tag writing
        album_info = AlbumInfo(
            artist=merged.get("artist", ""),
            album=merged.get("album", ""),
            date=merged.get("year", ""),
            genre=merged.get("genre", ""),
            musicbrainz_albumid=self._proposed.musicbrainz_albumid,
            tracks=self._proposed.tracks,
        )

        # Track title overrides
        title_overrides: dict[int, str] = {}
        for tr, prop_title, cb in self._track_rows:
            if cb.isChecked() and prop_title:
                title_overrides[tr.id] = prop_title

        # Artwork
        artwork_bytes: bytes | None = None
        if self._artwork_cb is not None and self._artwork_cb.isChecked() and self._artwork_bytes:
            artwork_bytes = self._artwork_bytes

        # Build DB update for album-level fields
        db_base: dict = {}
        if merged.get("album"):
            db_base["album"] = merged["album"]
        if merged.get("artist"):
            db_base["artist"] = merged["artist"]
            db_base["album_artist"] = merged["artist"]
        if merged.get("year"):
            try:
                db_base["year"] = int(merged["year"])
            except ValueError:
                pass
        if "genre" in merged:
            db_base["genre"] = merged["genre"]

        # Save artwork file next to first track
        if artwork_bytes and self._tracks:
            art_path = Path(self._tracks[0].path).parent / "cover.jpg"
            try:
                art_path.write_bytes(artwork_bytes)
                db_base["artwork_path"] = str(art_path)
            except OSError:
                artwork_bytes = None

        # Apply to each track
        failed_tags: list[str] = []
        for tr in self._tracks:
            db_fields = dict(db_base)
            if tr.id in title_overrides:
                db_fields["title"] = title_overrides[tr.id]

            # Write audio tags
            track_num = tr.track_no or 0
            title = title_overrides.get(tr.id, tr.title)
            tr_info = TrackInfo(
                number=track_num,
                title=title,
                artist=album_info.artist or tr.artist,
                disc_number=tr.disc_no or 1,
            )
            if not write_tags(Path(tr.path), album_info, tr_info, artwork_bytes):
                failed_tags.append(tr.title or Path(tr.path).name)
                continue
            if db_fields:
                self._library.update_track(tr.id, db_fields)

        if failed_tags:
            shown = "\n".join(failed_tags[:6])
            if len(failed_tags) > 6:
                shown += f"\n...and {len(failed_tags) - 6} more"
            QMessageBox.warning(
                self,
                "Some Tags Were Not Updated",
                "The library database was left unchanged for tracks whose audio tags "
                f"could not be written:\n\n{shown}",
            )
        self.accept()

    def closeEvent(self, event) -> None:
        self._stop_worker("_search_worker")
        self._stop_worker("_detail_worker")
        super().closeEvent(event)

    def _stop_worker(self, attr: str) -> None:
        worker = getattr(self, attr, None)
        if worker is None:
            return
        for signal_name in (
            "disc_found",
            "candidates",
            "not_found",
            "detail_ready",
            "artwork_ready",
            "error",
        ):
            signal = getattr(worker, signal_name, None)
            if signal is None:
                continue
            try:
                signal.disconnect()
            except (TypeError, RuntimeError):
                pass
        try:
            worker.requestInterruption()
            worker.quit()
            if worker.isRunning() and not worker.wait(2000):
                worker.terminate()
                worker.wait(500)
        except RuntimeError:
            pass
        setattr(self, attr, None)

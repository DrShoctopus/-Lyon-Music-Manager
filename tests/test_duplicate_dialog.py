from __future__ import annotations

import pytest

QtWidgets = pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from lyon.ui.duplicate_dialog import DuplicateDialog
from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import QApplication


def test_fingerprint_summary_uses_count_helpers(qapp, monkeypatch):
    monkeypatch.setattr("lyon.core.fingerprint.is_available", lambda: True)
    monkeypatch.setattr("lyon.core.fingerprint.is_lookup_configured", lambda: True)

    class Library:
        def find_duplicates(self):
            return []

        def find_duplicates_by_hash(self):
            return []

        def find_duplicates_by_fingerprint(self):
            return []

        def count_tracks_without_acoustid(self):
            return 2

        def count_tracks(self, media_type=None):
            assert media_type == "audio"
            return 2

        def tracks_without_acoustid(self):
            raise AssertionError("summary should not materialize pending tracks")

        def all_tracks(self, media_type=None):
            raise AssertionError("summary should not materialize all audio tracks")

    dialog = DuplicateDialog(Library())
    try:
        dialog._mode_combo.setCurrentIndex(2)

        assert "No fingerprints computed yet" in dialog._summary_label.text()
    finally:
        dialog.close()
        dialog.deleteLater()


def test_hash_mode_disables_combo_while_busy(qapp, monkeypatch):
    """Switching to hash mode disables the combo during the async scan,
    then re-enables it and populates the tree once the worker finishes."""
    from lyon.core.library import Track

    track_a = Track(
        id=1, path="/a.mp3", title="Song A", artist="", album_artist="",
        album="", track_no=1, disc_no=1, year=0, genre="",
        duration=180, bitrate=320000, media_type="audio",
    )
    track_b = Track(
        id=2, path="/b.mp3", title="Song A", artist="", album_artist="",
        album="", track_no=1, disc_no=1, year=0, genre="",
        duration=180, bitrate=128000, media_type="audio",
    )

    class Library:
        def find_duplicates(self):
            return []

        def find_duplicates_by_hash(self):
            return [[track_a, track_b]]

        def find_duplicates_by_fingerprint(self):
            return []

        def count_tracks_without_acoustid(self):
            return 0

        def count_tracks(self, media_type=None):
            return 0

    dialog = DuplicateDialog(Library())
    try:
        # Wait for the initial (title-mode) async-free refresh to settle.
        QApplication.processEvents()

        # Switch to hash mode — combo should become disabled immediately.
        dialog._mode_combo.setCurrentIndex(1)
        assert not dialog._mode_combo.isEnabled(), "combo should be disabled while hashing"
        assert not dialog._keep_best_btn.isEnabled(), "destructive action should be disabled while hashing"

        # Wait for the background worker to finish.
        QThreadPool.globalInstance().waitForDone()
        QApplication.processEvents()

        # After the scan completes, combo should be re-enabled and tree populated.
        assert dialog._mode_combo.isEnabled(), "combo should be re-enabled after hash scan"
        assert dialog._keep_best_btn.isEnabled(), "destructive action should be re-enabled after hash scan"
        assert dialog._tree.topLevelItemCount() == 1, "tree should have one duplicate group"
    finally:
        dialog.close()
        dialog.deleteLater()


def test_hash_scan_clears_stale_groups_before_worker_finishes(qapp, monkeypatch):
    from lyon.core.library import Track

    track_a = Track(
        id=1, path="/a.mp3", title="Song A", artist="", album_artist="",
        album="", track_no=1, disc_no=1, year=0, genre="",
        duration=180, bitrate=320000, media_type="audio",
    )
    track_b = Track(
        id=2, path="/b.mp3", title="Song A", artist="", album_artist="",
        album="", track_no=1, disc_no=1, year=0, genre="",
        duration=180, bitrate=128000, media_type="audio",
    )

    class Library:
        def find_duplicates(self):
            return [[track_a, track_b]]

        def find_duplicates_by_hash(self):
            raise AssertionError("fake pool should keep the worker pending")

        def find_duplicates_by_fingerprint(self):
            return []

        def count_tracks_without_acoustid(self):
            return 0

        def count_tracks(self, media_type=None):
            return 0

    started = []

    class FakePool:
        def start(self, runnable):
            started.append(runnable)

    monkeypatch.setattr(
        "lyon.ui.duplicate_dialog.QThreadPool.globalInstance",
        staticmethod(lambda: FakePool()),
    )

    dialog = DuplicateDialog(Library())
    try:
        assert dialog._groups == [[track_a, track_b]]

        dialog._mode_combo.setCurrentIndex(1)

        assert started
        assert dialog._groups == []
        assert dialog._tree.topLevelItemCount() == 0
        assert not dialog._keep_best_btn.isEnabled()
    finally:
        dialog.close()
        dialog.deleteLater()


def test_hash_scan_failure_shows_error(qapp, monkeypatch):
    """If find_duplicates_by_hash raises, the summary label shows the error
    and the dialog does not crash."""

    class Library:
        def find_duplicates(self):
            return []

        def find_duplicates_by_hash(self):
            raise RuntimeError("disk read error")

        def find_duplicates_by_fingerprint(self):
            return []

        def count_tracks_without_acoustid(self):
            return 0

        def count_tracks(self, media_type=None):
            return 0

    dialog = DuplicateDialog(Library())
    try:
        QApplication.processEvents()

        # Switch to hash mode to trigger the async scan.
        dialog._mode_combo.setCurrentIndex(1)

        # Wait for the background worker to finish.
        QThreadPool.globalInstance().waitForDone()
        QApplication.processEvents()

        label_text = dialog._summary_label.text()
        assert "Hash scan failed" in label_text, f"Expected error in label, got: {label_text!r}"
        assert "disk read error" in label_text
    finally:
        dialog.close()
        dialog.deleteLater()

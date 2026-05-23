from __future__ import annotations

import pytest

QtWidgets = pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from lyon.ui.duplicate_dialog import DuplicateDialog


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

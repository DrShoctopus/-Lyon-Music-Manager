from __future__ import annotations

import pytest

QtWidgets = pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from lyon.core.metadata import ArtistInfo
from lyon.ui.artist_panel import ArtistPanel


def test_artist_panel_renders_artist_details(qapp):
    panel = ArtistPanel()
    try:
        panel.set_artist(
            ArtistInfo(
                name="Artist",
                biography="A concise biography.",
                genre="Rock",
                country="Canada",
                formed_year=1999,
                website="artist.example.test",
                similar_artists=["A", "B"],
            )
        )

        labels = [label.text() for label in panel.findChildren(QtWidgets.QLabel)]
        assert "Artist" in labels
        assert "A concise biography." in labels
        assert any("Rock" in text and "Canada" in text and "Formed 1999" in text for text in labels)
        assert "Similar artists: A, B" in labels
    finally:
        panel.deleteLater()


def test_artist_panel_empty_state(qapp):
    panel = ArtistPanel()
    try:
        panel.set_empty("No artist data.")

        labels = [label.text() for label in panel.findChildren(QtWidgets.QLabel)]
        assert "No artist data." in labels
    finally:
        panel.deleteLater()

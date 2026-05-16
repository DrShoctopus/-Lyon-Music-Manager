"""Phase 3 library view tests: sort, "All Albums", playing indicator, search."""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtCore = pytest.importorskip("PySide6.QtCore", exc_type=ImportError)
QtWidgets = pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from lyon.core.library import Track
from lyon.ui.library_view import LibraryView, _ALL_ALBUMS_KEY, _PLAYING_GLYPH


def _track(id_: int, title: str, artist: str, album: str,
           track_no: int = 1, duration: float = 180.0) -> Track:
    return Track(
        id=id_, path=f"/m/{id_}.flac",
        title=title, artist=artist, album_artist=artist, album=album,
        track_no=track_no, disc_no=1, year=2024, genre="",
        duration=duration, bitrate=900_000, samplerate=44_100,
    )


class FakeLibrary:
    def __init__(self, artists_map: dict[str, dict[str, list[Track]]]):
        self._map = artists_map

    def all_artists(self, _media=None) -> list[str]:
        return list(self._map.keys())

    def albums_for_artist(self, artist: str, _media=None):
        for album_name in self._map.get(artist, {}):
            yield (album_name, None)

    def tracks_for_album(self, artist: str, album: str, _media=None) -> list[Track]:
        return list(self._map.get(artist, {}).get(album, []))

    def tracks_for_artist(self, artist: str, _media=None) -> list[Track]:
        out: list[Track] = []
        for tracks in self._map.get(artist, {}).values():
            out.extend(tracks)
        return out

    def search(self, q: str, _media=None) -> list[Track]:
        q_lower = q.lower()
        out: list[Track] = []
        for albums in self._map.values():
            for tracks in albums.values():
                for t in tracks:
                    if q_lower in t.title.lower():
                        out.append(t)
        return out


@pytest.fixture(scope="module")
def app():
    existing = QtWidgets.QApplication.instance()
    if existing is not None:
        return existing
    return QtWidgets.QApplication([])


@pytest.fixture
def view(app):
    library = FakeLibrary({
        "Alpha Band": {
            "First Album": [
                _track(1, "Aardvark", "Alpha Band", "First Album", track_no=1, duration=180),
                _track(2, "Zebra",    "Alpha Band", "First Album", track_no=2, duration=240),
            ],
            "Second Album": [
                _track(3, "Mango",    "Alpha Band", "Second Album", track_no=1, duration=120),
            ],
        },
        "Beta Crew": {
            "Solo": [
                _track(4, "Solo Song", "Beta Crew", "Solo", track_no=1, duration=200),
            ],
        },
    })
    return LibraryView(library)


def test_all_albums_pseudo_entry_when_artist_has_multiple_albums(view):
    # Alpha Band has 2 albums -> All Albums + 2 = 3 rows
    assert view.albums_model.rowCount() == 3
    assert view.albums_model.item(0).text() == "All Albums"
    assert view.albums_model.item(0).data(QtCore.Qt.UserRole) == _ALL_ALBUMS_KEY


def test_all_albums_aggregates_tracks(view):
    view.albums.setCurrentIndex(view.albums_model.index(0, 0))
    assert view.tracks_model.rowCount() == 3  # 2 from First Album + 1 from Second


def test_single_album_artist_skips_pseudo_entry(view):
    # Beta Crew has only one album → no "All Albums" entry
    view.artists.setCurrentIndex(view.artists_model.index(1, 0))
    assert view.albums_model.rowCount() == 1
    assert view.albums_model.item(0).text() == "Solo"


def test_tracks_table_is_sortable_by_title(view):
    view.artists.setCurrentIndex(view.artists_model.index(0, 0))
    view.albums.setCurrentIndex(view.albums_model.index(1, 0))  # First Album
    assert view.tracks_model.rowCount() == 2

    view.tracks.sortByColumn(1, QtCore.Qt.AscendingOrder)
    assert view.tracks_model.item(0, 1).text() == "Aardvark"
    view.tracks.sortByColumn(1, QtCore.Qt.DescendingOrder)
    assert view.tracks_model.item(0, 1).text() == "Zebra"


def test_tracks_sort_by_time_is_numeric(view):
    view.artists.setCurrentIndex(view.artists_model.index(0, 0))
    view.albums.setCurrentIndex(view.albums_model.index(1, 0))  # First Album
    view.tracks.sortByColumn(4, QtCore.Qt.AscendingOrder)
    # 180s (Aardvark) < 240s (Zebra)
    assert view.tracks_model.item(0, 1).text() == "Aardvark"


def test_displayed_tracks_respects_sort_order(view):
    view.artists.setCurrentIndex(view.artists_model.index(0, 0))
    view.albums.setCurrentIndex(view.albums_model.index(1, 0))
    view.tracks.sortByColumn(1, QtCore.Qt.DescendingOrder)
    displayed = view._displayed_tracks()
    assert [t.title for t in displayed] == ["Zebra", "Aardvark"]


def test_playing_indicator_replaces_track_number(view):
    view.artists.setCurrentIndex(view.artists_model.index(0, 0))
    view.albums.setCurrentIndex(view.albums_model.index(1, 0))
    view.tracks.sortByColumn(0, QtCore.Qt.AscendingOrder)

    target = view._track_at_row(1)  # Zebra
    view.highlight_track(target)
    assert view.tracks_model.item(1, 0).text() == _PLAYING_GLYPH
    assert view.tracks_model.item(0, 0).text() == "1"  # other row keeps number


def test_playing_indicator_clears_when_track_is_none(view):
    view.artists.setCurrentIndex(view.artists_model.index(0, 0))
    view.albums.setCurrentIndex(view.albums_model.index(1, 0))
    target = view._track_at_row(1)
    view.highlight_track(target)
    view.highlight_track(None)
    assert view.tracks_model.item(1, 0).text() == "2"


def test_search_clear_button_is_enabled(view):
    assert view.search.isClearButtonEnabled()


def test_empty_search_renders_no_results_footer(view):
    view.search.setText("nonexistent-xyz")
    view._do_search()
    assert view.tracks_model.rowCount() == 0
    assert 'No tracks match "nonexistent-xyz"' in view._footer_label.text()

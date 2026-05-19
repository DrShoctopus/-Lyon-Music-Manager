"""Phase 3 library view tests: sort, "All Albums", playing indicator, search."""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtCore = pytest.importorskip("PySide6.QtCore", exc_type=ImportError)
QtWidgets = pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from lyon.core.library import Track
from lyon.ui import library_view as library_view_module
from lyon.ui.library_view import (
    LibraryView,
    _ALL_ALBUMS_KEY,
    _COL_TITLE,
    _NUM_COLS,
    _PLAYING_GLYPH,
)


def _track(id_: int, title: str, artist: str, album: str,
           track_no: int = 1, duration: float = 180.0,
           media_type: str = "audio") -> Track:
    ext = ".mp4" if media_type == "video" else ".flac"
    return Track(
        id=id_, path=f"/m/{id_}{ext}",
        title=title, artist=artist, album_artist=artist, album=album,
        track_no=track_no, disc_no=1, year=2024, genre="",
        duration=duration, bitrate=900_000, samplerate=44_100,
        media_type=media_type,
    )


class FakeLibrary:
    def __init__(self, artists_map: dict[str, dict[str, list[Track]]]):
        self._map = artists_map
        self.updated_tracks: list[tuple[int, dict]] = []

    def _iter_tracks(self, media_type=None, genre=None):
        for albums in self._map.values():
            for tracks in albums.values():
                for track in tracks:
                    if media_type is not None and track.media_type != media_type:
                        continue
                    if genre is not None and track.genre != genre:
                        continue
                    yield track

    def all_artists(self, _media=None, genre=None) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()
        for track in self._iter_tracks(_media, genre=genre):
            artist = track.display_artist
            if artist not in seen:
                seen.add(artist)
                out.append(artist)
        return out

    def albums_for_artist(self, artist: str, _media=None):
        for album_name, tracks in self._map.get(artist, {}).items():
            if any(_media is None or track.media_type == _media for track in tracks):
                yield (album_name, None)

    def all_albums(self, _media=None):
        out: list[tuple[str, str, None]] = []
        seen: set[tuple[str, str]] = set()
        for track in self._iter_tracks(_media):
            album = track.album or "Unknown Album"
            key = (track.display_artist, album)
            if key in seen:
                continue
            seen.add(key)
            out.append((track.display_artist, album, None))
        return out

    def tracks_for_album(self, artist: str, album: str, _media=None) -> list[Track]:
        return [
            track
            for track in self._map.get(artist, {}).get(album, [])
            if _media is None or track.media_type == _media
        ]

    def tracks_for_artist(self, artist: str, _media=None) -> list[Track]:
        out: list[Track] = []
        for tracks in self._map.get(artist, {}).values():
            out.extend(
                track for track in tracks
                if _media is None or track.media_type == _media
            )
        return out

    def search(self, q: str, _media=None) -> list[Track]:
        q_lower = q.lower()
        out: list[Track] = []
        for albums in self._map.values():
            for tracks in albums.values():
                for t in tracks:
                    if (_media is None or t.media_type == _media) and q_lower in t.title.lower():
                        out.append(t)
        return out

    def update_track(self, track_id: int, fields: dict) -> None:
        self.updated_tracks.append((track_id, dict(fields)))


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


def test_grid_albums_respect_show_videos_toggle(app):
    library = FakeLibrary({
        "Audio Artist": {
            "Audio Album": [
                _track(11, "Song", "Audio Artist", "Audio Album"),
            ],
        },
        "Video Artist": {
            "Video Album": [
                _track(12, "Clip", "Video Artist", "Video Album", media_type="video"),
            ],
        },
    })
    view = LibraryView(library)

    view._grid_mode_btn.setChecked(True)

    assert [
        view._grid_albums_model.item(row, 0).text()
        for row in range(view._grid_albums_model.rowCount())
    ] == ["Audio Album\nAudio Artist"]

    view._show_videos_cb.setChecked(True)

    assert [
        view._grid_albums_model.item(row, 0).text()
        for row in range(view._grid_albums_model.rowCount())
    ] == ["Audio Album\nAudio Artist", "Video Album\nVideo Artist"]


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


def test_track_columns_are_resizable_and_title_gets_priority_width(view):
    header = view.tracks.horizontalHeader()

    for col in range(_NUM_COLS):
        assert header.sectionResizeMode(col) == QtWidgets.QHeaderView.Interactive
    assert view.tracks.columnWidth(_COL_TITLE) >= 300


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


def test_single_metadata_edit_reports_file_tag_write_failure(app, monkeypatch, tmp_path):
    path = tmp_path / "song.flac"
    path.write_bytes(b"not real flac")
    track = _track(1, "Song", "Artist", "Album")
    track.path = str(path)
    library = FakeLibrary({"Artist": {"Album": [track]}})
    view = LibraryView(library)
    messages: list[str] = []
    view.status_message.connect(messages.append)

    def accept_dialog(dialog):
        dialog.deleteLater()
        return QtWidgets.QDialog.Accepted

    monkeypatch.setattr(library_view_module, "_exec_dialog", accept_dialog)
    monkeypatch.setattr(library_view_module, "write_partial_tags", lambda *_args: False)

    view._show_edit_metadata_dialog(track)

    assert library.updated_tracks
    assert "file tags could not be written to disk" in messages[-1]


def test_fetch_album_metadata_reports_track_lookup_failure(view):
    messages: list[str] = []
    view.status_message.connect(messages.append)

    def fail_tracks_for_album(*_args):
        raise RuntimeError("database unavailable")

    view.library.tracks_for_album = fail_tracks_for_album

    view._fetch_album_metadata("Alpha Band", "First Album")

    assert messages[-1] == "Could not load tracks for metadata fetch."


def test_fetch_album_metadata_reports_dialog_start_failure(view, monkeypatch):
    messages: list[str] = []
    view.status_message.connect(messages.append)

    def fail_dialog(*_args, **_kwargs):
        raise RuntimeError("dialog failed")

    monkeypatch.setattr(library_view_module, "MetadataFetchDialog", fail_dialog)

    view._fetch_album_metadata("Alpha Band", "First Album")

    assert messages[-1] == "Metadata fetch could not be started."

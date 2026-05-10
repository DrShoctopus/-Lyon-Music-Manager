import importlib.util
import sys
import types
import xml.etree.ElementTree as ET


def _install_dependency_stubs() -> None:
    if importlib.util.find_spec("musicbrainzngs") is None:
        musicbrainzngs = types.ModuleType("musicbrainzngs")
        musicbrainzngs.ResponseError = Exception
        musicbrainzngs.NetworkError = Exception
        sys.modules["musicbrainzngs"] = musicbrainzngs

    if importlib.util.find_spec("requests") is None:
        requests = types.ModuleType("requests")
        requests.RequestException = Exception
        sys.modules["requests"] = requests


_install_dependency_stubs()

from lyon.core import metadata  # noqa: E402
from lyon.core.metadata import (  # noqa: E402
    _ctdb_meta_to_album,
    _musicbrainz_toc_to_ctdb_toc,
    _release_to_album,
)


def test_release_to_album_filters_to_matching_disc_medium():
    release = {
        "id": "release-1",
        "title": "Two Disc Album",
        "artist-credit": [{"artist": {"name": "Artist"}}],
        "medium-list": [
            {
                "position": "1",
                "disc-list": [{"id": "disc-one"}],
                "track-list": [
                    {"position": "1", "title": "Disc One Track"},
                ],
            },
            {
                "position": "2",
                "disc-list": [{"id": "disc-two"}],
                "track-list": [
                    {"position": "1", "title": "Disc Two Track"},
                    {"position": "2", "title": "Disc Two Track 2"},
                ],
            },
        ],
    }

    album = _release_to_album(release, "disc-two")

    assert [track.title for track in album.tracks] == ["Disc Two Track", "Disc Two Track 2"]
    assert [track.disc_number for track in album.tracks] == [2, 2]


def test_musicbrainz_toc_converts_to_ctdb_offsets():
    toc = "1 3 45150 150 15150 30150"

    assert _musicbrainz_toc_to_ctdb_toc(toc) == "0:15000:30000:45000"


def test_lookup_disc_uses_ctdb_when_musicbrainz_has_no_release(monkeypatch):
    fallback = metadata.AlbumInfo(artist="CTDB Artist", album="CTDB Album")
    calls = {}

    monkeypatch.setattr(metadata, "_init", lambda: None)
    monkeypatch.setattr(
        metadata.musicbrainzngs,
        "get_releases_by_discid",
        lambda *args, **kwargs: {"disc": {}},
    )

    def fake_lookup(toc):
        calls["toc"] = toc
        return fallback

    monkeypatch.setattr(metadata, "lookup_ctdb_disc", fake_lookup)

    assert metadata.lookup_disc("disc-id", "toc-data") is fallback
    assert calls["toc"] == "toc-data"


def test_ctdb_meta_to_album_maps_tracks_and_primary_art():
    meta = ET.fromstring(
        """
        <metadata source="discogs" artist="Artist" album="Album" year="1999" genre="Rock">
          <track name="One" artist="Guest" />
          <track name="Two" />
          <coverart uri="http://example.test/other.jpg" primary="false" />
          <coverart uri="/covers/front.jpg" primary="true" />
        </metadata>
        """
    )

    album = _ctdb_meta_to_album(meta)

    assert album.artist == "Artist"
    assert album.album == "Album"
    assert album.genre == "Rock"
    assert album.metadata_source == "ctdb:discogs"
    assert [track.title for track in album.tracks] == ["One", "Two"]
    assert album.tracks[0].artist == "Guest"
    assert album.tracks[1].artist == "Artist"
    assert album.artwork_url == "http://db.cuetools.net/covers/front.jpg"

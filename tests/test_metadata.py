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


def test_lookup_disc_uses_ctdb_before_musicbrainz(monkeypatch):
    ctdb_album = metadata.AlbumInfo(artist="CTDB Artist", album="CTDB Album")
    calls = {}

    def fake_ctdb_lookup(toc):
        calls["ctdb_toc"] = toc
        return ctdb_album

    def fake_musicbrainz_lookup(*args, **kwargs):
        calls["musicbrainz"] = True
        return metadata.AlbumInfo(artist="MB Artist", album="MB Album")

    monkeypatch.setattr(metadata, "lookup_ctdb_disc", fake_ctdb_lookup)
    monkeypatch.setattr(metadata, "lookup_musicbrainz_disc", fake_musicbrainz_lookup)

    assert metadata.lookup_disc("disc-id", "toc-data") is ctdb_album
    assert calls == {"ctdb_toc": "toc-data"}


def test_lookup_disc_falls_back_to_musicbrainz_when_ctdb_has_no_match(monkeypatch):
    musicbrainz_album = metadata.AlbumInfo(artist="MB Artist", album="MB Album")
    calls = {}

    def fake_ctdb_lookup(toc):
        calls["ctdb_toc"] = toc
        return None

    def fake_musicbrainz_lookup(discid, toc):
        calls["musicbrainz"] = (discid, toc)
        return musicbrainz_album

    monkeypatch.setattr(metadata, "lookup_ctdb_disc", fake_ctdb_lookup)
    monkeypatch.setattr(metadata, "lookup_musicbrainz_disc", fake_musicbrainz_lookup)

    assert metadata.lookup_disc("disc-id", "toc-data") is musicbrainz_album
    assert calls == {"ctdb_toc": "toc-data", "musicbrainz": ("disc-id", "toc-data")}


def test_lookup_musicbrainz_disc_returns_none_when_no_release(monkeypatch):
    monkeypatch.setattr(metadata, "_init", lambda: None)
    monkeypatch.setattr(
        metadata.musicbrainzngs,
        "get_releases_by_discid",
        lambda *args, **kwargs: {"disc": {}},
    )

    assert metadata.lookup_musicbrainz_disc("disc-id", "toc-data") is None


def test_lookup_ctdb_disc_uses_exact_toc_matching_by_default(monkeypatch):
    captured = {}

    monkeypatch.setattr(
        metadata._settings.Settings,
        "load",
        lambda: types.SimpleNamespace(
            musicbrainz_app="LyonTest",
            musicbrainz_version="1.0",
            musicbrainz_contact="test@example.invalid",
        ),
    )

    class FakeResponse:
        status_code = 200
        content = b'<ctdb><metadata source="musicbrainz" artist="Artist" album="Album" /></ctdb>'

    def fake_get(url, params, headers, timeout):
        captured["url"] = url
        captured["params"] = params
        captured["headers"] = headers
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(metadata.requests, "get", fake_get)

    album = metadata.lookup_ctdb_disc("1 1 45150 150")

    assert album is not None
    assert album.album == "Album"
    assert captured["url"] == metadata.CTDB_LOOKUP_URL
    assert captured["params"]["fuzzy"] == "0"
    assert captured["params"]["toc"] == "0:45000"


def test_lookup_ctdb_disc_allows_explicit_fuzzy_lookup(monkeypatch):
    captured = {}

    monkeypatch.setattr(
        metadata._settings.Settings,
        "load",
        lambda: types.SimpleNamespace(
            musicbrainz_app="LyonTest",
            musicbrainz_version="1.0",
            musicbrainz_contact="test@example.invalid",
        ),
    )

    class FakeResponse:
        status_code = 200
        content = b'<ctdb><metadata source="musicbrainz" artist="Artist" album="Album" /></ctdb>'

    def fake_get(url, params, headers, timeout):
        captured["params"] = params
        return FakeResponse()

    monkeypatch.setattr(metadata.requests, "get", fake_get)

    album = metadata.lookup_ctdb_disc("1 1 45150 150", fuzzy=True)

    assert album is not None
    assert captured["params"]["fuzzy"] == "1"

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

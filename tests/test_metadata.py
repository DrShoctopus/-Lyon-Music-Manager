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


def test_lookup_disc_uses_musicbrainz_before_ctdb(monkeypatch):
    musicbrainz_album = metadata.AlbumInfo(artist="MB Artist", album="MB Album")
    calls = {}

    def fake_ctdb_lookup(toc):
        calls["ctdb_toc"] = toc
        return metadata.AlbumInfo(artist="CTDB Artist", album="CTDB Album")

    def fake_musicbrainz_lookup(discid, toc):
        calls["musicbrainz"] = (discid, toc)
        return musicbrainz_album

    monkeypatch.setattr(metadata, "lookup_ctdb_disc", fake_ctdb_lookup)
    monkeypatch.setattr(metadata, "lookup_musicbrainz_disc", fake_musicbrainz_lookup)

    assert metadata.lookup_disc("disc-id", "toc-data") is musicbrainz_album
    assert calls == {"musicbrainz": ("disc-id", "toc-data")}


def test_lookup_disc_falls_back_to_ctdb_when_musicbrainz_has_no_match(monkeypatch):
    ctdb_album = metadata.AlbumInfo(artist="CTDB Artist", album="CTDB Album")
    calls = {}

    def fake_ctdb_lookup(toc):
        calls["ctdb_toc"] = toc
        return ctdb_album

    def fake_musicbrainz_lookup(discid, toc):
        calls["musicbrainz"] = (discid, toc)
        return None

    monkeypatch.setattr(metadata, "lookup_ctdb_disc", fake_ctdb_lookup)
    monkeypatch.setattr(metadata, "lookup_musicbrainz_disc", fake_musicbrainz_lookup)

    assert metadata.lookup_disc("disc-id", "toc-data") is ctdb_album
    assert calls == {"musicbrainz": ("disc-id", "toc-data"), "ctdb_toc": "toc-data"}


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


def test_search_album_uses_top_provider_order(monkeypatch):
    calls = []
    deezer_album = metadata.AlbumInfo(
        artist="Deezer Artist",
        album="Deezer Album",
        tracks=[metadata.TrackInfo(number=1, title="Song")],
        metadata_source="deezer",
    )

    def fake_provider(name, result=None):
        def provider(artist, album):
            calls.append((name, artist, album))
            return result

        return provider

    monkeypatch.setattr(
        metadata,
        "_album_search_providers",
        lambda: (
            fake_provider("musicbrainz"),
            fake_provider("discogs"),
            fake_provider("itunes"),
            fake_provider("deezer", deezer_album),
            fake_provider("lastfm"),
        ),
    )

    assert metadata.search_album("Artist", "Album") is deezer_album
    assert calls == [
        ("musicbrainz", "Artist", "Album"),
        ("discogs", "Artist", "Album"),
        ("itunes", "Artist", "Album"),
        ("deezer", "Artist", "Album"),
    ]


def test_search_album_provider_names_keep_musicbrainz_first_and_four_fallbacks():
    assert metadata.ALBUM_METADATA_PROVIDER_ORDER == (
        "musicbrainz",
        "discogs",
        "itunes",
        "deezer",
        "lastfm",
    )
    assert metadata.DISC_METADATA_PROVIDER_ORDER == ("musicbrainz", "ctdb")
    assert metadata.METADATA_PROVIDER_ORDER == metadata.ALBUM_METADATA_PROVIDER_ORDER


def test_itunes_search_maps_tracks_and_artwork(monkeypatch):
    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "results": [
                    {
                        "artistName": "Artist",
                        "collectionName": "Album",
                        "trackName": "Two",
                        "trackNumber": 2,
                        "discNumber": 1,
                        "trackTimeMillis": 2000,
                        "releaseDate": "2001-02-03T08:00:00Z",
                        "primaryGenreName": "Rock",
                        "artworkUrl100": "https://example.test/100x100bb.jpg",
                    },
                    {
                        "artistName": "Artist",
                        "collectionName": "Album",
                        "trackName": "One",
                        "trackNumber": 1,
                        "discNumber": 1,
                        "trackTimeMillis": 1000,
                        "releaseDate": "2001-02-03T08:00:00Z",
                        "primaryGenreName": "Rock",
                        "artworkUrl100": "https://example.test/100x100bb.jpg",
                    },
                ]
            }

    monkeypatch.setattr(metadata.requests, "get", lambda *args, **kwargs: FakeResponse())

    album = metadata.search_itunes_album("Artist", "Album")

    assert album.artist == "Artist"
    assert album.album == "Album"
    assert album.date == "2001-02-03"
    assert album.genre == "Rock"
    assert album.metadata_source == "itunes"
    assert album.artwork_url == "https://example.test/600x600bb.jpg"
    assert [track.title for track in album.tracks] == ["One", "Two"]


def test_deezer_search_maps_album_detail_tracks_and_artwork(monkeypatch):
    responses = [
        {
            "data": [
                {
                    "id": 42,
                    "title": "Album",
                    "artist": {"name": "Artist"},
                }
            ]
        },
        {
            "id": 42,
            "title": "Album",
            "artist": {"name": "Artist"},
            "release_date": "2002-03-04",
            "cover_xl": "https://example.test/deezer.jpg",
            "genres": {"data": [{"name": "Pop"}]},
            "tracks": {
                "data": [
                    {
                        "title": "Track A",
                        "track_position": 1,
                        "disk_number": 1,
                        "duration": 12,
                        "artist": {"name": "Artist"},
                    }
                ]
            },
        },
    ]

    class FakeResponse:
        status_code = 200

        def json(self):
            return responses.pop(0)

    monkeypatch.setattr(metadata.requests, "get", lambda *args, **kwargs: FakeResponse())

    album = metadata.search_deezer_album("Artist", "Album")

    assert album.artist == "Artist"
    assert album.album == "Album"
    assert album.date == "2002-03-04"
    assert album.genre == "Pop"
    assert album.metadata_source == "deezer"
    assert album.artwork_url == "https://example.test/deezer.jpg"
    assert [(track.number, track.title, track.length_ms) for track in album.tracks] == [
        (1, "Track A", 12000)
    ]


def test_fetch_artwork_uses_cover_art_archive_then_album_artwork(monkeypatch):
    album = metadata.AlbumInfo(
        artist="Artist",
        album="Album",
        musicbrainz_albumid="release-id",
        artwork_url="https://example.test/fallback.jpg",
    )
    calls = []

    class FakeResponse:
        def __init__(self, status_code, content):
            self.status_code = status_code
            self.content = content

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        if "coverartarchive" in url:
            return FakeResponse(404, b"")
        return FakeResponse(200, b"image-bytes")

    monkeypatch.setattr(metadata.requests, "get", fake_get)
    monkeypatch.setattr(metadata, "search_itunes_album", lambda *args: None)
    monkeypatch.setattr(metadata, "search_deezer_album", lambda *args: None)
    monkeypatch.setattr(metadata, "search_lastfm_album", lambda *args: None)

    assert metadata.fetch_artwork(album) == b"image-bytes"
    assert [url for url, _kwargs in calls] == [
        "https://coverartarchive.org/release/release-id/front-500",
        "https://example.test/fallback.jpg",
    ]


def test_search_album_continues_past_incomplete_metadata(monkeypatch):
    incomplete = metadata.AlbumInfo(artist="Artist", album="Album", metadata_source="musicbrainz")
    complete = metadata.AlbumInfo(
        artist="Artist",
        album="Album",
        tracks=[metadata.TrackInfo(number=1, title="Complete Track")],
        metadata_source="discogs",
    )
    calls = []

    def fake_provider(name, result=None):
        def provider(artist, album):
            calls.append(name)
            return result

        return provider

    monkeypatch.setattr(
        metadata,
        "_album_search_providers",
        lambda: (
            fake_provider("musicbrainz", incomplete),
            fake_provider("discogs", complete),
            fake_provider("itunes"),
        ),
    )

    assert metadata.search_album("Artist", "Album") is complete
    assert calls == ["musicbrainz", "discogs"]


def test_search_album_returns_first_basic_metadata_when_no_tracks(monkeypatch):
    incomplete = metadata.AlbumInfo(artist="Artist", album="Album", metadata_source="musicbrainz")

    monkeypatch.setattr(
        metadata,
        "_album_search_providers",
        lambda: (
            lambda _artist, _album: incomplete,
            lambda _artist, _album: None,
        ),
    )

    assert metadata.search_album("Artist", "Album") is incomplete


def test_fetch_artwork_does_not_search_providers_when_primary_url_succeeds(monkeypatch):
    album = metadata.AlbumInfo(
        artist="Artist",
        album="Album",
        musicbrainz_albumid="release-id",
        artwork_url="https://example.test/fallback.jpg",
    )
    calls = []

    class FakeResponse:
        status_code = 200
        content = b"cover-art"

    def fake_get(url, **kwargs):
        calls.append(url)
        return FakeResponse()

    def fail_provider(*_args):
        raise AssertionError("provider artwork lookup should not run")

    monkeypatch.setattr(metadata.requests, "get", fake_get)
    monkeypatch.setattr(metadata, "search_discogs_album", fail_provider)
    monkeypatch.setattr(metadata, "search_itunes_album", fail_provider)
    monkeypatch.setattr(metadata, "search_deezer_album", fail_provider)
    monkeypatch.setattr(metadata, "search_lastfm_album", fail_provider)

    assert metadata.fetch_artwork(album) == b"cover-art"
    assert calls == ["https://coverartarchive.org/release/release-id/front-500"]


def test_fetch_artwork_uses_provider_artwork_after_primary_urls_fail(monkeypatch):
    album = metadata.AlbumInfo(
        artist="Artist",
        album="Album",
        artwork_url="https://example.test/primary.jpg",
    )
    provider_album = metadata.AlbumInfo(
        artist="Artist",
        album="Album",
        artwork_url="https://example.test/provider.jpg",
        metadata_source="discogs",
    )
    calls = []

    class FakeResponse:
        def __init__(self, status_code, content):
            self.status_code = status_code
            self.content = content

    def fake_get(url, **kwargs):
        calls.append(url)
        if url == "https://example.test/provider.jpg":
            return FakeResponse(200, b"provider-art")
        return FakeResponse(404, b"")

    monkeypatch.setattr(metadata.requests, "get", fake_get)
    monkeypatch.setattr(metadata, "search_discogs_album", lambda *args: provider_album)
    monkeypatch.setattr(metadata, "search_itunes_album", lambda *args: None)
    monkeypatch.setattr(metadata, "search_deezer_album", lambda *args: None)
    monkeypatch.setattr(metadata, "search_lastfm_album", lambda *args: None)

    assert metadata.fetch_artwork(album) == b"provider-art"
    assert calls == ["https://example.test/primary.jpg", "https://example.test/provider.jpg"]


def test_itunes_search_orders_multi_disc_tracks(monkeypatch):
    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "results": [
                    {
                        "artistName": "Artist",
                        "collectionName": "Album",
                        "trackName": "Disc Two One",
                        "trackNumber": 1,
                        "discNumber": 2,
                    },
                    {
                        "artistName": "Artist",
                        "collectionName": "Album",
                        "trackName": "Disc One Two",
                        "trackNumber": 2,
                        "discNumber": 1,
                    },
                    {
                        "artistName": "Artist",
                        "collectionName": "Album",
                        "trackName": "Disc One One",
                        "trackNumber": 1,
                        "discNumber": 1,
                    },
                ]
            }

    monkeypatch.setattr(metadata.requests, "get", lambda *args, **kwargs: FakeResponse())

    album = metadata.search_itunes_album("Artist", "Album")

    assert [(track.disc_number, track.number, track.title) for track in album.tracks] == [
        (1, 1, "Disc One One"),
        (1, 2, "Disc One Two"),
        (2, 1, "Disc Two One"),
    ]


def test_discogs_search_maps_tracks_and_artwork(monkeypatch):
    responses = [
        {
            "results": [
                {
                    "id": 7,
                    "master_id": 7,
                    "type": "master",
                    "title": "Artist - Album",
                    "cover_image": "https://example.test/search.jpg",
                    "year": 2003,
                }
            ]
        },
        {
            "id": 7,
            "title": "Album",
            "year": 2003,
            "artists": [{"name": "Artist"}],
            "genres": ["Electronic"],
            "images": [{"uri": "https://example.test/discogs.jpg"}],
            "tracklist": [
                {"position": "1-1", "title": "One", "duration": "1:02"},
                {"position": "1-2", "title": "Two", "duration": "2:03"},
            ],
        },
    ]

    monkeypatch.setattr(metadata, "_get_json", lambda *args, **kwargs: responses.pop(0))

    album = metadata.search_discogs_album("Artist", "Album")

    assert album.artist == "Artist"
    assert album.album == "Album"
    assert album.date == "2003"
    assert album.genre == "Electronic"
    assert album.metadata_source == "discogs"
    assert album.artwork_url == "https://example.test/discogs.jpg"
    assert [(track.disc_number, track.number, track.title, track.length_ms) for track in album.tracks] == [
        (1, 1, "One", 62000),
        (1, 2, "Two", 123000),
    ]

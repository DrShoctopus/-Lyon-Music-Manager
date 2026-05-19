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


def _stub_settings(monkeypatch) -> None:
    monkeypatch.setattr(
        metadata._settings.Settings,
        "load",
        lambda: types.SimpleNamespace(
            musicbrainz_app="LyonTest",
            musicbrainz_version="1.0",
            musicbrainz_contact="test@example.invalid",
            cuetools_db_metadata_enabled=True,
            theaudiodb_api_key="123",
        ),
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


def test_lookup_disc_uses_cuetools_db_before_musicbrainz(monkeypatch):
    ctdb_album = metadata.AlbumInfo(
        artist="CTDB Artist",
        album="CTDB Album",
        artwork_url="https://example.test/cover.jpg",
        tracks=[metadata.TrackInfo(number=1, title="Song")],
    )
    calls = []

    def fake_cuetools(toc, ctdb_toc=None):
        calls.append(("cuetools", toc, ctdb_toc))
        return ctdb_album

    def fake_musicbrainz(_discid, _toc):
        calls.append(("musicbrainz",))
        return metadata.AlbumInfo(artist="MB Artist", album="MB Album")

    monkeypatch.setattr(metadata, "lookup_cuetools_db_disc", fake_cuetools)
    monkeypatch.setattr(metadata, "lookup_musicbrainz_disc", fake_musicbrainz)

    assert metadata.lookup_disc("disc-id", "mb-toc", ctdb_toc="ctdb-toc") is ctdb_album
    assert calls == [("cuetools", "mb-toc", "ctdb-toc")]


def test_lookup_disc_respects_cuetools_toggle(monkeypatch):
    musicbrainz_album = metadata.AlbumInfo(
        artist="MB Artist",
        album="MB Album",
        artwork_url="https://example.test/mb.jpg",
        tracks=[metadata.TrackInfo(number=1, title="MB Song")],
    )
    calls = []

    def fail_cuetools(*_args, **_kwargs):
        raise AssertionError("CUETools DB should be disabled")

    def fake_musicbrainz(discid, toc):
        calls.append((discid, toc))
        return musicbrainz_album

    monkeypatch.setattr(metadata, "lookup_cuetools_db_disc", fail_cuetools)
    monkeypatch.setattr(metadata, "lookup_musicbrainz_disc", fake_musicbrainz)

    assert metadata.lookup_disc("disc-id", "toc-data", use_cuetools_db=False) is musicbrainz_album
    assert calls == [("disc-id", "toc-data")]


def test_lookup_disc_falls_back_to_musicbrainz_when_cuetools_has_no_match(monkeypatch):
    musicbrainz_album = metadata.AlbumInfo(
        artist="MB Artist",
        album="MB Album",
        artwork_url="https://example.test/mb.jpg",
        tracks=[metadata.TrackInfo(number=1, title="MB Song")],
    )
    calls = []

    def fake_cuetools(toc, ctdb_toc=None):
        calls.append(("cuetools", toc, ctdb_toc))
        return None

    def fake_musicbrainz(discid, toc):
        calls.append(("musicbrainz", discid, toc))
        return musicbrainz_album

    monkeypatch.setattr(metadata, "lookup_cuetools_db_disc", fake_cuetools)
    monkeypatch.setattr(metadata, "lookup_musicbrainz_disc", fake_musicbrainz)

    assert metadata.lookup_disc("disc-id", "mb-toc", ctdb_toc="ctdb-toc") is musicbrainz_album
    assert calls == [
        ("cuetools", "mb-toc", "ctdb-toc"),
        ("musicbrainz", "disc-id", "mb-toc"),
    ]


def test_lookup_disc_enriches_incomplete_result_with_theaudiodb(monkeypatch):
    base = metadata.AlbumInfo(artist="Artist", album="Album", metadata_source="musicbrainz")
    audiodb = metadata.AlbumInfo(
        artist="Artist",
        album="Album",
        artwork_url="https://example.test/audiodb.jpg",
        tracks=[metadata.TrackInfo(number=1, title="Track")],
        metadata_source="theaudiodb",
    )

    monkeypatch.setattr(metadata, "lookup_cuetools_db_disc", lambda *args, **kwargs: None)
    monkeypatch.setattr(metadata, "lookup_musicbrainz_disc", lambda *args: base)
    monkeypatch.setattr(metadata, "search_theaudiodb_album", lambda *args: audiodb)

    album = metadata.lookup_disc("disc-id", "toc-data")

    assert album is base
    assert album.artwork_url == "https://example.test/audiodb.jpg"
    assert [track.title for track in album.tracks] == ["Track"]
    assert album.metadata_source == "musicbrainz+theaudiodb"


def test_lookup_cuetools_db_disc_uses_full_layout_before_converted_toc(monkeypatch):
    calls = []
    expected = metadata.AlbumInfo(artist="Artist", album="Album")

    def fake_layout(layout, fuzzy=False):
        calls.append((layout, fuzzy))
        return expected

    monkeypatch.setattr(metadata, "lookup_cuetools_db_layout", fake_layout)

    assert metadata.lookup_cuetools_db_disc(
        "1 1 45150 150", ctdb_toc="0:15000:-30000:45000"
    ) is expected
    assert calls == [("0:15000:-30000:45000", False)]


def test_lookup_cuetools_db_disc_falls_back_to_fuzzy(monkeypatch):
    calls = []
    expected = metadata.AlbumInfo(artist="Artist", album="Album")

    def fake_layout(layout, fuzzy=False):
        calls.append((layout, fuzzy))
        return expected if fuzzy else None

    monkeypatch.setattr(metadata, "lookup_cuetools_db_layout", fake_layout)

    assert metadata.lookup_cuetools_db_disc("1 1 45150 150") is expected
    assert calls == [("0:45000", False), ("0:45000", True)]


def test_lookup_cuetools_db_layout_uses_exact_toc_matching_by_default(monkeypatch):
    captured = {}
    _stub_settings(monkeypatch)

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

    album = metadata.lookup_cuetools_db_layout("0:45000")

    assert album is not None
    assert album.album == "Album"
    assert captured["url"] == metadata.CTDB_LOOKUP_URL
    assert captured["params"]["fuzzy"] == "0"
    assert captured["params"]["toc"] == "0:45000"


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
    assert album.metadata_source == "cuetools_db:discogs"
    assert [track.title for track in album.tracks] == ["One", "Two"]
    assert album.tracks[0].artist == "Guest"
    assert album.tracks[1].artist == "Artist"
    assert album.artwork_url == "http://db.cuetools.net/covers/front.jpg"


def test_search_album_uses_musicbrainz_before_theaudiodb(monkeypatch):
    calls = []
    audiodb_album = metadata.AlbumInfo(
        artist="AudioDB Artist",
        album="AudioDB Album",
        tracks=[metadata.TrackInfo(number=1, title="Song")],
        metadata_source="theaudiodb",
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
            fake_provider("theaudiodb", audiodb_album),
        ),
    )

    assert metadata.search_album("Artist", "Album") is audiodb_album
    assert calls == [
        ("musicbrainz", "Artist", "Album"),
        ("theaudiodb", "Artist", "Album"),
    ]


def test_provider_names_keep_only_supported_metadata_sources():
    assert metadata.DISC_METADATA_PROVIDER_ORDER == ("cuetools_db", "musicbrainz")
    assert metadata.ALBUM_METADATA_PROVIDER_ORDER == ("musicbrainz", "theaudiodb")
    assert metadata.ARTWORK_PROVIDER_ORDER == (
        "cover_art_archive",
        "album_artwork_url",
        "theaudiodb",
    )
    assert metadata.METADATA_PROVIDER_ORDER == metadata.ALBUM_METADATA_PROVIDER_ORDER


def test_musicbrainz_useragent_refreshes_when_settings_change(monkeypatch):
    calls = []
    current = [
        types.SimpleNamespace(
            musicbrainz_app="LyonTest",
            musicbrainz_version="1.0",
            musicbrainz_contact="first@example.invalid",
        )
    ]

    monkeypatch.setattr(metadata, "_initialised", False)
    monkeypatch.setattr(metadata, "_last_musicbrainz_useragent", None)
    monkeypatch.setattr(metadata._settings, "get_cached_settings", lambda: current[0])
    monkeypatch.setattr(metadata.musicbrainzngs, "set_useragent", lambda *args: calls.append(args))

    metadata._init()
    current[0] = types.SimpleNamespace(
        musicbrainz_app="LyonTest",
        musicbrainz_version="1.0",
        musicbrainz_contact="second@example.invalid",
    )
    metadata._init()

    assert calls == [
        ("LyonTest", "1.0", "first@example.invalid"),
        ("LyonTest", "1.0", "second@example.invalid"),
    ]


def test_theaudiodb_search_maps_album_tracks_and_artwork(monkeypatch):
    responses = [
        {
            "album": [
                {
                    "idAlbum": "42",
                    "strArtist": "Artist",
                    "strAlbum": "Album",
                    "intYearReleased": "2002",
                    "strGenre": "Rock",
                    "strAlbumThumb": "https://example.test/album.jpg",
                }
            ]
        },
        {
            "track": [
                {
                    "strTrack": "Two",
                    "intTrackNumber": "2",
                    "intDuration": "120000",
                    "strArtist": "Artist",
                },
                {
                    "strTrack": "One",
                    "intTrackNumber": "1",
                    "intDuration": "60000",
                    "strArtist": "Artist",
                },
            ]
        },
    ]
    calls = []

    def fake_get_json(url, params=None, headers=None):
        calls.append((url, params, headers))
        return responses.pop(0)

    monkeypatch.setattr(metadata, "_get_json", fake_get_json)
    monkeypatch.setattr(metadata, "_theaudiodb_api_key", lambda: "123")

    album = metadata.search_theaudiodb_album("Artist", "Album")

    assert album.artist == "Artist"
    assert album.album == "Album"
    assert album.date == "2002"
    assert album.genre == "Rock"
    assert album.metadata_source == "theaudiodb"
    assert album.artwork_url == "https://example.test/album.jpg"
    assert [(track.number, track.title, track.length_ms) for track in album.tracks] == [
        (1, "One", 60000),
        (2, "Two", 120000),
    ]
    assert calls[0][0].endswith("/123/searchalbum.php")
    assert calls[0][1] == {"a": "Album", "s": "Artist"}
    assert calls[1][0].endswith("/123/track.php")
    assert calls[1][1] == {"m": "42"}


def test_theaudiodb_artist_lookup_maps_bio_image_and_similar(monkeypatch):
    calls = []

    def fake_get_json(url, params=None, headers=None):
        calls.append((url, params, headers))
        return {
            "artists": [
                {
                    "strArtist": "Artist",
                    "strBiographyEN": "Artist biography.",
                    "strArtistThumb": "https://example.test/artist.jpg",
                    "strGenre": "Rock",
                    "strCountry": "Canada",
                    "intFormedYear": "1999",
                    "strWebsite": "artist.example.test",
                    "strSimilarArtists": "A, B; C",
                }
            ]
        }

    monkeypatch.setattr(metadata, "_get_json", fake_get_json)
    monkeypatch.setattr(metadata, "_theaudiodb_api_key", lambda: "123")

    artist = metadata.lookup_artist_info("Artist")

    assert artist.name == "Artist"
    assert artist.biography == "Artist biography."
    assert artist.image_url == "https://example.test/artist.jpg"
    assert artist.genre == "Rock"
    assert artist.country == "Canada"
    assert artist.formed_year == 1999
    assert artist.website == "artist.example.test"
    assert artist.similar_artists == ["A", "B", "C"]
    assert calls[0][0].endswith("/123/search.php")
    assert calls[0][1] == {"s": "Artist"}


def test_artist_lookup_skips_unknown_artist(monkeypatch):
    monkeypatch.setattr(
        metadata,
        "_get_json",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("network call")),
    )

    assert metadata.lookup_artist_info("Unknown Artist") is None


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

    assert metadata.fetch_artwork(album) == b"image-bytes"
    assert [url for url, _kwargs in calls] == [
        "https://coverartarchive.org/release/release-id/front-500",
        "https://example.test/fallback.jpg",
    ]


def test_fetch_artwork_uses_theaudiodb_after_primary_urls_fail(monkeypatch):
    album = metadata.AlbumInfo(
        artist="Artist",
        album="Album",
        artwork_url="https://example.test/primary.jpg",
    )
    provider_album = metadata.AlbumInfo(
        artist="Artist",
        album="Album",
        artwork_url="https://example.test/provider.jpg",
        metadata_source="theaudiodb",
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
    monkeypatch.setattr(metadata, "search_theaudiodb_album", lambda *args: provider_album)

    assert metadata.fetch_artwork(album) == b"provider-art"
    assert calls == ["https://example.test/primary.jpg", "https://example.test/provider.jpg"]


def test_fetch_artwork_skips_unsupported_url_without_request(monkeypatch):
    calls = []
    monkeypatch.setattr(metadata, "_http_get", lambda *args, **kwargs: calls.append((args, kwargs)))

    assert metadata._fetch_artwork_url("file:///tmp/cover.jpg") is None
    assert calls == []


def test_fetch_artwork_rejects_oversized_content_length(monkeypatch):
    captured = {}

    class FakeResponse:
        status_code = 200
        headers = {"Content-Length": str(metadata.MAX_ARTWORK_BYTES + 1)}
        content = b""

    def fake_get(url, **kwargs):
        captured["url"] = url
        captured["kwargs"] = kwargs
        return FakeResponse()

    monkeypatch.setattr(metadata, "_http_get", fake_get)

    assert metadata._fetch_artwork_url("https://example.test/huge.jpg") is None
    assert captured["kwargs"]["stream"] is True


def test_fetch_artwork_rejects_stream_that_exceeds_limit(monkeypatch):
    class FakeResponse:
        status_code = 200
        headers = {}
        content = b""

        def iter_content(self, chunk_size):
            assert chunk_size > 0
            yield b"abc"
            yield b"def"

    monkeypatch.setattr(metadata, "MAX_ARTWORK_BYTES", 4)
    monkeypatch.setattr(metadata, "_http_get", lambda *args, **kwargs: FakeResponse())

    assert metadata._fetch_artwork_url("https://example.test/too-large.jpg") is None


def test_fetch_artwork_stream_failure_does_not_read_unbounded_content(monkeypatch):
    class FakeResponse:
        status_code = 200
        headers = {}
        reason = "OK"

        @property
        def content(self):
            raise AssertionError("streaming artwork fetch should not read response.content")

        def iter_content(self, chunk_size):
            assert chunk_size > 0
            return iter(())

    monkeypatch.setattr(metadata, "_http_get", lambda *args, **kwargs: FakeResponse())

    assert metadata._fetch_artwork_url("https://example.test/empty.jpg") is None


def test_search_album_continues_past_incomplete_metadata(monkeypatch):
    incomplete = metadata.AlbumInfo(artist="Artist", album="Album", metadata_source="musicbrainz")
    complete = metadata.AlbumInfo(
        artist="Artist",
        album="Album",
        tracks=[metadata.TrackInfo(number=1, title="Complete Track")],
        metadata_source="theaudiodb",
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
            fake_provider("theaudiodb", complete),
        ),
    )

    assert metadata.search_album("Artist", "Album") is complete
    assert calls == ["musicbrainz", "theaudiodb"]


def test_lookup_disc_skips_diagnostics_when_setting_disabled(caplog, monkeypatch):
    monkeypatch.setattr(metadata, "lookup_cuetools_db_disc", lambda *args, **kwargs: None)
    monkeypatch.setattr(metadata, "lookup_musicbrainz_disc", lambda *args: None)
    monkeypatch.setattr(
        metadata._settings.Settings,
        "load",
        lambda: types.SimpleNamespace(metadata_diagnostics_enabled=False),
    )

    with caplog.at_level("WARNING", logger="lyon.core.metadata"):
        assert metadata.lookup_disc(
            "disc-id",
            "1 1 45150 150",
            ctdb_toc="0:45000",
            use_cuetools_db=True,
        ) is None

    assert not caplog.messages


def test_lookup_disc_logs_diagnostics_when_enabled_and_no_metadata(caplog, monkeypatch):
    monkeypatch.setattr(metadata, "lookup_cuetools_db_disc", lambda *args, **kwargs: None)
    monkeypatch.setattr(metadata, "lookup_musicbrainz_disc", lambda *args: None)
    monkeypatch.setattr(
        metadata._settings.Settings,
        "load",
        lambda: types.SimpleNamespace(metadata_diagnostics_enabled=True),
    )

    with caplog.at_level("WARNING", logger="lyon.core.metadata"):
        assert metadata.lookup_disc(
            "disc-id",
            "1 1 45150 150",
            ctdb_toc="0:45000",
            use_cuetools_db=True,
        ) is None

    message = caplog.messages[-1]
    assert "Album metadata lookup returned no usable metadata." in message
    assert "discid: disc-id" in message
    assert "musicbrainz_toc: 1 1 45150 150" in message
    assert "ctdb_toc: 0:45000" in message
    assert "cuetools_db: returned no result" in message
    assert "musicbrainz: returned no result" in message
    assert "theaudiodb: not attempted" in message


def test_search_album_logs_diagnostics_when_enabled_and_no_metadata(caplog, monkeypatch):
    def fake_provider(name):
        def provider(_artist, _album):
            return None

        provider.__name__ = name
        return provider

    monkeypatch.setattr(
        metadata,
        "_album_search_providers",
        lambda: (
            fake_provider("search_musicbrainz_album"),
            fake_provider("search_theaudiodb_album"),
        ),
    )
    monkeypatch.setattr(
        metadata._settings.Settings,
        "load",
        lambda: types.SimpleNamespace(metadata_diagnostics_enabled=True),
    )

    with caplog.at_level("WARNING", logger="lyon.core.metadata"):
        assert metadata.search_album("Missing Artist", "Missing Album") is None

    message = caplog.messages[-1]
    assert "Manual album metadata search returned no metadata." in message
    assert "artist: Missing Artist" in message
    assert "album: Missing Album" in message
    assert "musicbrainz: returned no result" in message
    assert "theaudiodb: returned no result" in message


def test_metadata_diagnostics_logs_cuetools_http_failure(monkeypatch, tmp_path):
    class FakeSettings:
        musicbrainz_app = "LyonTest"
        musicbrainz_version = "1.0"
        musicbrainz_contact = "test@example.invalid"
        metadata_diagnostics_enabled = True
        cuetools_db_metadata_enabled = True
        theaudiodb_api_key = "123"

    class FakeResponse:
        status_code = 403
        reason = "Forbidden"
        content = b"Forbidden"

    monkeypatch.setattr(metadata._settings.Settings, "load", lambda: FakeSettings())
    monkeypatch.setattr(metadata._settings, "app_data_dir", lambda: tmp_path)
    monkeypatch.setattr(metadata, "_metadata_file_handler", None)
    monkeypatch.setattr(metadata.requests, "get", lambda *args, **kwargs: FakeResponse())

    try:
        assert metadata.lookup_cuetools_db_layout("0:15000:45000") is None

        log_text = (tmp_path / metadata.METADATA_DIAGNOSTICS_LOG_NAME).read_text(
            encoding="utf-8"
        )
        assert "CUETools DB exact lookup failed" in log_text
        assert "HTTP 403 Forbidden" in log_text
        assert "layout=0:15000:45000" in log_text
    finally:
        for handler in list(metadata.LOG.handlers):
            if isinstance(handler, metadata.logging.FileHandler):
                metadata.LOG.removeHandler(handler)
                handler.close()
        metadata._metadata_file_handler = None


def test_metadata_diagnostics_logs_empty_disc_provider_summary(monkeypatch, tmp_path):
    class FakeSettings:
        musicbrainz_app = "LyonTest"
        musicbrainz_version = "1.0"
        musicbrainz_contact = "test@example.invalid"
        metadata_diagnostics_enabled = True
        cuetools_db_metadata_enabled = True
        theaudiodb_api_key = "123"

    monkeypatch.setattr(metadata._settings.Settings, "load", lambda: FakeSettings())
    monkeypatch.setattr(metadata._settings, "app_data_dir", lambda: tmp_path)
    monkeypatch.setattr(metadata, "_metadata_file_handler", None)
    monkeypatch.setattr(metadata, "lookup_cuetools_db_disc", lambda *args, **kwargs: None)
    monkeypatch.setattr(metadata, "lookup_musicbrainz_disc", lambda *args, **kwargs: None)

    try:
        assert metadata.lookup_disc("disc-id", "1 1 45150 150", ctdb_toc="0:45000") is None

        log_text = (tmp_path / metadata.METADATA_DIAGNOSTICS_LOG_NAME).read_text(
            encoding="utf-8"
        )
        assert "Album metadata lookup returned no usable metadata." in log_text
        assert "discid: disc-id" in log_text
        assert "cuetools_db: returned no result" in log_text
        assert "musicbrainz: returned no result" in log_text
    finally:
        for handler in list(metadata.LOG.handlers):
            if isinstance(handler, metadata.logging.FileHandler):
                metadata.LOG.removeHandler(handler)
                handler.close()
        metadata._metadata_file_handler = None

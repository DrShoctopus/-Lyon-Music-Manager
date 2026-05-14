import importlib.util
import sys
import types


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


def _stub_settings(monkeypatch) -> None:
    monkeypatch.setattr(
        metadata._settings.Settings,
        "load",
        lambda: types.SimpleNamespace(
            musicbrainz_app="LyonTest",
            musicbrainz_version="1.0",
            musicbrainz_contact="test@example.invalid",
            metadata_diagnostics_enabled=False,
            cuetools_db_metadata_enabled=True,
            theaudiodb_api_key="123",
        ),
    )


def test_lookup_cuetools_db_layout_parses_namespaced_ctdb_metadata(monkeypatch):
    _stub_settings(monkeypatch)
    captured = {}

    class FakeResponse:
        status_code = 200
        content = b"""
        <ctdb xmlns="http://db.cuetools.net/ns/mmd-1.0#" xmlns:ext="http://db.cuetools.net/ns/ext-1.0#">
          <entry />
          <metadata album="Al Hirt&apos;s Greatest Hits" artist="Al Hirt" discnumber="1" id="a0ca62a0-e95a-4b03-96c5-29f16008dfaa" relevance="91" source="musicbrainz">
            <track name="Bourbon Street Parade" />
            <track name="Do You now What It Means To Miss New Orleans" />
            <coverart primary="1" uri="http://coverartarchive.org/release/a0ca62a0-e95a-4b03-96c5-29f16008dfaa/41627707890.jpg" />
          </metadata>
          <metadata album="Greatest Hits" artist="Al Hirt" genre="Jazz" id="jazz/e510c510" relevance="85" source="freedb" year="1990">
            <track name="Bourbon Street Parade" />
          </metadata>
        </ctdb>
        """

    def fake_get(url, params, headers, timeout):
        captured["url"] = url
        captured["params"] = params
        captured["headers"] = headers
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(metadata.requests, "get", fake_get)

    album = metadata.lookup_cuetools_db_layout("0:21053:49278", fuzzy=True)

    assert album is not None
    assert album.artist == "Al Hirt"
    assert album.album == "Al Hirt's Greatest Hits"
    assert album.metadata_source == "cuetools_db:musicbrainz"
    assert album.musicbrainz_albumid == "a0ca62a0-e95a-4b03-96c5-29f16008dfaa"
    assert [track.title for track in album.tracks] == [
        "Bourbon Street Parade",
        "Do You now What It Means To Miss New Orleans",
    ]
    assert album.artwork_url == (
        "http://coverartarchive.org/release/"
        "a0ca62a0-e95a-4b03-96c5-29f16008dfaa/41627707890.jpg"
    )
    assert captured["url"] == metadata.CTDB_LOOKUP_URL
    assert captured["params"]["fuzzy"] == "1"
    assert captured["params"]["toc"] == "0:21053:49278"

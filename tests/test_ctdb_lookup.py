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

from lyon.core import ctdb_lookup, metadata  # noqa: E402


def _stub_settings(monkeypatch) -> None:
    monkeypatch.setattr(
        metadata._settings.Settings,
        "load",
        lambda: types.SimpleNamespace(
            musicbrainz_app="LyonTest",
            musicbrainz_version="1.0",
            musicbrainz_contact="test@example.invalid",
        ),
    )


def test_lookup_ctdb_layout_uses_native_layout_and_parses_metadata(monkeypatch):
    captured = {}
    _stub_settings(monkeypatch)

    class FakeResponse:
        status_code = 200
        content = (
            b'<ctdb><metadata source="musicbrainz" artist="Artist" album="Album">'
            b'<track name="One" /></metadata></ctdb>'
        )

    def fake_get(url, params, headers, timeout):
        captured["url"] = url
        captured["params"] = params
        captured["headers"] = headers
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(ctdb_lookup.requests, "get", fake_get)

    album = ctdb_lookup.lookup_ctdb_layout("0:15000:-30000:45000")

    assert album is not None
    assert album.album == "Album"
    assert album.tracks[0].title == "One"
    assert captured["url"] == metadata.CTDB_LOOKUP_URL
    assert captured["params"]["fuzzy"] == "0"
    assert captured["params"]["toc"] == "0:15000:-30000:45000"
    assert captured["headers"]["User-Agent"] == "LyonTest/1.0 (test@example.invalid)"


def test_lookup_ctdb_layout_allows_fuzzy_lookup(monkeypatch):
    captured = {}
    _stub_settings(monkeypatch)

    class FakeResponse:
        status_code = 200
        content = b'<ctdb><metadata artist="Artist" album="Album" /></ctdb>'

    def fake_get(_url, params, _headers, _timeout):
        captured["params"] = params
        return FakeResponse()

    monkeypatch.setattr(ctdb_lookup.requests, "get", fake_get)

    assert ctdb_lookup.lookup_ctdb_layout("0:45000", fuzzy=True) is not None
    assert captured["params"]["fuzzy"] == "1"


def test_sanitize_ctdb_layout_rejects_data_marker_on_leadout():
    assert ctdb_lookup._sanitize_ctdb_layout("0:-45000") == ""


def test_sanitize_ctdb_layout_normalizes_offsets():
    assert ctdb_lookup._sanitize_ctdb_layout(" 000 : -015000 : 045000 ") == "0:-15000:45000"

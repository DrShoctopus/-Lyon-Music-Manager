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


def test_lookup_ctdb_layout_delegates_to_cuetools_layout_lookup(monkeypatch):
    expected = metadata.AlbumInfo(artist="Artist", album="Album")
    calls = []

    def fake_lookup(layout, fuzzy=False):
        calls.append((layout, fuzzy))
        return expected

    monkeypatch.setattr(ctdb_lookup, "lookup_cuetools_db_layout", fake_lookup)

    assert ctdb_lookup.lookup_ctdb_layout("0:15000:-30000:45000", fuzzy=True) is expected
    assert calls == [("0:15000:-30000:45000", True)]


def test_sanitize_ctdb_layout_rejects_data_marker_on_leadout():
    assert ctdb_lookup._sanitize_ctdb_layout("0:-45000") == ""


def test_sanitize_ctdb_layout_normalizes_offsets():
    assert ctdb_lookup._sanitize_ctdb_layout(" 000 : -015000 : 045000 ") == "0:-15000:45000"

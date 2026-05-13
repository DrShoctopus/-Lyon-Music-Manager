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


def test_lookup_disc_skips_musicbrainz_when_discid_is_missing(monkeypatch):
    calls = []

    def fake_cuetools(toc, ctdb_toc=None):
        calls.append((toc, ctdb_toc))
        return None

    def fail_musicbrainz(*_args, **_kwargs):
        raise AssertionError("MusicBrainz disc lookup needs a disc ID")

    monkeypatch.setattr(metadata, "lookup_cuetools_db_disc", fake_cuetools)
    monkeypatch.setattr(metadata, "lookup_musicbrainz_disc", fail_musicbrainz)

    assert metadata.lookup_disc("", "", ctdb_toc="0:45000", use_cuetools_db=True) is None
    assert calls == [("", "0:45000")]


def test_lookup_musicbrainz_disc_returns_none_without_discid(monkeypatch):
    def fail_init():
        raise AssertionError("MusicBrainz should not initialise without a disc ID")

    monkeypatch.setattr(metadata, "_init", fail_init)

    assert metadata.lookup_musicbrainz_disc("", "") is None

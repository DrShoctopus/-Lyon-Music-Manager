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


def test_lookup_disc_uses_fuzzy_ctdb_after_exact_disc_lookups_miss(monkeypatch):
    fuzzy_album = metadata.AlbumInfo(
        artist="CTDB Artist",
        album="CTDB Album",
        tracks=[metadata.TrackInfo(number=1, title="Found Track")],
        metadata_source="ctdb:musicbrainz",
    )
    calls = []

    def fake_musicbrainz_lookup(discid, toc):
        calls.append(("musicbrainz", discid, toc))
        return None

    def fake_ctdb_lookup(toc, *, fuzzy=False):
        calls.append(("ctdb", toc, fuzzy))
        return fuzzy_album if fuzzy else None

    monkeypatch.setattr(metadata, "lookup_musicbrainz_disc", fake_musicbrainz_lookup)
    monkeypatch.setattr(metadata, "lookup_ctdb_disc", fake_ctdb_lookup)

    assert metadata.lookup_disc("disc-id", "toc-data") is fuzzy_album
    assert calls == [
        ("musicbrainz", "disc-id", "toc-data"),
        ("ctdb", "toc-data", False),
        ("ctdb", "toc-data", True),
    ]

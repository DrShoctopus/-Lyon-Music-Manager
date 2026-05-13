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

from lyon.core.metadata import _musicbrainz_toc_to_ctdb_toc  # noqa: E402


def test_musicbrainz_toc_keeps_nonstandard_first_track_offset_for_ctdb():
    toc = "1 2 45150 450 15150"

    assert _musicbrainz_toc_to_ctdb_toc(toc) == "300:15000:45000"


def test_musicbrainz_toc_rejects_offsets_before_cd_leadin():
    toc = "1 1 45150 149"

    assert _musicbrainz_toc_to_ctdb_toc(toc) == ""

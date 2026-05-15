"""Tests for lyon.core.ctdb_verify — CRC computation and CTDB lookup parsing."""
import struct
import sys
import types
import unittest.mock as mock


def _install_dependency_stubs() -> None:
    if "requests" not in sys.modules:
        req = types.ModuleType("requests")
        req.RequestException = Exception

        class _Session:
            def get(self, *a, **kw):
                raise NotImplementedError

        req.Session = _Session
        sys.modules["requests"] = req


_install_dependency_stubs()

from lyon.core.ctdb_verify import (  # noqa: E402
    TrackVerifyResult,
    _iter_tag,
    compute_accuraterip_v1_crc,
    fetch_ctdb_crcs,
    verify_rips,
)

try:
    import defusedxml.ElementTree as ET
except ImportError:
    import xml.etree.ElementTree as ET


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_pcm(samples: list[int]) -> bytes:
    """Pack a list of uint32 values as little-endian raw PCM."""
    return struct.pack(f"<{len(samples)}I", *samples)


def _pcm_file(tmp_path, samples: list[int], name: str = "track.raw") -> object:
    p = tmp_path / name
    p.write_bytes(_make_pcm(samples))
    return p


# ---------------------------------------------------------------------------
# AccurateRip CRC computation
# ---------------------------------------------------------------------------

def test_crc_simple_non_boundary(monkeypatch, tmp_path):
    # 6 samples, not first/last track — all contribute
    samples = [1, 2, 3, 4, 5, 6]
    expected = sum(s * (i + 1) for i, s in enumerate(samples)) & 0xFFFFFFFF

    def fake_run(cmd, **kwargs):
        r = mock.MagicMock()
        r.stdout = _make_pcm(samples)
        r.returncode = 0
        return r

    monkeypatch.setattr("subprocess.run", fake_run)
    assert compute_accuraterip_v1_crc("f.flac", "ffmpeg", is_first_track=False, is_last_track=False) == expected


def test_crc_first_track_skips_leading_samples(monkeypatch):
    skip = 2940
    n = skip + 10
    samples = list(range(1, n + 1))
    # Only samples[2940:] contribute, but multiplier is still 1-based from index 0
    expected = sum(samples[i] * (i + 1) for i in range(skip, n)) & 0xFFFFFFFF

    def fake_run(cmd, **kwargs):
        r = mock.MagicMock()
        r.stdout = _make_pcm(samples)
        return r

    monkeypatch.setattr("subprocess.run", fake_run)
    assert compute_accuraterip_v1_crc("f.flac", "ffmpeg", is_first_track=True, is_last_track=False) == expected


def test_crc_last_track_skips_trailing_samples(monkeypatch):
    skip = 2940
    n = skip + 10
    samples = list(range(1, n + 1))
    end = n - skip
    expected = sum(samples[i] * (i + 1) for i in range(0, end)) & 0xFFFFFFFF

    def fake_run(cmd, **kwargs):
        r = mock.MagicMock()
        r.stdout = _make_pcm(samples)
        return r

    monkeypatch.setattr("subprocess.run", fake_run)
    assert compute_accuraterip_v1_crc("f.flac", "ffmpeg", is_first_track=False, is_last_track=True) == expected


def test_crc_returns_none_on_empty_stdout(monkeypatch):
    def fake_run(cmd, **kwargs):
        r = mock.MagicMock()
        r.stdout = b""
        return r

    monkeypatch.setattr("subprocess.run", fake_run)
    assert compute_accuraterip_v1_crc("f.flac", "ffmpeg", is_first_track=False, is_last_track=False) is None


def test_crc_returns_none_on_subprocess_error(monkeypatch):
    import subprocess

    def fake_run(cmd, **kwargs):
        raise subprocess.SubprocessError("boom")

    monkeypatch.setattr("subprocess.run", fake_run)
    assert compute_accuraterip_v1_crc("f.flac", "ffmpeg", is_first_track=False, is_last_track=False) is None


def test_crc_wraps_at_32_bits(monkeypatch):
    # Use a large sample value to force overflow past 2^32
    samples = [0xFFFFFFFF] * 5
    expected = sum(0xFFFFFFFF * (i + 1) for i in range(5)) & 0xFFFFFFFF

    def fake_run(cmd, **kwargs):
        r = mock.MagicMock()
        r.stdout = _make_pcm(samples)
        return r

    monkeypatch.setattr("subprocess.run", fake_run)
    result = compute_accuraterip_v1_crc("f.flac", "ffmpeg", is_first_track=False, is_last_track=False)
    assert result == expected
    assert 0 <= result <= 0xFFFFFFFF


# ---------------------------------------------------------------------------
# CTDB CRC fetch
# ---------------------------------------------------------------------------

def _xml_response(entries: list[tuple[int, list[tuple[int, str]]]]) -> bytes:
    """Build a minimal CTDB ctdb=1 XML response.

    *entries* is a list of (confidence, [(track_id, crc_hex), ...]).
    """
    parts = ['<ctdb version="3">']
    for confidence, tracks in entries:
        parts.append(f'  <entry confidence="{confidence}">')
        for tid, crc in tracks:
            parts.append(f'    <track id="{tid}" CRC="{crc}"/>')
        parts.append("  </entry>")
    parts.append("</ctdb>")
    return "\n".join(parts).encode()


def test_fetch_ctdb_crcs_parses_entries(monkeypatch):
    xml = _xml_response([(50, [(1, "AABBCCDD"), (2, "11223344")])])

    session = mock.MagicMock()
    session.get.return_value = mock.MagicMock(
        status_code=200,
        content=xml,
    )

    result = fetch_ctdb_crcs("0:15000:45000", session=session)
    assert result is not None
    assert result[1] == [(0xAABBCCDD, 50)]
    assert result[2] == [(0x11223344, 50)]


def test_fetch_ctdb_crcs_merges_multiple_entries(monkeypatch):
    xml = _xml_response([
        (50, [(1, "AABBCCDD")]),
        (10, [(1, "DEADBEEF")]),
    ])

    session = mock.MagicMock()
    session.get.return_value = mock.MagicMock(status_code=200, content=xml)

    result = fetch_ctdb_crcs("0:15000:45000", session=session)
    assert result is not None
    assert len(result[1]) == 2
    crcs = {crc for crc, _ in result[1]}
    assert crcs == {0xAABBCCDD, 0xDEADBEEF}


def test_fetch_ctdb_crcs_returns_none_on_http_error(monkeypatch):
    session = mock.MagicMock()
    session.get.return_value = mock.MagicMock(status_code=503, content=b"")
    assert fetch_ctdb_crcs("0:15000:45000", session=session) is None


def test_fetch_ctdb_crcs_returns_none_on_network_error(monkeypatch):
    import requests as req

    session = mock.MagicMock()
    session.get.side_effect = req.RequestException("timeout")
    assert fetch_ctdb_crcs("0:15000:45000", session=session) is None


def test_fetch_ctdb_crcs_returns_none_on_bad_xml(monkeypatch):
    session = mock.MagicMock()
    session.get.return_value = mock.MagicMock(status_code=200, content=b"not xml <<<")
    assert fetch_ctdb_crcs("0:15000:45000", session=session) is None


def test_fetch_ctdb_crcs_returns_none_for_empty_toc():
    assert fetch_ctdb_crcs("") is None


def test_fetch_ctdb_crcs_handles_namespace_in_tags(monkeypatch):
    xml = (
        b'<ctdb xmlns="http://db.cuetools.net/ns/mmd-1.0#">'
        b'<entry confidence="20">'
        b'<track id="1" CRC="CAFEBABE"/>'
        b"</entry>"
        b"</ctdb>"
    )
    session = mock.MagicMock()
    session.get.return_value = mock.MagicMock(status_code=200, content=xml)

    result = fetch_ctdb_crcs("0:15000:45000", session=session)
    assert result is not None
    assert result[1] == [(0xCAFEBABE, 20)]


# ---------------------------------------------------------------------------
# verify_rips integration
# ---------------------------------------------------------------------------

def _patched_crc(crc_map: dict[int, int | None]):
    """Return a monkeypatched compute_accuraterip_v1_crc that returns from map."""
    import lyon.core.ctdb_verify as mod

    def fake_crc(path, ffmpeg, *, is_first_track, is_last_track):
        track_no = int(str(path).split("_")[-1].replace(".flac", ""))
        return crc_map.get(track_no)

    return mock.patch.object(mod, "compute_accuraterip_v1_crc", side_effect=fake_crc)


def _patched_fetch(result):
    import lyon.core.ctdb_verify as mod
    return mock.patch.object(mod, "fetch_ctdb_crcs", return_value=result)


def _files(track_nos: list[int]) -> dict[int, object]:
    return {n: f"track_{n}.flac" for n in track_nos}


def test_verify_rips_all_match():
    files = _files([1, 2])
    ctdb = {1: [(0xAAAA, 30)], 2: [(0xBBBB, 30)]}
    crcs = {1: 0xAAAA, 2: 0xBBBB}

    with _patched_fetch(ctdb), _patched_crc(crcs):
        results = verify_rips(files, "0:15000:45000", "ffmpeg", 2)

    assert len(results) == 2
    assert all(r.verified for r in results)
    assert results[0].confidence == 30


def test_verify_rips_crc_mismatch():
    files = _files([1])
    ctdb = {1: [(0xAAAA, 10)]}
    crcs = {1: 0xBBBB}

    with _patched_fetch(ctdb), _patched_crc(crcs):
        results = verify_rips(files, "0:15000:45000", "ffmpeg", 1)

    assert len(results) == 1
    assert not results[0].verified
    assert "mismatch" in results[0].message


def test_verify_rips_not_in_db():
    files = _files([1])
    ctdb: dict = {}  # no entries at all

    with _patched_fetch(ctdb), _patched_crc({1: 0xAAAA}):
        results = verify_rips(files, "0:15000:45000", "ffmpeg", 1)

    assert not results[0].verified
    assert "no reference" in results[0].message


def test_verify_rips_ctdb_unreachable():
    files = _files([1, 2])

    with _patched_fetch(None):
        results = verify_rips(files, "0:15000:45000", "ffmpeg", 2)

    assert len(results) == 2
    assert all(not r.verified for r in results)
    assert "unreachable" in results[0].message


def test_verify_rips_skips_when_no_ctdb_toc():
    assert verify_rips(_files([1]), "", "ffmpeg", 1) == []


def test_verify_rips_skips_when_no_files():
    assert verify_rips({}, "0:15000:45000", "ffmpeg", 0) == []


def test_verify_rips_crc_decode_failure():
    files = _files([1])
    ctdb = {1: [(0xAAAA, 5)]}

    with _patched_fetch(ctdb), _patched_crc({1: None}):
        results = verify_rips(files, "0:15000:45000", "ffmpeg", 1)

    assert not results[0].verified
    assert "ffmpeg decode failed" in results[0].message


# ---------------------------------------------------------------------------
# _iter_tag helper
# ---------------------------------------------------------------------------

def test_iter_tag_strips_namespace():
    xml = ET.fromstring(
        '<root xmlns="http://example.com/ns">'
        "<child/><child/><other/>"
        "</root>"
    )
    children = list(_iter_tag(xml, "child"))
    assert len(children) == 2


def test_iter_tag_no_namespace():
    xml = ET.fromstring("<root><item/><item/></root>")
    assert len(list(_iter_tag(xml, "item"))) == 2

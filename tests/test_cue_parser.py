"""Tests for lyon/core/cue_parser.py."""
from pathlib import Path

import pytest
from lyon.core.cue_parser import CueSheet, _parse_sectors, _unquote, parse_cue

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _write_cue(tmp_path: Path, content: str, name: str = "album.cue") -> Path:
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return p


def _touch_image(tmp_path: Path, name: str = "album.flac") -> Path:
    p = tmp_path / name
    p.write_bytes(b"\x00" * 16)
    return p


# ---------------------------------------------------------------------------
# _parse_sectors
# ---------------------------------------------------------------------------

def test_parse_sectors_zero():
    assert _parse_sectors("00:00:00") == 0


def test_parse_sectors_minutes():
    # 1 min = 60 sec × 75 frames
    assert _parse_sectors("01:00:00") == 4500


def test_parse_sectors_frames():
    assert _parse_sectors("00:00:37") == 37


def test_parse_sectors_mixed():
    # 3:45:20 => (3*60 + 45)*75 + 20 = 225*75 + 20 = 16875 + 20
    assert _parse_sectors("03:45:20") == 16895


def test_parse_sectors_invalid():
    with pytest.raises(ValueError):
        _parse_sectors("bad")


# ---------------------------------------------------------------------------
# _unquote
# ---------------------------------------------------------------------------

def test_unquote_strips_double_quotes():
    assert _unquote('"Hello World"') == "Hello World"


def test_unquote_no_quotes_unchanged():
    assert _unquote("Hello") == "Hello"


def test_unquote_strips_whitespace():
    assert _unquote('  "Test"  ') == "Test"


# ---------------------------------------------------------------------------
# parse_cue — basic structure
# ---------------------------------------------------------------------------

CUE_BASIC = """\
REM GENRE Rock
PERFORMER "The Artist"
TITLE "The Album"
FILE "album.flac" WAVE
  TRACK 01 AUDIO
    TITLE "Track One"
    PERFORMER "The Artist"
    INDEX 01 00:00:00
  TRACK 02 AUDIO
    TITLE "Track Two"
    INDEX 01 03:45:20
  TRACK 03 AUDIO
    TITLE "Track Three"
    INDEX 01 07:12:00
"""


def test_parse_cue_returns_sheet(tmp_path):
    _touch_image(tmp_path, "album.flac")
    cue = _write_cue(tmp_path, CUE_BASIC)
    sheet = parse_cue(cue)
    assert sheet is not None
    assert isinstance(sheet, CueSheet)


def test_parse_cue_album_metadata(tmp_path):
    _touch_image(tmp_path, "album.flac")
    cue = _write_cue(tmp_path, CUE_BASIC)
    sheet = parse_cue(cue)
    assert sheet.album == "The Album"
    assert sheet.performer == "The Artist"


def test_parse_cue_track_count(tmp_path):
    _touch_image(tmp_path, "album.flac")
    cue = _write_cue(tmp_path, CUE_BASIC)
    sheet = parse_cue(cue)
    assert len(sheet.tracks) == 3


def test_parse_cue_track_titles(tmp_path):
    _touch_image(tmp_path, "album.flac")
    cue = _write_cue(tmp_path, CUE_BASIC)
    sheet = parse_cue(cue)
    assert [t.title for t in sheet.tracks] == ["Track One", "Track Two", "Track Three"]


def test_parse_cue_start_sectors(tmp_path):
    _touch_image(tmp_path, "album.flac")
    cue = _write_cue(tmp_path, CUE_BASIC)
    sheet = parse_cue(cue)
    assert sheet.tracks[0].start_sectors == 0
    assert sheet.tracks[1].start_sectors == 16895  # 03:45:20
    assert sheet.tracks[2].start_sectors == _parse_sectors("07:12:00")


def test_parse_cue_end_sectors_filled(tmp_path):
    _touch_image(tmp_path, "album.flac")
    cue = _write_cue(tmp_path, CUE_BASIC)
    sheet = parse_cue(cue)
    # end of track 1 == start of track 2
    assert sheet.tracks[0].end_sectors == sheet.tracks[1].start_sectors
    assert sheet.tracks[1].end_sectors == sheet.tracks[2].start_sectors
    # last track has no end
    assert sheet.tracks[2].end_sectors is None


def test_parse_cue_track_numbers(tmp_path):
    _touch_image(tmp_path, "album.flac")
    cue = _write_cue(tmp_path, CUE_BASIC)
    sheet = parse_cue(cue)
    assert [t.number for t in sheet.tracks] == [1, 2, 3]


# ---------------------------------------------------------------------------
# parse_cue — image path resolution
# ---------------------------------------------------------------------------

def test_parse_cue_resolves_relative_image_path(tmp_path):
    _touch_image(tmp_path, "album.flac")
    cue = _write_cue(tmp_path, CUE_BASIC)
    sheet = parse_cue(cue)
    assert sheet.image_path is not None
    assert sheet.image_path == (tmp_path / "album.flac").resolve()


def test_parse_cue_image_not_found_is_none(tmp_path):
    # No image file on disk
    cue = _write_cue(tmp_path, CUE_BASIC)
    sheet = parse_cue(cue)
    assert sheet is not None     # tracks still parsed
    assert sheet.image_path is None


def test_parse_cue_image_path_absolute(tmp_path):
    img = _touch_image(tmp_path, "absolute.flac")
    content = CUE_BASIC.replace('"album.flac"', f'"{img}"')
    cue = _write_cue(tmp_path, content)
    sheet = parse_cue(cue)
    assert sheet.image_path == img.resolve()


# ---------------------------------------------------------------------------
# parse_cue — edge cases
# ---------------------------------------------------------------------------

def test_parse_cue_no_tracks_returns_none(tmp_path):
    cue = _write_cue(tmp_path, 'TITLE "Empty"\nPERFORMER "Nobody"\n')
    assert parse_cue(cue) is None


def test_parse_cue_missing_file_returns_none(tmp_path):
    assert parse_cue(tmp_path / "nonexistent.cue") is None


def test_parse_cue_bom_utf8(tmp_path):
    _touch_image(tmp_path, "album.flac")
    cue = tmp_path / "bom.cue"
    cue.write_bytes(b"\xef\xbb\xbf" + CUE_BASIC.encode("utf-8"))
    sheet = parse_cue(cue)
    assert sheet is not None
    assert sheet.album == "The Album"


def test_parse_cue_latin1_encoding(tmp_path):
    _touch_image(tmp_path, "album.flac")
    content = 'TITLE "Ré"\nFILE "album.flac" WAVE\n  TRACK 01 AUDIO\n    INDEX 01 00:00:00\n'
    cue = tmp_path / "latin1.cue"
    cue.write_bytes(content.encode("latin-1"))
    sheet = parse_cue(cue)
    assert sheet is not None
    assert "R" in sheet.album


def test_parse_cue_multifile_stops_at_first_file(tmp_path):
    _touch_image(tmp_path, "disc1.flac")
    _touch_image(tmp_path, "disc2.flac")
    content = (
        'TITLE "Multi"\nPERFORMER "X"\n'
        'FILE "disc1.flac" WAVE\n'
        '  TRACK 01 AUDIO\n    TITLE "T1"\n    INDEX 01 00:00:00\n'
        'FILE "disc2.flac" WAVE\n'
        '  TRACK 02 AUDIO\n    TITLE "T2"\n    INDEX 01 00:00:00\n'
    )
    cue = _write_cue(tmp_path, content)
    sheet = parse_cue(cue)
    assert sheet is not None
    # Only the track from the first FILE should be present
    assert len(sheet.tracks) == 1
    assert sheet.tracks[0].title == "T1"


def test_parse_cue_isrc_captured(tmp_path):
    _touch_image(tmp_path, "album.flac")
    content = (
        'TITLE "X"\nFILE "album.flac" WAVE\n'
        '  TRACK 01 AUDIO\n    ISRC USRC12345678\n    INDEX 01 00:00:00\n'
    )
    cue = _write_cue(tmp_path, content)
    sheet = parse_cue(cue)
    assert sheet.tracks[0].isrc == "USRC12345678"


def test_parse_cue_track_performer_overrides_album(tmp_path):
    _touch_image(tmp_path, "album.flac")
    content = (
        'PERFORMER "Album Artist"\nTITLE "VA"\nFILE "album.flac" WAVE\n'
        '  TRACK 01 AUDIO\n    TITLE "T1"\n    PERFORMER "Track Artist"\n    INDEX 01 00:00:00\n'
    )
    cue = _write_cue(tmp_path, content)
    sheet = parse_cue(cue)
    assert sheet.performer == "Album Artist"
    assert sheet.tracks[0].performer == "Track Artist"

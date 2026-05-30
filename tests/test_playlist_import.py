"""Tests for M3U / PLS playlist import (lyon/core/playlist_import.py)."""
from pathlib import Path

import pytest
from lyon.core.library import Library
from lyon.core.playlist_import import ImportResult, import_playlist, parse_m3u, parse_pls


def _add_track(library: Library, path: str) -> None:
    library.conn.execute(
        "INSERT INTO tracks "
        "(path, title, artist, album_artist, album, track_no, disc_no, year, genre, duration, bitrate, samplerate) "
        "VALUES (?, ?, '', '', '', 1, 1, 0, '', 120.0, 320000, 44100)",
        (path, Path(path).stem),
    )
    library.conn.commit()


# ---------------------------------------------------------------------------
# parse_m3u
# ---------------------------------------------------------------------------

def test_parse_m3u_skips_comments_and_blank_lines(tmp_path):
    m3u = tmp_path / "test.m3u"
    m3u.write_text(
        "#EXTM3U\n"
        "#EXTINF:120,Artist - Title\n"
        "/music/track1.flac\n"
        "\n"
        "# stray comment\n"
        "/music/track2.mp3\n",
        encoding="utf-8",
    )
    assert parse_m3u(m3u) == ["/music/track1.flac", "/music/track2.mp3"]


def test_parse_m3u_resolves_relative_paths(tmp_path):
    m3u = tmp_path / "playlist.m3u"
    m3u.write_text("track1.flac\n../other/track2.flac\n", encoding="utf-8")
    result = parse_m3u(m3u)
    assert result[0] == str((tmp_path / "track1.flac").resolve())
    assert result[1] == str((tmp_path.parent / "other" / "track2.flac").resolve())


def test_parse_m3u_handles_bom(tmp_path):
    m3u = tmp_path / "bom.m3u"
    m3u.write_bytes(b"\xef\xbb\xbf#EXTM3U\n/music/a.flac\n")  # UTF-8 BOM
    assert parse_m3u(m3u) == ["/music/a.flac"]


def test_parse_m3u_empty_file(tmp_path):
    m3u = tmp_path / "empty.m3u"
    m3u.write_text("#EXTM3U\n", encoding="utf-8")
    assert parse_m3u(m3u) == []


# ---------------------------------------------------------------------------
# parse_pls
# ---------------------------------------------------------------------------

def test_parse_pls_extracts_file_entries(tmp_path):
    pls = tmp_path / "test.pls"
    pls.write_text(
        "[playlist]\n"
        "File1=/music/track1.flac\n"
        "Title1=Track 1\n"
        "Length1=120\n"
        "File2=/music/track2.mp3\n"
        "NumberOfEntries=2\n"
        "Version=2\n",
        encoding="utf-8",
    )
    assert parse_pls(pls) == ["/music/track1.flac", "/music/track2.mp3"]


def test_parse_pls_ignores_non_file_keys(tmp_path):
    pls = tmp_path / "test.pls"
    pls.write_text(
        "[playlist]\nFile1=/music/a.flac\nfilename=/should/be/ignored\nFile2=/music/b.flac\n",
        encoding="utf-8",
    )
    # "filename" has letters after "file" that are not digits — should be skipped
    assert parse_pls(pls) == ["/music/a.flac", "/music/b.flac"]


def test_parse_pls_case_insensitive_keys(tmp_path):
    pls = tmp_path / "test.pls"
    pls.write_text("FILE1=/music/a.flac\nfile2=/music/b.flac\n", encoding="utf-8")
    assert parse_pls(pls) == ["/music/a.flac", "/music/b.flac"]


def test_parse_pls_empty(tmp_path):
    pls = tmp_path / "empty.pls"
    pls.write_text("[playlist]\nNumberOfEntries=0\n", encoding="utf-8")
    assert parse_pls(pls) == []


# ---------------------------------------------------------------------------
# import_playlist
# ---------------------------------------------------------------------------

def test_import_matches_tracks_and_reports_unmatched(tmp_path):
    library = Library(tmp_path / "lib.db")
    _add_track(library, "/music/a.flac")
    _add_track(library, "/music/b.mp3")

    m3u = tmp_path / "mix.m3u"
    m3u.write_text(
        "#EXTM3U\n/music/a.flac\n/music/b.mp3\n/music/missing.flac\n",
        encoding="utf-8",
    )
    result = import_playlist(library, m3u)

    assert result.matched == 2
    assert result.unmatched == ["/music/missing.flac"]
    tracks = library.playlist_tracks(result.playlist_id)
    assert [t.path for t in tracks] == ["/music/a.flac", "/music/b.mp3"]


def test_import_preserves_m3u_order(tmp_path):
    library = Library(tmp_path / "lib.db")
    for i in range(5):
        _add_track(library, f"/music/track{i}.flac")

    order = [4, 2, 0, 3, 1]
    m3u = tmp_path / "ordered.m3u"
    m3u.write_text("\n".join(f"/music/track{i}.flac" for i in order) + "\n", encoding="utf-8")

    result = import_playlist(library, m3u)
    tracks = library.playlist_tracks(result.playlist_id)
    assert [t.path for t in tracks] == [f"/music/track{i}.flac" for i in order]


def test_import_names_playlist_after_file_stem(tmp_path):
    library = Library(tmp_path / "lib.db")
    m3u = tmp_path / "Summer Vibes.m3u"
    m3u.write_text("#EXTM3U\n", encoding="utf-8")

    import_playlist(library, m3u)
    playlists = library.all_playlists()
    assert any(p.name == "Summer Vibes" for p in playlists)


def test_import_pls_file(tmp_path):
    library = Library(tmp_path / "lib.db")
    _add_track(library, "/music/song.flac")

    pls = tmp_path / "mix.pls"
    pls.write_text("[playlist]\nFile1=/music/song.flac\nNumberOfEntries=1\n", encoding="utf-8")

    result = import_playlist(library, pls)
    assert result.matched == 1
    assert result.unmatched == []
    assert len(library.playlist_tracks(result.playlist_id)) == 1


def test_import_empty_playlist(tmp_path):
    library = Library(tmp_path / "lib.db")
    m3u = tmp_path / "empty.m3u"
    m3u.write_text("#EXTM3U\n", encoding="utf-8")

    result = import_playlist(library, m3u)
    assert result.matched == 0
    assert result.unmatched == []
    assert result.playlist_id is not None


def test_import_all_unmatched(tmp_path):
    library = Library(tmp_path / "lib.db")
    m3u = tmp_path / "ghost.m3u"
    m3u.write_text("/no/such/track.flac\n/also/missing.mp3\n", encoding="utf-8")

    result = import_playlist(library, m3u)
    assert result.matched == 0
    assert len(result.unmatched) == 2
    assert library.playlist_tracks(result.playlist_id) == []


def test_import_unsupported_format_raises(tmp_path):
    library = Library(tmp_path / "lib.db")
    wpl = tmp_path / "list.wpl"
    wpl.write_text("<smil></smil>", encoding="utf-8")

    with pytest.raises(ValueError, match="Unsupported playlist format"):
        import_playlist(library, wpl)


def test_import_result_is_dataclass():
    r = ImportResult(playlist_id=1, matched=3, unmatched=["/x.flac"])
    assert r.playlist_id == 1
    assert r.matched == 3
    assert r.unmatched == ["/x.flac"]

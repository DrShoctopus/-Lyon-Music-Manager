"""Tests for CUE sheet indexing (2.4) and file-hash duplicate detection (2.6)."""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from lyon.core import library as library_module
from lyon.core.library import Library, _compute_file_hash


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _add_audio_track(library: Library, path: str, bitrate: int = 320000) -> None:
    library.conn.execute(
        "INSERT INTO tracks "
        "(path, title, artist, album_artist, album, track_no, disc_no, year, genre, "
        " duration, bitrate, samplerate, media_type) "
        "VALUES (?, ?, 'Artist', 'Artist', 'Album', 1, 1, 0, '', 120.0, ?, 44100, 'audio')",
        (path, Path(path).stem, bitrate),
    )
    library.conn.commit()


def _write_cue(tmp_path: Path, tracks: list[str], image: str = "album.flac") -> Path:
    """Write a minimal CUE file referencing *image* with one track per entry in *tracks*."""
    lines = [f'TITLE "Test Album"', f'PERFORMER "Test Artist"', f'FILE "{image}" WAVE']
    for i, title in enumerate(tracks, 1):
        mm = (i - 1) * 3
        lines.append(f"  TRACK {i:02d} AUDIO")
        lines.append(f'    TITLE "{title}"')
        lines.append(f"    INDEX 01 {mm:02d}:00:00")
    cue = tmp_path / "album.cue"
    cue.write_text("\n".join(lines), encoding="utf-8")
    return cue


def _write_image(tmp_path: Path, name: str = "album.flac") -> Path:
    p = tmp_path / name
    p.write_bytes(b"\xff\xf3" + b"\x00" * 62)  # plausible audio header
    return p


# ===========================================================================
# 2.6 — file_hash helpers
# ===========================================================================

def test_compute_file_hash_returns_md5_hex(tmp_path):
    f = tmp_path / "a.flac"
    f.write_bytes(b"hello world")
    result = _compute_file_hash(str(f))
    assert result == hashlib.md5(b"hello world").hexdigest()


def test_compute_file_hash_reads_at_most_64k(tmp_path):
    data = b"x" * 131072  # 128 KB
    f = tmp_path / "big.flac"
    f.write_bytes(data)
    result = _compute_file_hash(str(f))
    assert result == hashlib.md5(data[:65536]).hexdigest()


def test_compute_file_hash_missing_file_returns_none(tmp_path):
    assert _compute_file_hash(str(tmp_path / "no_such.flac")) is None


# ===========================================================================
# 2.6 — file_hash stored during index_file
# ===========================================================================

def test_index_file_stores_hash_for_audio(tmp_path, monkeypatch):
    audio = tmp_path / "song.flac"
    audio.write_bytes(b"FLAC" + b"\x00" * 60)

    class _FakeInfo:
        length = 60.0
        bitrate = 320000
        sample_rate = 44100

    class _FakeAudio(dict):
        info = _FakeInfo()
        def get(self, key):  # noqa: D102
            return {"title": ["Song"], "artist": ["A"], "albumartist": ["A"],
                    "album": ["B"], "tracknumber": ["1"], "discnumber": ["1"],
                    "date": ["2024"], "genre": ["Rock"]}.get(key)

    monkeypatch.setattr(library_module, "MutagenFile", lambda *a, **k: _FakeAudio())
    library = Library(tmp_path / "lib.db")
    library.index_file(str(audio))

    row = library.conn.execute(
        "SELECT file_hash FROM tracks WHERE path = ?", (str(audio),)
    ).fetchone()
    expected = _compute_file_hash(str(audio))
    assert row["file_hash"] == expected


def test_index_file_no_hash_for_video(tmp_path, monkeypatch):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"\x00" * 64)
    monkeypatch.setattr(library_module, "MutagenFile", lambda *a, **k: None)

    library = Library(tmp_path / "lib.db")
    library.index_file(str(video))

    row = library.conn.execute(
        "SELECT file_hash FROM tracks WHERE path = ?", (str(video),)
    ).fetchone()
    assert row is None or row["file_hash"] is None


# ===========================================================================
# 2.6 — find_duplicates_by_hash
# ===========================================================================

def test_find_duplicates_by_hash_finds_exact_copies(tmp_path):
    library = Library(tmp_path / "lib.db")
    # Two rows with the same hash
    for path in ["/music/copy_a.flac", "/music/copy_b.flac"]:
        library.conn.execute(
            "INSERT INTO tracks (path, title, artist, album_artist, album, track_no, "
            "disc_no, year, genre, duration, bitrate, samplerate, media_type, file_hash) "
            "VALUES (?,?,?,?,?,1,1,0,'',120.0,320000,44100,'audio','aabbcc')",
            (path, Path(path).stem, "A", "A", "B"),
        )
    library.conn.commit()

    groups = library.find_duplicates_by_hash()
    assert len(groups) == 1
    assert len(groups[0]) == 2
    paths = {t.path for t in groups[0]}
    assert paths == {"/music/copy_a.flac", "/music/copy_b.flac"}


def test_find_duplicates_by_hash_ignores_null_hash(tmp_path):
    library = Library(tmp_path / "lib.db")
    # Two rows with NULL hash (e.g. unscanned files)
    for path in ["/music/a.flac", "/music/b.flac"]:
        library.conn.execute(
            "INSERT INTO tracks (path, title, artist, album_artist, album, track_no, "
            "disc_no, year, genre, duration, bitrate, samplerate, media_type, file_hash) "
            "VALUES (?,?,?,?,?,1,1,0,'',120.0,320000,44100,'audio',NULL)",
            (path, Path(path).stem, "A", "A", "B"),
        )
    library.conn.commit()

    assert library.find_duplicates_by_hash() == []


def test_find_duplicates_by_hash_groups_ordered_by_bitrate(tmp_path):
    library = Library(tmp_path / "lib.db")
    for path, br in [("/music/lo.flac", 128000), ("/music/hi.flac", 320000)]:
        library.conn.execute(
            "INSERT INTO tracks (path, title, artist, album_artist, album, track_no, "
            "disc_no, year, genre, duration, bitrate, samplerate, media_type, file_hash) "
            "VALUES (?,?,?,?,?,1,1,0,'',120.0,?  ,44100,'audio','deadbeef')",
            (path, Path(path).stem, "A", "A", "B", br),
        )
    library.conn.commit()

    groups = library.find_duplicates_by_hash()
    assert groups[0][0].path == "/music/hi.flac"  # highest bitrate first


def test_find_duplicates_by_hash_excludes_cue_tracks(tmp_path):
    library = Library(tmp_path / "lib.db")
    library.conn.execute(
        "INSERT INTO tracks (path, title, artist, album_artist, album, track_no, "
        "disc_no, year, genre, duration, bitrate, samplerate, media_type, file_hash) "
        "VALUES ('/cue.flac::1',?,?,?,?,1,1,0,'',120.0,320000,44100,'cue_track','aabbcc')",
        ("T", "A", "A", "B"),
    )
    library.conn.execute(
        "INSERT INTO tracks (path, title, artist, album_artist, album, track_no, "
        "disc_no, year, genre, duration, bitrate, samplerate, media_type, file_hash) "
        "VALUES ('/cue.flac::2',?,?,?,?,2,1,0,'',120.0,320000,44100,'cue_track','aabbcc')",
        ("T2", "A", "A", "B"),
    )
    library.conn.commit()
    assert library.find_duplicates_by_hash() == []


# ===========================================================================
# 2.4 — CUE sheet indexing via _index_cue_file
# ===========================================================================

def test_index_cue_file_creates_track_rows(tmp_path):
    _write_image(tmp_path)
    _write_cue(tmp_path, ["Track One", "Track Two", "Track Three"])
    library = Library(tmp_path / "lib.db")
    summary = library._index_cue_file(str(tmp_path / "album.cue"))

    assert summary.added == 3
    rows = library.conn.execute(
        "SELECT * FROM tracks WHERE media_type = 'cue_track'"
    ).fetchall()
    assert len(rows) == 3


def test_index_cue_file_track_paths_use_double_colon(tmp_path):
    _write_image(tmp_path)
    cue = _write_cue(tmp_path, ["A", "B"])
    library = Library(tmp_path / "lib.db")
    library._index_cue_file(str(cue))

    paths = {
        row["path"]
        for row in library.conn.execute(
            "SELECT path FROM tracks WHERE media_type = 'cue_track'"
        ).fetchall()
    }
    assert paths == {f"{cue}::1", f"{cue}::2"}


def test_index_cue_file_sets_cue_image_path(tmp_path):
    img = _write_image(tmp_path)
    cue = _write_cue(tmp_path, ["T1"])
    library = Library(tmp_path / "lib.db")
    library._index_cue_file(str(cue))

    row = library.conn.execute(
        "SELECT cue_image_path, cue_offset_sectors FROM tracks WHERE media_type='cue_track'"
    ).fetchone()
    assert row["cue_image_path"] == str(img.resolve())
    assert row["cue_offset_sectors"] == 0


def test_index_cue_file_second_track_offset(tmp_path):
    _write_image(tmp_path)
    # Track 2 starts at 03:45:20
    cue = tmp_path / "album.cue"
    cue.write_text(
        'TITLE "A"\nFILE "album.flac" WAVE\n'
        '  TRACK 01 AUDIO\n    TITLE "T1"\n    INDEX 01 00:00:00\n'
        '  TRACK 02 AUDIO\n    TITLE "T2"\n    INDEX 01 03:45:20\n',
        encoding="utf-8",
    )
    library = Library(tmp_path / "lib.db")
    library._index_cue_file(str(cue))

    row = library.conn.execute(
        "SELECT cue_offset_sectors FROM tracks WHERE path = ?",
        (f"{cue}::2",),
    ).fetchone()
    from lyon.core.cue_parser import _parse_sectors
    assert row["cue_offset_sectors"] == _parse_sectors("03:45:20")


def test_index_cue_file_unchanged_on_rescan(tmp_path):
    _write_image(tmp_path)
    cue = _write_cue(tmp_path, ["T1", "T2"])
    library = Library(tmp_path / "lib.db")
    library._index_cue_file(str(cue))
    summary = library._index_cue_file(str(cue))  # second scan, file unchanged

    assert summary.added == 0
    assert summary.unchanged == 2


def test_index_cue_file_updates_on_cue_change(tmp_path):
    _write_image(tmp_path)
    cue = _write_cue(tmp_path, ["T1", "T2"])
    library = Library(tmp_path / "lib.db")
    library._index_cue_file(str(cue))

    # Rewrite CUE with different content and bump mtime
    import time, os
    time.sleep(0.01)
    cue.write_text(
        'TITLE "Changed"\nFILE "album.flac" WAVE\n'
        '  TRACK 01 AUDIO\n    TITLE "New Title"\n    INDEX 01 00:00:00\n',
        encoding="utf-8",
    )
    os.utime(cue, ns=(int(time.time_ns()), int(time.time_ns())))

    summary = library._index_cue_file(str(cue), force=True)
    assert summary.updated >= 1


def test_index_cue_file_removes_orphaned_tracks(tmp_path):
    _write_image(tmp_path)
    cue = _write_cue(tmp_path, ["T1", "T2", "T3"])
    library = Library(tmp_path / "lib.db")
    library._index_cue_file(str(cue))

    # Rewrite with only 2 tracks
    import time, os
    cue.write_text(
        'TITLE "A"\nFILE "album.flac" WAVE\n'
        '  TRACK 01 AUDIO\n    TITLE "T1"\n    INDEX 01 00:00:00\n'
        '  TRACK 02 AUDIO\n    TITLE "T2"\n    INDEX 01 03:00:00\n',
        encoding="utf-8",
    )
    os.utime(cue, ns=(int(time.time_ns()), int(time.time_ns())))
    library._index_cue_file(str(cue), force=True)

    count = library.conn.execute(
        "SELECT COUNT(*) FROM tracks WHERE media_type = 'cue_track'"
    ).fetchone()[0]
    assert count == 2


def test_index_cue_file_skips_nonexistent_cue(tmp_path):
    library = Library(tmp_path / "lib.db")
    summary = library._index_cue_file(str(tmp_path / "ghost.cue"))
    assert summary.failed == 1


# ===========================================================================
# 2.4 — _row_to_track populates playback fields for CUE tracks
# ===========================================================================

def test_row_to_track_sets_playback_uri_for_cue(tmp_path):
    img = _write_image(tmp_path)
    cue = _write_cue(tmp_path, ["T1", "T2"])
    library = Library(tmp_path / "lib.db")
    library._index_cue_file(str(cue))

    tracks = library.conn.execute(
        "SELECT * FROM tracks WHERE media_type = 'cue_track' ORDER BY track_no"
    ).fetchall()
    from lyon.core.library import _row_to_track
    t1 = _row_to_track(tracks[0])
    assert t1.playback_uri == str(img.resolve())
    assert "--start-time=0.000" in t1.playback_options
    assert any("--stop-time=" in o for o in t1.playback_options)


def test_row_to_track_last_cue_track_has_no_stop_time(tmp_path):
    img = _write_image(tmp_path)
    cue = _write_cue(tmp_path, ["Only Track"])
    library = Library(tmp_path / "lib.db")
    library._index_cue_file(str(cue))

    tracks = library.conn.execute(
        "SELECT * FROM tracks WHERE media_type = 'cue_track'"
    ).fetchall()
    from lyon.core.library import _row_to_track
    t = _row_to_track(tracks[0])
    # duration is 0 for last track → no --stop-time
    assert not any("--stop-time=" in o for o in t.playback_options)


# ===========================================================================
# 2.4 — remove_missing excludes CUE tracks
# ===========================================================================

def test_remove_missing_does_not_touch_cue_tracks(tmp_path):
    _write_image(tmp_path)
    cue = _write_cue(tmp_path, ["T1"])
    library = Library(tmp_path / "lib.db")
    library._index_cue_file(str(cue))

    # Verify track exists before remove_missing
    count_before = library.conn.execute(
        "SELECT COUNT(*) FROM tracks WHERE media_type='cue_track'"
    ).fetchone()[0]
    assert count_before == 1

    library.remove_missing()

    count_after = library.conn.execute(
        "SELECT COUNT(*) FROM tracks WHERE media_type='cue_track'"
    ).fetchone()[0]
    assert count_after == 1


# ===========================================================================
# 2.4 — remove_stale_cue_tracks
# ===========================================================================

def test_remove_stale_cue_tracks_cleans_deleted_cue(tmp_path):
    _write_image(tmp_path)
    cue = _write_cue(tmp_path, ["T1", "T2"])
    library = Library(tmp_path / "lib.db")
    library._index_cue_file(str(cue))

    cue.unlink()
    removed = library.remove_stale_cue_tracks()
    assert removed == 2

    count = library.conn.execute(
        "SELECT COUNT(*) FROM tracks WHERE media_type='cue_track'"
    ).fetchone()[0]
    assert count == 0


def test_remove_stale_cue_tracks_keeps_existing_cue(tmp_path):
    _write_image(tmp_path)
    cue = _write_cue(tmp_path, ["T1"])
    library = Library(tmp_path / "lib.db")
    library._index_cue_file(str(cue))

    removed = library.remove_stale_cue_tracks()
    assert removed == 0

    count = library.conn.execute(
        "SELECT COUNT(*) FROM tracks WHERE media_type='cue_track'"
    ).fetchone()[0]
    assert count == 1


# ===========================================================================
# 2.4 — scan_paths_summary picks up CUE files
# ===========================================================================

def test_scan_paths_summary_indexes_cue_files(tmp_path, monkeypatch):
    _write_image(tmp_path)
    _write_cue(tmp_path, ["T1", "T2"])
    # Prevent actual mutagen reads for any accidental .flac scan attempts
    monkeypatch.setattr(library_module, "MutagenFile", lambda *a, **k: None)

    library = Library(tmp_path / "lib.db")
    summary = library.scan_paths_summary([tmp_path])

    cue_rows = library.conn.execute(
        "SELECT COUNT(*) FROM tracks WHERE media_type='cue_track'"
    ).fetchone()[0]
    assert cue_rows == 2
    assert summary.added >= 2

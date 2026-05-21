"""Tests for CUE sheet indexing (2.4) and file-hash duplicate detection (2.6)."""
from __future__ import annotations

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


def _patch_basic_audio_metadata(monkeypatch) -> None:
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


# ===========================================================================
# 2.6 — file_hash helpers
# ===========================================================================

def test_compute_file_hash_returns_hex_digest(tmp_path):
    f = tmp_path / "a.flac"
    f.write_bytes(b"hello world")
    result = _compute_file_hash(str(f))
    assert result is not None
    assert len(result) == 32
    int(result, 16)  # raises if not hex


def test_compute_file_hash_distinguishes_files_that_differ_only_in_middle(tmp_path):
    # 1 MB files identical in the first and last 64 KB but differing in the
    # middle — header-only hashing would collide.
    head = b"H" * 65536
    tail = b"T" * 65536
    body_a = b"A" * (1024 * 1024 - 2 * 65536)
    body_b = b"B" * (1024 * 1024 - 2 * 65536)
    a = tmp_path / "a.flac"
    b = tmp_path / "b.flac"
    a.write_bytes(head + body_a + tail)
    b.write_bytes(head + body_b + tail)
    assert _compute_file_hash(str(a)) != _compute_file_hash(str(b))


def test_compute_file_hash_stable_across_calls(tmp_path):
    f = tmp_path / "x.flac"
    f.write_bytes(b"\xab" * 200_000)
    assert _compute_file_hash(str(f)) == _compute_file_hash(str(f))


def test_compute_file_hash_missing_file_returns_none(tmp_path):
    assert _compute_file_hash(str(tmp_path / "no_such.flac")) is None


# ===========================================================================
# 2.6 — file_hash deferred during index_file
# ===========================================================================

def test_index_file_defers_hash_for_audio(tmp_path, monkeypatch):
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
    assert row["file_hash"] is None


def test_index_file_preserves_hash_for_forced_unchanged_rescan(tmp_path, monkeypatch):
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
    monkeypatch.setattr(
        library_module,
        "_compute_file_hash",
        lambda *a, **k: pytest.fail("index_file should not hash unchanged audio"),
    )
    library = Library(tmp_path / "lib.db")
    library.index_file(str(audio))
    library.conn.execute(
        "UPDATE tracks SET file_hash = 'cafebabe', acoustid_id = 'acoustid-1' WHERE path = ?",
        (str(audio),),
    )
    library.conn.commit()

    library.index_file(str(audio), force=True)

    row = library.conn.execute(
        "SELECT file_hash, acoustid_id FROM tracks WHERE path = ?", (str(audio),)
    ).fetchone()
    assert row["file_hash"] == "cafebabe"
    assert row["acoustid_id"] == "acoustid-1"


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


def test_index_file_clears_stale_hash_when_audio_changes(tmp_path, monkeypatch):
    audio = tmp_path / "song.flac"
    audio.write_bytes(b"FLAC" + b"\x00" * 60)
    _patch_basic_audio_metadata(monkeypatch)

    library = Library(tmp_path / "lib.db")
    library.index_file(str(audio))
    library.conn.execute(
        "UPDATE tracks SET file_hash = 'cafebabe', acoustid_id = 'acoustid-1' WHERE path = ?",
        (str(audio),),
    )
    library.conn.commit()

    audio.write_bytes(b"FLAC" + b"\x01" * 61)
    library.index_file(str(audio), force=True)

    row = library.conn.execute(
        "SELECT file_hash, acoustid_id FROM tracks WHERE path = ?", (str(audio),)
    ).fetchone()
    assert row["file_hash"] is None
    assert row["acoustid_id"] is None


def test_index_file_preserves_acoustid_when_file_hash_is_null(tmp_path, monkeypatch):
    """Regression: acoustid must survive a rescan even when file_hash is still NULL."""
    audio = tmp_path / "song.flac"
    audio.write_bytes(b"FLAC" + b"\x00" * 60)
    _patch_basic_audio_metadata(monkeypatch)

    library = Library(tmp_path / "lib.db")
    library.index_file(str(audio))

    # Simulate fingerprinting: acoustid set but file_hash still NULL (deferred hashing).
    library.conn.execute(
        "UPDATE tracks SET acoustid_id = 'test-acoustid-uuid' WHERE path = ?",
        (str(audio),),
    )
    library.conn.commit()

    # Rescan the unchanged file — acoustid must not be erased.
    library.index_file(str(audio), force=True)

    row = library.conn.execute(
        "SELECT file_hash, acoustid_id FROM tracks WHERE path = ?", (str(audio),)
    ).fetchone()
    assert row["file_hash"] is None, "hash should remain NULL (deferred)"
    assert row["acoustid_id"] == "test-acoustid-uuid", "acoustid must be preserved on unchanged rescan"


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


def test_find_duplicates_by_hash_backfills_indexed_audio(tmp_path, monkeypatch):
    a = tmp_path / "copy_a.flac"
    b = tmp_path / "copy_b.flac"
    payload = b"FLAC" + b"\x01" * 200_000
    a.write_bytes(payload)
    b.write_bytes(payload)
    _patch_basic_audio_metadata(monkeypatch)

    library = Library(tmp_path / "lib.db")
    library.index_file(str(a))
    library.index_file(str(b))

    rows = library.conn.execute(
        "SELECT file_hash FROM tracks ORDER BY path"
    ).fetchall()
    assert [row["file_hash"] for row in rows] == [None, None]

    groups = library.find_duplicates_by_hash()

    assert len(groups) == 1
    assert {track.path for track in groups[0]} == {str(a), str(b)}
    hashes = library.conn.execute(
        "SELECT DISTINCT file_hash FROM tracks ORDER BY file_hash"
    ).fetchall()
    assert [row["file_hash"] for row in hashes] == [_compute_file_hash(str(a))]


def test_find_duplicates_by_hash_reuses_backfilled_hash_after_reopen(tmp_path, monkeypatch):
    a = tmp_path / "copy_a.flac"
    b = tmp_path / "copy_b.flac"
    payload = b"FLAC" + b"\x02" * 200_000
    a.write_bytes(payload)
    b.write_bytes(payload)
    _patch_basic_audio_metadata(monkeypatch)
    db_path = tmp_path / "lib.db"

    library = Library(db_path)
    library.index_file(str(a))
    library.index_file(str(b))
    assert len(library.find_duplicates_by_hash()) == 1
    library.close()

    monkeypatch.setattr(
        library_module,
        "_compute_file_hash",
        lambda *a, **k: pytest.fail("existing hashes should not be recomputed"),
    )
    reopened = Library(db_path)
    try:
        groups = reopened.find_duplicates_by_hash()
    finally:
        reopened.close()

    assert len(groups) == 1
    assert {track.path for track in groups[0]} == {str(a), str(b)}


def test_backfill_does_not_overwrite_hash_set_concurrently(tmp_path, monkeypatch):
    """Regression: backfill UPDATE must not stomp a hash written by a concurrent index_file."""
    audio = tmp_path / "song.flac"
    audio.write_bytes(b"FLAC" + b"\x00" * 60)
    _patch_basic_audio_metadata(monkeypatch)

    library = Library(tmp_path / "lib.db")
    library.index_file(str(audio))

    track_id = library.conn.execute(
        "SELECT id FROM tracks WHERE path = ?", (str(audio),)
    ).fetchone()["id"]

    sentinel = "hash-set-by-concurrent-index"

    # Wrap _compute_file_hash to also simulate a concurrent index setting the hash first.
    original_compute = library_module._compute_file_hash

    def _compute_and_inject(path):
        # Simulate a concurrent index_file winning the race and writing the hash.
        library.conn.execute(
            "UPDATE tracks SET file_hash = ? WHERE id = ?",
            (sentinel, track_id),
        )
        library.conn.commit()
        return original_compute(path)

    monkeypatch.setattr(library_module, "_compute_file_hash", _compute_and_inject)

    library._backfill_missing_hashes()

    row = library.conn.execute(
        "SELECT file_hash FROM tracks WHERE id = ?", (track_id,)
    ).fetchone()
    assert row["file_hash"] == sentinel, "backfill must not overwrite a concurrently-written hash"


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


def test_index_cue_file_defers_commit_by_default(tmp_path):
    _write_image(tmp_path)
    cue = _write_cue(tmp_path, ["Track One"])
    db_path = tmp_path / "lib.db"
    library = Library(db_path)
    try:
        library._index_cue_file(str(cue))
        same_connection_count = library.conn.execute(
            "SELECT COUNT(*) FROM tracks WHERE media_type='cue_track'"
        ).fetchone()[0]
        assert same_connection_count == 1

        observer = Library(db_path)
        try:
            committed_count = observer.conn.execute(
                "SELECT COUNT(*) FROM tracks WHERE media_type='cue_track'"
            ).fetchone()[0]
            assert committed_count == 0
        finally:
            observer.close()

        library.conn.commit()
        observer = Library(db_path)
        try:
            committed_count = observer.conn.execute(
                "SELECT COUNT(*) FROM tracks WHERE media_type='cue_track'"
            ).fetchone()[0]
            assert committed_count == 1
        finally:
            observer.close()
    finally:
        library.close()


def test_index_cue_file_commit_option_persists_immediately(tmp_path):
    _write_image(tmp_path)
    cue = _write_cue(tmp_path, ["Track One"])
    db_path = tmp_path / "lib.db"
    library = Library(db_path)
    try:
        library._index_cue_file(str(cue), commit=True)

        observer = Library(db_path)
        try:
            committed_count = observer.conn.execute(
                "SELECT COUNT(*) FROM tracks WHERE media_type='cue_track'"
            ).fetchone()[0]
            assert committed_count == 1
        finally:
            observer.close()
    finally:
        library.close()


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
    assert ":start-time=0.000" in t1.playback_options
    assert any(o.startswith(":stop-time=") for o in t1.playback_options)


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
    # duration is 0 for last track → no :stop-time
    assert not any(o.startswith(":stop-time=") for o in t.playback_options)


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


def test_remove_stale_cue_tracks_cleans_missing_image(tmp_path):
    img = _write_image(tmp_path)
    cue = _write_cue(tmp_path, ["T1", "T2"])
    library = Library(tmp_path / "lib.db")
    library._index_cue_file(str(cue))

    img.unlink()
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

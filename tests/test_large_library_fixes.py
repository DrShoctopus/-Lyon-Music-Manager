"""Regression tests for crashes triggered by very large (100k-track) libraries.

Covers the fixes for:
- SQLite "too many SQL variables" when tracks_for_paths() is given more
  paths than the host-parameter limit (startup queue restore, playlist
  import of whole-library M3U files).
- Playlist import building its case-insensitive fallback map from lean
  (path, id) pairs instead of full Track objects.
- QueueDialog outliving its C++ widgets through player signal connections
  (RuntimeError: Internal C++ object already deleted on track change), and
  rebuilding the whole table on every track change.
"""
from __future__ import annotations

from pathlib import Path

import pytest

QtCore = pytest.importorskip("PySide6.QtCore", exc_type=ImportError)

from lyon.core.library import IndexResult, Library, ScanProgress, Track  # noqa: E402
from lyon.core.playlist_import import import_playlist  # noqa: E402


def add_track(library: Library, path: str, artist: str = "Artist") -> None:
    library.conn.execute(
        """INSERT INTO tracks
           (path, title, artist, album_artist, album, track_no, disc_no, year,
            genre, duration, bitrate, samplerate, media_type)
           VALUES (?, ?, ?, ?, 'Album', 1, 1, 0, '', 60.0, 320000, 48000, 'audio')""",
        (path, Path(path).stem, artist, artist),
    )
    library.conn.commit()


# --------------------------------------------------------------- tracks_for_paths
def test_tracks_for_paths_survives_more_paths_than_sqlite_parameter_limit(tmp_path):
    """A restored 100k-track queue used to raise 'too many SQL variables'."""
    library = Library(tmp_path / "library.db")
    known = [f"/music/known_{i:05}.flac" for i in range(40)]
    for p in known:
        add_track(library, p)

    # 40k paths (> the modern 32766-parameter cap) with the known tracks
    # interleaved throughout.
    paths = [f"/music/missing_{i:05}.flac" for i in range(40_000)]
    paths[::1000] = known

    tracks = library.tracks_for_paths(paths)

    assert [t.path for t in tracks] == known


def test_tracks_for_paths_preserves_order_and_duplicates_across_chunks(tmp_path, monkeypatch):
    from lyon.core import library as library_module

    monkeypatch.setattr(library_module, "_SQL_IN_CHUNK", 3)
    library = Library(tmp_path / "library.db")
    for i in range(8):
        add_track(library, f"/music/t{i}.flac")

    request = [
        "/music/t5.flac",
        "/music/t0.flac",
        "/music/none.flac",
        "/music/t7.flac",
        "/music/t5.flac",  # duplicate request → duplicate result, as before
        "/music/t2.flac",
    ]
    tracks = library.tracks_for_paths(request)
    assert [t.path for t in tracks] == [
        "/music/t5.flac",
        "/music/t0.flac",
        "/music/t7.flac",
        "/music/t5.flac",
        "/music/t2.flac",
    ]


def test_all_track_path_ids_returns_lean_pairs(tmp_path):
    library = Library(tmp_path / "library.db")
    add_track(library, "/music/a.flac")
    add_track(library, "/music/b.flac")

    pairs = library.all_track_path_ids()

    assert sorted(p for p, _ in pairs) == ["/music/a.flac", "/music/b.flac"]
    assert all(isinstance(tid, int) for _, tid in pairs)


def test_100k_scan_progress_snapshots_stay_bounded(tmp_path, monkeypatch):
    """Verbose status must not retain one UI/log object for every library file."""
    from lyon.core import library as library_module

    root = tmp_path / "Music"
    root.mkdir()
    names = [f"track-{i:06}.flac" for i in range(100_000)]
    monkeypatch.setattr(
        library_module.os,
        "walk",
        lambda _root: iter([(str(root), [], names)]),
    )
    library = Library(tmp_path / "library.db")
    monkeypatch.setattr(library, "_metadata_candidates", lambda paths, *, force: [])
    monkeypatch.setattr(
        library,
        "index_file",
        lambda path, **_kwargs: IndexResult("added", str(path)),
    )
    progress: list[ScanProgress] = []
    try:
        summary = library.scan_paths_summary(
            [root],
            isolate_metadata=True,
            on_progress=progress.append,
        )

        assert summary.added == 100_000
        assert progress[-1].processed == 100_000
        assert max(len(snapshot.recent) for snapshot in progress) <= 50
    finally:
        library.close()


# --------------------------------------------------------------- playlist import
def test_import_playlist_larger_than_sqlite_parameter_limit(tmp_path, monkeypatch):
    """Importing a whole-library M3U (33k entries) must not blow the SQL cap."""
    # normcase only folds case on Windows; emulate that here so the
    # case-insensitive fallback (now fed by all_track_path_ids) is covered
    # on every platform.
    monkeypatch.setattr("os.path.normcase", lambda p: p.lower())
    library = Library(tmp_path / "library.db")
    known = [f"/music/known_{i:05}.flac" for i in range(40)]
    for p in known:
        add_track(library, p)
    # One track that only matches case-insensitively.
    add_track(library, "/music/CaseSensitive.flac")

    lines = [f"/music/missing_{i:05}.flac" for i in range(33_000)]
    lines[::1000] = known[:33]
    lines.extend(known[33:])
    lines.append("/music/casesensitive.flac")
    m3u = tmp_path / "everything.m3u"
    m3u.write_text("\n".join(["#EXTM3U", *lines]), encoding="utf-8")

    result = import_playlist(library, m3u)

    assert result.matched == 41
    assert len(result.unmatched) == 33_000 - 33
    assert len(library.playlist_tracks(result.playlist_id)) == 41


# --------------------------------------------------------------- queue dialog
def _track(i: int) -> Track:
    return Track(
        id=i,
        path=f"/music/t{i}.mp3",
        title=f"Track {i}",
        artist="Artist",
        album_artist="Artist",
        album="Album",
        track_no=i,
        disc_no=1,
        year=2020,
        genre="",
        duration=60.0,
    )


@pytest.fixture
def player(qapp, fake_backend):
    from lyon.core.player import Player

    return Player(backend=fake_backend)


def test_queue_dialog_track_change_after_close_does_not_raise(player):
    """Player signals used to keep calling into the deleted dialog's widgets."""
    from lyon.ui.queue_dialog import QueueDialog

    tracks = [_track(1), _track(2)]
    player.load_queue(tracks, 0)

    dialog = QueueDialog(player)
    dialog.reject()  # user closes the dialog → finished → disconnect
    dialog.deleteLater()
    QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)

    # Before the fix this raised RuntimeError (Internal C++ object deleted)
    # from the leftover lambda connection.
    player.track_changed.emit(tracks[1])
    player.queue_changed.emit()


def test_queue_dialog_track_change_moves_marker_without_rebuilding(player):
    from lyon.ui.queue_dialog import QueueDialog

    tracks = [_track(1), _track(2), _track(3)]
    player.load_queue(tracks, 0)

    dialog = QueueDialog(player)
    try:
        assert dialog.table.item(0, 0).text() == "▶"
        surviving_item = dialog.table.item(1, 1)

        assert player.play_index(2)

        # Marker moved…
        assert dialog.table.item(0, 0).text() == "1"
        assert dialog.table.item(2, 0).text() == "▶"
        assert "Now playing 3 of 3" in dialog.summary.text()
        # …and the table was patched in place, not rebuilt item-by-item.
        assert dialog.table.item(1, 1) is surviving_item
    finally:
        dialog.reject()
        dialog.deleteLater()
        QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)


def test_queue_dialog_full_refresh_still_runs_when_queue_length_changes(player):
    from lyon.ui.queue_dialog import QueueDialog

    player.load_queue([_track(1), _track(2)], 0)
    dialog = QueueDialog(player)
    try:
        assert dialog.table.rowCount() == 2
        player.enqueue([_track(3)])
        assert dialog.table.rowCount() == 3
    finally:
        dialog.reject()
        dialog.deleteLater()
        QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)


# --------------------------------------------------------------- rescan tag re-reads
class _FakeInfo:
    length = 60.0
    bitrate = 320000
    sample_rate = 44100


class _NoDiscIdAudio(dict):
    """Minimal mutagen-like object whose tags carry no MusicBrainz disc ID."""

    info = _FakeInfo()

    def get(self, key):
        return {
            "title": ["Title"],
            "artist": ["Artist"],
            "albumartist": ["Artist"],
            "album": ["Album"],
            "tracknumber": ["1"],
            "discnumber": ["1"],
            "date": ["2024"],
            "genre": ["Rock"],
        }.get(key)


def test_rescan_reads_tags_once_for_files_without_disc_id(tmp_path, monkeypatch):
    """Files with no disc ID in tags used to be re-parsed on EVERY scan —
    a full-library re-read per app launch at 100k tracks."""
    from lyon.core import library as library_module

    calls: list[int] = []

    def fake_mutagen(*_args, **_kwargs):
        calls.append(1)
        return _NoDiscIdAudio()

    monkeypatch.setattr(library_module, "MutagenFile", fake_mutagen)
    path = tmp_path / "song.flac"
    path.write_bytes(b"payload")

    library = Library(tmp_path / "library.db")
    try:
        assert library.index_file(path).status == "added"
        assert calls == [1]  # initial index reads tags and stores '' (checked)

        assert library.index_file(path).status == "unchanged"
        assert library.index_file(path).status == "unchanged"
        assert calls == [1], "unchanged rescans must not re-read tags"
    finally:
        library.close()


def test_rescan_backfills_legacy_null_disc_id_exactly_once(tmp_path, monkeypatch):
    """Rows from older versions have disc_id NULL: one backfill read, then done."""
    from lyon.core import library as library_module

    calls: list[int] = []

    def fake_mutagen(*_args, **_kwargs):
        calls.append(1)
        return _NoDiscIdAudio()

    monkeypatch.setattr(library_module, "MutagenFile", fake_mutagen)
    path = tmp_path / "song.flac"
    path.write_bytes(b"payload")

    library = Library(tmp_path / "library.db")
    try:
        library.index_file(path)
        # Simulate a database written before '' meant "checked".
        library.conn.execute("UPDATE tracks SET disc_id = NULL")
        library.conn.commit()

        assert library.index_file(path).status == "unchanged"
        assert calls == [1, 1], "first rescan performs the one backfill read"
        row = library.conn.execute("SELECT disc_id FROM tracks").fetchone()
        assert row["disc_id"] == ""  # now marked checked-absent

        assert library.index_file(path).status == "unchanged"
        assert calls == [1, 1], "subsequent rescans skip the tag read"
    finally:
        library.close()


def test_rip_disc_id_still_overwrites_checked_absent_marker(tmp_path, monkeypatch):
    from lyon.core import library as library_module

    monkeypatch.setattr(
        library_module, "MutagenFile", lambda *_a, **_k: _NoDiscIdAudio()
    )
    path = tmp_path / "song.flac"
    path.write_bytes(b"payload")

    library = Library(tmp_path / "library.db")
    try:
        library.index_file(path)  # stores '' (checked, absent)
        assert library.index_file(path, disc_id="ripped-disc").status == "unchanged"
        row = library.conn.execute("SELECT disc_id FROM tracks").fetchone()
        assert row["disc_id"] == "ripped-disc"
    finally:
        library.close()

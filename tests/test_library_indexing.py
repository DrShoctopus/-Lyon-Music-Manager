import os
import threading
import wave
from pathlib import Path

from lyon.core import library as library_module
from lyon.core import library_watcher as library_watcher_module
from lyon.core.library import Library, ScanProgress
from lyon.core.library_watcher import (
    LibraryFolderWatcher,
    LibraryIndexThread,
    WatchBatch,
    coalesce_batch,
)


class _FakeInfo:
    length = 60.0
    bitrate = 320000
    sample_rate = 44100


class _FakeAudio(dict):
    info = _FakeInfo()

    def __init__(self, title: str, artist: str = "Artist", album: str = "Album") -> None:
        super().__init__()
        self._title = title
        self._artist = artist
        self._album = album

    def get(self, key):
        return {
            "title": [self._title],
            "artist": [self._artist],
            "albumartist": [self._artist],
            "album": [self._album],
            "tracknumber": ["1"],
            "discnumber": ["1"],
            "date": ["2024"],
            "genre": ["Rock"],
        }.get(key)


class _ExplodingAudio(dict):
    info = _FakeInfo()

    def get(self, key):
        raise RuntimeError(f"bad tag value for {key}")


def _set_file_state(path: Path, payload: bytes, mtime_ns: int) -> None:
    path.write_bytes(payload)
    os.utime(path, ns=(mtime_ns, mtime_ns))


def test_index_file_skips_unchanged_files_without_rereading_tags(tmp_path, monkeypatch):
    calls = []
    title = {"value": "First Title"}

    def fake_mutagen(*_args, **_kwargs):
        calls.append(1)
        return _FakeAudio(title["value"])

    monkeypatch.setattr(library_module, "MutagenFile", fake_mutagen)
    path = tmp_path / "song.flac"
    _set_file_state(path, b"one", 1_700_000_000_000_000_000)

    library = Library(tmp_path / "library.db")
    try:
        added = library.index_file(path, disc_id="known-disc")
        library.commit()
        title["value"] = "Should Not Be Read"
        unchanged = library.index_file(path)
        library.commit()

        assert added.status == "added"
        assert unchanged.status == "unchanged"
        assert len(calls) == 1
        assert next(library.all_tracks()).title == "First Title"
    finally:
        library.close()


def test_index_file_refreshes_changed_metadata_and_preserves_user_state(tmp_path, monkeypatch):
    title = {"value": "Original"}
    monkeypatch.setattr(
        library_module,
        "MutagenFile",
        lambda *_args, **_kwargs: _FakeAudio(title["value"]),
    )
    path = tmp_path / "song.flac"
    _set_file_state(path, b"one", 1_700_000_000_000_000_000)

    library = Library(tmp_path / "library.db")
    try:
        assert library.index_file(path).status == "added"
        library.commit()
        track = next(library.all_tracks())
        library.update_rating(track.id, 5)
        library.update_liked(track.id, True)
        library.increment_play_count(track.id)

        title["value"] = "Updated"
        _set_file_state(path, b"two", 1_700_000_100_000_000_000)
        assert library.index_file(path).status == "updated"
        library.commit()

        updated = next(library.all_tracks())
        assert updated.title == "Updated"
        assert updated.rating == 5
        assert updated.liked is True
        assert updated.play_count == 1
        assert updated.file_size == 3
        assert updated.file_mtime_ns == 1_700_000_100_000_000_000
    finally:
        library.close()


def test_scan_paths_summary_continues_after_bad_tag_object(tmp_path, monkeypatch):
    root = tmp_path / "Music"
    root.mkdir()
    good_a = root / "good-a.flac"
    bad = root / "bad.flac"
    good_b = root / "good-b.flac"
    for i, path in enumerate((good_a, bad, good_b), start=1):
        _set_file_state(path, f"file-{i}".encode(), 1_700_000_000_000_000_000 + i)

    def fake_mutagen(path, **_kwargs):
        if Path(path).name == "bad.flac":
            return _ExplodingAudio()
        return _FakeAudio(Path(path).stem)

    monkeypatch.setattr(library_module, "MutagenFile", fake_mutagen)
    library = Library(tmp_path / "library.db")
    try:
        summary = library.scan_paths_summary([root])

        assert summary.added == 2
        assert summary.skipped == 1
        assert {track.title for track in library.all_tracks()} == {"good-a", "good-b"}
    finally:
        library.close()


def test_scan_paths_summary_checks_cancel_between_files(tmp_path, monkeypatch):
    root = tmp_path / "Music"
    root.mkdir()
    for i in range(3):
        _set_file_state(
            root / f"track-{i}.flac",
            f"file-{i}".encode(),
            1_700_000_000_000_000_000 + i,
        )

    monkeypatch.setattr(
        library_module,
        "MutagenFile",
        lambda path, **_kwargs: _FakeAudio(Path(path).stem),
    )
    calls = 0

    def should_cancel() -> bool:
        nonlocal calls
        calls += 1
        return calls > 2

    library = Library(tmp_path / "library.db")
    try:
        summary = library.scan_paths_summary([root], should_cancel=should_cancel)

        assert summary.added == 1
        assert library.count_tracks() == 1
    finally:
        library.close()


def test_scan_paths_summary_commits_large_scans_in_batches(tmp_path, monkeypatch):
    root = tmp_path / "Music"
    root.mkdir()
    for i in range(501):
        _set_file_state(
            root / f"track-{i:03d}.flac",
            b"file",
            1_700_000_000_000_000_000 + i,
        )

    monkeypatch.setattr(
        library_module,
        "MutagenFile",
        lambda path, **_kwargs: _FakeAudio(Path(path).stem),
    )
    library = Library(tmp_path / "library.db")

    class CountingConnection:
        def __init__(self, conn):
            self.conn = conn
            self.commits = 0

        def __getattr__(self, name):
            return getattr(self.conn, name)

        def commit(self):
            self.commits += 1
            return self.conn.commit()

    counting_conn = CountingConnection(library.conn)
    library.conn = counting_conn
    try:
        summary = library.scan_paths_summary([root])

        assert summary.added == 501
        assert counting_conn.commits >= 2
    finally:
        library.close()


def test_resource_safe_scan_reads_metadata_in_bounded_isolated_batch(tmp_path, monkeypatch):
    root = tmp_path / "Music"
    root.mkdir()
    paths = []
    for i in range(3):
        path = root / f"track-{i}.flac"
        _set_file_state(path, b"file", 1_700_000_000_000_000_000 + i)
        paths.append(str(path))

    def fail_if_read_in_scan_process(*_args, **_kwargs):
        raise AssertionError("resource-safe scan must use the isolated metadata result")

    monkeypatch.setattr(library_module, "MutagenFile", fail_if_read_in_scan_process)
    library = Library(tmp_path / "library.db")
    batches: list[list[str]] = []
    progress: list[ScanProgress] = []

    def isolated_reader(batch, *, should_cancel):
        assert should_cancel is None
        batches.append(list(batch))
        return {
            path: {
                "title": Path(path).stem,
                "artist": "Artist",
                "album_artist": "Artist",
                "album": "Album",
                "track_no": 1,
                "disc_no": 1,
                "year": 2024,
                "genre": "Rock",
                "grouping": "",
                "duration": 60.0,
                "bitrate": 320000,
                "samplerate": 44100,
                "disc_id": "",
            }
            for path in batch
        }

    monkeypatch.setattr(library, "_read_metadata_batch_isolated", isolated_reader)
    try:
        summary = library.scan_paths_summary(
            [root],
            isolate_metadata=True,
            on_progress=progress.append,
        )

        assert summary.added == 3
        assert len(batches) == 1
        assert set(batches[0]) == set(paths)
        assert progress[-1].phase == "complete"
        assert progress[-1].processed == 3
    finally:
        library.close()


def test_isolated_metadata_reader_splits_crashed_batch_to_individual_files(
    tmp_path, monkeypatch
):
    library = Library(tmp_path / "library.db")
    calls: list[list[str]] = []

    def fake_process(batch, *, should_cancel):
        assert should_cancel is None
        calls.append(list(batch))
        if len(batch) > 1:
            return None
        return {batch[0]: {"title": Path(batch[0]).stem}}

    monkeypatch.setattr(library_module, "_run_metadata_process", fake_process)
    try:
        result = library._read_metadata_batch_isolated(
            ["/music/a.flac", "/music/b.flac"],
            should_cancel=None,
        )

        assert result == {
            "/music/a.flac": {"title": "a"},
            "/music/b.flac": {"title": "b"},
        }
        assert calls == [
            ["/music/a.flac", "/music/b.flac"],
            ["/music/a.flac"],
            ["/music/b.flac"],
        ]
    finally:
        library.close()


def test_resource_safe_scan_uses_real_spawned_metadata_parser(tmp_path):
    root = tmp_path / "Music"
    root.mkdir()
    path = root / "valid.wav"
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(44100)
        wav.writeframes(b"\x00\x00" * 100)

    library = Library(tmp_path / "library.db")
    try:
        summary = library.scan_paths_summary([root], isolate_metadata=True)

        assert summary.added == 1
        assert library.count_tracks() == 1
    finally:
        library.close()


def test_move_path_preserves_playlist_membership_and_rating(tmp_path, monkeypatch):
    monkeypatch.setattr(
        library_module,
        "MutagenFile",
        lambda path, **_kwargs: _FakeAudio(Path(path).stem),
    )
    old_path = tmp_path / "old.flac"
    new_path = tmp_path / "new.flac"
    _set_file_state(old_path, b"one", 1_700_000_000_000_000_000)

    library = Library(tmp_path / "library.db")
    try:
        assert library.index_file(old_path).status == "added"
        library.commit()
        track = next(library.all_tracks())
        playlist_id = library.create_playlist("Keep Me")
        library.add_to_playlist(playlist_id, [track.id])
        library.update_rating(track.id, 4)

        old_path.rename(new_path)
        os.utime(new_path, ns=(1_700_000_200_000_000_000, 1_700_000_200_000_000_000))
        result = library.move_path(old_path, new_path)

        assert result.status == "updated"
        moved = next(library.all_tracks())
        assert moved.id == track.id
        assert moved.path == str(new_path)
        assert moved.rating == 4
        assert [t.id for t in library.playlist_tracks(playlist_id)] == [track.id]
    finally:
        library.close()


def test_move_path_keeps_check_and_update_in_one_locked_section(tmp_path, monkeypatch):
    monkeypatch.setattr(
        library_module,
        "MutagenFile",
        lambda path, **_kwargs: _FakeAudio(Path(path).stem),
    )
    old_path = tmp_path / "old.flac"
    new_path = tmp_path / "new.flac"
    _set_file_state(old_path, b"one", 1_700_000_000_000_000_000)

    library = Library(tmp_path / "library.db")

    class DeleteOldPathAfterFirstCriticalSection:
        def __init__(self) -> None:
            self._lock = threading.RLock()
            self._exited_once = False

        def __enter__(self):
            self._lock.acquire()
            if self._exited_once:
                library.conn.execute("DELETE FROM tracks WHERE path = ?", (str(old_path),))
                library.conn.commit()
                self._exited_once = False
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            self._exited_once = True
            self._lock.release()

    try:
        assert library.index_file(old_path).status == "added"
        library.commit()
        track = next(library.all_tracks())
        library.update_rating(track.id, 4)

        library._lock = DeleteOldPathAfterFirstCriticalSection()
        old_path.rename(new_path)
        os.utime(new_path, ns=(1_700_000_200_000_000_000, 1_700_000_200_000_000_000))

        result = library.move_path(old_path, new_path)

        moved = next(library.all_tracks())
        assert result.status == "updated"
        assert moved.id == track.id
        assert moved.path == str(new_path)
        assert moved.rating == 4
    finally:
        library.close()


def test_remove_paths_under_deletes_only_that_folder(tmp_path):
    library = Library(tmp_path / "library.db")
    try:
        library.conn.execute(
            """INSERT INTO tracks
               (path, title, artist, album_artist, album, track_no, disc_no, year,
                genre, duration, bitrate, samplerate)
               VALUES (?, 'A', '', '', '', 1, 1, 0, '', 1, 1, 1)""",
            (str(tmp_path / "Music" / "a.flac"),),
        )
        library.conn.execute(
            """INSERT INTO tracks
               (path, title, artist, album_artist, album, track_no, disc_no, year,
                genre, duration, bitrate, samplerate)
               VALUES (?, 'B', '', '', '', 1, 1, 0, '', 1, 1, 1)""",
            (str(tmp_path / "Other" / "b.flac"),),
        )
        library.commit()

        assert library.remove_paths_under(tmp_path / "Music") == 1
        assert [track.path for track in library.all_tracks()] == [
            str(tmp_path / "Other" / "b.flac")
        ]
    finally:
        library.close()


def test_scan_prune_ignores_missing_files_under_offline_roots(tmp_path):
    mounted_root = tmp_path / "Mounted"
    offline_root = tmp_path / "Offline"
    mounted_root.mkdir()
    present_file = mounted_root / "present.flac"
    present_file.write_bytes(b"present")
    missing_mounted = mounted_root / "missing.flac"
    missing_offline = offline_root / "missing.flac"

    library = Library(tmp_path / "library.db")
    try:
        for path, title in (
            (present_file, "Present"),
            (missing_mounted, "Missing Mounted"),
            (missing_offline, "Missing Offline"),
        ):
            library.conn.execute(
                """INSERT INTO tracks
                   (path, title, artist, album_artist, album, track_no, disc_no, year,
                    genre, duration, bitrate, samplerate)
                   VALUES (?, ?, '', '', '', 1, 1, 0, '', 1, 1, 1)""",
                (str(path), title),
            )
        library.commit()

        removed = library.remove_missing_under_existing_roots([mounted_root, offline_root])

        assert removed == 1
        assert {track.title for track in library.all_tracks()} == {
            "Present",
            "Missing Offline",
        }
    finally:
        library.close()


def test_watch_batch_coalesces_duplicate_and_conflicting_events():
    target = WatchBatch(changed_paths={"/music/a.flac"})
    coalesce_batch(target, WatchBatch(deleted_paths={"/music/a.flac"}))
    coalesce_batch(target, WatchBatch(moved_paths={"/music/b.flac": "/music/c.flac"}))
    coalesce_batch(target, WatchBatch(changed_paths={"/music/c.flac"}))

    assert target.changed_paths == set()
    assert target.deleted_paths == {"/music/a.flac"}
    assert target.moved_paths == {"/music/b.flac": "/music/c.flac"}


def test_watch_batch_collapses_nested_scan_roots_and_covered_file_events():
    target = WatchBatch(
        scan_roots={"/music/Artist"},
        changed_paths={"/music/Artist/Album/a.flac", "/music/Other/b.flac"},
    )

    coalesce_batch(
        target,
        WatchBatch(
            scan_roots={"/music", "/music/Artist/Album"},
            changed_paths={"/music/Artist/Album/c.flac"},
        ),
    )

    assert target.scan_roots == {"/music"}
    assert target.changed_paths == set()


def test_library_folder_watcher_collapses_nested_roots_before_scheduling(tmp_path, monkeypatch):
    scheduled: list[str] = []

    class FakeObserver:
        def schedule(self, _handler, root, recursive=False):
            scheduled.append(root)
            assert recursive is True

        def start(self):
            pass

        def stop(self):
            pass

        def join(self, timeout=None):
            pass

        def is_alive(self):
            return True

    root = tmp_path / "Music"
    artist = root / "Artist"
    album = artist / "Album"
    album.mkdir(parents=True)
    other = tmp_path / "Other"
    other.mkdir()
    monkeypatch.setattr(library_watcher_module, "Observer", FakeObserver)

    watcher = LibraryFolderWatcher()
    watcher.start([str(album), str(root), str(artist), str(other)])

    assert scheduled == [str(root), str(other)]
    watcher.stop()


def test_library_index_thread_settles_changed_paths_as_one_batch(monkeypatch):
    calls: list[str] = []
    sleeps: list[float] = []

    def fake_stat(path: str):
        calls.append(path)
        return (10, 1)

    monkeypatch.setattr(library_watcher_module, "_stat_signature", fake_stat)
    monkeypatch.setattr(library_watcher_module.time, "sleep", sleeps.append)
    worker = LibraryIndexThread(object(), WatchBatch(), settle_ms=300)

    worker._wait_for_stable_batch(["/music/a.flac", "/music/b.flac"])

    assert sleeps == [0.1]
    assert calls == [
        "/music/a.flac",
        "/music/b.flac",
        "/music/a.flac",
        "/music/b.flac",
    ]


def test_library_index_thread_applies_watched_folder_batch(tmp_path, monkeypatch):
    monkeypatch.setattr(
        library_module,
        "MutagenFile",
        lambda path, **_kwargs: _FakeAudio(Path(path).stem),
    )
    path = tmp_path / "song.flac"
    _set_file_state(path, b"one", 1_700_000_000_000_000_000)
    library = Library(tmp_path / "library.db")
    try:
        batch = WatchBatch(changed_paths={str(path)})
        worker = LibraryIndexThread(library, batch, settle_ms=0)
        worker.run()

        assert [track.title for track in library.all_tracks()] == ["song"]

        path.unlink()
        batch = WatchBatch(deleted_paths={str(path)})
        worker = LibraryIndexThread(library, batch, settle_ms=0)
        worker.run()

        assert list(library.all_tracks()) == []
    finally:
        library.close()


def test_library_index_thread_reindexes_stale_delete_event_when_file_exists(tmp_path):
    media_dir = tmp_path / "YouTube" / "Uploader"
    media_dir.mkdir(parents=True)
    video = media_dir / "Example Video.mp4"
    video.write_bytes(b"not a real mp4")

    library = Library(tmp_path / "library.db")
    try:
        assert library.index_file(video).status == "added"
        library.commit()
        assert next(library.all_tracks(media_type="video")).artwork_path is None

        thumbnail = media_dir / "Example Video.jpg"
        thumbnail.write_bytes(b"thumbnail")
        summaries = []
        worker = LibraryIndexThread(
            library,
            WatchBatch(deleted_paths={str(video)}),
            settle_ms=0,
        )
        worker.finished_with.connect(summaries.append)
        worker.run()

        track = next(library.all_tracks(media_type="video"))
        assert track.path == str(video)
        assert track.artwork_path == str(thumbnail)
        assert summaries[0].removed == 0
        assert summaries[0].updated == 1
    finally:
        library.close()


def test_folder_move_batch_preserves_track_ids_and_playlist_state(tmp_path, monkeypatch):
    monkeypatch.setattr(
        library_module,
        "MutagenFile",
        lambda path, **_kwargs: _FakeAudio(Path(path).stem),
    )
    old_folder = tmp_path / "Music" / "Old Album"
    new_folder = tmp_path / "Music" / "New Album"
    old_folder.mkdir(parents=True)
    old_path = old_folder / "song.flac"
    _set_file_state(old_path, b"one", 1_700_000_000_000_000_000)

    library = Library(tmp_path / "library.db")
    try:
        assert library.index_file(old_path).status == "added"
        library.commit()
        track = next(library.all_tracks())
        playlist_id = library.create_playlist("Folder Move")
        library.add_to_playlist(playlist_id, [track.id])
        library.update_rating(track.id, 5)

        new_folder.parent.mkdir(parents=True, exist_ok=True)
        old_folder.rename(new_folder)
        new_path = new_folder / "song.flac"
        os.utime(new_path, ns=(1_700_000_300_000_000_000, 1_700_000_300_000_000_000))

        worker = LibraryIndexThread(
            library,
            WatchBatch(moved_folders={str(old_folder): str(new_folder)}),
            settle_ms=0,
        )
        worker.run()

        moved = next(library.all_tracks())
        assert moved.id == track.id
        assert moved.path == str(new_path)
        assert moved.rating == 5
        assert [t.id for t in library.playlist_tracks(playlist_id)] == [track.id]
    finally:
        library.close()


def test_artwork_folder_scan_forces_unchanged_media_refresh(tmp_path, monkeypatch):
    calls = []

    def fake_mutagen(path, **_kwargs):
        calls.append(str(path))
        return _FakeAudio(Path(path).stem)

    monkeypatch.setattr(library_module, "MutagenFile", fake_mutagen)
    album = tmp_path / "Album"
    album.mkdir()
    media = album / "song.flac"
    _set_file_state(media, b"one", 1_700_000_000_000_000_000)

    library = Library(tmp_path / "library.db")
    try:
        assert library.index_file(media).status == "added"
        library.commit()
        assert next(library.all_tracks()).artwork_path is None

        cover = album / "cover.jpg"
        cover.write_bytes(b"cover")
        worker = LibraryIndexThread(
            library,
            WatchBatch(scan_roots={str(album)}),
            settle_ms=0,
        )
        worker.run()

        track = next(library.all_tracks())
        assert track.artwork_path == str(cover)
        assert calls == [str(media), str(media)]
    finally:
        library.close()


def test_watchdog_handler_emits_folder_refresh_for_artwork_sidecars(qapp):
    watcher = LibraryFolderWatcher()
    captured = []
    watcher.folders_changed.connect(captured.extend)

    class Event:
        is_directory = False

        def __init__(self, src_path: str):
            self.src_path = src_path

    from lyon.core.library_watcher import _WatchdogHandler

    _WatchdogHandler(watcher).on_modified(Event("/music/Album/cover.jpg"))

    assert captured == ["/music/Album"]


def test_index_file_recovers_disc_id_from_audio_tags(tmp_path, monkeypatch):
    """When a file's tags contain a musicbrainz_discid, index_file should
    populate the disc_id column even without an explicit disc_id argument.
    This is the key fix for the fresh-install-then-scan edge case.
    """

    class _FakeAudioWithDiscId(dict):
        info = _FakeInfo()

        def get(self, key):
            return {
                "title": ["Track 01"],
                "artist": ["Artist"],
                "albumartist": ["Artist"],
                "album": ["Album"],
                "tracknumber": ["1"],
                "discnumber": ["1"],
                "date": ["2024"],
                "genre": ["Rock"],
                "musicbrainz_discid": ["abc123XYZ"],
                "grouping": [""],
            }.get(key)

    monkeypatch.setattr(
        library_module, "MutagenFile",
        lambda *_a, **_kw: _FakeAudioWithDiscId(),
    )
    path = tmp_path / "track01.flac"
    _set_file_state(path, b"audio", 1_700_000_000_000_000_000)

    library = Library(tmp_path / "library.db")
    result = library.index_file(path)
    library.commit()

    assert result.status == "added"
    assert library.has_disc("abc123XYZ", 1)


def test_index_file_backfills_disc_id_from_tags_for_unchanged_existing_row(tmp_path, monkeypatch):
    """A rescan recovers disc_id tags for never-checked (NULL) rows.

    Rows written before the disc_id column existed (pre-v2) have NULL there;
    the first unchanged-file rescan reads tags once to backfill.  Rows whose
    tags were already read store '' (checked, absent) and are never re-read —
    a real tag edit changes size/mtime and takes the full reindex path, which
    picks the new disc ID up there.
    """

    class _FakeAudioWithMutableDiscId(dict):
        info = _FakeInfo()
        disc_id = ""

        def get(self, key):
            return {
                "title": ["Track 01"],
                "artist": ["Artist"],
                "albumartist": ["Artist"],
                "album": ["Album"],
                "tracknumber": ["1"],
                "discnumber": ["1"],
                "date": ["2024"],
                "genre": ["Rock"],
                "musicbrainz_discid": [self.disc_id] if self.disc_id else None,
                "grouping": [""],
            }.get(key)

    fake_audio = _FakeAudioWithMutableDiscId()
    monkeypatch.setattr(
        library_module, "MutagenFile",
        lambda *_a, **_kw: fake_audio,
    )
    path = tmp_path / "track01.flac"
    _set_file_state(path, b"audio", 1_700_000_000_000_000_000)

    library = Library(tmp_path / "library.db")
    try:
        assert library.index_file(path).status == "added"
        library.commit()
        assert not library.has_disc("abc123XYZ", 1)

        # Simulate a pre-v2 row: the disc_id column was never populated.
        library.conn.execute("UPDATE tracks SET disc_id = NULL")
        library.commit()

        fake_audio.disc_id = "abc123XYZ"
        assert library.index_file(path).status == "unchanged"
        library.commit()

        assert library.has_disc("abc123XYZ", 1)
    finally:
        library.close()

import os
from pathlib import Path

from lyon.core import library as library_module
from lyon.core import library_watcher as library_watcher_module
from lyon.core.library import Library
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
        added = library.index_file(path)
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

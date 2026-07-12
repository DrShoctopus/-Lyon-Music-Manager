from pathlib import Path

from lyon.core import library as library_module
from lyon.core.library import SUPPORTED_AUDIO_EXTS, Library


def add_track(
    library: Library,
    path: str,
    artist: str = "",
    album_artist: str = "",
    album: str = "",
    media_type: str = "audio",
    genre: str = "",
) -> None:
    library.conn.execute(
        """INSERT INTO tracks
           (path, title, artist, album_artist, album, track_no, disc_no, year, genre, duration, bitrate, samplerate, media_type)
           VALUES (?, ?, ?, ?, ?, 1, 1, 0, ?, 60.0, 320000, 48000, ?)""",
        (path, Path(path).stem, artist, album_artist, album, genre, media_type),
    )
    library.conn.commit()


def test_blank_artist_and_album_tracks_are_browsable(tmp_path):
    library = Library(tmp_path / "library.db")
    add_track(library, "/music/untagged.flac")

    assert library.all_artists() == ["Unknown Artist"]
    assert library.albums_for_artist("Unknown Artist") == [("Unknown Album", None)]

    tracks = library.tracks_for_album("Unknown Artist", "Unknown Album")
    assert [track.title for track in tracks] == ["untagged"]


def test_blank_album_tracks_are_returned_from_display_album_name(tmp_path):
    library = Library(tmp_path / "library.db")
    add_track(library, "/music/song.flac", artist="Artist")

    assert library.albums_for_artist("Artist") == [("Unknown Album", None)]

    tracks = library.tracks_for_album("Artist", "Unknown Album")
    assert [track.path for track in tracks] == ["/music/song.flac"]


def test_album_artist_falls_back_to_track_artist_only_when_blank(tmp_path):
    library = Library(tmp_path / "library.db")
    add_track(
        library,
        "/music/album_artist.flac",
        artist="Track Artist",
        album_artist="Album Artist",
        album="Album",
    )
    add_track(library, "/music/track_artist.flac", artist="Track Artist", album="Album")

    assert library.all_artists() == ["Album Artist", "Track Artist"]
    assert [track.path for track in library.tracks_for_album("Album Artist", "Album")] == [
        "/music/album_artist.flac"
    ]
    assert [track.path for track in library.tracks_for_album("Track Artist", "Album")] == [
        "/music/track_artist.flac"
    ]


def test_search_matches_album_artist_and_display_fallbacks(tmp_path):
    library = Library(tmp_path / "library.db")
    add_track(
        library,
        "/music/album_artist_search.flac",
        artist="Track Artist",
        album_artist="Album Artist",
        album="Album",
    )
    add_track(library, "/music/unknowns.flac")

    assert [track.path for track in library.search("Album Artist")] == [
        "/music/album_artist_search.flac"
    ]
    assert [track.path for track in library.search("Unknown Album")] == [
        "/music/unknowns.flac"
    ]


def test_track_rows_include_audio_details(tmp_path):
    library = Library(tmp_path / "library.db")
    add_track(library, "/music/song.flac", artist="Artist", album="Album")

    track = library.tracks_for_album("Artist", "Album")[0]

    assert track.bitrate == 320000
    assert track.samplerate == 48000


def test_video_resume_position_round_trips(tmp_path):
    library = Library(tmp_path / "library.db")
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"video")
    assert library.add_file(video)
    track = next(library.all_tracks(media_type="video"))

    library.update_resume_position(track.id, 45_000)
    updated = next(library.all_tracks(media_type="video"))

    assert updated.resume_position == 45_000


def test_all_tracks_iterates_over_a_consistent_snapshot(tmp_path, monkeypatch):
    library = Library(tmp_path / "library.db")
    monkeypatch.setattr(library_module, "_PAGE_SIZE", 1)
    add_track(library, "/music/first.flac", artist="Artist", album="Album")

    tracks = library.all_tracks()
    first = next(tracks)
    add_track(library, "/music/second.flac", artist="Artist", album="Album")

    assert first.path == "/music/first.flac"
    assert list(tracks) == []


def test_resume_position_update_ignores_audio_tracks(tmp_path):
    library = Library(tmp_path / "library.db")
    add_track(library, "/music/song.flac", artist="Artist", album="Album")
    track = next(library.all_tracks())

    library.update_resume_position(track.id, 45_000)
    updated = next(library.all_tracks())

    assert updated.resume_position == 0


def test_tracks_for_artist_returns_all_albums_without_extra_view_queries(tmp_path):
    library = Library(tmp_path / "library.db")
    add_track(library, "/music/a_first.flac", artist="Artist", album="First")
    add_track(library, "/music/b_second.flac", artist="Artist", album="Second")
    add_track(library, "/music/c_other.flac", artist="Other", album="First")

    tracks = library.tracks_for_artist("Artist")

    assert [track.path for track in tracks] == [
        "/music/a_first.flac",
        "/music/b_second.flac",
    ]


def test_all_albums_respects_media_type_filter(tmp_path):
    library = Library(tmp_path / "library.db")
    add_track(library, "/music/song.flac", artist="Artist", album="Album")
    add_track(
        library,
        "/videos/clip.mp4",
        artist="Video Artist",
        album="Videos",
        media_type="video",
    )

    assert library.all_albums("audio") == [("Artist", "Album", None)]
    assert library.all_albums("video") == [("Video Artist", "Videos", None)]
    assert library.all_albums() == [
        ("Artist", "Album", None),
        ("Video Artist", "Videos", None),
    ]


def test_albums_for_genre_returns_lean_album_summaries(tmp_path):
    library = Library(tmp_path / "library.db")
    add_track(
        library,
        "/music/rock-a.flac",
        artist="Artist",
        album="Rock Album",
        genre="Rock",
    )
    add_track(
        library,
        "/music/rock-b.flac",
        artist="Artist",
        album="Rock Album",
        genre="Rock",
    )
    add_track(
        library,
        "/music/jazz.flac",
        artist="Other",
        album="Jazz Album",
        genre="Jazz",
    )

    assert library.albums_for_genre("Rock", "audio") == [
        ("Artist", "Rock Album", None)
    ]


def test_album_summary_pages_are_bounded_and_filterable(tmp_path):
    library = Library(tmp_path / "library.db")
    for i in range(5):
        add_track(
            library,
            f"/music/{i}.flac",
            artist="Artist",
            album=f"Album {i}",
            genre="Rock" if i < 4 else "Jazz",
        )

    assert library.album_summaries_page(
        limit=2,
        offset=1,
        media_type="audio",
        genre="Rock",
    ) == [
        ("Artist", "Album 1", None),
        ("Artist", "Album 2", None),
    ]


def test_playlist_rows_cascade_when_playlist_or_track_is_deleted(tmp_path):
    library = Library(tmp_path / "library.db")
    add_track(library, "/music/song_one.flac", artist="Artist", album="Album")
    add_track(library, "/music/song_two.flac", artist="Artist", album="Album")
    first, second = list(library.all_tracks())

    playlist_id = library.create_playlist("Manual")
    library.add_to_playlist(playlist_id, [first.id, second.id])

    library.delete_track(first.id)

    assert [track.id for track in library.playlist_tracks(playlist_id)] == [second.id]

    library.delete_playlist(playlist_id)
    count = library.conn.execute("SELECT COUNT(*) FROM playlist_tracks").fetchone()[0]
    assert count == 0


def test_add_file_backfills_disc_id_for_existing_track(tmp_path):
    """add_file() must write disc_id even when the path already exists in the DB.

    Without this, tracks scanned before disc-ID support was added would never
    get their disc_id populated, so has_disc() would always return False and
    the "Already in library" dialog would never appear.
    """
    library = Library(tmp_path / "library.db")
    # Simulate a track added before disc_id support (no disc_id column value).
    add_track(library, "/music/track01.flac", artist="Artist", album="Album")

    # Confirm no disc_id is set yet.
    assert not library.has_disc("DISCID123", 1)

    # Re-add the same path with a disc_id (simulates re-ripping or backfill).
    library.add_file("/music/track01.flac", disc_id="DISCID123")
    library.commit()

    assert library.has_disc("DISCID123", 1)


def test_find_album_match_returns_match_on_artist_album_track_count(tmp_path):
    library = Library(tmp_path / "library.db")
    for i in range(1, 11):
        add_track(library, f"/music/track{i:02d}.flac", artist="Artist", album="Album")
    assert library.find_album_match("Artist", "Album", 10) == ("Artist", "Album")


def test_find_album_match_is_case_insensitive(tmp_path):
    library = Library(tmp_path / "library.db")
    for i in range(1, 4):
        add_track(library, f"/music/t{i}.flac", artist="The Band", album="Greatest Hits")
    assert library.find_album_match("the band", "greatest hits", 3) is not None


def test_find_album_match_returns_none_when_track_count_differs(tmp_path):
    library = Library(tmp_path / "library.db")
    for i in range(1, 6):
        add_track(library, f"/music/t{i}.flac", artist="Artist", album="Album")
    assert library.find_album_match("Artist", "Album", 10) is None


def test_find_album_match_returns_none_when_no_matching_album(tmp_path):
    library = Library(tmp_path / "library.db")
    add_track(library, "/music/t1.flac", artist="Artist", album="Album")
    assert library.find_album_match("Artist", "Other Album", 1) is None


def test_find_album_match_ignores_empty_inputs(tmp_path):
    library = Library(tmp_path / "library.db")
    add_track(library, "/music/t1.flac", artist="Artist", album="Album")
    assert library.find_album_match("", "Album", 1) is None
    assert library.find_album_match("Artist", "", 1) is None
    assert library.find_album_match("Artist", "Album", 0) is None


def test_video_file_prefers_same_stem_thumbnail_sidecar(tmp_path):
    library = Library(tmp_path / "library.db")
    media_dir = tmp_path / "YouTube" / "Uploader"
    media_dir.mkdir(parents=True)
    video = media_dir / "Example Video.mp4"
    video.write_bytes(b"not a real mp4")
    thumbnail = media_dir / "Example Video.jpg"
    thumbnail.write_bytes(b"thumbnail")
    folder_cover = media_dir / "cover.jpg"
    folder_cover.write_bytes(b"folder cover")

    assert library.add_file(video)
    library.commit()

    track = next(library.all_tracks(media_type="video"))
    assert track.artwork_path == str(thumbnail)


def test_video_file_uses_folder_art_when_no_same_stem_thumbnail(tmp_path):
    library = Library(tmp_path / "library.db")
    media_dir = tmp_path / "Videos"
    media_dir.mkdir()
    video = media_dir / "Local Clip.mp4"
    video.write_bytes(b"not a real mp4")
    folder_cover = media_dir / "cover.jpg"
    folder_cover.write_bytes(b"folder cover")

    assert library.add_file(video)
    library.commit()

    track = next(library.all_tracks(media_type="video"))
    assert track.artwork_path == str(folder_cover)


def _add_track_with_genre(
    library: Library,
    path: str,
    *,
    artist: str = "",
    album_artist: str = "",
    album: str = "",
    genre: str | None = None,
    media_type: str = "audio",
) -> None:
    library.conn.execute(
        """INSERT INTO tracks
           (path, title, artist, album_artist, album, track_no, disc_no, year,
            genre, duration, bitrate, samplerate, media_type)
           VALUES (?, ?, ?, ?, ?, 1, 1, 0, ?, 60.0, 320000, 48000, ?)""",
        (path, Path(path).stem, artist, album_artist, album, genre, media_type),
    )
    library.conn.commit()


def test_media_counts_by_artist_returns_sorted_pairs(tmp_path):
    library = Library(tmp_path / "library.db")
    _add_track_with_genre(library, "/music/z1.flac", artist="Zeppelin")
    _add_track_with_genre(library, "/music/z2.flac", artist="Zeppelin")
    _add_track_with_genre(library, "/music/b1.flac", artist="Beatles")

    result = library.media_counts_by_artist()

    assert result == [("Beatles", 1), ("Zeppelin", 2)]


def test_media_counts_by_artist_filters_by_media_type(tmp_path):
    library = Library(tmp_path / "library.db")
    _add_track_with_genre(library, "/music/a.flac", artist="Audio Artist", media_type="audio")
    _add_track_with_genre(library, "/video/v.mp4", artist="Video Artist", media_type="video")

    audio_counts = library.media_counts_by_artist("audio")
    video_counts = library.media_counts_by_artist("video")

    assert audio_counts == [("Audio Artist", 1)]
    assert video_counts == [("Video Artist", 1)]


def test_media_counts_by_album_collapses_empty_album_to_unknown(tmp_path):
    library = Library(tmp_path / "library.db")
    _add_track_with_genre(library, "/music/a.flac", artist="Artist", album="")
    _add_track_with_genre(library, "/music/b.flac", artist="Artist", album="")

    result = library.media_counts_by_album()

    assert result == [("Artist", "Unknown Album", 2)]


def test_media_counts_by_album_returns_sorted_triples(tmp_path):
    library = Library(tmp_path / "library.db")
    _add_track_with_genre(library, "/music/a1.flac", artist="Artist A", album="Alpha")
    _add_track_with_genre(library, "/music/a2.flac", artist="Artist A", album="Alpha")
    _add_track_with_genre(library, "/music/a3.flac", artist="Artist A", album="Beta")
    _add_track_with_genre(library, "/music/b1.flac", artist="Artist B", album="Gamma")

    result = library.media_counts_by_album()

    assert result == [
        ("Artist A", "Alpha", 2),
        ("Artist A", "Beta", 1),
        ("Artist B", "Gamma", 1),
    ]


def test_media_counts_by_album_filters_by_media_type(tmp_path):
    library = Library(tmp_path / "library.db")
    _add_track_with_genre(library, "/music/a.flac", artist="Audio Artist", album="Album A", media_type="audio")
    _add_track_with_genre(library, "/video/v.mp4", artist="Video Artist", album="Album V", media_type="video")

    assert library.media_counts_by_album("audio") == [("Audio Artist", "Album A", 1)]
    assert library.media_counts_by_album("video") == [("Video Artist", "Album V", 1)]


def test_media_counts_by_genre_excludes_null_and_empty_genre(tmp_path):
    library = Library(tmp_path / "library.db")
    _add_track_with_genre(library, "/music/a.flac", genre="Jazz")
    _add_track_with_genre(library, "/music/b.flac", genre=None)
    _add_track_with_genre(library, "/music/c.flac", genre="")

    result = library.media_counts_by_genre()

    assert result == [("Jazz", 1)]


def test_media_counts_by_genre_returns_sorted_pairs(tmp_path):
    library = Library(tmp_path / "library.db")
    _add_track_with_genre(library, "/music/j1.flac", genre="Jazz")
    _add_track_with_genre(library, "/music/j2.flac", genre="Jazz")
    _add_track_with_genre(library, "/music/b1.flac", genre="Blues")

    result = library.media_counts_by_genre()

    assert result == [("Blues", 1), ("Jazz", 2)]


def test_media_counts_by_genre_filters_by_media_type(tmp_path):
    library = Library(tmp_path / "library.db")
    _add_track_with_genre(library, "/music/a.flac", genre="Rock", media_type="audio")
    _add_track_with_genre(library, "/video/v.mp4", genre="Documentary", media_type="video")

    assert library.media_counts_by_genre("audio") == [("Rock", 1)]
    assert library.media_counts_by_genre("video") == [("Documentary", 1)]


def test_aiff_rip_outputs_are_scannable_audio_files(tmp_path, monkeypatch):
    class FakeInfo:
        length = 42.0
        bitrate = 1411000
        sample_rate = 44100

    class FakeAudio(dict):
        info = FakeInfo()

        def get(self, key):
            return {
                "title": ["AIFF Track"],
                "artist": ["Artist"],
                "album": ["Album"],
                "tracknumber": ["1"],
            }.get(key)

    monkeypatch.setattr(library_module, "MutagenFile", lambda *_args, **_kwargs: FakeAudio())

    library = Library(tmp_path / "library.db")
    path = tmp_path / "Artist" / "Album" / "01 - AIFF Track.aiff"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"fake aiff")

    assert ".aiff" in SUPPORTED_AUDIO_EXTS
    assert ".aif" in SUPPORTED_AUDIO_EXTS
    assert library.scan_paths([tmp_path]) == 1

    track = next(library.all_tracks())
    assert track.path == str(path)
    assert track.media_type == "audio"

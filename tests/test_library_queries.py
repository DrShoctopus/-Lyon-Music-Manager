from pathlib import Path

from lyon.core.library import Library


def add_track(
    library: Library,
    path: str,
    artist: str = "",
    album_artist: str = "",
    album: str = "",
) -> None:
    library.conn.execute(
        """INSERT INTO tracks
           (path, title, artist, album_artist, album, track_no, disc_no, year, genre, duration, bitrate, samplerate)
           VALUES (?, ?, ?, ?, ?, 1, 1, 0, '', 60.0, 320000, 48000)""",
        (path, Path(path).stem, artist, album_artist, album),
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

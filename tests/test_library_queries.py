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
           (path, title, artist, album_artist, album, track_no, disc_no, year, genre, duration)
           VALUES (?, ?, ?, ?, ?, 1, 1, 0, '', 60.0)""",
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

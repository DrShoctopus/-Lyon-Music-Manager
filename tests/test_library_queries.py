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
    assert [
        track.path for track in library.tracks_for_album("Album Artist", "Album")
    ] == ["/music/album_artist.flac"]
    assert [
        track.path for track in library.tracks_for_album("Track Artist", "Album")
    ] == ["/music/track_artist.flac"]


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


def test_add_file_commits_standalone_insert(tmp_path, monkeypatch):
    import sqlite3
    from lyon.core import library as library_module

    db = tmp_path / "library.db"
    audio = tmp_path / "song.flac"
    audio.write_bytes(b"fake")
    library = Library(db)

    monkeypatch.setattr(
        library_module,
        "_read_tags",
        lambda path: {
            "title": "Song",
            "artist": "Artist",
            "album_artist": "Artist",
            "album": "Album",
            "track_no": 1,
            "disc_no": 1,
            "year": 2026,
            "genre": "",
            "duration": 60.0,
            "bitrate": 0,
            "samplerate": 0,
        },
    )

    assert library.add_file(audio)

    with sqlite3.connect(db) as conn:
        rows = conn.execute("SELECT path, title FROM tracks").fetchall()
    assert rows == [(str(audio), "Song")]


def test_all_tracks_filters_by_search_genre_and_sorts_safely(tmp_path):
    library = Library(tmp_path / "library.db")
    add_track(library, "/music/b.flac", artist="Beta", album="Second")
    add_track(library, "/music/a.flac", artist="Alpha", album="First")
    library.conn.execute(
        "UPDATE tracks SET genre = 'Rock' WHERE path = ?", ("/music/b.flac",)
    )
    library.conn.execute(
        "UPDATE tracks SET genre = 'Jazz' WHERE path = ?", ("/music/a.flac",)
    )
    library.conn.commit()

    assert [track.path for track in library.all_tracks(sort="artist")] == [
        "/music/a.flac",
        "/music/b.flac",
    ]
    assert [
        track.path for track in library.all_tracks("sec", genre="Rock", sort="title")
    ] == ["/music/b.flac"]


def test_all_genres_omits_blank_values(tmp_path):
    library = Library(tmp_path / "library.db")
    add_track(library, "/music/blank.flac")
    add_track(library, "/music/rock.flac")
    library.conn.execute(
        "UPDATE tracks SET genre = 'Rock' WHERE path = ?", ("/music/rock.flac",)
    )
    library.conn.commit()

    assert library.all_genres() == ["Rock"]

from __future__ import annotations

from io import BytesIO
from pathlib import Path

from lyon.core.dlna_server import (
    DlnaServer,
    _encode_object_value,
    _is_allowed_client,
    _server_header,
)
from lyon.core.library import Library
from lyon.core.settings import Settings


def _insert_track(library: Library, path: Path, *, media_type: str = "audio") -> int:
    path.write_bytes(b"sample-media-bytes")
    cur = library.conn.execute(
        """INSERT INTO tracks
           (path, title, artist, album_artist, album, track_no, disc_no, year,
            genre, duration, bitrate, samplerate, media_type, file_size, file_mtime_ns)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            str(path),
            "Ocean Song",
            "Sea Artist",
            "Sea Artist",
            "Blue Album",
            1,
            1,
            2026,
            "Rock",
            185.25,
            320,
            44100,
            media_type,
            path.stat().st_size,
            path.stat().st_mtime_ns,
        ),
    )
    library.commit()
    return int(cur.lastrowid)


class _FakeHandler:
    def __init__(self, *, range_header: str = ""):
        self.headers = {"Range": range_header} if range_header else {}
        self.status = 0
        self.response_headers: dict[str, str] = {}
        self.wfile = BytesIO()

    def send_response(self, status) -> None:
        self.status = int(status)

    def send_header(self, name: str, value: str) -> None:
        self.response_headers[name] = value

    def end_headers(self) -> None:
        pass


def test_dlna_description_exposes_media_server(tmp_path):
    library = Library(tmp_path / "library.db")
    server = DlnaServer(
        library,
        Settings(music_root=str(tmp_path), dlna_port=0, dlna_friendly_name="Sea Test"),
    )
    try:
        body = server.description_xml().decode()
    finally:
        library.close()

    assert "<friendlyName>Sea Test</friendlyName>" in body
    assert "urn:schemas-upnp-org:device:MediaServer:1" in body
    assert "/ContentDirectory/control" in body


def test_dlna_server_header_does_not_disclose_host_os():
    header = _server_header()

    assert header.startswith("UPnP/1.0 SeaLyon/")
    assert "Darwin" not in header
    assert "Windows" not in header
    assert "Linux" not in header


def test_dlna_browse_returns_library_tracks(tmp_path):
    library = Library(tmp_path / "library.db")
    _insert_track(library, tmp_path / "song.mp3")
    server = DlnaServer(library, Settings(music_root=str(tmp_path), dlna_port=0))
    soap = b"""<?xml version="1.0"?>
<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/">
  <s:Body>
    <u:Browse xmlns:u="urn:schemas-upnp-org:service:ContentDirectory:1">
      <ObjectID>audio:all</ObjectID>
      <BrowseFlag>BrowseDirectChildren</BrowseFlag>
      <Filter>*</Filter>
      <StartingIndex>0</StartingIndex>
      <RequestedCount>0</RequestedCount>
      <SortCriteria></SortCriteria>
    </u:Browse>
    </s:Body>
</s:Envelope>"""
    try:
        server._base_url = "http://127.0.0.1:8200"
        body = server.handle_content_directory(soap).decode()
    finally:
        library.close()

    assert "BrowseResponse" in body
    assert "Ocean Song" in body
    assert "Sea Artist" in body
    assert "audio/mpeg" in body
    assert "NumberReturned>1<" in body


def test_dlna_browse_exposes_music_containers(tmp_path):
    library = Library(tmp_path / "library.db")
    _insert_track(library, tmp_path / "song.mp3")
    server = DlnaServer(library, Settings(music_root=str(tmp_path), dlna_port=0))
    soap = b"""<?xml version="1.0"?>
<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/">
  <s:Body>
    <u:Browse xmlns:u="urn:schemas-upnp-org:service:ContentDirectory:1">
      <ObjectID>audio</ObjectID>
      <BrowseFlag>BrowseDirectChildren</BrowseFlag>
      <Filter>*</Filter>
      <StartingIndex>0</StartingIndex>
      <RequestedCount>0</RequestedCount>
      <SortCriteria></SortCriteria>
    </u:Browse>
    </s:Body>
</s:Envelope>"""
    try:
        body = server.handle_content_directory(soap).decode()
    finally:
        library.close()

    assert "All Music" in body
    assert "Artists" in body
    assert "Albums" in body
    assert "Genres" in body


def test_dlna_search_filters_library_tracks(tmp_path):
    library = Library(tmp_path / "library.db")
    _insert_track(library, tmp_path / "ocean.mp3")
    _insert_track(library, tmp_path / "other.mp3", media_type="audio")
    library.conn.execute("UPDATE tracks SET title = ? WHERE path = ?", ("Mountain Song", str(tmp_path / "other.mp3")))
    library.commit()
    server = DlnaServer(library, Settings(music_root=str(tmp_path), dlna_port=0))
    soap = b"""<?xml version="1.0"?>
<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/">
  <s:Body>
    <u:Search xmlns:u="urn:schemas-upnp-org:service:ContentDirectory:1">
      <ContainerID>0</ContainerID>
      <SearchCriteria>dc:title contains "Ocean"</SearchCriteria>
      <Filter>*</Filter>
      <StartingIndex>0</StartingIndex>
      <RequestedCount>0</RequestedCount>
      <SortCriteria></SortCriteria>
    </u:Search>
    </s:Body>
</s:Envelope>"""
    try:
        server._base_url = "http://127.0.0.1:8200"
        body = server.handle_content_directory(soap).decode()
    finally:
        library.close()

    assert "Ocean Song" in body
    assert "Mountain Song" not in body
    assert "NumberReturned>1<" in body


def test_dlna_search_upnp_audio_class_returns_music_tracks(tmp_path):
    library = Library(tmp_path / "library.db")
    _insert_track(library, tmp_path / "song.mp3")
    video_id = _insert_track(library, tmp_path / "clip.mp4", media_type="video")
    library.conn.execute(
        "UPDATE tracks SET title = ? WHERE id = ?",
        ("Sea Clip", video_id),
    )
    library.commit()
    server = DlnaServer(library, Settings(music_root=str(tmp_path), dlna_port=0))
    soap = b"""<?xml version="1.0"?>
<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/">
  <s:Body>
    <u:Search xmlns:u="urn:schemas-upnp-org:service:ContentDirectory:1">
      <ContainerID>0</ContainerID>
      <SearchCriteria>upnp:class derivedfrom "object.item.audioItem"</SearchCriteria>
      <Filter>*</Filter>
      <StartingIndex>0</StartingIndex>
      <RequestedCount>0</RequestedCount>
      <SortCriteria></SortCriteria>
    </u:Search>
    </s:Body>
</s:Envelope>"""
    try:
        server._base_url = "http://127.0.0.1:8200"
        body = server.handle_content_directory(soap).decode()
    finally:
        library.close()

    assert "Ocean Song" in body
    assert "object.item.audioItem.musicTrack" in body
    assert "Sea Clip" not in body
    assert "object.item.videoItem" not in body
    assert "NumberReturned>1<" in body


def test_dlna_browsed_music_tracks_keep_selected_container_parent(tmp_path):
    library = Library(tmp_path / "library.db")
    _insert_track(library, tmp_path / "song.mp3")
    server = DlnaServer(library, Settings(music_root=str(tmp_path), dlna_port=0))
    artist_id = f"artist:{_encode_object_value('Sea Artist')}"
    soap = f"""<?xml version="1.0"?>
<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/">
  <s:Body>
    <u:Browse xmlns:u="urn:schemas-upnp-org:service:ContentDirectory:1">
      <ObjectID>{artist_id}</ObjectID>
      <BrowseFlag>BrowseDirectChildren</BrowseFlag>
      <Filter>*</Filter>
      <StartingIndex>0</StartingIndex>
      <RequestedCount>0</RequestedCount>
      <SortCriteria></SortCriteria>
    </u:Browse>
    </s:Body>
</s:Envelope>""".encode()
    try:
        server._base_url = "http://127.0.0.1:8200"
        body = server.handle_content_directory(soap).decode()
    finally:
        library.close()

    assert "Ocean Song" in body
    assert f'parentID="{artist_id}"' in body


def test_dlna_media_endpoint_supports_byte_ranges(tmp_path):
    library = Library(tmp_path / "library.db")
    track_id = _insert_track(library, tmp_path / "clip.mp4", media_type="video")
    server = DlnaServer(library, Settings(music_root=str(tmp_path), dlna_port=0))
    handler = _FakeHandler(range_header="bytes=1-5")
    try:
        server.serve_media(handler, track_id, send_body=True)
        body = handler.wfile.getvalue()
    finally:
        library.close()

    assert handler.status == 206
    assert handler.response_headers["Content-Range"] == "bytes 1-5/18"
    assert handler.response_headers["Content-Type"] == "video/mp4"
    assert handler.response_headers["transferMode.dlna.org"] == "Streaming"
    assert body == b"ample"


def test_dlna_media_url_for_track_matches_servable_media(tmp_path):
    from unittest.mock import MagicMock
    library = Library(tmp_path / "library.db")
    track_id = _insert_track(library, tmp_path / "My Song.mp3")
    server = DlnaServer(library, Settings(music_root=str(tmp_path), dlna_port=0))
    server._base_url = "http://127.0.0.1:8200"
    # Simulate a running server so the CAST-2 guard passes.
    server._httpd = MagicMock()
    server._thread = MagicMock()
    server._thread.is_alive.return_value = True
    try:
        track = library.track_by_id(track_id)
        assert track is not None
        assert (
            server.media_url_for_track(track)
            == f"http://127.0.0.1:8200/media/{track_id}/My%20Song.mp3"
        )
    finally:
        library.close()


def test_dlna_media_url_returns_none_when_server_not_running(tmp_path):
    """CAST-2: media_url_for_track must return None when the DLNA server is stopped."""
    library = Library(tmp_path / "library.db")
    track_id = _insert_track(library, tmp_path / "song.mp3")
    server = DlnaServer(library, Settings(music_root=str(tmp_path), dlna_port=0))
    # Server not started: running is False and _base_url is "".
    try:
        track = library.track_by_id(track_id)
        assert track is not None
        assert server.media_url_for_track(track) is None
    finally:
        library.close()


def test_dlna_media_url_returns_none_when_base_url_empty(tmp_path):
    """CAST-2: media_url_for_track must return None when _base_url is cleared."""
    from unittest.mock import MagicMock
    library = Library(tmp_path / "library.db")
    track_id = _insert_track(library, tmp_path / "song.mp3")
    server = DlnaServer(library, Settings(music_root=str(tmp_path), dlna_port=0))
    # Simulate server stopped mid-cast: thread alive but base_url cleared.
    server._httpd = MagicMock()
    server._thread = MagicMock()
    server._thread.is_alive.return_value = True
    server._base_url = ""
    try:
        track = library.track_by_id(track_id)
        assert track is not None
        assert server.media_url_for_track(track) is None
    finally:
        library.close()


def test_dlna_browse_skips_track_deleted_after_cache_fill(tmp_path):
    library = Library(tmp_path / "library.db")
    track_path = tmp_path / "gone.mp3"
    _insert_track(library, track_path)
    server = DlnaServer(library, Settings(music_root=str(tmp_path), dlna_port=0))
    server._base_url = "http://127.0.0.1:8200"
    try:
        assert len(server._tracks("audio")) == 1
        track_path.unlink()
        items = server._track_items("audio")
    finally:
        library.close()

    assert items == []


def test_dlna_cache_invalidation_refreshes_track_list(tmp_path):
    library = Library(tmp_path / "library.db")
    _insert_track(library, tmp_path / "one.mp3")
    server = DlnaServer(library, Settings(music_root=str(tmp_path), dlna_port=0))
    try:
        assert len(server._tracks("audio")) == 1
        _insert_track(library, tmp_path / "two.mp3")
        assert len(server._tracks("audio")) == 1
        server.invalidate_cache()
        assert len(server._tracks("audio")) == 2
    finally:
        library.close()


def _insert_track_full(
    library: Library,
    path: Path,
    *,
    title: str = "Track",
    artist: str = "Artist",
    album_artist: str = "",
    album: str = "Album",
    genre: str = "Rock",
    media_type: str = "audio",
) -> int:
    path.write_bytes(b"sample-media-bytes")
    cur = library.conn.execute(
        """INSERT INTO tracks
           (path, title, artist, album_artist, album, track_no, disc_no, year,
            genre, duration, bitrate, samplerate, media_type, file_size, file_mtime_ns)
           VALUES (?, ?, ?, ?, ?, 1, 1, 2026, ?, 180.0, 320, 44100, ?, ?, ?)""",
        (
            str(path),
            title,
            artist,
            album_artist,
            album,
            genre,
            media_type,
            path.stat().st_size,
            path.stat().st_mtime_ns,
        ),
    )
    library.commit()
    return int(cur.lastrowid)


def test_dlna_artist_counts_returns_correct_counts_and_order(tmp_path):
    library = Library(tmp_path / "library.db")
    _insert_track_full(library, tmp_path / "a1.mp3", artist="Zeppelin", album="Houses")
    _insert_track_full(library, tmp_path / "a2.mp3", artist="Zeppelin", album="Physical Graffiti")
    _insert_track_full(library, tmp_path / "a3.mp3", artist="Beatles", album="Abbey Road")
    server = DlnaServer(library, Settings(music_root=str(tmp_path), dlna_port=0))
    try:
        counts = server._artist_counts("audio")
    finally:
        library.close()

    assert counts == {"Beatles": 1, "Zeppelin": 2}
    assert list(counts.keys()) == ["Beatles", "Zeppelin"]


def test_dlna_album_counts_returns_correct_counts_and_order(tmp_path):
    library = Library(tmp_path / "library.db")
    _insert_track_full(library, tmp_path / "b1.mp3", artist="Artist A", album="Alpha")
    _insert_track_full(library, tmp_path / "b2.mp3", artist="Artist A", album="Alpha")
    _insert_track_full(library, tmp_path / "b3.mp3", artist="Artist A", album="Beta")
    _insert_track_full(library, tmp_path / "b4.mp3", artist="Artist B", album="Gamma")
    server = DlnaServer(library, Settings(music_root=str(tmp_path), dlna_port=0))
    try:
        counts = server._album_counts("audio")
    finally:
        library.close()

    assert counts == {
        ("Artist A", "Alpha"): 2,
        ("Artist A", "Beta"): 1,
        ("Artist B", "Gamma"): 1,
    }
    assert list(counts.keys()) == [
        ("Artist A", "Alpha"),
        ("Artist A", "Beta"),
        ("Artist B", "Gamma"),
    ]


def test_dlna_genre_counts_returns_correct_counts_and_order(tmp_path):
    library = Library(tmp_path / "library.db")
    _insert_track_full(library, tmp_path / "g1.mp3", genre="Jazz")
    _insert_track_full(library, tmp_path / "g2.mp3", genre="Jazz")
    _insert_track_full(library, tmp_path / "g3.mp3", genre="Blues")
    server = DlnaServer(library, Settings(music_root=str(tmp_path), dlna_port=0))
    try:
        counts = server._genre_counts("audio")
    finally:
        library.close()

    assert counts == {"Blues": 1, "Jazz": 2}
    assert list(counts.keys()) == ["Blues", "Jazz"]


def test_dlna_rejects_track_outside_configured_library_roots(tmp_path):
    library_root = tmp_path / "Music"
    library_root.mkdir()
    outside_root = tmp_path / "Other"
    outside_root.mkdir()
    library = Library(tmp_path / "library.db")
    track_id = _insert_track(library, outside_root / "private.mp3")
    server = DlnaServer(library, Settings(music_root=str(library_root), dlna_port=0))
    handler = _FakeHandler()
    try:
        # HTTP serving must 404 for files outside the music root.
        server.serve_media(handler, track_id, send_body=True)
        assert handler.status == 404
        assert handler.wfile.getvalue() == b"Media file not found"

        # media_url_for_track must return None (server not running → guard fires).
        track = library.track_by_id(track_id)
        assert track is not None
        assert server.media_url_for_track(track) is None

        soap = b"""<?xml version="1.0"?>
<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/">
  <s:Body>
    <u:Browse xmlns:u="urn:schemas-upnp-org:service:ContentDirectory:1">
      <ObjectID>audio:artists</ObjectID>
      <BrowseFlag>BrowseDirectChildren</BrowseFlag>
      <Filter>*</Filter>
      <StartingIndex>0</StartingIndex>
      <RequestedCount>0</RequestedCount>
      <SortCriteria></SortCriteria>
    </u:Browse>
    </s:Body>
</s:Envelope>"""
        artists_body = server.handle_content_directory(soap).decode()

        # Verify that drilling into the artist yields no playable tracks.
        from lyon.core.dlna_server import _encode_object_value
        artist_container_id = f"artist:{_encode_object_value('Sea Artist')}"
        drill_soap = f"""<?xml version="1.0"?>
<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/">
  <s:Body>
    <u:Browse xmlns:u="urn:schemas-upnp-org:service:ContentDirectory:1">
      <ObjectID>{artist_container_id}</ObjectID>
      <BrowseFlag>BrowseDirectChildren</BrowseFlag>
      <Filter>*</Filter>
      <StartingIndex>0</StartingIndex>
      <RequestedCount>0</RequestedCount>
      <SortCriteria></SortCriteria>
    </u:Browse>
    </s:Body>
</s:Envelope>""".encode()
        drill_body = server.handle_content_directory(drill_soap).decode()
    finally:
        library.close()

    assert "Sea Artist" not in artists_body
    # No playable track items in the drill-down either (file is outside root).
    assert "NumberReturned>0<" in drill_body


def test_dlna_allows_only_local_network_clients():
    assert _is_allowed_client("127.0.0.1")
    assert _is_allowed_client("192.168.1.20")
    assert _is_allowed_client("10.4.3.2")
    assert _is_allowed_client("169.254.10.20")
    assert not _is_allowed_client("8.8.8.8")

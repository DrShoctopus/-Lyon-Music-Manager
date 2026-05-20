"""Minimal DLNA / UPnP MediaServer for the local library."""
from __future__ import annotations

import base64
import logging
import mimetypes
import platform
import socket
import threading
import time
import uuid
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from ipaddress import ip_address
from pathlib import Path
from typing import BinaryIO
from urllib.parse import quote, unquote, urlparse
from xml.sax.saxutils import escape

from defusedxml.ElementTree import fromstring

from .. import __app_name__, __version__
from .library import Library, Track
from .settings import Settings

LOG = logging.getLogger(__name__)

_SSDP_ADDR = ("239.255.255.250", 1900)
_CHUNK_SIZE = 256 * 1024
_MAX_SOAP_BODY = 1024 * 1024
_MAX_BROWSE_ITEMS = 500

_MIME_BY_EXT = {
    ".flac": "audio/flac",
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".aac": "audio/aac",
    ".ogg": "audio/ogg",
    ".opus": "audio/ogg",
    ".wav": "audio/wav",
    ".aiff": "audio/aiff",
    ".aif": "audio/aiff",
    ".wma": "audio/x-ms-wma",
    ".mp4": "video/mp4",
    ".mkv": "video/x-matroska",
    ".webm": "video/webm",
    ".avi": "video/x-msvideo",
    ".mov": "video/quicktime",
}


@dataclass(frozen=True)
class _BrowseItem:
    xml: str


class DlnaServer:
    """Expose library tracks as a UPnP ContentDirectory + HTTP media server."""

    def __init__(self, library: Library, settings: Settings):
        self.library = library
        self.settings = settings
        seed = f"sea-lyon:{Path(settings.music_root).expanduser()}"
        self.uuid = str(uuid.uuid5(uuid.NAMESPACE_URL, seed))
        self._httpd: "_DlnaHTTPServer | None" = None
        self._thread: threading.Thread | None = None
        self._ssdp: _SsdpResponder | None = None
        self._base_url = ""

    @property
    def running(self) -> bool:
        return self._httpd is not None and self._thread is not None and self._thread.is_alive()

    @property
    def base_url(self) -> str:
        return self._base_url

    def start(self) -> None:
        if self.running:
            return
        host = "0.0.0.0"
        port = int(self.settings.dlna_port)
        httpd = _DlnaHTTPServer((host, port), _DlnaRequestHandler)
        httpd.dlna = self
        actual_port = int(httpd.server_address[1])
        self._base_url = f"http://{_local_ip()}:{actual_port}"
        self._httpd = httpd
        self._thread = threading.Thread(
            target=httpd.serve_forever,
            name="LyonDLNAServer",
            daemon=True,
        )
        self._thread.start()
        self._ssdp = _SsdpResponder(self)
        self._ssdp.start()
        LOG.info("DLNA server listening at %s", self._base_url)

    def stop(self) -> None:
        if self._ssdp is not None:
            self._ssdp.stop()
            self._ssdp = None
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        self._base_url = ""

    def description_xml(self) -> bytes:
        udn = f"uuid:{self.uuid}"
        friendly = escape(self.settings.dlna_friendly_name)
        return f"""<?xml version="1.0" encoding="utf-8"?>
<root xmlns="urn:schemas-upnp-org:device-1-0">
  <specVersion><major>1</major><minor>0</minor></specVersion>
  <device>
    <deviceType>urn:schemas-upnp-org:device:MediaServer:1</deviceType>
    <friendlyName>{friendly}</friendlyName>
    <manufacturer>Sea Lyon</manufacturer>
    <modelName>{escape(__app_name__)}</modelName>
    <modelNumber>{escape(__version__)}</modelNumber>
    <UDN>{udn}</UDN>
    <serviceList>
      <service>
        <serviceType>urn:schemas-upnp-org:service:ContentDirectory:1</serviceType>
        <serviceId>urn:upnp-org:serviceId:ContentDirectory</serviceId>
        <SCPDURL>/ContentDirectory/scpd.xml</SCPDURL>
        <controlURL>/ContentDirectory/control</controlURL>
        <eventSubURL>/ContentDirectory/event</eventSubURL>
      </service>
      <service>
        <serviceType>urn:schemas-upnp-org:service:ConnectionManager:1</serviceType>
        <serviceId>urn:upnp-org:serviceId:ConnectionManager</serviceId>
        <SCPDURL>/ConnectionManager/scpd.xml</SCPDURL>
        <controlURL>/ConnectionManager/control</controlURL>
        <eventSubURL>/ConnectionManager/event</eventSubURL>
      </service>
    </serviceList>
  </device>
</root>
""".encode("utf-8")

    def content_directory_scpd(self) -> bytes:
        return _CONTENT_DIRECTORY_SCPD

    def connection_manager_scpd(self) -> bytes:
        return _CONNECTION_MANAGER_SCPD

    def handle_content_directory(self, body: bytes) -> bytes:
        root = fromstring(body)
        action = _soap_action(root)
        if action == "Search":
            return self._search_response(root)
        if action == "Browse":
            return self._browse_response(root)
        if action == "GetSearchCapabilities":
            return _soap_envelope(
                "GetSearchCapabilitiesResponse",
                "urn:schemas-upnp-org:service:ContentDirectory:1",
                "<SearchCaps>dc:title,dc:creator,upnp:artist,upnp:album</SearchCaps>",
            )
        if action == "GetSortCapabilities":
            return _soap_envelope(
                "GetSortCapabilitiesResponse",
                "urn:schemas-upnp-org:service:ContentDirectory:1",
                "<SortCaps>dc:title,dc:creator,upnp:album</SortCaps>",
            )
        if action == "GetSystemUpdateID":
            return _soap_envelope(
                "GetSystemUpdateIDResponse",
                "urn:schemas-upnp-org:service:ContentDirectory:1",
                "<Id>1</Id>",
            )
        return _soap_fault(401, "Invalid Action")

    def handle_connection_manager(self, body: bytes) -> bytes:
        root = fromstring(body)
        action = _soap_action(root)
        protocols = ",".join(
            f"http-get:*:{mime}:*" for mime in sorted(set(_MIME_BY_EXT.values()))
        )
        if action == "GetProtocolInfo":
            return _soap_envelope(
                "GetProtocolInfoResponse",
                "urn:schemas-upnp-org:service:ConnectionManager:1",
                f"<Source>{escape(protocols)}</Source><Sink></Sink>",
            )
        if action == "GetCurrentConnectionIDs":
            return _soap_envelope(
                "GetCurrentConnectionIDsResponse",
                "urn:schemas-upnp-org:service:ConnectionManager:1",
                "<ConnectionIDs>0</ConnectionIDs>",
            )
        if action == "GetCurrentConnectionInfo":
            return _soap_envelope(
                "GetCurrentConnectionInfoResponse",
                "urn:schemas-upnp-org:service:ConnectionManager:1",
                (
                    "<RcsID>-1</RcsID><AVTransportID>-1</AVTransportID>"
                    f"<ProtocolInfo>{escape(protocols)}</ProtocolInfo>"
                    "<PeerConnectionManager></PeerConnectionManager>"
                    "<PeerConnectionID>-1</PeerConnectionID>"
                    "<Direction>Output</Direction><Status>OK</Status>"
                ),
            )
        return _soap_fault(401, "Invalid Action")

    def serve_media(self, handler: BaseHTTPRequestHandler, track_id: int, *, send_body: bool) -> None:
        track = self.library.track_by_id(track_id)
        if track is None:
            _send_error(handler, HTTPStatus.NOT_FOUND, "Track not found")
            return
        path = self._track_file_path(track)
        if path is None or not path.exists() or not path.is_file():
            _send_error(handler, HTTPStatus.NOT_FOUND, "Media file not found")
            return
        mime = _mime_type(path)
        size = path.stat().st_size
        byte_range = _parse_range(handler.headers.get("Range"), size)
        if byte_range is None:
            start, end = 0, max(0, size - 1)
            status = HTTPStatus.OK
        elif byte_range == (-1, -1):
            _send_error(handler, HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE, "Invalid byte range")
            return
        else:
            start, end = byte_range
            status = HTTPStatus.PARTIAL_CONTENT

        length = max(0, end - start + 1)
        handler.send_response(status)
        handler.send_header("Content-Type", mime)
        handler.send_header("Accept-Ranges", "bytes")
        handler.send_header("Content-Length", str(length))
        handler.send_header("transferMode.dlna.org", "Streaming")
        handler.send_header("contentFeatures.dlna.org", "DLNA.ORG_OP=01;DLNA.ORG_CI=0")
        if status == HTTPStatus.PARTIAL_CONTENT:
            handler.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        handler.end_headers()
        if not send_body:
            return
        with path.open("rb") as fh:
            fh.seek(start)
            _copy_limited(fh, handler.wfile, length)

    def _browse_response(self, root) -> bytes:
        object_id = _xml_text(root, "ObjectID", "0")
        flag = _xml_text(root, "BrowseFlag", "BrowseDirectChildren")
        start = _nonnegative_xml_int(root, "StartingIndex", 0)
        count = _nonnegative_xml_int(root, "RequestedCount", 0)
        items = self._browse_items(object_id, flag)
        limit = _MAX_BROWSE_ITEMS if count <= 0 else min(count, _MAX_BROWSE_ITEMS)
        visible = items[start:start + limit]
        didl = _didl_xml(visible)
        payload = (
            f"<Result>{escape(didl)}</Result>"
            f"<NumberReturned>{len(visible)}</NumberReturned>"
            f"<TotalMatches>{len(items)}</TotalMatches>"
            "<UpdateID>1</UpdateID>"
        )
        return _soap_envelope(
            "BrowseResponse",
            "urn:schemas-upnp-org:service:ContentDirectory:1",
            payload,
        )

    def _search_response(self, root) -> bytes:
        start = _nonnegative_xml_int(root, "StartingIndex", 0)
        count = _nonnegative_xml_int(root, "RequestedCount", 0)
        query = _search_query(_xml_text(root, "SearchCriteria", ""))
        tracks = self._tracks_matching(query) if query else self._tracks()
        items = [self._track_item(track) for track in tracks]
        limit = _MAX_BROWSE_ITEMS if count <= 0 else min(count, _MAX_BROWSE_ITEMS)
        visible = items[start:start + limit]
        payload = (
            f"<Result>{escape(_didl_xml(visible))}</Result>"
            f"<NumberReturned>{len(visible)}</NumberReturned>"
            f"<TotalMatches>{len(items)}</TotalMatches>"
            "<UpdateID>1</UpdateID>"
        )
        return _soap_envelope(
            "SearchResponse",
            "urn:schemas-upnp-org:service:ContentDirectory:1",
            payload,
        )

    def _browse_items(self, object_id: str, flag: str) -> list[_BrowseItem]:
        if flag == "BrowseMetadata":
            if object_id == "0":
                return [_container("0", "-1", self.settings.dlna_friendly_name, 2)]
            if object_id == "audio":
                return [_container("audio", "0", "Music", 4)]
            if object_id == "video":
                return [_container("video", "0", "Videos", len(self._tracks("video")))]
            if object_id == "audio:all":
                return [_container("audio:all", "audio", "All Music", len(self._tracks("audio")))]
            if object_id == "audio:artists":
                return [_container("audio:artists", "audio", "Artists", len(self._artists("audio")))]
            if object_id == "audio:albums":
                return [_container("audio:albums", "audio", "Albums", len(self._albums("audio")))]
            if object_id == "audio:genres":
                return [_container("audio:genres", "audio", "Genres", len(self._genres("audio")))]
            if object_id == "video:all":
                return [_container("video:all", "video", "All Videos", len(self._tracks("video")))]
            if object_id.startswith("artist:"):
                artist = _decode_object_value(object_id.removeprefix("artist:"))
                tracks = self._tracks_for_artist(artist, "audio") if artist else []
                return [_container(object_id, "audio:artists", artist, len(tracks))] if artist else []
            if object_id.startswith("album:"):
                decoded = _decode_object_value(object_id.removeprefix("album:"))
                artist, album = _split_pair(decoded)
                tracks = self._tracks_for_album(artist, album, "audio") if artist and album else []
                return [_container(object_id, "audio:albums", album, len(tracks))] if artist and album else []
            if object_id.startswith("genre:"):
                genre = _decode_object_value(object_id.removeprefix("genre:"))
                tracks = self._tracks_for_genre(genre, "audio") if genre else []
                return [_container(object_id, "audio:genres", genre, len(tracks))] if genre else []
            if object_id.startswith("track:"):
                track = _track_from_object_id(self.library, object_id)
                return [self._track_item(track)] if track and self._track_file_path(track) else []
            return []
        if object_id == "0":
            return [
                _container("audio", "0", "Music", 4),
                _container("video", "0", "Videos", len(self._tracks("video"))),
            ]
        if object_id == "audio":
            return [
                _container("audio:all", "audio", "All Music", len(self._tracks("audio"))),
                _container("audio:artists", "audio", "Artists", len(self._artists("audio"))),
                _container("audio:albums", "audio", "Albums", len(self._albums("audio"))),
                _container("audio:genres", "audio", "Genres", len(self._genres("audio"))),
            ]
        if object_id == "audio:all":
            return self._track_items("audio")
        if object_id == "audio:artists":
            return [
                _container(
                    f"artist:{_encode_object_value(artist)}",
                    "audio:artists",
                    artist,
                    len(self._tracks_for_artist(artist, "audio")),
                )
                for artist in self._artists("audio")
            ]
        if object_id.startswith("artist:"):
            artist = _decode_object_value(object_id.removeprefix("artist:"))
            return [self._track_item(track) for track in self._tracks_for_artist(artist, "audio")] if artist else []
        if object_id == "audio:albums":
            return [
                _container(
                    f"album:{_encode_object_value(_join_pair(artist, album))}",
                    "audio:albums",
                    f"{artist} - {album}",
                    len(self._tracks_for_album(artist, album, "audio")),
                )
                for artist, album in self._albums("audio")
            ]
        if object_id.startswith("album:"):
            decoded = _decode_object_value(object_id.removeprefix("album:"))
            artist, album = _split_pair(decoded)
            return [self._track_item(track) for track in self._tracks_for_album(artist, album, "audio")] if artist and album else []
        if object_id == "audio:genres":
            return [
                _container(
                    f"genre:{_encode_object_value(genre)}",
                    "audio:genres",
                    genre,
                    len(self._tracks_for_genre(genre, "audio")),
                )
                for genre in self._genres("audio")
            ]
        if object_id.startswith("genre:"):
            genre = _decode_object_value(object_id.removeprefix("genre:"))
            return [self._track_item(track) for track in self._tracks_for_genre(genre, "audio")] if genre else []
        if object_id == "video":
            return [_container("video:all", "video", "All Videos", len(self._tracks("video")))]
        if object_id == "video:all":
            return self._track_items("video")
        return []

    def _track_items(self, media_type: str | None = None) -> list[_BrowseItem]:
        return [self._track_item(track) for track in self._tracks(media_type)]

    def _artists(self, media_type: str) -> list[str]:
        return sorted({track.display_artist for track in self._tracks(media_type)}, key=str.casefold)

    def _albums(self, media_type: str) -> list[tuple[str, str]]:
        albums = {
            (track.display_artist, track.album or "Unknown Album")
            for track in self._tracks(media_type)
        }
        return sorted(albums, key=lambda item: (item[0].casefold(), item[1].casefold()))

    def _genres(self, media_type: str) -> list[str]:
        return sorted({track.genre for track in self._tracks(media_type) if track.genre}, key=str.casefold)

    def _tracks(self, media_type: str | None = None) -> list[Track]:
        tracks: list[Track] = []
        for track in self.library.all_tracks():
            if track.media_type not in {"audio", "video"}:
                continue
            if media_type is not None and track.media_type != media_type:
                continue
            path = self._track_file_path(track)
            if path is None or not path.exists() or not path.is_file():
                continue
            tracks.append(track)
        return tracks

    def _tracks_for_artist(self, artist: str, media_type: str) -> list[Track]:
        return self._filter_tracks(self.library.tracks_for_artist(artist, media_type))

    def _tracks_for_album(self, artist: str, album: str, media_type: str) -> list[Track]:
        return self._filter_tracks(self.library.tracks_for_album(artist, album, media_type))

    def _tracks_for_genre(self, genre: str, media_type: str) -> list[Track]:
        return self._filter_tracks(self.library.tracks_for_genre(genre, media_type))

    def _tracks_matching(self, query: str) -> list[Track]:
        return self._filter_tracks(self.library.search(query))

    def _filter_tracks(self, tracks: list[Track]) -> list[Track]:
        return [
            track
            for track in tracks
            if track.media_type in {"audio", "video"}
            and (path := self._track_file_path(track)) is not None
            and path.exists()
            and path.is_file()
        ]

    def _track_file_path(self, track: Track) -> Path | None:
        path = _track_file_path(track)
        if path is None:
            return None
        resolved = _resolved_path(path)
        if resolved is None or not _path_is_under_roots(resolved, self._library_roots()):
            return None
        return resolved

    def _library_roots(self) -> list[Path]:
        roots = [Path(self.settings.music_root), *(Path(p) for p in self.settings.library_paths)]
        return [resolved for root in roots if (resolved := _resolved_path(root)) is not None]

    def _track_item(self, track: Track) -> _BrowseItem:
        path = self._track_file_path(track)
        assert path is not None
        mime = _mime_type(path)
        parent = "video" if track.media_type == "video" else "audio"
        upnp_class = "object.item.videoItem" if track.media_type == "video" else "object.item.audioItem.musicTrack"
        url = f"{self.base_url}/media/{track.id}/{quote(path.name)}"
        stat = path.stat()
        attrs = f'protocolInfo="http-get:*:{escape(mime)}:*" size="{stat.st_size}"'
        if track.duration > 0:
            attrs += f' duration="{_duration_text(track.duration)}"'
        title = escape(track.title or path.stem)
        artist = escape(track.display_artist)
        album = escape(track.album or "")
        xml = (
            f'<item id="track:{track.id}" parentID="{parent}" restricted="1">'
            f"<dc:title>{title}</dc:title>"
            f"<dc:creator>{artist}</dc:creator>"
            f"<upnp:artist>{artist}</upnp:artist>"
            f"<upnp:album>{album}</upnp:album>"
            f"<upnp:class>{upnp_class}</upnp:class>"
            f"<res {attrs}>{escape(url)}</res>"
            "</item>"
        )
        return _BrowseItem(xml)


class _DlnaHTTPServer(ThreadingHTTPServer):
    dlna: DlnaServer
    allow_reuse_address = True
    daemon_threads = True


class _DlnaRequestHandler(BaseHTTPRequestHandler):
    server: _DlnaHTTPServer
    server_version = f"SeaLyon/{__version__}"
    sys_version = "UPnP/1.0"

    def setup(self) -> None:
        super().setup()
        self.request.settimeout(10.0)

    def log_message(self, fmt: str, *args) -> None:  # pragma: no cover - noisy server hook
        LOG.debug("DLNA HTTP: " + fmt, *args)

    def do_GET(self) -> None:
        if not self._client_allowed():
            return
        self._route(send_body=True)

    def do_HEAD(self) -> None:
        if not self._client_allowed():
            return
        self._route(send_body=False)

    def do_POST(self) -> None:
        if not self._client_allowed():
            return
        parsed = urlparse(self.path)
        try:
            length = int(self.headers.get("Content-Length", "0") or 0)
        except ValueError:
            _send_error(self, HTTPStatus.BAD_REQUEST, "Invalid Content-Length")
            return
        if length <= 0:
            _send_error(self, HTTPStatus.LENGTH_REQUIRED, "Content-Length required")
            return
        if length > _MAX_SOAP_BODY:
            _send_error(self, HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "DLNA control request is too large")
            return
        body = self.rfile.read(length)
        try:
            if parsed.path == "/ContentDirectory/control":
                _send_xml(self, self.server.dlna.handle_content_directory(body))
            elif parsed.path == "/ConnectionManager/control":
                _send_xml(self, self.server.dlna.handle_connection_manager(body))
            else:
                _send_error(self, HTTPStatus.NOT_FOUND, "Unknown DLNA control endpoint")
        except Exception as exc:  # pragma: no cover - defensive protocol boundary
            LOG.warning("DLNA control request failed: %s", exc)
            _send_error(self, HTTPStatus.INTERNAL_SERVER_ERROR, "DLNA control request failed")

    def _route(self, *, send_body: bool) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/" or path == "/description.xml":
            _send_xml(self, self.server.dlna.description_xml(), send_body=send_body)
            return
        if path == "/ContentDirectory/scpd.xml":
            _send_xml(self, self.server.dlna.content_directory_scpd(), send_body=send_body)
            return
        if path == "/ConnectionManager/scpd.xml":
            _send_xml(self, self.server.dlna.connection_manager_scpd(), send_body=send_body)
            return
        if path.startswith("/media/"):
            parts = [unquote(part) for part in path.split("/") if part]
            if len(parts) >= 2 and parts[0] == "media":
                try:
                    track_id = int(parts[1])
                except ValueError:
                    track_id = -1
                self.server.dlna.serve_media(self, track_id, send_body=send_body)
                return
        _send_error(self, HTTPStatus.NOT_FOUND, "Not found")

    def _client_allowed(self) -> bool:
        host = self.client_address[0]
        if _is_allowed_client(host):
            return True
        LOG.warning("Rejected DLNA request from non-local client %s", host)
        _send_error(self, HTTPStatus.FORBIDDEN, "DLNA is available to local network clients only")
        return False


class _SsdpResponder:
    def __init__(self, server: DlnaServer):
        self.server = server
        self._stop = threading.Event()
        self._socket: socket.socket | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
            sock.settimeout(1.0)
            try:
                sock.bind(("", 1900))
            except OSError:
                sock.bind(("", 0))
            self._socket = sock
        except OSError as exc:
            LOG.info("DLNA SSDP unavailable: %s", exc)
            return
        self._notify("ssdp:alive")
        self._thread = threading.Thread(target=self._run, name="LyonSSDPResponder", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._notify("ssdp:byebye")
        if self._socket is not None:
            self._socket.close()
            self._socket = None
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None

    def _run(self) -> None:
        last_notify = time.monotonic()
        while not self._stop.is_set():
            if time.monotonic() - last_notify > 300:
                self._notify("ssdp:alive")
                last_notify = time.monotonic()
            sock = self._socket
            if sock is None:
                return
            try:
                data, addr = sock.recvfrom(2048)
            except TimeoutError:
                continue
            except OSError:
                return
            text = data.decode("utf-8", "ignore")
            if _is_allowed_client(addr[0]) and "M-SEARCH" in text.upper() and _ssdp_search_matches(text):
                self._respond(addr)

    def _respond(self, addr: tuple[str, int]) -> None:
        sock = self._socket
        if sock is None:
            return
        for st, usn in self._targets():
            msg = (
                "HTTP/1.1 200 OK\r\n"
                "CACHE-CONTROL: max-age=1800\r\n"
                f"DATE: {time.strftime('%a, %d %b %Y %H:%M:%S GMT', time.gmtime())}\r\n"
                "EXT:\r\n"
                f"LOCATION: {self.server.base_url}/description.xml\r\n"
                f"SERVER: {_server_header()}\r\n"
                f"ST: {st}\r\n"
                f"USN: {usn}\r\n"
                "\r\n"
            )
            try:
                sock.sendto(msg.encode("utf-8"), addr)
            except OSError:
                return

    def _notify(self, nts: str) -> None:
        sock = self._socket
        if sock is None:
            return
        for nt, usn in self._targets():
            msg = (
                "NOTIFY * HTTP/1.1\r\n"
                "HOST: 239.255.255.250:1900\r\n"
                "CACHE-CONTROL: max-age=1800\r\n"
                f"LOCATION: {self.server.base_url}/description.xml\r\n"
                f"NT: {nt}\r\n"
                f"NTS: {nts}\r\n"
                f"SERVER: {_server_header()}\r\n"
                f"USN: {usn}\r\n"
                "\r\n"
            )
            try:
                sock.sendto(msg.encode("utf-8"), _SSDP_ADDR)
            except OSError:
                return

    def _targets(self) -> list[tuple[str, str]]:
        udn = f"uuid:{self.server.uuid}"
        return [
            ("upnp:rootdevice", f"{udn}::upnp:rootdevice"),
            (udn, udn),
            ("urn:schemas-upnp-org:device:MediaServer:1", f"{udn}::urn:schemas-upnp-org:device:MediaServer:1"),
            ("urn:schemas-upnp-org:service:ContentDirectory:1", f"{udn}::urn:schemas-upnp-org:service:ContentDirectory:1"),
            ("urn:schemas-upnp-org:service:ConnectionManager:1", f"{udn}::urn:schemas-upnp-org:service:ConnectionManager:1"),
        ]


def _container(object_id: str, parent_id: str, title: str, child_count: int) -> _BrowseItem:
    xml = (
        f'<container id="{escape(object_id)}" parentID="{escape(parent_id)}" '
        f'restricted="1" childCount="{child_count}">'
        f"<dc:title>{escape(title)}</dc:title>"
        "<upnp:class>object.container.storageFolder</upnp:class>"
        "</container>"
    )
    return _BrowseItem(xml)


def _didl_xml(items: list[_BrowseItem]) -> str:
    body = "".join(item.xml for item in items)
    return (
        '<DIDL-Lite xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/" '
        'xmlns:upnp="urn:schemas-upnp-org:metadata-1-0/upnp/">'
        f"{body}</DIDL-Lite>"
    )


def _soap_envelope(action: str, namespace: str, payload: str) -> bytes:
    return f"""<?xml version="1.0" encoding="utf-8"?>
<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"
            s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">
  <s:Body>
    <u:{action} xmlns:u="{namespace}">
      {payload}
    </u:{action}>
  </s:Body>
</s:Envelope>
""".encode("utf-8")


def _soap_fault(error_code: int, description: str) -> bytes:
    return f"""<?xml version="1.0" encoding="utf-8"?>
<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/">
  <s:Body>
    <s:Fault>
      <faultcode>s:Client</faultcode>
      <faultstring>UPnPError</faultstring>
      <detail>
        <UPnPError xmlns="urn:schemas-upnp-org:control-1-0">
          <errorCode>{error_code}</errorCode>
          <errorDescription>{escape(description)}</errorDescription>
        </UPnPError>
      </detail>
    </s:Fault>
  </s:Body>
</s:Envelope>
""".encode("utf-8")


def _track_from_object_id(library: Library, object_id: str) -> Track | None:
    try:
        track_id = int(object_id.split(":", 1)[1])
    except (IndexError, ValueError):
        return None
    return library.track_by_id(track_id)


def _track_file_path(track: Track) -> Path | None:
    path = Path(track.playback_uri or track.path)
    return path if not track.playback_is_location else None


def _resolved_path(path: Path) -> Path | None:
    try:
        return path.expanduser().resolve(strict=False)
    except OSError:
        return None


def _path_is_under_roots(path: Path, roots: list[Path]) -> bool:
    for root in roots:
        try:
            path.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def _mime_type(path: Path) -> str:
    return _MIME_BY_EXT.get(path.suffix.lower()) or mimetypes.guess_type(path.name)[0] or "application/octet-stream"


def _duration_text(seconds: float) -> str:
    total_ms = max(0, int(seconds * 1000))
    hours, rem = divmod(total_ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, millis = divmod(rem, 1000)
    return f"{hours}:{minutes:02d}:{secs:02d}.{millis:03d}"


def _xml_text(root, local_name: str, default: str = "") -> str:
    for elem in root.iter():
        if elem.tag.rsplit("}", 1)[-1] == local_name:
            return (elem.text or "").strip()
    return default


def _xml_int(root, local_name: str, default: int) -> int:
    try:
        return int(_xml_text(root, local_name, str(default)))
    except ValueError:
        return default


def _nonnegative_xml_int(root, local_name: str, default: int) -> int:
    return max(0, _xml_int(root, local_name, default))


def _soap_action(root) -> str:
    body_seen = False
    for elem in root.iter():
        local = elem.tag.rsplit("}", 1)[-1]
        if local == "Body":
            body_seen = True
            continue
        if body_seen:
            return local
    return ""


def _encode_object_value(value: str) -> str:
    return base64.urlsafe_b64encode(value.encode("utf-8")).decode("ascii").rstrip("=")


def _decode_object_value(value: str) -> str:
    try:
        padding = "=" * (-len(value) % 4)
        return base64.urlsafe_b64decode((value + padding).encode("ascii")).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return ""


def _join_pair(first: str, second: str) -> str:
    return f"{first}\0{second}"


def _split_pair(value: str) -> tuple[str, str]:
    first, sep, second = value.partition("\0")
    return (first, second) if sep else ("", "")


def _search_query(criteria: str) -> str:
    criteria = criteria.strip()
    if not criteria or criteria == "*":
        return ""
    values: list[str] = []
    in_quote = False
    current = []
    for char in criteria:
        if char == '"':
            if in_quote:
                values.append("".join(current).strip())
                current = []
            in_quote = not in_quote
        elif in_quote:
            current.append(char)
    values = [value for value in values if value and value != "*"]
    if values:
        return max(values, key=len)[:128]
    return criteria[:128]


def _parse_range(header: str | None, size: int) -> tuple[int, int] | None:
    if not header:
        return None
    if not header.startswith("bytes=") or size <= 0:
        return (-1, -1)
    spec = header.removeprefix("bytes=").split(",", 1)[0].strip()
    if "-" not in spec:
        return (-1, -1)
    start_text, end_text = spec.split("-", 1)
    try:
        if start_text == "":
            suffix = int(end_text)
            if suffix <= 0:
                return (-1, -1)
            start = max(0, size - suffix)
            end = size - 1
        else:
            start = int(start_text)
            end = int(end_text) if end_text else size - 1
    except ValueError:
        return (-1, -1)
    if start < 0 or end < start or start >= size:
        return (-1, -1)
    return (start, min(end, size - 1))


def _copy_limited(src: BinaryIO, dst: BinaryIO, length: int) -> None:
    remaining = length
    while remaining > 0:
        chunk = src.read(min(_CHUNK_SIZE, remaining))
        if not chunk:
            return
        dst.write(chunk)
        remaining -= len(chunk)


def _send_xml(handler: BaseHTTPRequestHandler, data: bytes, *, send_body: bool = True) -> None:
    handler.send_response(HTTPStatus.OK)
    handler.send_header("Content-Type", 'text/xml; charset="utf-8"')
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    if send_body:
        handler.wfile.write(data)


def _send_error(handler: BaseHTTPRequestHandler, status: HTTPStatus, message: str) -> None:
    data = message.encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "text/plain; charset=utf-8")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def _is_allowed_client(host: str) -> bool:
    try:
        address = ip_address(host.split("%", 1)[0])
    except ValueError:
        return False
    return address.is_loopback or address.is_private or address.is_link_local


def _local_ip() -> str:
    """Resolve a LAN-reachable IPv4 address for DLNA discovery URLs.

    The connect-to-internet trick works on most setups but fails on
    air-gapped LANs; falling back to host-interface enumeration keeps
    the server reachable without exposing loopback as a last resort.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            return sock.getsockname()[0]
    except OSError:
        pass
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            address = info[4][0]
            if address and not address.startswith("127."):
                return address
    except OSError:
        pass
    return "127.0.0.1"


def _server_header() -> str:
    return f"{platform.system()}/{platform.release()} UPnP/1.0 SeaLyon/{__version__}"


def _ssdp_search_matches(text: str) -> bool:
    lowered = text.casefold()
    return (
        "ssdp:all" in lowered
        or "upnp:rootdevice" in lowered
        or "mediaserver" in lowered
        or "contentdirectory" in lowered
    )


_CONTENT_DIRECTORY_SCPD = b"""<?xml version="1.0" encoding="utf-8"?>
<scpd xmlns="urn:schemas-upnp-org:service-1-0">
  <specVersion><major>1</major><minor>0</minor></specVersion>
  <actionList>
    <action>
      <name>Browse</name>
      <argumentList>
        <argument><name>ObjectID</name><direction>in</direction><relatedStateVariable>A_ARG_TYPE_ObjectID</relatedStateVariable></argument>
        <argument><name>BrowseFlag</name><direction>in</direction><relatedStateVariable>A_ARG_TYPE_BrowseFlag</relatedStateVariable></argument>
        <argument><name>Filter</name><direction>in</direction><relatedStateVariable>A_ARG_TYPE_Filter</relatedStateVariable></argument>
        <argument><name>StartingIndex</name><direction>in</direction><relatedStateVariable>A_ARG_TYPE_Index</relatedStateVariable></argument>
        <argument><name>RequestedCount</name><direction>in</direction><relatedStateVariable>A_ARG_TYPE_Count</relatedStateVariable></argument>
        <argument><name>SortCriteria</name><direction>in</direction><relatedStateVariable>A_ARG_TYPE_SortCriteria</relatedStateVariable></argument>
        <argument><name>Result</name><direction>out</direction><relatedStateVariable>A_ARG_TYPE_Result</relatedStateVariable></argument>
        <argument><name>NumberReturned</name><direction>out</direction><relatedStateVariable>A_ARG_TYPE_Count</relatedStateVariable></argument>
        <argument><name>TotalMatches</name><direction>out</direction><relatedStateVariable>A_ARG_TYPE_Count</relatedStateVariable></argument>
        <argument><name>UpdateID</name><direction>out</direction><relatedStateVariable>A_ARG_TYPE_UpdateID</relatedStateVariable></argument>
      </argumentList>
    </action>
    <action>
      <name>Search</name>
      <argumentList>
        <argument><name>ContainerID</name><direction>in</direction><relatedStateVariable>A_ARG_TYPE_ObjectID</relatedStateVariable></argument>
        <argument><name>SearchCriteria</name><direction>in</direction><relatedStateVariable>A_ARG_TYPE_SearchCriteria</relatedStateVariable></argument>
        <argument><name>Filter</name><direction>in</direction><relatedStateVariable>A_ARG_TYPE_Filter</relatedStateVariable></argument>
        <argument><name>StartingIndex</name><direction>in</direction><relatedStateVariable>A_ARG_TYPE_Index</relatedStateVariable></argument>
        <argument><name>RequestedCount</name><direction>in</direction><relatedStateVariable>A_ARG_TYPE_Count</relatedStateVariable></argument>
        <argument><name>SortCriteria</name><direction>in</direction><relatedStateVariable>A_ARG_TYPE_SortCriteria</relatedStateVariable></argument>
        <argument><name>Result</name><direction>out</direction><relatedStateVariable>A_ARG_TYPE_Result</relatedStateVariable></argument>
        <argument><name>NumberReturned</name><direction>out</direction><relatedStateVariable>A_ARG_TYPE_Count</relatedStateVariable></argument>
        <argument><name>TotalMatches</name><direction>out</direction><relatedStateVariable>A_ARG_TYPE_Count</relatedStateVariable></argument>
        <argument><name>UpdateID</name><direction>out</direction><relatedStateVariable>A_ARG_TYPE_UpdateID</relatedStateVariable></argument>
      </argumentList>
    </action>
    <action>
      <name>GetSearchCapabilities</name>
      <argumentList>
        <argument><name>SearchCaps</name><direction>out</direction><relatedStateVariable>SearchCapabilities</relatedStateVariable></argument>
      </argumentList>
    </action>
    <action>
      <name>GetSortCapabilities</name>
      <argumentList>
        <argument><name>SortCaps</name><direction>out</direction><relatedStateVariable>SortCapabilities</relatedStateVariable></argument>
      </argumentList>
    </action>
    <action>
      <name>GetSystemUpdateID</name>
      <argumentList>
        <argument><name>Id</name><direction>out</direction><relatedStateVariable>SystemUpdateID</relatedStateVariable></argument>
      </argumentList>
    </action>
  </actionList>
  <serviceStateTable>
    <stateVariable sendEvents="yes"><name>SystemUpdateID</name><dataType>ui4</dataType></stateVariable>
    <stateVariable sendEvents="no"><name>SearchCapabilities</name><dataType>string</dataType></stateVariable>
    <stateVariable sendEvents="no"><name>SortCapabilities</name><dataType>string</dataType></stateVariable>
    <stateVariable sendEvents="no"><name>A_ARG_TYPE_ObjectID</name><dataType>string</dataType></stateVariable>
    <stateVariable sendEvents="no"><name>A_ARG_TYPE_Result</name><dataType>string</dataType></stateVariable>
    <stateVariable sendEvents="no"><name>A_ARG_TYPE_BrowseFlag</name><dataType>string</dataType></stateVariable>
    <stateVariable sendEvents="no"><name>A_ARG_TYPE_Filter</name><dataType>string</dataType></stateVariable>
    <stateVariable sendEvents="no"><name>A_ARG_TYPE_Index</name><dataType>ui4</dataType></stateVariable>
    <stateVariable sendEvents="no"><name>A_ARG_TYPE_Count</name><dataType>ui4</dataType></stateVariable>
    <stateVariable sendEvents="no"><name>A_ARG_TYPE_UpdateID</name><dataType>ui4</dataType></stateVariable>
    <stateVariable sendEvents="no"><name>A_ARG_TYPE_SearchCriteria</name><dataType>string</dataType></stateVariable>
    <stateVariable sendEvents="no"><name>A_ARG_TYPE_SortCriteria</name><dataType>string</dataType></stateVariable>
  </serviceStateTable>
</scpd>
"""

_CONNECTION_MANAGER_SCPD = b"""<?xml version="1.0" encoding="utf-8"?>
<scpd xmlns="urn:schemas-upnp-org:service-1-0">
  <specVersion><major>1</major><minor>0</minor></specVersion>
  <actionList>
    <action>
      <name>GetProtocolInfo</name>
      <argumentList>
        <argument><name>Source</name><direction>out</direction><relatedStateVariable>SourceProtocolInfo</relatedStateVariable></argument>
        <argument><name>Sink</name><direction>out</direction><relatedStateVariable>SinkProtocolInfo</relatedStateVariable></argument>
      </argumentList>
    </action>
    <action>
      <name>GetCurrentConnectionIDs</name>
      <argumentList>
        <argument><name>ConnectionIDs</name><direction>out</direction><relatedStateVariable>CurrentConnectionIDs</relatedStateVariable></argument>
      </argumentList>
    </action>
    <action>
      <name>GetCurrentConnectionInfo</name>
      <argumentList>
        <argument><name>ConnectionID</name><direction>in</direction><relatedStateVariable>A_ARG_TYPE_ConnectionID</relatedStateVariable></argument>
        <argument><name>RcsID</name><direction>out</direction><relatedStateVariable>A_ARG_TYPE_RcsID</relatedStateVariable></argument>
        <argument><name>AVTransportID</name><direction>out</direction><relatedStateVariable>A_ARG_TYPE_AVTransportID</relatedStateVariable></argument>
        <argument><name>ProtocolInfo</name><direction>out</direction><relatedStateVariable>A_ARG_TYPE_ProtocolInfo</relatedStateVariable></argument>
        <argument><name>PeerConnectionManager</name><direction>out</direction><relatedStateVariable>A_ARG_TYPE_ConnectionManager</relatedStateVariable></argument>
        <argument><name>PeerConnectionID</name><direction>out</direction><relatedStateVariable>A_ARG_TYPE_ConnectionID</relatedStateVariable></argument>
        <argument><name>Direction</name><direction>out</direction><relatedStateVariable>A_ARG_TYPE_Direction</relatedStateVariable></argument>
        <argument><name>Status</name><direction>out</direction><relatedStateVariable>A_ARG_TYPE_ConnectionStatus</relatedStateVariable></argument>
      </argumentList>
    </action>
  </actionList>
  <serviceStateTable>
    <stateVariable sendEvents="no"><name>SourceProtocolInfo</name><dataType>string</dataType></stateVariable>
    <stateVariable sendEvents="no"><name>SinkProtocolInfo</name><dataType>string</dataType></stateVariable>
    <stateVariable sendEvents="no"><name>CurrentConnectionIDs</name><dataType>string</dataType></stateVariable>
    <stateVariable sendEvents="no"><name>A_ARG_TYPE_ConnectionStatus</name><dataType>string</dataType></stateVariable>
    <stateVariable sendEvents="no"><name>A_ARG_TYPE_ConnectionManager</name><dataType>string</dataType></stateVariable>
    <stateVariable sendEvents="no"><name>A_ARG_TYPE_Direction</name><dataType>string</dataType></stateVariable>
    <stateVariable sendEvents="no"><name>A_ARG_TYPE_ProtocolInfo</name><dataType>string</dataType></stateVariable>
    <stateVariable sendEvents="no"><name>A_ARG_TYPE_ConnectionID</name><dataType>i4</dataType></stateVariable>
    <stateVariable sendEvents="no"><name>A_ARG_TYPE_AVTransportID</name><dataType>i4</dataType></stateVariable>
    <stateVariable sendEvents="no"><name>A_ARG_TYPE_RcsID</name><dataType>i4</dataType></stateVariable>
  </serviceStateTable>
</scpd>
"""

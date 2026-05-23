"""Control a DLNA/UPnP AVTransport renderer — one-way cast from the local player."""
from __future__ import annotations

import logging
import random
from pathlib import Path
from xml.sax.saxutils import escape

import requests
from PySide6.QtCore import QObject, Signal

from .dlna_renderer_discovery import RendererDevice
from .dlna_server import DlnaServer
from .library import Track
from .player import Player, RepeatMode

LOG = logging.getLogger(__name__)

_AV_TRANSPORT_NS = "urn:schemas-upnp-org:service:AVTransport:1"


class CastController(QObject):
    """Manage a cast session to a single DLNA MediaRenderer.

    Signals
    -------
    cast_started(friendly_name)   — emitted when renderer starts playing
    cast_stopped()                — emitted when the session ends cleanly
    cast_error(message)           — emitted on SOAP failure
    """

    cast_started = Signal(str)
    cast_stopped = Signal()
    cast_error = Signal(str)
    cast_playback_state_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._renderer: RendererDevice | None = None
        self._player: Player | None = None
        self._dlna: DlnaServer | None = None
        self._remote_playing = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def is_casting(self) -> bool:
        return self._renderer is not None

    @property
    def renderer(self) -> RendererDevice | None:
        return self._renderer

    def start_cast(
        self,
        renderer: RendererDevice,
        player: Player,
        dlna_server: DlnaServer,
    ) -> None:
        """Begin casting the currently playing track to *renderer*.

        Pauses local playback and proxies subsequent play/pause/track-change
        events from *player* to the renderer via AVTransport SOAP.
        """
        if self._renderer is not None:
            self.stop_cast()

        track = player.current()
        if track is None:
            self.cast_error.emit("Nothing is currently playing.")
            return
        if not dlna_server.running:
            self.cast_error.emit(
                "DLNA sharing is not enabled. Enable it in Settings first."
            )
            return

        media_url = _media_url(dlna_server, track)
        if media_url is None:
            self.cast_error.emit("Cannot cast this track — file not found in library.")
            return

        try:
            _soap(renderer.av_transport_url, _AV_TRANSPORT_NS, "SetAVTransportURI", {
                "InstanceID": "0",
                "CurrentURI": escape(media_url),
                "CurrentURIMetaData": escape(_didl(track, media_url)),
            })
            _soap(renderer.av_transport_url, _AV_TRANSPORT_NS, "Play", {
                "InstanceID": "0",
                "Speed": "1",
            })
        except Exception as exc:
            LOG.warning("Cast start failed: %s", exc)
            self.cast_error.emit(f"Cast failed: {exc}")
            return

        self._renderer = renderer
        self._player = player
        self._dlna = dlna_server
        self._remote_playing = True

        # Pause local audio BEFORE connecting signals so the resulting
        # state_changed("paused") does not propagate to the renderer.
        player.pause()

        player.state_changed.connect(self._on_state_changed)
        player.track_changed.connect(self._on_track_changed)

        self.cast_started.emit(renderer.friendly_name)
        self.cast_playback_state_changed.emit("playing")

    def stop_cast(self) -> None:
        """Stop the active cast session and send Stop to the renderer."""
        if self._renderer is None:
            return

        renderer = self._renderer
        player = self._player

        self._renderer = None
        self._dlna = None
        self._player = None
        self._remote_playing = False

        if player is not None:
            try:
                player.state_changed.disconnect(self._on_state_changed)
                player.track_changed.disconnect(self._on_track_changed)
            except RuntimeError:
                pass

        try:
            _soap(renderer.av_transport_url, _AV_TRANSPORT_NS, "Stop", {
                "InstanceID": "0",
            })
        except Exception as exc:
            LOG.debug("Stop SOAP failed (renderer may be gone): %s", exc)

        self.cast_stopped.emit()
        self.cast_playback_state_changed.emit("stopped")

    def toggle_play_pause(self) -> None:
        """Toggle playback on the renderer without resuming local audio."""
        if self._renderer is None:
            return
        if self._remote_playing:
            self._send_transport_action("Pause", {"InstanceID": "0"}, state="paused")
        else:
            self._send_transport_action(
                "Play",
                {"InstanceID": "0", "Speed": "1"},
                state="playing",
            )

    def next_track(self) -> None:
        """Advance the cast queue and load the next track on the renderer."""
        player = self._player
        if player is None:
            return
        queue = player.queue()
        if not queue:
            return

        index = player.current_index()
        if player.repeat() == RepeatMode.ONE and 0 <= index < len(queue):
            self._select_queue_index(index)
            return
        if player.shuffle():
            candidates = [i for i in range(len(queue)) if i != index]
            if candidates:
                self._select_queue_index(random.choice(candidates))
            elif player.repeat() == RepeatMode.ALL and 0 <= index < len(queue):
                self._select_queue_index(index)
            else:
                self.stop_cast()
            return
        if index + 1 < len(queue):
            self._select_queue_index(index + 1)
        elif player.repeat() == RepeatMode.ALL and queue:
            self._select_queue_index(0)
        else:
            self.stop_cast()

    def previous_track(self) -> None:
        """Move the cast queue to the previous track."""
        player = self._player
        if player is None:
            return
        index = player.current_index()
        if index > 0:
            self._select_queue_index(index - 1)

    def _select_queue_index(self, index: int) -> None:
        player = self._player
        if player is None:
            return
        queue = player.queue()
        if not (0 <= index < len(queue)):
            return
        self._remote_playing = True
        player.load_queue(queue, index)

    # ------------------------------------------------------------------
    # Player signal handlers
    # ------------------------------------------------------------------

    def _on_state_changed(self, state: str) -> None:
        if self._renderer is None:
            return
        try:
            if state == "playing":
                _soap(
                    self._renderer.av_transport_url,
                    _AV_TRANSPORT_NS,
                    "Play",
                    {"InstanceID": "0", "Speed": "1"},
                )
                self._remote_playing = True
                self.cast_playback_state_changed.emit("playing")
            elif state == "paused":
                _soap(
                    self._renderer.av_transport_url,
                    _AV_TRANSPORT_NS,
                    "Pause",
                    {"InstanceID": "0"},
                )
                self._remote_playing = False
                self.cast_playback_state_changed.emit("paused")
            elif state == "stopped":
                _soap(
                    self._renderer.av_transport_url,
                    _AV_TRANSPORT_NS,
                    "Stop",
                    {"InstanceID": "0"},
                )
                self._remote_playing = False
                self.cast_playback_state_changed.emit("stopped")
        except Exception as exc:
            LOG.warning("Cast state sync failed: %s", exc)
            self.cast_error.emit(f"Lost connection to renderer: {exc}")

    def _on_track_changed(self, track: object) -> None:
        if self._renderer is None or self._dlna is None:
            return

        if not isinstance(track, Track):
            try:
                _soap(self._renderer.av_transport_url, _AV_TRANSPORT_NS, "Stop", {
                    "InstanceID": "0",
                })
            except Exception:
                pass
            self._remote_playing = False
            self.cast_playback_state_changed.emit("stopped")
            return

        media_url = _media_url(self._dlna, track)
        if media_url is None:
            self.cast_error.emit("Cannot cast this track — file is not available over DLNA.")
            self.stop_cast()
            return

        try:
            _soap(self._renderer.av_transport_url, _AV_TRANSPORT_NS, "SetAVTransportURI", {
                "InstanceID": "0",
                "CurrentURI": escape(media_url),
                "CurrentURIMetaData": escape(_didl(track, media_url)),
            })
            _soap(self._renderer.av_transport_url, _AV_TRANSPORT_NS, "Play", {
                "InstanceID": "0",
                "Speed": "1",
            })
            self._remote_playing = True
            self.cast_playback_state_changed.emit("playing")
        except Exception as exc:
            LOG.warning("Cast track-change failed: %s", exc)
            self.cast_error.emit(f"Cast lost: {exc}")

    def _send_transport_action(
        self,
        action: str,
        args: dict[str, str],
        *,
        state: str,
    ) -> None:
        if self._renderer is None:
            return
        try:
            _soap(self._renderer.av_transport_url, _AV_TRANSPORT_NS, action, args)
        except Exception as exc:
            LOG.warning("Cast transport action failed: %s", exc)
            self.cast_error.emit(f"Lost connection to renderer: {exc}")
            return
        self._remote_playing = state == "playing"
        self.cast_playback_state_changed.emit(state)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _media_url(dlna_server: DlnaServer, track: Track) -> str | None:
    return dlna_server.media_url_for_track(track)


def _didl(track: Track, url: str) -> str:
    title = escape(track.title or Path(track.path or "").stem or "Unknown")
    artist = escape(track.display_artist)
    album = escape(track.album or "")
    upnp_class = (
        "object.item.videoItem"
        if track.media_type == "video"
        else "object.item.audioItem.musicTrack"
    )
    return (
        '<DIDL-Lite xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/" '
        'xmlns:upnp="urn:schemas-upnp-org:metadata-1-0/upnp/">'
        '<item id="0" parentID="-1" restricted="1">'
        f"<dc:title>{title}</dc:title>"
        f"<dc:creator>{artist}</dc:creator>"
        f"<upnp:artist>{artist}</upnp:artist>"
        f"<upnp:album>{album}</upnp:album>"
        f"<upnp:class>{upnp_class}</upnp:class>"
        f'<res protocolInfo="http-get:*:*:*">{escape(url)}</res>'
        "</item>"
        "</DIDL-Lite>"
    )


def _soap(url: str, service: str, action: str, args: dict[str, str]) -> None:
    args_xml = "".join(f"<{k}>{v}</{k}>" for k, v in args.items())
    body = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
        's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">'
        "<s:Body>"
        f'<u:{action} xmlns:u="{service}">'
        f"{args_xml}"
        f"</u:{action}>"
        "</s:Body>"
        "</s:Envelope>"
    )
    headers = {
        "Content-Type": 'text/xml; charset="utf-8"',
        "SOAPAction": f'"{service}#{action}"',
    }
    resp = requests.post(url, data=body.encode("utf-8"), headers=headers, timeout=5.0)
    if resp.status_code >= 400:
        raise RuntimeError(f"SOAP {action} returned HTTP {resp.status_code}")

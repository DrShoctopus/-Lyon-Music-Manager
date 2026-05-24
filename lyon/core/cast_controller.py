"""Control a DLNA/UPnP AVTransport renderer — one-way cast from the local player."""
from __future__ import annotations

import logging
import queue as _queue
import random
from collections.abc import Callable
from pathlib import Path
from xml.sax.saxutils import escape

import requests
from PySide6.QtCore import QObject, QThread, Signal

from .dlna_renderer_discovery import RendererDevice
from .dlna_server import DlnaServer, dlna_protocol_info
from .library import Track
from .player import Player, RepeatMode

LOG = logging.getLogger(__name__)

_AV_TRANSPORT_NS = "urn:schemas-upnp-org:service:AVTransport:1"


# ---------------------------------------------------------------------------
# SOAP worker
# ---------------------------------------------------------------------------

class _SoapJob:
    """One ordered unit of renderer work: a sequence of SOAP calls + a label."""

    def __init__(
        self,
        label: str,
        calls: list,
        on_success_state: str | None = None,
        *,
        session_id: int = 0,
        renderer_name: str = "",
        report_errors: bool = True,
    ):
        self.label = label                    # e.g. "start", "track-change", "Play"
        self.calls = calls                    # list[tuple[url, service, action, args]]
        self.on_success_state = on_success_state  # "playing"/"paused"/"stopped"/None
        self.session_id = session_id
        self.renderer_name = renderer_name
        self.report_errors = report_errors


class _SoapWorker(QObject):
    job_done = Signal(object, object)  # (_SoapJob, exception_or_None)

    def __init__(self):
        super().__init__()
        self._jobs: "_queue.Queue[_SoapJob | None]" = _queue.Queue()

    def submit(self, job: _SoapJob) -> None:
        self._jobs.put(job)

    def shutdown(self) -> None:
        self._jobs.put(None)  # sentinel: drain remaining, then stop

    def run(self) -> None:  # connected to QThread.started
        while True:
            job = self._jobs.get()
            if job is None:
                return
            err = None
            try:
                for url, service, action, args in job.calls:
                    _soap(url, service, action, args)
            except Exception as exc:
                err = exc
            self.job_done.emit(job, err)


# ---------------------------------------------------------------------------
# Controller
# ---------------------------------------------------------------------------

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
        self._suppress_state_mirror = False
        self._session_id = 0
        self._shuffle_played: set[int] = set()

        self._thread = QThread()
        self._worker = _SoapWorker()
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.job_done.connect(self._on_job_done)  # auto queued → GUI thread

    def __del__(self) -> None:
        try:
            self.shutdown()
        except RuntimeError:
            pass

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def is_casting(self) -> bool:
        return self._renderer is not None

    @property
    def renderer(self) -> RendererDevice | None:
        return self._renderer

    def shutdown(self) -> None:
        """Stop the worker thread; wait for any in-flight SOAP call."""
        if self._thread.isRunning():
            self._worker.shutdown()  # sentinel drains queue
            self._thread.quit()
            self._thread.wait(8000)  # > 1 job worst case; tune vs. _soap timeout

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
        self._start_track_cast(
            renderer,
            track,
            dlna_server,
            player=player,
            pause_local=player.pause,
        )

    def start_cast_track(
        self,
        renderer: RendererDevice,
        track: Track,
        dlna_server: DlnaServer,
        *,
        pause_local: Callable[[], None] | None = None,
    ) -> None:
        """Cast one known library track without binding to the audio queue."""
        self._start_track_cast(
            renderer,
            track,
            dlna_server,
            pause_local=pause_local,
        )

    def _start_track_cast(
        self,
        renderer: RendererDevice,
        track: Track | None,
        dlna_server: DlnaServer,
        *,
        player: Player | None = None,
        pause_local: Callable[[], None] | None = None,
    ) -> None:
        if self._renderer is not None:
            self.stop_cast()

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

        self._session_id += 1
        session_id = self._session_id
        self._renderer = renderer
        self._player = player
        self._dlna = dlna_server
        self._shuffle_played.clear()
        self._remember_shuffle_track(track)
        self._remote_playing = True

        # Pause local playback before mirroring signals so the pause does not
        # immediately propagate back to the renderer.
        if pause_local is not None:
            pause_local()

        if player is not None:
            player.state_changed.connect(self._on_state_changed)
            player.track_changed.connect(self._on_track_changed)

        self._submit_job(_SoapJob("start", [
            (renderer.av_transport_url, _AV_TRANSPORT_NS, "SetAVTransportURI", {
                "InstanceID": "0",
                "CurrentURI": escape(media_url),
                "CurrentURIMetaData": escape(_didl(track, media_url)),
            }),
            (renderer.av_transport_url, _AV_TRANSPORT_NS, "Play", {
                "InstanceID": "0",
                "Speed": "1",
            }),
        ], on_success_state="playing", session_id=session_id, renderer_name=renderer.friendly_name))

    def stop_cast(self) -> None:
        """Stop the active cast session and send Stop to the renderer."""
        if self._renderer is None:
            return

        renderer = self._renderer
        player = self._player
        session_id = self._session_id
        self._session_id += 1

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

        # State is cleared above; worker only needs the captured renderer URL.
        self._submit_job(_SoapJob("stop", [
            (renderer.av_transport_url, _AV_TRANSPORT_NS, "Stop", {
                "InstanceID": "0",
            }),
        ], session_id=session_id, report_errors=False))

        self.cast_stopped.emit()
        self.cast_playback_state_changed.emit("stopped")

    def toggle_play_pause(self) -> None:
        """Toggle playback on the renderer without resuming local audio."""
        if self._renderer is None:
            return
        if self._remote_playing:
            # Set optimistically so rapid double-clicks don't both go the same direction.
            self._remote_playing = False
            self._send_transport_action("Pause", {"InstanceID": "0"}, state="paused")
        else:
            self._remote_playing = True
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
            played = set(self._shuffle_played)
            if 0 <= index < len(queue):
                played.add(index)
            candidates = [
                i for i in range(len(queue))
                if i != index and i not in played
            ]
            if not candidates and player.repeat() == RepeatMode.ALL:
                self._shuffle_played.clear()
                if 0 <= index < len(queue):
                    self._shuffle_played.add(index)
                candidates = [i for i in range(len(queue)) if i != index]
            if candidates:
                nxt = random.choice(candidates)
                self._shuffle_played.add(nxt)
                self._select_queue_index(nxt)
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
        self._suppress_state_mirror = True
        try:
            player.load_queue(queue, index)
            # load_queue resets the local source key and emits track_changed;
            # re-pause so the local backend cannot audibly resume while casting.
            player.pause()
        finally:
            self._suppress_state_mirror = False

    def _remember_shuffle_track(self, track: Track | None = None) -> None:
        player = self._player
        if player is None:
            return
        try:
            if not player.shuffle():
                return
            queue = player.queue()
        except (AttributeError, RuntimeError, TypeError):
            return

        try:
            index = int(player.current_index())
        except (TypeError, ValueError):
            index = -1

        if 0 <= index < len(queue):
            if track is None or queue[index] is track or queue[index] == track:
                self._shuffle_played.add(index)
                return

        if track is None:
            return
        for i, queued_track in enumerate(queue):
            if queued_track is track or queued_track == track:
                self._shuffle_played.add(i)
                return

    # ------------------------------------------------------------------
    # Player signal handlers
    # ------------------------------------------------------------------

    def _on_state_changed(self, state: str) -> None:
        if self._renderer is None or self._suppress_state_mirror:
            return
        if state == "playing":
            self._submit_job(_SoapJob("Play", [
                (self._renderer.av_transport_url, _AV_TRANSPORT_NS, "Play",
                 {"InstanceID": "0", "Speed": "1"}),
            ], on_success_state="playing", session_id=self._session_id))
        elif state == "paused":
            self._submit_job(_SoapJob("Pause", [
                (self._renderer.av_transport_url, _AV_TRANSPORT_NS, "Pause",
                 {"InstanceID": "0"}),
            ], on_success_state="paused", session_id=self._session_id))
        elif state == "stopped":
            # Local player stopped → end the cast session entirely.
            # stop_cast() sends Stop, clears renderer state, disconnects
            # signals, and emits cast_stopped + state("stopped").
            self.stop_cast()

    def _on_track_changed(self, track: object) -> None:
        if self._renderer is None or self._dlna is None:
            return

        if not isinstance(track, Track):
            self._remote_playing = False
            self.cast_playback_state_changed.emit("stopped")
            self._submit_job(_SoapJob("stop-non-track", [
                (self._renderer.av_transport_url, _AV_TRANSPORT_NS, "Stop",
                 {"InstanceID": "0"}),
            ], session_id=self._session_id, report_errors=False))
            return

        media_url = _media_url(self._dlna, track)
        if media_url is None:
            self.cast_error.emit("Cannot cast this track — file is not available over DLNA.")
            self.stop_cast()
            return

        self._remember_shuffle_track(track)
        self._submit_job(_SoapJob("track-change", [
            (self._renderer.av_transport_url, _AV_TRANSPORT_NS, "SetAVTransportURI", {
                "InstanceID": "0",
                "CurrentURI": escape(media_url),
                "CurrentURIMetaData": escape(_didl(track, media_url)),
            }),
            (self._renderer.av_transport_url, _AV_TRANSPORT_NS, "Play", {
                "InstanceID": "0",
                "Speed": "1",
            }),
        ], on_success_state="playing", session_id=self._session_id))

    def _send_transport_action(
        self,
        action: str,
        args: dict[str, str],
        *,
        state: str,
    ) -> None:
        if self._renderer is None:
            return
        self._submit_job(_SoapJob(action, [
            (self._renderer.av_transport_url, _AV_TRANSPORT_NS, action, args),
        ], on_success_state=state, session_id=self._session_id))

    def _submit_job(self, job: _SoapJob) -> None:
        if not self._thread.isRunning():
            self._thread.start()
        self._worker.submit(job)

    def _clear_session_state(self, session_id: int | None = None) -> bool:
        if session_id is not None and session_id != self._session_id:
            return False
        player = self._player
        self._session_id += 1
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
        return True

    def _on_job_done(self, job: object, err: object) -> None:
        if not isinstance(job, _SoapJob):
            return
        if job.session_id != self._session_id:
            return
        if err is not None:
            LOG.warning("Cast %s failed: %s", job.label, err)
            if job.report_errors:
                prefix = "Cast failed" if job.label == "start" else "Lost connection to renderer"
                self.cast_error.emit(f"{prefix}: {err}")
            if self._clear_session_state(job.session_id):
                if job.label != "start":
                    self.cast_stopped.emit()
                self.cast_playback_state_changed.emit("stopped")
            return
        if job.label == "start" and job.renderer_name:
            self.cast_started.emit(job.renderer_name)
        if job.on_success_state is not None:
            self._remote_playing = job.on_success_state == "playing"
            self.cast_playback_state_changed.emit(job.on_success_state)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _media_url(dlna_server: DlnaServer, track: Track) -> str | None:
    return dlna_server.media_url_for_track(track)


def _didl(track: Track, url: str) -> str:
    title = escape(track.title or Path(track.path or "").stem or "Unknown")
    artist = escape(track.display_artist)
    album = escape(track.album or "")
    protocol_info = dlna_protocol_info(track.path or Path(url).name)
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
        f'<res protocolInfo="{escape(protocol_info)}">{escape(url)}</res>'
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

"""Tests for CastController SOAP logic and player signal proxying."""
from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from lyon.core.cast_controller import CastController, _SoapJob, _didl, _media_url, _soap
from lyon.core.dlna_renderer_discovery import RendererDevice
from lyon.core.library import Track
from lyon.core.player import RepeatMode


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

def _make_renderer(av_url: str = "http://192.168.1.5:49152/AVTransport/control") -> RendererDevice:
    return RendererDevice(
        friendly_name="Living Room TV",
        location_url="http://192.168.1.5:49152/description.xml",
        av_transport_url=av_url,
        udn="uuid:test-renderer-1234",
    )


def _make_track(path: str = "/music/song.mp3", track_id: int = 1) -> Track:
    return Track(
        id=track_id,
        path=path,
        title="Ocean Song",
        artist="Sea Artist",
        album_artist="Sea Artist",
        album="Blue Album",
        track_no=1,
        disc_no=1,
        year=2026,
        genre="Rock",
        duration=185.0,
    )


def _make_player(track: Track | None = None, state: str = "playing"):
    player = MagicMock()
    player.current.return_value = track
    player.state = state
    return player


def _make_dlna(base_url: str = "http://192.168.1.1:8200", running: bool = True):
    dlna = MagicMock()
    dlna.base_url = base_url
    dlna.running = running
    dlna.media_url_for_track.side_effect = (
        lambda track: None
        if not track.path or not track.is_library_item
        else f"{base_url}/media/{track.id}/{Path(track.path).name.replace(' ', '%20')}"
    )
    return dlna


def _drain(ctrl: CastController, qapp, timeout: float = 2.0) -> None:
    """Wait for the worker thread to drain all queued jobs."""
    ctrl._thread.wait(int(timeout * 1000))
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        qapp.processEvents()
        if ctrl._worker._jobs.empty():
            break
        time.sleep(0.01)
    qapp.processEvents()


# ---------------------------------------------------------------------------
# _media_url
# ---------------------------------------------------------------------------

def test_media_url_builds_correctly():
    dlna = _make_dlna("http://192.168.1.1:8200")
    track = _make_track("/music/My Song.mp3", track_id=42)
    url = _media_url(dlna, track)
    assert url == "http://192.168.1.1:8200/media/42/My%20Song.mp3"


def test_media_url_no_path():
    dlna = _make_dlna("http://192.168.1.1:8200")
    track = _make_track("", track_id=1)
    assert _media_url(dlna, track) is None


def test_media_url_rejects_non_library_track():
    dlna = _make_dlna("http://192.168.1.1:8200")
    track = _make_track("/music/stream.mp3", track_id=0)
    track.is_library_item = False
    assert _media_url(dlna, track) is None


# ---------------------------------------------------------------------------
# _didl
# ---------------------------------------------------------------------------

def test_didl_contains_title_and_class():
    track = _make_track()
    xml = _didl(track, "http://192.168.1.1:8200/media/1/song.mp3")
    assert "Ocean Song" in xml
    assert "object.item.audioItem.musicTrack" in xml
    assert "DIDL-Lite" in xml


def test_didl_video_class():
    track = Track(
        id=2, path="/video/clip.mp4", title="My Clip",
        artist="", album_artist="", album="",
        track_no=0, disc_no=0, year=0, genre="",
        duration=60.0, media_type="video",
    )
    xml = _didl(track, "http://192.168.1.1:8200/media/2/clip.mp4")
    assert "object.item.videoItem" in xml
    assert 'protocolInfo="http-get:*:video/mp4:*"' in xml


def test_didl_escapes_special_chars():
    track = Track(
        id=3, path="/music/a&b.mp3", title="A & B <test>",
        artist="Artist & Co.", album_artist="Artist & Co.", album="",
        track_no=1, disc_no=1, year=2024, genre="", duration=100.0,
    )
    xml = _didl(track, "http://host/media/3/a%26b.mp3")
    assert "&amp;" in xml
    assert "&lt;" in xml


# ---------------------------------------------------------------------------
# _soap helper
# ---------------------------------------------------------------------------

def test_soap_sends_correct_headers_and_action():
    mock_resp = MagicMock()
    mock_resp.status_code = 200

    with patch("lyon.core.cast_controller.requests.post", return_value=mock_resp) as mock_post:
        _soap("http://renderer/AVTransport/control",
              "urn:schemas-upnp-org:service:AVTransport:1",
              "Play",
              {"InstanceID": "0", "Speed": "1"})

    args, kwargs = mock_post.call_args
    assert args[0] == "http://renderer/AVTransport/control"
    assert kwargs["headers"]["SOAPAction"] == (
        '"urn:schemas-upnp-org:service:AVTransport:1#Play"'
    )
    body = kwargs["data"].decode("utf-8")
    assert "<u:Play" in body
    assert "<InstanceID>0</InstanceID>" in body
    assert "<Speed>1</Speed>" in body


def test_soap_raises_on_http_error():
    mock_resp = MagicMock()
    mock_resp.status_code = 500
    mock_resp.content = b"not xml"

    with patch("lyon.core.cast_controller.requests.post", return_value=mock_resp):
        with pytest.raises(RuntimeError, match="HTTP 500"):
            _soap("http://renderer/control",
                  "urn:schemas-upnp-org:service:AVTransport:1",
                  "Play", {"InstanceID": "0", "Speed": "1"})


_UPNP_FAULT = (
    b'<?xml version="1.0"?>'
    b'<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/">'
    b"<s:Body><s:Fault><faultcode>s:Client</faultcode>"
    b"<faultstring>UPnPError</faultstring><detail>"
    b'<UPnPError xmlns="urn:schemas-upnp-org:control-1-0">'
    b"<errorCode>{code}</errorCode>{desc}</UPnPError>"
    b"</detail></s:Fault></s:Body></s:Envelope>"
)


def test_soap_surfaces_upnp_fault_detail():
    mock_resp = MagicMock()
    mock_resp.status_code = 500
    mock_resp.content = _UPNP_FAULT.replace(
        b"{code}", b"716"
    ).replace(b"{desc}", b"<errorDescription>Resource not found</errorDescription>")

    with patch("lyon.core.cast_controller.requests.post", return_value=mock_resp):
        with pytest.raises(RuntimeError, match="716.*Resource not found"):
            _soap("http://renderer/control",
                  "urn:schemas-upnp-org:service:AVTransport:1",
                  "SetAVTransportURI", {"InstanceID": "0"})


def test_soap_fault_falls_back_to_code_name_without_description():
    mock_resp = MagicMock()
    mock_resp.status_code = 500
    mock_resp.content = _UPNP_FAULT.replace(b"{code}", b"714").replace(b"{desc}", b"")

    with patch("lyon.core.cast_controller.requests.post", return_value=mock_resp):
        with pytest.raises(RuntimeError, match="714.*Illegal MIME type"):
            _soap("http://renderer/control",
                  "urn:schemas-upnp-org:service:AVTransport:1",
                  "SetAVTransportURI", {"InstanceID": "0"})


# ---------------------------------------------------------------------------
# CastController.start_cast
# ---------------------------------------------------------------------------

def test_start_cast_sends_set_uri_and_play(qapp):
    renderer = _make_renderer()
    track = _make_track()
    player = _make_player(track=track)
    dlna = _make_dlna()

    ctrl = CastController()
    mock_resp = MagicMock()
    mock_resp.status_code = 200

    try:
        with patch("lyon.core.cast_controller.requests.post", return_value=mock_resp) as mock_post:
            ctrl.start_cast(renderer, player, dlna)
            _drain(ctrl, qapp)

        assert mock_post.call_count == 2
        actions = [c.kwargs["headers"]["SOAPAction"] for c in mock_post.call_args_list]
        assert any("SetAVTransportURI" in a for a in actions)
        assert any(a.endswith('#Play"') for a in actions)
    finally:
        ctrl.shutdown()


def test_start_cast_does_not_block_gui(qapp):
    """start_cast must return quickly even when SOAP is slow."""
    renderer = _make_renderer()
    track = _make_track()
    player = _make_player(track=track)
    dlna = _make_dlna()

    ctrl = CastController()
    mock_resp = MagicMock()
    mock_resp.status_code = 200

    def slow_post(*args, **kwargs):
        time.sleep(0.5)
        return mock_resp

    try:
        start = time.monotonic()
        with patch("lyon.core.cast_controller.requests.post", side_effect=slow_post):
            ctrl.start_cast(renderer, player, dlna)
        elapsed = time.monotonic() - start
        assert elapsed < 0.2, f"start_cast blocked for {elapsed:.2f}s"
    finally:
        ctrl.shutdown()


def test_soap_jobs_execute_in_order(qapp):
    renderer = _make_renderer()
    track = _make_track()
    player = _make_player(track=track)
    dlna = _make_dlna()

    ctrl = CastController()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    recorded_actions: list[str] = []

    def recording_post(*args, **kwargs):
        action_header = kwargs["headers"]["SOAPAction"]
        for name in ("SetAVTransportURI", "Play", "Pause", "Stop"):
            if name in action_header:
                recorded_actions.append(name)
                break
        return mock_resp

    try:
        with patch("lyon.core.cast_controller.requests.post", side_effect=recording_post):
            ctrl.start_cast(renderer, player, dlna)
            _drain(ctrl, qapp)

        assert recorded_actions[:2] == ["SetAVTransportURI", "Play"]
    finally:
        ctrl.shutdown()


def test_soap_failure_emits_cast_error_async(qapp):
    renderer = _make_renderer()
    track = _make_track()
    player = _make_player(track=track)
    dlna = _make_dlna()

    ctrl = CastController()
    errors: list[str] = []
    ctrl.cast_error.connect(errors.append)

    try:
        with patch("lyon.core.cast_controller.requests.post", side_effect=Exception("timeout")):
            ctrl.start_cast(renderer, player, dlna)
            _drain(ctrl, qapp)

        assert errors
    finally:
        ctrl.shutdown()


def test_start_cast_pauses_local_player(qapp):
    renderer = _make_renderer()
    track = _make_track()
    player = _make_player(track=track)
    dlna = _make_dlna()

    ctrl = CastController()
    mock_resp = MagicMock()
    mock_resp.status_code = 200

    try:
        with patch("lyon.core.cast_controller.requests.post", return_value=mock_resp):
            ctrl.start_cast(renderer, player, dlna)

        player.pause.assert_called_once()
    finally:
        ctrl.shutdown()


def test_start_cast_track_sends_video_uri_and_pauses_local_video(qapp):
    renderer = _make_renderer()
    track = Track(
        id=7,
        path="/videos/clip.mp4",
        title="Sea Clip",
        artist="",
        album_artist="",
        album="",
        track_no=0,
        disc_no=0,
        year=2026,
        genre="",
        duration=60.0,
        media_type="video",
    )
    dlna = _make_dlna()
    pauses: list[bool] = []

    ctrl = CastController()
    mock_resp = MagicMock()
    mock_resp.status_code = 200

    try:
        with patch("lyon.core.cast_controller.requests.post", return_value=mock_resp) as mock_post:
            ctrl.start_cast_track(
                renderer,
                track,
                dlna,
                pause_local=lambda: pauses.append(True),
            )
            _drain(ctrl, qapp)

        assert pauses == [True]
        assert mock_post.call_count == 2
        bodies = [call.kwargs["data"].decode("utf-8") for call in mock_post.call_args_list]
        assert any("clip.mp4" in body for body in bodies)
        assert any("object.item.videoItem" in body for body in bodies)
    finally:
        ctrl.shutdown()


def test_start_cast_emits_cast_started(qapp):
    renderer = _make_renderer()
    track = _make_track()
    player = _make_player(track=track)
    dlna = _make_dlna()

    ctrl = CastController()
    received = []
    ctrl.cast_started.connect(received.append)

    mock_resp = MagicMock()
    mock_resp.status_code = 200

    try:
        with patch("lyon.core.cast_controller.requests.post", return_value=mock_resp):
            ctrl.start_cast(renderer, player, dlna)
            _drain(ctrl, qapp)

        assert received == ["Living Room TV"]
    finally:
        ctrl.shutdown()


def test_start_cast_emits_error_when_nothing_playing(qapp):
    renderer = _make_renderer()
    player = _make_player(track=None)
    dlna = _make_dlna()

    ctrl = CastController()
    errors = []
    ctrl.cast_error.connect(errors.append)

    try:
        ctrl.start_cast(renderer, player, dlna)

        assert errors
        assert "Nothing is currently playing" in errors[0]
    finally:
        ctrl.shutdown()


def test_start_cast_emits_error_when_dlna_not_running(qapp):
    renderer = _make_renderer()
    track = _make_track()
    player = _make_player(track=track)
    dlna = _make_dlna(running=False)

    ctrl = CastController()
    errors = []
    ctrl.cast_error.connect(errors.append)

    try:
        ctrl.start_cast(renderer, player, dlna)

        assert errors
        assert "DLNA sharing" in errors[0]
    finally:
        ctrl.shutdown()


def test_start_cast_emits_error_when_track_not_servable(qapp):
    renderer = _make_renderer()
    track = _make_track("/music/stream.mp3", track_id=0)
    track.is_library_item = False
    player = _make_player(track=track)
    dlna = _make_dlna()

    ctrl = CastController()
    errors = []
    ctrl.cast_error.connect(errors.append)

    try:
        ctrl.start_cast(renderer, player, dlna)

        assert errors
        assert "file not found in library" in errors[0]
    finally:
        ctrl.shutdown()


def test_start_cast_emits_error_on_soap_failure(qapp):
    renderer = _make_renderer()
    track = _make_track()
    player = _make_player(track=track)
    dlna = _make_dlna()

    ctrl = CastController()
    errors = []
    started = []
    ctrl.cast_error.connect(errors.append)
    ctrl.cast_started.connect(started.append)

    try:
        with patch("lyon.core.cast_controller.requests.post", side_effect=Exception("timeout")):
            ctrl.start_cast(renderer, player, dlna)
            _drain(ctrl, qapp)

        assert errors
        assert not started
        assert not ctrl.is_casting
    finally:
        ctrl.shutdown()


# ---------------------------------------------------------------------------
# CastController.stop_cast
# ---------------------------------------------------------------------------

def test_stop_cast_sends_stop_soap(qapp):
    renderer = _make_renderer()
    track = _make_track()
    player = _make_player(track=track)
    dlna = _make_dlna()

    ctrl = CastController()
    mock_resp = MagicMock()
    mock_resp.status_code = 200

    try:
        with patch("lyon.core.cast_controller.requests.post", return_value=mock_resp) as mock_post:
            ctrl.start_cast(renderer, player, dlna)
            _drain(ctrl, qapp)
            mock_post.reset_mock()
            ctrl.stop_cast()
            _drain(ctrl, qapp)

        assert mock_post.call_count == 1
        action = mock_post.call_args.kwargs["headers"]["SOAPAction"]
        assert action.endswith('#Stop"')
    finally:
        ctrl.shutdown()


def test_stop_cast_emits_cast_stopped(qapp):
    renderer = _make_renderer()
    track = _make_track()
    player = _make_player(track=track)
    dlna = _make_dlna()

    ctrl = CastController()
    stopped = []
    ctrl.cast_stopped.connect(lambda: stopped.append(True))

    mock_resp = MagicMock()
    mock_resp.status_code = 200

    try:
        with patch("lyon.core.cast_controller.requests.post", return_value=mock_resp):
            ctrl.start_cast(renderer, player, dlna)
            ctrl.stop_cast()

        assert stopped
    finally:
        ctrl.shutdown()


def test_stop_cast_clears_is_casting(qapp):
    renderer = _make_renderer()
    track = _make_track()
    player = _make_player(track=track)
    dlna = _make_dlna()

    ctrl = CastController()
    mock_resp = MagicMock()
    mock_resp.status_code = 200

    try:
        with patch("lyon.core.cast_controller.requests.post", return_value=mock_resp):
            ctrl.start_cast(renderer, player, dlna)
            assert ctrl.is_casting
            ctrl.stop_cast()
            assert not ctrl.is_casting
    finally:
        ctrl.shutdown()


def test_stop_cast_noop_when_not_casting(qapp):
    ctrl = CastController()
    stopped = []
    ctrl.cast_stopped.connect(lambda: stopped.append(True))
    try:
        ctrl.stop_cast()
        assert not stopped
    finally:
        ctrl.shutdown()


def test_stop_cast_tolerates_soap_failure(qapp):
    renderer = _make_renderer()
    track = _make_track()
    player = _make_player(track=track)
    dlna = _make_dlna()

    ctrl = CastController()
    stopped = []
    ctrl.cast_stopped.connect(lambda: stopped.append(True))

    mock_resp = MagicMock()
    mock_resp.status_code = 200

    try:
        with patch("lyon.core.cast_controller.requests.post", return_value=mock_resp):
            ctrl.start_cast(renderer, player, dlna)

        with patch("lyon.core.cast_controller.requests.post", side_effect=Exception("gone")):
            ctrl.stop_cast()
            _drain(ctrl, qapp)

        assert stopped
        assert not ctrl.is_casting
    finally:
        ctrl.shutdown()


def test_stop_cast_drops_pending_stale_jobs_before_stop(qapp):
    renderer = _make_renderer()
    ctrl = CastController()
    try:
        ctrl._renderer = renderer
        ctrl._session_id = 1
        ctrl._worker.submit(_SoapJob("stale-track-change", []))

        ctrl.stop_cast()

        pending_labels = [
            job.label
            for job in list(ctrl._worker._jobs.queue)
            if job is not None
        ]
        assert "stale-track-change" not in pending_labels
        assert pending_labels == ["stop"]
    finally:
        ctrl.shutdown()


# ---------------------------------------------------------------------------
# is_casting / renderer properties
# ---------------------------------------------------------------------------

def test_is_casting_false_initially(qapp):
    ctrl = CastController()
    try:
        assert not ctrl.is_casting
        assert ctrl.renderer is None
    finally:
        ctrl.shutdown()


# ---------------------------------------------------------------------------
# CAST-3: local stop ends the cast session
# ---------------------------------------------------------------------------

def test_local_stop_ends_cast_session(qapp):
    renderer = _make_renderer()
    track = _make_track()
    player = _make_player(track=track)
    dlna = _make_dlna()

    ctrl = CastController()
    stopped = []
    ctrl.cast_stopped.connect(lambda: stopped.append(True))

    mock_resp = MagicMock()
    mock_resp.status_code = 200

    try:
        with patch("lyon.core.cast_controller.requests.post", return_value=mock_resp):
            ctrl.start_cast(renderer, player, dlna)
            ctrl._on_state_changed("stopped")
            _drain(ctrl, qapp)

        assert not ctrl.is_casting
        assert stopped
    finally:
        ctrl.shutdown()


def test_local_stop_does_not_double_stop(qapp):
    """stop_cast is idempotent — calling it twice must not crash or double-emit."""
    renderer = _make_renderer()
    track = _make_track()
    player = _make_player(track=track)
    dlna = _make_dlna()

    ctrl = CastController()
    stopped_count = [0]
    ctrl.cast_stopped.connect(lambda: stopped_count.__setitem__(0, stopped_count[0] + 1))

    mock_resp = MagicMock()
    mock_resp.status_code = 200

    try:
        with patch("lyon.core.cast_controller.requests.post", return_value=mock_resp):
            ctrl.start_cast(renderer, player, dlna)
        ctrl.stop_cast()
        ctrl.stop_cast()  # second call must be a no-op

        assert stopped_count[0] == 1
    finally:
        ctrl.shutdown()


# ---------------------------------------------------------------------------
# CAST-4: cast queue advance re-pauses local player
# ---------------------------------------------------------------------------

def test_cast_next_repauses_local_player(qapp):
    renderer = _make_renderer()
    track = _make_track()
    player = _make_player(track=track)
    player.queue.return_value = [track, _make_track(track_id=2)]
    player.current_index.return_value = 0
    player.repeat.return_value = None
    player.shuffle.return_value = False
    dlna = _make_dlna()

    ctrl = CastController()
    mock_resp = MagicMock()
    mock_resp.status_code = 200

    try:
        with patch("lyon.core.cast_controller.requests.post", return_value=mock_resp):
            ctrl.start_cast(renderer, player, dlna)
            player.pause.reset_mock()
            ctrl.next_track()

        player.pause.assert_called_once()
    finally:
        ctrl.shutdown()


def test_cast_next_does_not_pause_renderer(qapp):
    """After a cast skip, SOAP actions must be SetAVTransportURI + Play, no Pause."""
    renderer = _make_renderer()
    track = _make_track()
    track2 = _make_track(track_id=2)
    player = _make_player(track=track)
    player.queue.return_value = [track, track2]
    player.current_index.return_value = 0
    player.repeat.return_value = None
    player.shuffle.return_value = False
    dlna = _make_dlna()

    ctrl = CastController()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    recorded_actions: list[str] = []

    def recording_post(*args, **kwargs):
        action_header = kwargs["headers"]["SOAPAction"]
        for name in ("SetAVTransportURI", "Play", "Pause", "Stop"):
            if name in action_header:
                recorded_actions.append(name)
                break
        return mock_resp

    try:
        with patch("lyon.core.cast_controller.requests.post", side_effect=recording_post):
            ctrl.start_cast(renderer, player, dlna)
            _drain(ctrl, qapp)
            recorded_actions.clear()

            # Simulate track_changed fired by load_queue inside next_track
            ctrl.next_track()
            ctrl._on_track_changed(track2)
            _drain(ctrl, qapp)

        assert "Pause" not in recorded_actions
        assert "SetAVTransportURI" in recorded_actions
        assert "Play" in recorded_actions
    finally:
        ctrl.shutdown()


def test_cast_shuffle_remembers_manual_track_change(qapp):
    renderer = _make_renderer()
    track1 = _make_track(track_id=1)
    track2 = _make_track(track_id=2)
    track3 = _make_track(track_id=3)
    queue = [track1, track2, track3]
    player = _make_player(track=track1)
    player.queue.return_value = queue
    player.current_index.return_value = 0
    player.repeat.return_value = RepeatMode.OFF
    player.shuffle.return_value = True
    dlna = _make_dlna()

    ctrl = CastController()
    mock_resp = MagicMock()
    mock_resp.status_code = 200

    def choose(candidates):
        assert candidates == [2]
        return candidates[0]

    try:
        with patch("lyon.core.cast_controller.requests.post", return_value=mock_resp), \
             patch("lyon.core.cast_controller.random.choice", side_effect=choose):
            ctrl.start_cast(renderer, player, dlna)
            player.current_index.return_value = 1
            ctrl._on_track_changed(track2)
            ctrl.next_track()

        player.load_queue.assert_called_with(queue, 2)
    finally:
        ctrl.shutdown()


# ---------------------------------------------------------------------------
# CAST-5: stale async jobs do not resurrect stopped sessions
# ---------------------------------------------------------------------------

def test_stale_start_completion_after_stop_is_ignored(qapp):
    renderer = _make_renderer()
    track = _make_track()
    player = _make_player(track=track)
    dlna = _make_dlna()

    ctrl = CastController()
    states: list[str] = []
    ctrl.cast_playback_state_changed.connect(states.append)

    mock_resp = MagicMock()
    mock_resp.status_code = 200

    try:
        with patch("lyon.core.cast_controller.requests.post", return_value=mock_resp):
            ctrl.start_cast(renderer, player, dlna)
            session_id = ctrl._session_id
            ctrl.stop_cast()

        states.clear()
        ctrl._on_job_done(
            _SoapJob(
                "start",
                [],
                on_success_state="playing",
                session_id=session_id,
                renderer_name=renderer.friendly_name,
            ),
            None,
        )

        assert not ctrl.is_casting
        assert not ctrl._remote_playing
        assert states == []
    finally:
        ctrl.shutdown()


# ---------------------------------------------------------------------------
# CAST-1: shutdown joins the worker
# ---------------------------------------------------------------------------

def test_shutdown_joins_worker(qapp):
    ctrl = CastController()
    try:
        assert not ctrl._thread.isRunning()
        ctrl._submit_job(_SoapJob("noop", [], session_id=ctrl._session_id, report_errors=False))
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline and not ctrl._thread.isRunning():
            qapp.processEvents()
            time.sleep(0.01)
        assert ctrl._thread.isRunning()
        ctrl.shutdown()
        assert not ctrl._thread.isRunning()
    finally:
        ctrl.shutdown()

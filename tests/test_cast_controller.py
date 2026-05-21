"""Tests for CastController SOAP logic and player signal proxying."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from lyon.core.cast_controller import CastController, _didl, _media_url, _soap
from lyon.core.dlna_renderer_discovery import RendererDevice
from lyon.core.library import Track


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
    return dlna


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

    with patch("lyon.core.cast_controller.requests.post", return_value=mock_resp):
        with pytest.raises(RuntimeError, match="HTTP 500"):
            _soap("http://renderer/control",
                  "urn:schemas-upnp-org:service:AVTransport:1",
                  "Play", {"InstanceID": "0", "Speed": "1"})


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

    with patch("lyon.core.cast_controller.requests.post", return_value=mock_resp) as mock_post:
        ctrl.start_cast(renderer, player, dlna)

    assert mock_post.call_count == 2
    actions = [c.kwargs["headers"]["SOAPAction"] for c in mock_post.call_args_list]
    assert any("SetAVTransportURI" in a for a in actions)
    assert any('"Play"' in a for a in actions)


def test_start_cast_pauses_local_player(qapp):
    renderer = _make_renderer()
    track = _make_track()
    player = _make_player(track=track)
    dlna = _make_dlna()

    ctrl = CastController()
    mock_resp = MagicMock()
    mock_resp.status_code = 200

    with patch("lyon.core.cast_controller.requests.post", return_value=mock_resp):
        ctrl.start_cast(renderer, player, dlna)

    player.pause.assert_called_once()


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

    with patch("lyon.core.cast_controller.requests.post", return_value=mock_resp):
        ctrl.start_cast(renderer, player, dlna)

    assert received == ["Living Room TV"]


def test_start_cast_emits_error_when_nothing_playing(qapp):
    renderer = _make_renderer()
    player = _make_player(track=None)
    dlna = _make_dlna()

    ctrl = CastController()
    errors = []
    ctrl.cast_error.connect(errors.append)

    ctrl.start_cast(renderer, player, dlna)

    assert errors
    assert "Nothing is currently playing" in errors[0]


def test_start_cast_emits_error_when_dlna_not_running(qapp):
    renderer = _make_renderer()
    track = _make_track()
    player = _make_player(track=track)
    dlna = _make_dlna(running=False)

    ctrl = CastController()
    errors = []
    ctrl.cast_error.connect(errors.append)

    ctrl.start_cast(renderer, player, dlna)

    assert errors
    assert "DLNA sharing" in errors[0]


def test_start_cast_emits_error_on_soap_failure(qapp):
    renderer = _make_renderer()
    track = _make_track()
    player = _make_player(track=track)
    dlna = _make_dlna()

    ctrl = CastController()
    errors = []
    ctrl.cast_error.connect(errors.append)

    with patch("lyon.core.cast_controller.requests.post", side_effect=Exception("timeout")):
        ctrl.start_cast(renderer, player, dlna)

    assert errors
    assert not ctrl.is_casting


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

    with patch("lyon.core.cast_controller.requests.post", return_value=mock_resp) as mock_post:
        ctrl.start_cast(renderer, player, dlna)
        mock_post.reset_mock()
        ctrl.stop_cast()

    assert mock_post.call_count == 1
    action = mock_post.call_args.kwargs["headers"]["SOAPAction"]
    assert '"Stop"' in action


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

    with patch("lyon.core.cast_controller.requests.post", return_value=mock_resp):
        ctrl.start_cast(renderer, player, dlna)
        ctrl.stop_cast()

    assert stopped


def test_stop_cast_clears_is_casting(qapp):
    renderer = _make_renderer()
    track = _make_track()
    player = _make_player(track=track)
    dlna = _make_dlna()

    ctrl = CastController()
    mock_resp = MagicMock()
    mock_resp.status_code = 200

    with patch("lyon.core.cast_controller.requests.post", return_value=mock_resp):
        ctrl.start_cast(renderer, player, dlna)
        assert ctrl.is_casting
        ctrl.stop_cast()
        assert not ctrl.is_casting


def test_stop_cast_noop_when_not_casting(qapp):
    ctrl = CastController()
    stopped = []
    ctrl.cast_stopped.connect(lambda: stopped.append(True))
    ctrl.stop_cast()
    assert not stopped


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

    with patch("lyon.core.cast_controller.requests.post", return_value=mock_resp):
        ctrl.start_cast(renderer, player, dlna)

    with patch("lyon.core.cast_controller.requests.post", side_effect=Exception("gone")):
        ctrl.stop_cast()

    assert stopped
    assert not ctrl.is_casting


# ---------------------------------------------------------------------------
# is_casting / renderer properties
# ---------------------------------------------------------------------------

def test_is_casting_false_initially(qapp):
    ctrl = CastController()
    assert not ctrl.is_casting
    assert ctrl.renderer is None

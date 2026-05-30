"""Tests for ScrobblerService and related helpers."""
from __future__ import annotations

import importlib
import time
from unittest.mock import MagicMock, patch

import pytest
from lyon.core.scrobbler import (
    _SCROBBLE_CAP_S,
    ScrobblerService,
    _lastfm_post,
    _lastfm_sign,
    _lbz_post,
    _scrobbler_user_agent,
)
from lyon.core.settings import Settings

# ScrobblerService is a QObject — every test in this module needs a QApplication.
pytestmark = pytest.mark.usefixtures("qapp")


def _make_track(
    title="Song",
    artist="Artist",
    album="Album",
    duration=240.0,
    track_id=1,
    playback_is_location=False,
    is_library_item=True,
):
    from lyon.core.library import Track

    return Track(
        id=track_id,
        path=f"/music/{title}.flac",
        title=title,
        artist=artist,
        album_artist="",
        album=album,
        track_no=1,
        disc_no=1,
        year=2024,
        genre="",
        duration=duration,
        playback_uri=f"https://stream.example.test/{title}" if playback_is_location else None,
        playback_is_location=playback_is_location,
        is_library_item=is_library_item,
    )


def _make_player():
    """Minimal Player stand-in with signals as MagicMocks."""
    player = MagicMock()
    player.track_changed = MagicMock()
    player.track_changed.connect = MagicMock()
    player.position_changed = MagicMock()
    player.position_changed.connect = MagicMock()
    return player


def _make_settings(**kwargs):
    return Settings(**kwargs)


# ------------------------------------------------------------------ unit tests

class TestLastFmSign:
    def test_known_signature(self):
        # If API secret is "", md5("api_keyKEYmethodauth.getTokensecret".encode()) would work,
        # but since _LASTFM_API_SECRET is "", we just check the function returns a hex string.
        params = {"method": "auth.getToken", "api_key": "KEY", "format": "json"}
        sig = _lastfm_sign(params)
        assert len(sig) == 32
        assert all(c in "0123456789abcdef" for c in sig)

    def test_format_excluded_from_signature(self):
        params_with = {"method": "m", "api_key": "k", "format": "json"}
        params_without = {"method": "m", "api_key": "k"}
        assert _lastfm_sign(params_with) == _lastfm_sign(params_without)

    def test_api_sig_excluded_from_signature(self):
        params = {"method": "m", "api_key": "k", "api_sig": "old"}
        sig = _lastfm_sign(params)
        assert len(sig) == 32


class TestScrobblerHttpHelpers:
    def test_lastfm_defaults_to_unconfigured_without_env_credentials(self, monkeypatch):
        monkeypatch.delenv("LYON_LASTFM_API_KEY", raising=False)
        monkeypatch.delenv("LYON_LASTFM_API_SECRET", raising=False)

        import lyon.core.scrobbler as scrobbler

        importlib.reload(scrobbler)

        assert scrobbler.lastfm_api_configured() is False

    def test_lastfm_post_uses_shared_session_and_returns_json(self, monkeypatch):
        calls = []

        class Response:
            def json(self):
                return {"ok": True}

        class Session:
            def post(self, url, *, data=None, timeout=None, **_kwargs):
                calls.append((url, data, timeout))
                return Response()

        monkeypatch.setattr("lyon.core.scrobbler._SESSION", Session())
        params = {"method": "track.updateNowPlaying", "api_key": "KEY"}

        result = _lastfm_post(params)

        assert result == {"ok": True}
        assert calls == [(
            "https://ws.audioscrobbler.com/2.0/",
            params,
            10,
        )]
        assert params["format"] == "json"
        assert "api_sig" in params

    def test_listenbrainz_post_uses_shared_session_json_body(self, monkeypatch):
        calls = []

        class Response:
            status_code = 200

        class Session:
            def post(self, url, *, json=None, headers=None, timeout=None, **_kwargs):
                calls.append((url, json, headers, timeout))
                return Response()

        monkeypatch.setattr("lyon.core.scrobbler._SESSION", Session())
        payload = {"listen_type": "single", "payload": []}

        assert _lbz_post(payload, "token-123") is True
        assert calls == [(
            "https://api.listenbrainz.org/1/submit-listens",
            payload,
            {
                "Authorization": "Token token-123",
                "Content-Type": "application/json",
                "User-Agent": _scrobbler_user_agent(),
            },
            10,
        )]

    def test_scrobbler_http_helpers_handle_errors(self, monkeypatch):
        class Session:
            def post(self, *_args, **_kwargs):
                raise RuntimeError("offline")

        monkeypatch.setattr("lyon.core.scrobbler._SESSION", Session())

        assert _lastfm_post({"method": "auth.getToken"})["error"] == -1
        assert _lbz_post({"payload": []}, "token") is False


class TestLastFmCredentials:
    def test_module_level_credentials_configure_lastfm(self, monkeypatch):
        import lyon.core.scrobbler as scrobbler

        monkeypatch.setattr(scrobbler, "_LASTFM_API_KEY", "build-key")
        monkeypatch.setattr(scrobbler, "_LASTFM_API_SECRET", "build-secret")

        assert scrobbler.lastfm_api_configured() is True
        assert scrobbler.lastfm_auth_url("token-123") == (
            "https://www.last.fm/api/auth/?api_key=build-key&token=token-123"
        )

    def test_missing_secret_keeps_lastfm_unconfigured(self, monkeypatch):
        import lyon.core.scrobbler as scrobbler

        monkeypatch.setattr(scrobbler, "_LASTFM_API_KEY", "build-key")
        monkeypatch.setattr(scrobbler, "_LASTFM_API_SECRET", "")

        assert scrobbler.lastfm_api_configured() is False


class TestScrobblerServiceInit:
    def test_connects_to_player(self):
        player = _make_player()
        svc = ScrobblerService(player, Settings())
        player.track_changed.connect.assert_called_once()
        player.position_changed.connect.assert_called_once()
        svc.deleteLater()


class TestTrackChanged:
    def setup_method(self):
        self.player = _make_player()
        self.svc = ScrobblerService(self.player, Settings())

    def teardown_method(self):
        self.svc.deleteLater()

    def test_sets_current_track(self):
        track = _make_track()
        self.svc._on_track_changed(track)
        assert self.svc._current_track is track

    def test_resets_scrobbled_flag(self):
        self.svc._scrobbled = True
        self.svc._on_track_changed(_make_track())
        assert not self.svc._scrobbled

    def test_none_clears_track(self):
        self.svc._on_track_changed(_make_track())
        self.svc._on_track_changed(None)
        assert self.svc._current_track is None

    def test_now_playing_submitted_when_enabled(self, monkeypatch):
        import lyon.core.scrobbler as scrobbler
        monkeypatch.setattr(scrobbler, "_LASTFM_API_KEY", "testkey")
        monkeypatch.setattr(scrobbler, "_LASTFM_API_SECRET", "testsecret")
        settings = _make_settings(
            lastfm_scrobbling_enabled=True,
            lastfm_session_key="sk123",
        )
        self.svc.update_settings(settings)
        with patch("lyon.core.scrobbler.QThreadPool") as mock_pool:
            mock_pool.globalInstance.return_value = MagicMock()
            self.svc._on_track_changed(_make_track())
            mock_pool.globalInstance.return_value.start.assert_called_once()

    def test_now_playing_not_submitted_without_lastfm_secret(self, monkeypatch):
        import lyon.core.scrobbler as scrobbler
        monkeypatch.setattr(scrobbler, "_LASTFM_API_KEY", "testkey")
        monkeypatch.setattr(scrobbler, "_LASTFM_API_SECRET", "")
        settings = _make_settings(
            lastfm_scrobbling_enabled=True,
            lastfm_session_key="sk123",
        )
        self.svc.update_settings(settings)
        with patch("lyon.core.scrobbler.QThreadPool") as mock_pool:
            mock_pool.globalInstance.return_value = MagicMock()
            self.svc._on_track_changed(_make_track())
            mock_pool.globalInstance.return_value.start.assert_not_called()

    def test_no_submission_when_disabled(self):
        settings = _make_settings(lastfm_scrobbling_enabled=False)
        self.svc.update_settings(settings)
        with patch("lyon.core.scrobbler.QThreadPool") as mock_pool:
            mock_pool.globalInstance.return_value = MagicMock()
            self.svc._on_track_changed(_make_track())
            mock_pool.globalInstance.return_value.start.assert_not_called()


class TestPositionChanged:
    def setup_method(self):
        self.player = _make_player()
        self.svc = ScrobblerService(self.player, Settings())
        self.svc._current_track = _make_track(duration=240.0)
        self.svc._track_start_time = time.time() - 10

    def teardown_method(self):
        self.svc.deleteLater()

    def _advance_to(self, pos_ms: int, total_ms: int, *, step_ms: int = 10_000) -> None:
        for pos in range(0, pos_ms + 1, step_ms):
            self.svc._on_position_changed(pos, total_ms)
        if pos_ms % step_ms:
            self.svc._on_position_changed(pos_ms, total_ms)

    def test_no_scrobble_before_threshold(self):
        with patch.object(self.svc, "_submit_scrobble") as mock:
            self._advance_to(110_000, 240_000)
            mock.assert_not_called()

    def test_scrobble_at_50_percent(self):
        with patch.object(self.svc, "_submit_scrobble") as mock:
            self._advance_to(120_000, 240_000)  # exactly 50%
            mock.assert_called_once()

    def test_scrobble_capped_at_240s(self):
        # 10-minute track: 50% is 300s which exceeds 240s cap.
        self.svc._current_track = _make_track(duration=600.0)
        with patch.object(self.svc, "_submit_scrobble") as mock:
            self._advance_to(240_000, 600_000)
            mock.assert_called_once()

    def test_no_scrobble_before_cap_on_long_track(self):
        self.svc._current_track = _make_track(duration=600.0)
        with patch.object(self.svc, "_submit_scrobble") as mock:
            self._advance_to(200_000, 600_000)
            mock.assert_not_called()

    def test_no_duplicate_scrobble(self):
        with patch.object(self.svc, "_submit_scrobble") as mock:
            self._advance_to(120_000, 240_000)
            self.svc._on_position_changed(180_000, 240_000)
            assert mock.call_count == 1

    def test_forward_seek_does_not_count_as_listened_time(self):
        self.svc._current_track = _make_track(duration=40.0)
        with patch.object(self.svc, "_submit_scrobble") as mock:
            self.svc._on_position_changed(0, 40_000)
            self.svc._on_position_changed(25_000, 40_000)
            mock.assert_not_called()

    def test_short_track_not_scrobbled(self):
        self.svc._current_track = _make_track(duration=20.0)
        with patch.object(self.svc, "_submit_scrobble") as mock:
            self.svc._on_position_changed(10_000, 20_000)
            mock.assert_not_called()

    def test_no_track_no_scrobble(self):
        self.svc._current_track = None
        with patch.object(self.svc, "_submit_scrobble") as mock:
            self.svc._on_position_changed(120_000, 240_000)
            mock.assert_not_called()

    def test_zero_duration_ignored(self):
        with patch.object(self.svc, "_submit_scrobble") as mock:
            self.svc._on_position_changed(0, 0)
            mock.assert_not_called()

    def test_durationless_stream_accumulates_until_stream_threshold(self):
        self.svc._current_track = _make_track(
            title="One More Time",
            artist="Daft Punk",
            duration=0.0,
            playback_is_location=True,
            is_library_item=False,
        )
        with patch.object(self.svc, "_submit_scrobble") as mock:
            self._advance_to(_SCROBBLE_CAP_S * 1000, 0)
            mock.assert_called_once()

    def test_durationless_non_stream_ignored(self):
        self.svc._current_track = _make_track(duration=0.0)
        with patch.object(self.svc, "_submit_scrobble") as mock:
            self._advance_to(_SCROBBLE_CAP_S * 1000, 0)
            mock.assert_not_called()

    def test_tiny_backward_seek_keeps_listened_time(self):
        self.svc._last_position_ms = 240_000
        self.svc._listened_ms = 100_000

        self.svc._on_position_changed(239_999, 240_000)

        assert self.svc._listened_ms == 100_000

    def test_large_backward_seek_resets_listened_time(self):
        self.svc._last_position_ms = 240_000
        self.svc._listened_ms = 100_000

        self.svc._on_position_changed(230_000, 240_000)

        assert self.svc._listened_ms == 0


class TestScrobblerUpdateSettings:
    def test_update_settings_replaces_reference(self):
        player = _make_player()
        svc = ScrobblerService(player, Settings())
        new_settings = _make_settings(
            lastfm_scrobbling_enabled=True,
            lastfm_session_key="newkey",
        )
        svc.update_settings(new_settings)
        assert svc._settings is new_settings
        svc.deleteLater()


class TestStreamPlaceholderGuard:
    """Submissions must skip placeholder Track metadata used for raw URL plays."""

    def setup_method(self):
        self.player = _make_player()
        self.svc = ScrobblerService(self.player, Settings())

    def teardown_method(self):
        self.svc.deleteLater()

    def test_now_playing_skips_network_stream_placeholder(self, monkeypatch):
        import lyon.core.scrobbler as scrobbler
        monkeypatch.setattr(scrobbler, "_LASTFM_API_KEY", "testkey")
        monkeypatch.setattr(scrobbler, "_LASTFM_API_SECRET", "testsecret")
        settings = _make_settings(
            lastfm_scrobbling_enabled=True,
            lastfm_session_key="sk123",
        )
        self.svc.update_settings(settings)
        track = _make_track(title="Sea Lyon Jazz", artist="Network Stream")
        with patch("lyon.core.scrobbler.QThreadPool") as mock_pool:
            mock_pool.globalInstance.return_value = MagicMock()
            self.svc._on_track_changed(track)
            mock_pool.globalInstance.return_value.start.assert_not_called()

    def test_scrobble_skips_network_stream_placeholder(self, monkeypatch):
        import lyon.core.scrobbler as scrobbler
        monkeypatch.setattr(scrobbler, "_LASTFM_API_KEY", "testkey")
        monkeypatch.setattr(scrobbler, "_LASTFM_API_SECRET", "testsecret")
        settings = _make_settings(
            lastfm_scrobbling_enabled=True,
            lastfm_session_key="sk123",
        )
        self.svc.update_settings(settings)
        track = _make_track(title="Sea Lyon Jazz", artist="Network Stream")
        with patch("lyon.core.scrobbler.QThreadPool") as mock_pool:
            mock_pool.globalInstance.return_value = MagicMock()
            self.svc._submit_scrobble(track, int(time.time()))
            mock_pool.globalInstance.return_value.start.assert_not_called()

    def test_now_playing_submitted_once_metadata_arrives(self, monkeypatch):
        import lyon.core.scrobbler as scrobbler
        monkeypatch.setattr(scrobbler, "_LASTFM_API_KEY", "testkey")
        monkeypatch.setattr(scrobbler, "_LASTFM_API_SECRET", "testsecret")
        settings = _make_settings(
            lastfm_scrobbling_enabled=True,
            lastfm_session_key="sk123",
        )
        self.svc.update_settings(settings)
        track = _make_track(title="One More Time", artist="Daft Punk")
        with patch("lyon.core.scrobbler.QThreadPool") as mock_pool:
            mock_pool.globalInstance.return_value = MagicMock()
            self.svc._on_track_changed(track)
            mock_pool.globalInstance.return_value.start.assert_called_once()

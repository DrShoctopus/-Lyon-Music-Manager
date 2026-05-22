"""Last.fm and ListenBrainz scrobbling service."""
from __future__ import annotations

import hashlib
import logging
import os
import time
from typing import TYPE_CHECKING

import requests
from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

if TYPE_CHECKING:
    from .library import Track
    from .settings import Settings

LOG = logging.getLogger(__name__)

# Register your app at https://www.last.fm/api/account/create.
# Supply credentials through environment variables; never commit secrets.
_LASTFM_API_KEY: str = (os.environ.get("LYON_LASTFM_API_KEY") or "").strip()
_LASTFM_API_SECRET: str = (os.environ.get("LYON_LASTFM_API_SECRET") or "").strip()

_LASTFM_API_URL = "https://ws.audioscrobbler.com/2.0/"
_LASTFM_AUTH_URL = "https://www.last.fm/api/auth/"
_LBZ_SUBMIT_URL = "https://api.listenbrainz.org/1/submit-listens"
_SESSION = requests.Session()

_MIN_TRACK_DURATION_S = 30   # Last.fm requires >= 30 s
_SCROBBLE_CAP_S = 240        # scrobble at 4 min if track is longer than 8 min


def _lastfm_sign(params: dict[str, str]) -> str:
    keys = sorted(k for k in params if k not in ("format", "api_sig"))
    raw = "".join(f"{k}{params[k]}" for k in keys) + _LASTFM_API_SECRET
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def _lastfm_post(params: dict[str, str]) -> dict:
    params["format"] = "json"
    params["api_sig"] = _lastfm_sign(params)
    try:
        resp = _SESSION.post(_LASTFM_API_URL, data=params, timeout=10)
        return resp.json()
    except Exception as exc:
        LOG.debug("Last.fm POST failed: %s", exc)
        return {"error": -1, "message": str(exc)}


def _lbz_post(payload: dict, token: str) -> bool:
    headers = {
        "Authorization": f"Token {token}",
        "Content-Type": "application/json",
    }
    try:
        resp = _SESSION.post(
            _LBZ_SUBMIT_URL,
            json=payload,
            headers=headers,
            timeout=10,
        )
        return resp.status_code == 200
    except Exception as exc:
        LOG.debug("ListenBrainz POST failed: %s", exc)
        return False


def lastfm_api_key() -> str:
    return _LASTFM_API_KEY


def lastfm_api_secret() -> str:
    return _LASTFM_API_SECRET


def lastfm_api_configured() -> bool:
    return bool(_LASTFM_API_KEY and _LASTFM_API_SECRET)


def lastfm_auth_url(token: str) -> str:
    return f"{_LASTFM_AUTH_URL}?api_key={_LASTFM_API_KEY}&token={token}"


class _HttpTask(QRunnable):
    def __init__(self, fn):
        super().__init__()
        self.setAutoDelete(True)
        self._fn = fn

    def run(self) -> None:
        try:
            self._fn()
        except Exception as exc:
            LOG.debug("Scrobble task error: %s", exc)


class ScrobblerService(QObject):
    """Listens to Player signals and dispatches NowPlaying/Scrobble submissions."""

    # Public signals for the auth flow. Receivers should be QObjects so Qt
    # auto-disconnects when the receiver is destroyed (e.g. the settings dialog
    # closes before a request returns).
    lastfm_token_ready = Signal(str)           # token — caller opens browser, starts polling
    lastfm_auth_complete = Signal(str, str)    # (session_key, username)
    lastfm_auth_failed = Signal(str)           # error message

    # Private signals marshal worker-thread results onto the main thread.
    _token_received = Signal(str)
    _token_failed = Signal(str)
    _session_received = Signal(str, str)
    _session_failed = Signal(str)

    def __init__(self, player: object, settings: "Settings", parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._settings = settings
        self._current_track: "Track | None" = None
        self._track_start_time: float = 0.0
        self._scrobbled = False
        self._auth_token: str = ""

        self._token_received.connect(self._on_token_received)
        self._token_failed.connect(self._on_auth_error)
        self._session_received.connect(self._on_session_received)
        self._session_failed.connect(self._on_auth_error)

        player.track_changed.connect(self._on_track_changed)
        player.position_changed.connect(self._on_position_changed)

    def update_settings(self, settings: "Settings") -> None:
        self._settings = settings

    # ------------------------------------------------------------------ player hooks

    def _on_track_changed(self, track: "Track | None") -> None:
        self._current_track = track
        self._scrobbled = False
        self._track_start_time = time.time()
        if track is not None:
            self._submit_now_playing(track)

    def _on_position_changed(self, pos_ms: int, total_ms: int) -> None:
        if self._scrobbled or self._current_track is None or total_ms <= 0:
            return
        duration_s = total_ms / 1000.0
        if duration_s < _MIN_TRACK_DURATION_S:
            return
        threshold_ms = min(total_ms // 2, _SCROBBLE_CAP_S * 1000)
        if pos_ms >= threshold_ms:
            self._scrobbled = True
            self._submit_scrobble(self._current_track, int(self._track_start_time))

    # ------------------------------------------------------------------ submissions

    def _submit_now_playing(self, track: "Track") -> None:
        if (
            self._settings.lastfm_scrobbling_enabled
            and self._settings.lastfm_session_key
            and lastfm_api_configured()
        ):
            params = {
                "method": "track.updateNowPlaying",
                "api_key": _LASTFM_API_KEY,
                "sk": self._settings.lastfm_session_key,
                "track": track.title or "",
                "artist": track.display_artist or "",
            }
            if track.album:
                params["album"] = track.album
            QThreadPool.globalInstance().start(_HttpTask(lambda p=params: _lastfm_post(p)))

        if self._settings.listenbrainz_scrobbling_enabled and self._settings.listenbrainz_token:
            payload = {
                "listen_type": "playing_now",
                "payload": [{"track_metadata": {
                    "artist_name": track.display_artist or "",
                    "track_name": track.title or "",
                    "release_name": track.album or "",
                }}],
            }
            token = self._settings.listenbrainz_token
            QThreadPool.globalInstance().start(_HttpTask(lambda p=payload, t=token: _lbz_post(p, t)))

    def _submit_scrobble(self, track: "Track", timestamp: int) -> None:
        if (
            self._settings.lastfm_scrobbling_enabled
            and self._settings.lastfm_session_key
            and lastfm_api_configured()
        ):
            params = {
                "method": "track.scrobble",
                "api_key": _LASTFM_API_KEY,
                "sk": self._settings.lastfm_session_key,
                "track[0]": track.title or "",
                "artist[0]": track.display_artist or "",
                "timestamp[0]": str(timestamp),
            }
            if track.album:
                params["album[0]"] = track.album
            QThreadPool.globalInstance().start(_HttpTask(lambda p=params: _lastfm_post(p)))

        if self._settings.listenbrainz_scrobbling_enabled and self._settings.listenbrainz_token:
            payload = {
                "listen_type": "single",
                "payload": [{"listened_at": timestamp, "track_metadata": {
                    "artist_name": track.display_artist or "",
                    "track_name": track.title or "",
                    "release_name": track.album or "",
                }}],
            }
            token = self._settings.listenbrainz_token
            QThreadPool.globalInstance().start(_HttpTask(lambda p=payload, t=token: _lbz_post(p, t)))

    # ------------------------------------------------------------------ Last.fm auth flow

    def start_lastfm_auth(self) -> None:
        """Request a Last.fm token. Emits lastfm_token_ready on success."""
        if not lastfm_api_configured():
            self.lastfm_auth_failed.emit("Last.fm API key/secret not configured.")
            return

        def get_token() -> None:
            result = _lastfm_post({"method": "auth.getToken", "api_key": _LASTFM_API_KEY})
            if "error" in result:
                self._token_failed.emit(result.get("message", "Could not get token."))
                return
            token = result.get("token", "")
            if not token:
                self._token_failed.emit("Empty token received from Last.fm.")
                return
            self._token_received.emit(token)

        QThreadPool.globalInstance().start(_HttpTask(get_token))

    def poll_lastfm_session(self) -> None:
        """Poll auth.getSession once; call from a QTimer after lastfm_token_ready."""
        token = self._auth_token
        if not token:
            return

        def do_poll() -> None:
            result = _lastfm_post({
                "method": "auth.getSession",
                "api_key": _LASTFM_API_KEY,
                "token": token,
            })
            if "session" in result:
                sk = result["session"].get("key", "")
                name = result["session"].get("name", "")
                if sk:
                    self._session_received.emit(sk, name)
            elif result.get("error") not in (4, 14):
                # Errors 4 and 14 = token not yet authorised — keep polling.
                self._session_failed.emit(result.get("message", "Auth failed."))

        QThreadPool.globalInstance().start(_HttpTask(do_poll))

    def _on_token_received(self, token: str) -> None:
        self._auth_token = token
        self.lastfm_token_ready.emit(token)

    def _on_session_received(self, sk: str, name: str) -> None:
        self._auth_token = ""
        self.lastfm_auth_complete.emit(sk, name)

    def _on_auth_error(self, message: str) -> None:
        self.lastfm_auth_failed.emit(message)

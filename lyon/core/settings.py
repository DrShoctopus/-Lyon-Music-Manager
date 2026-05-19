"""User settings and path management."""
from __future__ import annotations

import json
import logging
import os
import sys
from dataclasses import dataclass, asdict, field
from pathlib import Path
from urllib.parse import urlparse

from .equalizer import (
    DEFAULT_EQ_CURVE_NAME,
    DEFAULT_EQ_PREAMP_DB,
    RESERVED_EQ_CURVE_NAMES,
    UNSAVED_EQ_CURVE_NAME,
    clamp_preamp,
    flat_equalizer_bands,
    normalize_equalizer_bands,
)

LOG = logging.getLogger(__name__)
_RIP_FORMATS = {"flac", "mp3", "aac", "opus", "ogg", "alac", "wav", "aiff", "wma"}
_YT_AUDIO_FORMATS = {"flac", "mp3"}
_YT_VIDEO_FORMATS = {"mp4", "mkv", "webm"}
_STREAM_URL_SCHEMES = {
    "http",
    "https",
    "rtmp",
    "rtmps",
    "rtsp",
    "mms",
    "mmsh",
    "icy",
}
_MAX_RECENT_STREAM_URLS = 25
_MAX_RADIO_STATIONS = 200


def _default_music_root() -> Path:
    if sys.platform == "win32":
        # Use standard Windows Music folder
        userprofile = os.environ.get("USERPROFILE", os.path.expanduser("~"))
        return Path(userprofile) / "Music" / "Lyon"
    return Path.home() / "Music" / "Lyon"


def app_data_dir() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    p = Path(base) / "LyonMusicManager"
    p.mkdir(parents=True, exist_ok=True)
    return p


def bundled_bin_dir() -> Path:
    """Where ffmpeg.exe / libdiscid live when packaged or in-tree."""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "bin"  # type: ignore[attr-defined]
    return Path(__file__).resolve().parent.parent.parent / "bin"


def _app_version() -> str:
    # Imported lazily to avoid a circular import (lyon.__init__ imports nothing
    # heavy, but settings is imported by lyon.core which __init__ may touch).
    from .. import __version__
    return __version__


def _is_custom_curve_name(name: str) -> bool:
    return bool(name) and name not in RESERVED_EQ_CURVE_NAMES


def _clamp_int(value: object, default: int, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(maximum, number))


def _nonnegative_int(value: object, default: int = 0) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(0, number)


def _bool_value(value: object, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    text = str(value).strip().casefold()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


def normalize_library_paths(paths: object) -> list[str]:
    """Return non-empty library paths without exact duplicates, preserving order."""
    if not isinstance(paths, list | tuple):
        return []

    normalized: list[str] = []
    seen: set[str] = set()
    for value in paths:
        path = str(value).strip()
        if not path or path in seen:
            continue
        normalized.append(path)
        seen.add(path)
    return normalized


def normalize_stream_urls(urls: object, *, limit: int = _MAX_RECENT_STREAM_URLS) -> list[str]:
    """Return valid network stream URLs without duplicates, preserving order."""
    if not isinstance(urls, list | tuple):
        return []

    normalized: list[str] = []
    seen: set[str] = set()
    for value in urls:
        url = str(value).strip()
        if not _is_network_stream_url(url):
            continue
        key = url.casefold()
        if key in seen:
            continue
        normalized.append(url)
        seen.add(key)
        if len(normalized) >= limit:
            break
    return normalized


def _is_network_stream_url(url: str) -> bool:
    if not url:
        return False
    parsed = urlparse(url)
    return parsed.scheme.casefold() in _STREAM_URL_SCHEMES and bool(parsed.netloc)


def normalize_radio_stations(stations: object, *, limit: int = _MAX_RADIO_STATIONS) -> list[dict[str, object]]:
    """Return saved radio stations with valid stream URLs and stable keys."""
    if not isinstance(stations, list | tuple):
        return []

    normalized: list[dict[str, object]] = []
    seen: set[str] = set()
    for value in stations:
        if not isinstance(value, dict):
            continue
        url = str(value.get("url") or "").strip()
        if not _is_network_stream_url(url):
            continue
        key = url.casefold()
        if key in seen:
            continue
        name = str(value.get("name") or "").strip() or url
        genre = str(value.get("genre") or "").strip()
        bitrate = _nonnegative_int(value.get("bitrate"), 0)
        normalized.append({
            "name": name,
            "url": url,
            "genre": genre,
            "bitrate": bitrate,
        })
        seen.add(key)
        if len(normalized) >= limit:
            break
    return normalized


@dataclass
class Settings:
    music_root: str = field(default_factory=lambda: str(_default_music_root()))
    rip_format: str = "flac"           # flac | mp3 | aac | opus | ogg | alac | wav | aiff | wma
    flac_compression: int = 4           # 0-8
    rip_audio_bitrate: int = 320        # kbps, used by lossy formats (mp3, aac, opus, ogg, wma)
    cd_drive: str = ""                 # e.g. "D:" - blank means auto-pick first
    musicbrainz_app: str = "LyonMusicManager"
    musicbrainz_version: str = field(default_factory=_app_version)
    musicbrainz_contact: str = "https://example.invalid/lyon"
    theaudiodb_api_key: str = "123"
    eject_after_rip: bool = True
    auto_lookup_metadata: bool = True
    cuetools_db_metadata_enabled: bool = True
    download_artwork: bool = True
    metadata_diagnostics_enabled: bool = False
    ctdb_verify_rips: bool = True
    last_volume: int = 80
    library_paths: list[str] = field(default_factory=list)
    watch_library_folders: bool = True
    equalizer_enabled: bool = False
    equalizer_preamp: int = DEFAULT_EQ_PREAMP_DB
    equalizer_bands: list[int] = field(default_factory=flat_equalizer_bands)
    equalizer_curve_name: str = DEFAULT_EQ_CURVE_NAME
    equalizer_custom_curves: dict[str, list[int]] = field(default_factory=dict)
    first_run_completed: bool = False
    yt_audio_format: str = "flac"        # flac | mp3
    yt_video_format: str = "mp4"         # mp4 | mkv | webm
    yt_output_dir: str = ""              # defaults to music_root/YouTube at runtime
    yt_auto_add: bool = True             # add downloaded files to library automatically
    queue_track_paths: list[str] = field(default_factory=list)
    queue_current_index: int = 0
    crossfade_seconds: int = 0          # 0 = disabled; >0 = overlap duration on track change
    fetch_lyrics_online: bool = True    # query lrclib.net when no local .lrc / embedded lyrics
    replaygain_mode: str = "off"        # "off" | "track" | "album"
    replaygain_preamp_db: float = 0.0   # additional offset applied after gain, -6.0 to +6.0
    replaygain_prevent_clipping: bool = True
    audio_output: str = ""              # VLC audio output module ID (e.g. "wasapi", "directsound")
    audio_output_device: str = ""       # VLC device ID string; "" = VLC default
    gapless_playback: bool = False      # pre-buffer next track to minimize inter-track gap; no-op when crossfade > 0
    lastfm_session_key: str = ""        # per-user session key obtained via auth.getSession
    lastfm_username: str = ""           # display name for the connected Last.fm account
    lastfm_scrobbling_enabled: bool = False
    listenbrainz_token: str = ""        # per-user token from listenbrainz.org/profile/
    listenbrainz_scrobbling_enabled: bool = False
    recent_stream_urls: list[str] = field(default_factory=list)
    dlna_enabled: bool = False
    dlna_port: int = 8200
    dlna_friendly_name: str = "Sea Lyon Media Manager"
    radio_stations: list[dict[str, object]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.rip_format = str(self.rip_format or "flac").lower()
        if self.rip_format not in _RIP_FORMATS:
            self.rip_format = "flac"
        self.flac_compression = _clamp_int(self.flac_compression, 4, 0, 8)
        self.rip_audio_bitrate = _clamp_int(self.rip_audio_bitrate, 320, 32, 1411)
        self.last_volume = _clamp_int(self.last_volume, 80, 0, 100)
        self.queue_current_index = _nonnegative_int(self.queue_current_index, 0)
        self.crossfade_seconds = _nonnegative_int(self.crossfade_seconds, 0)
        self.replaygain_mode = str(self.replaygain_mode or "off").lower()
        if self.replaygain_mode not in {"off", "track", "album"}:
            self.replaygain_mode = "off"
        try:
            self.replaygain_preamp_db = max(-6.0, min(6.0, float(self.replaygain_preamp_db)))
        except (TypeError, ValueError):
            self.replaygain_preamp_db = 0.0
        self.replaygain_prevent_clipping = _bool_value(self.replaygain_prevent_clipping, True)
        self.audio_output = str(self.audio_output or "").strip()
        self.audio_output_device = str(self.audio_output_device or "").strip()
        self.gapless_playback = _bool_value(self.gapless_playback, False)
        self.lastfm_scrobbling_enabled = _bool_value(self.lastfm_scrobbling_enabled, False)
        self.listenbrainz_scrobbling_enabled = _bool_value(self.listenbrainz_scrobbling_enabled, False)
        self.lastfm_session_key = str(self.lastfm_session_key or "").strip()
        self.lastfm_username = str(self.lastfm_username or "").strip()
        self.listenbrainz_token = str(self.listenbrainz_token or "").strip()
        self.recent_stream_urls = normalize_stream_urls(self.recent_stream_urls)
        self.dlna_enabled = _bool_value(self.dlna_enabled, False)
        self.dlna_port = _clamp_int(self.dlna_port, 8200, 0, 65535)
        self.dlna_friendly_name = str(self.dlna_friendly_name or "").strip() or "Sea Lyon Media Manager"
        self.radio_stations = normalize_radio_stations(self.radio_stations)
        self.yt_audio_format = str(self.yt_audio_format or "flac").lower()
        if self.yt_audio_format not in _YT_AUDIO_FORMATS:
            self.yt_audio_format = "flac"
        self.yt_video_format = str(self.yt_video_format or "mp4").lower()
        if self.yt_video_format not in _YT_VIDEO_FORMATS:
            self.yt_video_format = "mp4"
        self.library_paths = normalize_library_paths(self.library_paths)
        self.watch_library_folders = _bool_value(self.watch_library_folders, True)
        self.equalizer_preamp = clamp_preamp(self.equalizer_preamp)
        self.equalizer_bands = normalize_equalizer_bands(self.equalizer_bands)
        custom_curves = self.equalizer_custom_curves if isinstance(self.equalizer_custom_curves, dict) else {}
        self.equalizer_custom_curves = {
            str(name).strip(): normalize_equalizer_bands(curve)
            for name, curve in custom_curves.items()
            if _is_custom_curve_name(str(name).strip())
        }
        self.equalizer_curve_name = str(self.equalizer_curve_name or DEFAULT_EQ_CURVE_NAME).strip()
        custom_curve_selected = self.equalizer_curve_name in self.equalizer_custom_curves
        built_in_curve_selected = self.equalizer_curve_name in RESERVED_EQ_CURVE_NAMES
        if self.equalizer_curve_name == UNSAVED_EQ_CURVE_NAME or not (
            custom_curve_selected or built_in_curve_selected
        ):
            self.equalizer_curve_name = DEFAULT_EQ_CURVE_NAME

    def remember_stream_url(self, url: str) -> None:
        """Move a valid stream URL to the front of the recents list."""
        self.recent_stream_urls = normalize_stream_urls([url, *self.recent_stream_urls])

    def add_radio_stations(self, stations: list[dict[str, object]]) -> None:
        """Append or update saved radio stations by URL."""
        merged: dict[str, dict[str, object]] = {
            str(station["url"]).casefold(): dict(station)
            for station in normalize_radio_stations(self.radio_stations)
        }
        for station in normalize_radio_stations(stations):
            merged[str(station["url"]).casefold()] = station
        self.radio_stations = normalize_radio_stations(list(merged.values()))

    @classmethod
    def load(cls) -> "Settings":
        path = app_data_dir() / "settings.json"
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                # Drop unknown keys so older configs don't crash on upgrade
                known = {f for f in cls.__dataclass_fields__}
                data = {k: v for k, v in data.items() if k in known}
                return cls(**data)
            except OSError as exc:
                LOG.warning("Could not read settings.json; using defaults: %s", exc)
                return cls()
            except (json.JSONDecodeError, TypeError, ValueError):
                backup = path.with_suffix(".json.bad")
                try:
                    path.replace(backup)
                except OSError as exc:
                    LOG.debug("Could not back up corrupt settings file %s: %s", path, exc)
                LOG.warning(
                    "settings.json was corrupt; reset to defaults. Bad file saved to %s",
                    backup,
                )
                instance = cls()
                instance._corrupt_backup_path = str(backup)
                return instance
        return cls()

    def save(self) -> None:
        path = app_data_dir() / "settings.json"
        data = json.dumps(asdict(self), indent=2)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(data, encoding="utf-8")
        os.replace(tmp, path)
        invalidate_settings_cache()


# ---------------------------------------------------------------------------
# Module-level settings cache so repeated hot-path calls (metadata lookups,
# diagnostics checks) avoid redundant file I/O on every invocation.
# ---------------------------------------------------------------------------
_settings_cache: "Settings | None" = None


def get_cached_settings() -> "Settings":
    """Return cached Settings, loading from disk on first call."""
    global _settings_cache
    if _settings_cache is None:
        _settings_cache = Settings.load()
    return _settings_cache


def invalidate_settings_cache() -> None:
    """Discard the cached Settings so the next call re-reads from disk."""
    global _settings_cache
    _settings_cache = None

"""Album metadata and artwork lookups from the supported provider fallbacks."""
from __future__ import annotations

import logging
import re
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Optional
from urllib.parse import urljoin, urlparse

try:
    import defusedxml.ElementTree as ET
except ImportError:  # defusedxml is an optional hardening layer
    import xml.etree.ElementTree as ET  # type: ignore[no-redef]

from . import settings as _settings


CTDB_LOOKUP_URL = "http://db.cuetools.net/lookup2.php"
CTDB_BASE_URL = "http://db.cuetools.net/"
CTDB_TIMEOUT_SECONDS = 20
THEAUDIODB_API_BASE = "https://www.theaudiodb.com/api/v1/json"
THEAUDIODB_DEFAULT_API_KEY = ""   # empty → TheAudioDB lookups are skipped
HTTP_TIMEOUT_SECONDS = 15
MAX_ARTWORK_BYTES = 5 * 1024 * 1024
DISC_METADATA_PROVIDER_ORDER = ("cuetools_db", "musicbrainz")
ALBUM_METADATA_PROVIDER_ORDER = ("musicbrainz", "theaudiodb")
ARTWORK_PROVIDER_ORDER = ("cover_art_archive", "album_artwork_url", "theaudiodb")
METADATA_PROVIDER_ORDER = ALBUM_METADATA_PROVIDER_ORDER
METADATA_DIAGNOSTICS_LOG_NAME = "metadata-diagnostics.log"

LOG = logging.getLogger(__name__)
_metadata_file_handler: logging.Handler | None = None
_DEFAULT_REQUESTS_GET: Any = None
_DEFAULT_SETTINGS_LOAD = getattr(_settings.Settings.load, "__func__", _settings.Settings.load)

# Shared HTTP session — reuses TCP connections and avoids repeated TLS handshakes.
_http_session: "requests.Session | None" = None
_http_session_lock = threading.Lock()

# Guards the one-time musicbrainzngs useragent initialisation.
_init_lock = threading.Lock()
_initialised = False
_last_musicbrainz_useragent: tuple[str, str, str] | None = None

# MusicBrainz API ToS requires ≤1 request per second.
_mb_rate_limit_lock = threading.Lock()
_mb_last_request_time: float = 0.0

_METADATA_CACHE_TTL_SECONDS = 15 * 60
_DISC_LOOKUP_CACHE_MAX = 128
_ALBUM_SEARCH_CACHE_MAX = 128
_ARTIST_LOOKUP_CACHE_MAX = 128


def __getattr__(name: str) -> Any:
    """Lazily expose optional provider modules for tests and legacy callers."""
    if name == "musicbrainzngs":
        import musicbrainzngs

        return musicbrainzngs
    if name == "requests":
        global _DEFAULT_REQUESTS_GET
        import requests

        if _DEFAULT_REQUESTS_GET is None:
            _DEFAULT_REQUESTS_GET = requests.get
        return requests
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


@dataclass
class TrackInfo:
    number: int
    title: str
    length_ms: int = 0
    artist: str = ""
    disc_number: int = 1


@dataclass
class AlbumInfo:
    artist: str
    album: str
    date: str = ""
    musicbrainz_albumid: str = ""
    tracks: list[TrackInfo] = field(default_factory=list)
    artwork: bytes | None = None
    genre: str = ""
    artwork_url: str = ""
    metadata_source: str = "musicbrainz"
    grouping: str = ""

    @property
    def year(self) -> int:
        if self.date and self.date[:4].isdigit():
            return int(self.date[:4])
        return 0


@dataclass
class ArtistInfo:
    name: str
    biography: str = ""
    image_url: str = ""
    genre: str = ""
    country: str = ""
    formed_year: int = 0
    website: str = ""
    similar_artists: list[str] = field(default_factory=list)
    metadata_source: str = "theaudiodb"


_CacheValue = AlbumInfo | ArtistInfo | None
_metadata_cache_lock = threading.RLock()
_disc_lookup_cache: "OrderedDict[tuple[Any, ...], tuple[float, _CacheValue]]" = OrderedDict()
_album_search_cache: "OrderedDict[tuple[Any, ...], tuple[float, _CacheValue]]" = OrderedDict()
_artist_lookup_cache: "OrderedDict[tuple[Any, ...], tuple[float, _CacheValue]]" = OrderedDict()


def clear_metadata_cache() -> None:
    """Clear bounded metadata lookup caches used by network provider fallbacks."""
    with _metadata_cache_lock:
        _disc_lookup_cache.clear()
        _album_search_cache.clear()
        _artist_lookup_cache.clear()


def _get_http_session() -> "requests.Session":
    global _http_session
    if _http_session is None:
        import requests

        with _http_session_lock:
            if _http_session is None:
                _http_session = requests.Session()
    return _http_session


def _http_get(url: str, **kwargs: Any) -> "requests.Response":
    """Use the shared session unless tests replace the module-level requests hook."""
    global _DEFAULT_REQUESTS_GET
    import requests

    if _DEFAULT_REQUESTS_GET is None:
        _DEFAULT_REQUESTS_GET = requests.get
    if requests.get is not _DEFAULT_REQUESTS_GET:
        return requests.get(url, **kwargs)
    return _get_http_session().get(url, **kwargs)


def _cache_get(
    cache: "OrderedDict[tuple[Any, ...], tuple[float, _CacheValue]]",
    key: tuple[Any, ...],
) -> _CacheValue | object:
    now = time.monotonic()
    with _metadata_cache_lock:
        entry = cache.get(key)
        if entry is None:
            return _CACHE_MISS
        created_at, value = entry
        if now - created_at > _METADATA_CACHE_TTL_SECONDS:
            cache.pop(key, None)
            return _CACHE_MISS
        cache.move_to_end(key)
        return deepcopy(value)


def _cache_put(
    cache: "OrderedDict[tuple[Any, ...], tuple[float, _CacheValue]]",
    key: tuple[Any, ...],
    value: _CacheValue,
    max_size: int,
) -> None:
    with _metadata_cache_lock:
        cache[key] = (time.monotonic(), deepcopy(value))
        cache.move_to_end(key)
        while len(cache) > max_size:
            cache.popitem(last=False)


_CACHE_MISS = object()


def _function_cache_token(fn: Any) -> tuple[str, int]:
    return (getattr(fn, "__name__", type(fn).__name__), id(fn))


def _metadata_cache_text(value: Any) -> str:
    return _text(value).strip()


def _current_settings() -> Any:
    loader = _settings.Settings.load
    loader_func = getattr(loader, "__func__", loader)
    if loader_func is not _DEFAULT_SETTINGS_LOAD:
        return _settings.Settings.load()
    return _settings.get_cached_settings()


def _init() -> None:
    global _initialised, _last_musicbrainz_useragent
    s = _settings.get_cached_settings()
    useragent = (s.musicbrainz_app, s.musicbrainz_version, s.musicbrainz_contact)
    if _initialised and _last_musicbrainz_useragent == useragent:
        return
    with _init_lock:
        import musicbrainzngs

        s = _settings.get_cached_settings()
        useragent = (s.musicbrainz_app, s.musicbrainz_version, s.musicbrainz_contact)
        if _initialised and _last_musicbrainz_useragent == useragent:
            return
        musicbrainzngs.set_useragent(s.musicbrainz_app, s.musicbrainz_version, s.musicbrainz_contact)
        _last_musicbrainz_useragent = useragent
        _initialised = True


def reset_musicbrainz_useragent() -> None:
    """Force the next MusicBrainz lookup to apply the latest saved settings."""
    global _initialised, _last_musicbrainz_useragent
    with _init_lock:
        _initialised = False
        _last_musicbrainz_useragent = None


def _mb_rate_limit() -> None:
    """Throttle to ≤1 MusicBrainz request per second as required by their ToS."""
    global _mb_last_request_time
    with _mb_rate_limit_lock:
        now = time.monotonic()
        wait = 1.0 - (now - _mb_last_request_time)
        if wait > 0:
            time.sleep(wait)
        _mb_last_request_time = time.monotonic()


def shutdown() -> None:
    """Close the shared HTTP session and diagnostics log handler."""
    global _http_session, _metadata_file_handler
    if _http_session is not None:
        try:
            _http_session.close()
        except Exception as exc:
            LOG.debug("Could not close metadata HTTP session: %s", exc)
        _http_session = None
    if _metadata_file_handler is not None:
        try:
            LOG.removeHandler(_metadata_file_handler)
            _metadata_file_handler.close()
        except Exception as exc:
            LOG.debug("Could not close metadata diagnostics handler: %s", exc)
        _metadata_file_handler = None


def lookup_disc(
    discid_str: str,
    toc: str | None = None,
    *,
    ctdb_toc: str | None = None,
    use_cuetools_db: bool | None = None,
) -> Optional[AlbumInfo]:
    """Look up an album by disc identity using the supported provider order."""
    diagnostics_enabled = bool(getattr(_current_settings(), "metadata_diagnostics_enabled", False))
    cache_key = (
        "lookup_disc",
        _metadata_cache_text(discid_str),
        _metadata_cache_text(toc),
        _metadata_cache_text(ctdb_toc),
        _use_cuetools_db(use_cuetools_db),
        diagnostics_enabled,
        _theaudiodb_api_key(),
        _function_cache_token(lookup_cuetools_db_disc),
        _function_cache_token(lookup_musicbrainz_disc),
        _function_cache_token(search_theaudiodb_album),
    )
    cached = _cache_get(_disc_lookup_cache, cache_key)
    if cached is not _CACHE_MISS:
        return cached  # type: ignore[return-value]

    provider_attempts: list[tuple[str, AlbumInfo | None]] = []
    providers: list[tuple[str, Callable[[], Optional[AlbumInfo]]]] = []
    if _use_cuetools_db(use_cuetools_db):
        providers.append((
            "cuetools_db",
            lambda: lookup_cuetools_db_disc(toc, ctdb_toc=ctdb_toc),
        ))
    if discid_str:
        providers.append(("musicbrainz", lambda: lookup_musicbrainz_disc(discid_str, toc)))

    for provider_name, provider in providers:
        info = provider()
        provider_attempts.append((provider_name, info))
        if _has_usable_metadata(info):
            result = _with_theaudiodb_enrichment(info)
            _cache_put(_disc_lookup_cache, cache_key, result, _DISC_LOOKUP_CACHE_MAX)
            return result

    if diagnostics_enabled and _metadata_diagnostics_enabled():
        _log_empty_disc_lookup(discid_str, toc, ctdb_toc, use_cuetools_db, provider_attempts)
    if not diagnostics_enabled:
        _cache_put(_disc_lookup_cache, cache_key, None, _DISC_LOOKUP_CACHE_MAX)
    return None


def lookup_disc_with_fallback(
    discid_str: str,
    toc: str | None = None,
    *,
    ctdb_toc: str | None = None,
    use_cuetools_db: bool | None = None,
) -> Optional[AlbumInfo]:
    """Compatibility wrapper for disc lookup with provider fallbacks."""
    return lookup_disc(
        discid_str,
        toc,
        ctdb_toc=ctdb_toc,
        use_cuetools_db=use_cuetools_db,
    )


def lookup_musicbrainz_disc(discid_str: str, toc: str | None = None) -> Optional[AlbumInfo]:
    """Look up an album by MusicBrainz disc ID."""
    import musicbrainzngs

    if not discid_str:
        return None
    _init()
    _mb_rate_limit()
    try:
        result = musicbrainzngs.get_releases_by_discid(
            discid_str, includes=["recordings", "artists"], toc=toc, cdstubs=True
        )
    except (musicbrainzngs.ResponseError, musicbrainzngs.NetworkError) as exc:
        _log_metadata_diagnostic(
            "MusicBrainz disc lookup failed for discid=%s toc=%s: %s",
            _diagnostic_value(discid_str),
            _diagnostic_value(toc),
            exc,
        )
        return None

    release = None
    if "disc" in result and result["disc"].get("release-list"):
        release = result["disc"]["release-list"][0]
    elif "cdstub" in result:
        return _musicbrainz_cdstub_to_album(result["cdstub"])

    if not release:
        _log_metadata_diagnostic(
            "MusicBrainz disc lookup returned no release for discid=%s toc=%s",
            _diagnostic_value(discid_str),
            _diagnostic_value(toc),
        )
        return None
    return _release_to_album(release, discid_str)


def lookup_cuetools_db_disc(
    toc: str | None,
    *,
    ctdb_toc: str | None = None,
) -> Optional[AlbumInfo]:
    """Look up album metadata through the CUETools Database metadata endpoint."""
    layouts = _unique_non_empty(
        [sanitize_ctdb_layout(ctdb_toc), _musicbrainz_toc_to_ctdb_toc(toc)]
    )
    if not layouts:
        _log_metadata_diagnostic(
            "CUETools DB lookup skipped because no CTDB-compatible TOC layout was available "
            "(musicbrainz_toc=%s, ctdb_toc=%s)",
            _diagnostic_value(toc),
            _diagnostic_value(ctdb_toc),
        )
        return None

    for fuzzy in (False, True):
        for layout in layouts:
            info = lookup_cuetools_db_layout(layout, fuzzy=fuzzy)
            if _has_usable_metadata(info):
                return info
    _log_metadata_diagnostic(
        "CUETools DB lookup returned no usable metadata for layouts=%s",
        ", ".join(layouts),
    )
    return None


def lookup_ctdb_disc(toc: str | None, *, fuzzy: bool = False) -> Optional[AlbumInfo]:
    """Compatibility wrapper for older CTDB lookup call sites."""
    layout = _musicbrainz_toc_to_ctdb_toc(toc)
    return lookup_cuetools_db_layout(layout, fuzzy=fuzzy)


def lookup_cuetools_db_layout(ctdb_toc: str | None, *, fuzzy: bool = False) -> Optional[AlbumInfo]:
    """Look up album metadata from a CUETools-style CTDB TOC layout."""
    import requests

    layout = sanitize_ctdb_layout(ctdb_toc)
    if not layout:
        _log_metadata_diagnostic(
            "CUETools DB %s lookup skipped because CTDB TOC layout was empty or invalid: %s",
            "fuzzy" if fuzzy else "exact",
            _diagnostic_value(ctdb_toc),
        )
        return None

    try:
        response = _http_get(
            CTDB_LOOKUP_URL,
            params={
                "version": "3",
                "ctdb": "0",
                "metadata": "extensive",
                "fuzzy": "1" if fuzzy else "0",
                "toc": layout,
            },
            headers={"User-Agent": _user_agent()},
            timeout=CTDB_TIMEOUT_SECONDS,
        )
        if response.status_code != 200:
            _log_metadata_diagnostic(
                "CUETools DB %s lookup failed for layout=%s: HTTP %s %s",
                "fuzzy" if fuzzy else "exact",
                layout,
                response.status_code,
                _text(getattr(response, "reason", "")),
            )
            return None
        if not response.content:
            _log_metadata_diagnostic(
                "CUETools DB %s lookup failed for layout=%s: empty HTTP response body",
                "fuzzy" if fuzzy else "exact",
                layout,
            )
            return None
    except requests.RequestException as exc:
        _log_metadata_diagnostic(
            "CUETools DB %s lookup failed for layout=%s: %s",
            "fuzzy" if fuzzy else "exact",
            layout,
            exc,
        )
        return None

    try:
        root = ET.fromstring(response.content)
    except ET.ParseError as exc:
        _log_metadata_diagnostic(
            "CUETools DB %s lookup returned invalid XML for layout=%s: %s",
            "fuzzy" if fuzzy else "exact",
            layout,
            exc,
        )
        return None

    candidates = [_ctdb_meta_to_album(meta) for meta in _xml_descendants(root, "metadata")]
    candidates = [info for info in candidates if info is not None]
    if not candidates:
        _log_metadata_diagnostic(
            "CUETools DB %s lookup returned XML with no usable <metadata> entries for layout=%s",
            "fuzzy" if fuzzy else "exact",
            layout,
        )
        return None

    candidates.sort(key=_ctdb_album_score, reverse=True)
    return candidates[0]


def search_album(artist: str, album: str) -> Optional[AlbumInfo]:
    """Search album metadata providers, preferring results with track data."""
    providers = _album_search_providers()
    diagnostics_enabled = bool(getattr(_current_settings(), "metadata_diagnostics_enabled", False))
    cache_key = (
        "search_album",
        _metadata_cache_text(artist),
        _metadata_cache_text(album),
        diagnostics_enabled,
        _theaudiodb_api_key(),
        tuple(_function_cache_token(provider) for provider in providers),
    )
    cached = _cache_get(_album_search_cache, cache_key)
    if cached is not _CACHE_MISS:
        return cached  # type: ignore[return-value]

    fallback_info = None
    provider_attempts: list[tuple[str, AlbumInfo | None]] = []
    for provider in providers:
        provider_name = _provider_log_name(provider)
        info = provider(artist, album)
        provider_attempts.append((provider_name, info))
        if _has_track_metadata(info):
            _cache_put(_album_search_cache, cache_key, info, _ALBUM_SEARCH_CACHE_MAX)
            return info
        if fallback_info is None and _has_basic_metadata(info):
            fallback_info = info
    if fallback_info is None and diagnostics_enabled and _metadata_diagnostics_enabled():
        _log_empty_album_search(artist, album, provider_attempts)
    if fallback_info is not None or not diagnostics_enabled:
        _cache_put(_album_search_cache, cache_key, fallback_info, _ALBUM_SEARCH_CACHE_MAX)
    return fallback_info


def fetch_artwork(album: AlbumInfo) -> bytes | None:
    """Fetch artwork lazily from primary URLs before TheAudioDB fallback lookup."""
    for url in _primary_artwork_urls(album):
        artwork = _fetch_artwork_url(url)
        if artwork:
            return artwork

    if not (album.artist and album.album):
        return None

    info = search_theaudiodb_album(album.artist, album.album)
    if info and info.artwork_url:
        return _fetch_artwork_url(info.artwork_url)
    return None


def search_musicbrainz_album(artist: str, album: str) -> Optional[AlbumInfo]:
    """Search MusicBrainz release metadata by artist and album title."""
    import musicbrainzngs

    _init()
    _mb_rate_limit()
    try:
        result = musicbrainzngs.search_releases(artist=artist, release=album, limit=1)
    except (musicbrainzngs.ResponseError, musicbrainzngs.NetworkError) as exc:
        _log_metadata_diagnostic(
            "MusicBrainz album search failed for artist=%s album=%s: %s",
            _diagnostic_value(artist),
            _diagnostic_value(album),
            exc,
        )
        return None
    rels = result.get("release-list") or []
    if not rels:
        _log_metadata_diagnostic(
            "MusicBrainz album search returned no releases for artist=%s album=%s",
            _diagnostic_value(artist),
            _diagnostic_value(album),
        )
        return None
    rid = rels[0]["id"]
    _mb_rate_limit()
    try:
        full = musicbrainzngs.get_release_by_id(
            rid, includes=["recordings", "artists"]
        )["release"]
    except (musicbrainzngs.ResponseError, musicbrainzngs.NetworkError) as exc:
        _log_metadata_diagnostic(
            "MusicBrainz album detail lookup failed for release=%s artist=%s album=%s: %s",
            _diagnostic_value(rid),
            _diagnostic_value(artist),
            _diagnostic_value(album),
            exc,
        )
        return None
    return _release_to_album(full)


def search_musicbrainz_releases(artist: str, album: str, limit: int = 5) -> list[AlbumInfo]:
    """Search MusicBrainz and return up to *limit* release candidates (basic info only)."""
    import musicbrainzngs

    _init()
    _mb_rate_limit()
    try:
        result = musicbrainzngs.search_releases(artist=artist, release=album, limit=limit)
    except (musicbrainzngs.ResponseError, musicbrainzngs.NetworkError) as exc:
        _log_metadata_diagnostic(
            "MusicBrainz release search failed for artist=%s album=%s: %s",
            _diagnostic_value(artist),
            _diagnostic_value(album),
            exc,
        )
        return []
    rels = result.get("release-list") or []
    infos: list[AlbumInfo] = []
    for rel in rels[:limit]:
        infos.append(AlbumInfo(
            artist=_musicbrainz_artist(rel),
            album=rel.get("title", ""),
            date=rel.get("date", ""),
            musicbrainz_albumid=rel.get("id", ""),
            metadata_source="musicbrainz",
        ))
    return infos


def fetch_musicbrainz_release(mbid: str) -> Optional[AlbumInfo]:
    """Fetch a full MusicBrainz release (with track listing) by release ID."""
    import musicbrainzngs

    if not mbid:
        return None
    _init()
    _mb_rate_limit()
    try:
        full = musicbrainzngs.get_release_by_id(
            mbid, includes=["recordings", "artists"]
        )["release"]
    except (musicbrainzngs.ResponseError, musicbrainzngs.NetworkError) as exc:
        _log_metadata_diagnostic(
            "MusicBrainz release detail fetch failed for mbid=%s: %s",
            _diagnostic_value(mbid),
            exc,
        )
        return None
    return _release_to_album(full)


def download_cover_art(mbid: str) -> bytes | None:
    """Fetch front cover art from the Cover Art Archive for the given release MBID."""
    if not mbid:
        return None
    url = f"https://coverartarchive.org/release/{mbid}/front-500"
    return _fetch_artwork_url(url)


def search_theaudiodb_album(artist: str, album: str) -> Optional[AlbumInfo]:
    """Search TheAudioDB by album and optional artist name.

    Returns ``None`` immediately when no API key is configured so that the
    caller's provider-fallback chain simply moves on to the next source.
    """
    if not _theaudiodb_api_key():
        return None
    artist = artist.strip()
    album = album.strip()
    if not album:
        return None

    params = {"a": album}
    if artist:
        params["s"] = artist
    payload = _get_json(_theaudiodb_url("searchalbum.php"), params=params)
    albums = _ensure_list(payload.get("album") or payload.get("albums"))
    if not albums:
        _log_metadata_diagnostic(
            "TheAudioDB album search returned no albums for artist=%s album=%s",
            _diagnostic_value(artist),
            _diagnostic_value(album),
        )
        return None

    match = next(
        (candidate for candidate in albums if _is_theaudiodb_album_match(candidate, artist, album)),
        None,
    ) or albums[0]
    info = _theaudiodb_album_to_info(match, artist, album)

    album_id = _text(match.get("idAlbum"))
    if album_id:
        info.tracks = _theaudiodb_tracks(album_id, info.artist)
    return info


def lookup_artist_info(artist: str) -> Optional[ArtistInfo]:
    """Look up artist biography and image data from TheAudioDB.

    Returns ``None`` immediately when no API key is configured.
    """
    if not _theaudiodb_api_key():
        return None
    artist = artist.strip()
    if not artist or artist.casefold() == "unknown artist":
        return None
    cache_key = (
        "lookup_artist_info",
        artist,
        _theaudiodb_api_key(),
        _function_cache_token(_get_json),
    )
    cached = _cache_get(_artist_lookup_cache, cache_key)
    if cached is not _CACHE_MISS:
        return cached  # type: ignore[return-value]

    payload = _get_json(_theaudiodb_url("search.php"), params={"s": artist})
    artists = _ensure_list(payload.get("artists") or payload.get("artist"))
    match = next(
        (
            item for item in artists
            if isinstance(item, dict) and _is_theaudiodb_artist_match(item, artist)
        ),
        None,
    )
    if not isinstance(match, dict):
        _cache_put(_artist_lookup_cache, cache_key, None, _ARTIST_LOOKUP_CACHE_MAX)
        return None
    info = _theaudiodb_artist_to_info(match, artist)
    _cache_put(_artist_lookup_cache, cache_key, info, _ARTIST_LOOKUP_CACHE_MAX)
    return info


def fetch_artist_image(artist: ArtistInfo) -> bytes | None:
    """Fetch the preferred artist image bytes, bounded by artwork size limits."""
    if not artist.image_url:
        return None
    return _fetch_artwork_url(artist.image_url)


def _album_search_providers() -> tuple[Callable[[str, str], Optional[AlbumInfo]], ...]:
    return (search_musicbrainz_album, search_theaudiodb_album)


def metadata_diagnostics_log_path() -> str:
    """Return the file used for detailed metadata lookup diagnostics."""
    return str(_settings.app_data_dir() / METADATA_DIAGNOSTICS_LOG_NAME)


def _metadata_diagnostics_enabled() -> bool:
    settings = _current_settings()
    enabled = bool(getattr(settings, "metadata_diagnostics_enabled", False))
    if enabled:
        _ensure_metadata_diagnostics_logging()
    return enabled


def _ensure_metadata_diagnostics_logging() -> None:
    global _metadata_file_handler
    if _metadata_file_handler is not None:
        return

    path = _settings.app_data_dir() / METADATA_DIAGNOSTICS_LOG_NAME
    try:
        handler = logging.FileHandler(path, encoding="utf-8")
    except OSError:
        LOG.setLevel(logging.INFO)
        return
    handler.setLevel(logging.INFO)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    LOG.addHandler(handler)
    LOG.setLevel(logging.INFO)
    _metadata_file_handler = handler


def _log_metadata_diagnostic(message: str, *args: Any) -> None:
    if _metadata_diagnostics_enabled():
        LOG.warning(message, *args)


def _log_empty_disc_lookup(
    discid_str: str,
    toc: str | None,
    ctdb_toc: str | None,
    use_cuetools_db: bool | None,
    provider_attempts: list[tuple[str, AlbumInfo | None]],
) -> None:
    """Emit detailed diagnostics for a disc lookup that found no metadata."""
    diagnostics = [
        "Album metadata lookup returned no usable metadata.",
        "Lookup context:",
        f"  discid: {_diagnostic_value(discid_str)}",
        f"  musicbrainz_toc: {_diagnostic_value(toc)}",
        f"  ctdb_toc: {_diagnostic_value(ctdb_toc)}",
        f"  cuetools_db_enabled: {_use_cuetools_db(use_cuetools_db)}",
        "Provider attempts:",
    ]

    if provider_attempts:
        diagnostics.extend(
            f"  {_provider_attempt_summary(provider_name, info)}"
            for provider_name, info in provider_attempts
        )
    else:
        diagnostics.append("  none (no enabled provider had enough lookup input)")

    if not any(_has_basic_metadata(info) for _provider_name, info in provider_attempts):
        diagnostics.append(
            "  theaudiodb: not attempted; disc providers did not return artist/album "
            "identifiers for enrichment"
        )
    _log_metadata_diagnostic("%s", "\n".join(diagnostics))


def _log_empty_album_search(
    artist: str,
    album: str,
    provider_attempts: list[tuple[str, AlbumInfo | None]],
) -> None:
    """Emit detailed diagnostics for a manual album search with no metadata."""
    diagnostics = [
        "Manual album metadata search returned no metadata.",
        "Search context:",
        f"  artist: {_diagnostic_value(artist)}",
        f"  album: {_diagnostic_value(album)}",
        "Provider attempts:",
    ]
    diagnostics.extend(
        f"  {_provider_attempt_summary(provider_name, info)}"
        for provider_name, info in provider_attempts
    )
    _log_metadata_diagnostic("%s", "\n".join(diagnostics))


def _provider_attempt_summary(provider_name: str, info: AlbumInfo | None) -> str:
    if info is None:
        return f"{provider_name}: returned no result"
    if not _has_basic_metadata(info):
        return f"{provider_name}: returned an empty metadata object"
    return (
        f"{provider_name}: returned partial metadata "
        f"(source={_diagnostic_value(info.metadata_source)}, "
        f"artist={_diagnostic_value(info.artist)}, "
        f"album={_diagnostic_value(info.album)}, "
        f"date={_diagnostic_value(info.date)}, "
        f"tracks={len(info.tracks)}, "
        f"musicbrainz_albumid={_diagnostic_value(info.musicbrainz_albumid)}, "
        f"artwork_url={_diagnostic_value(info.artwork_url)})"
    )


def _provider_log_name(provider: Callable[[str, str], Optional[AlbumInfo]]) -> str:
    name = getattr(provider, "__name__", "metadata_provider")
    return name.removeprefix("search_").removesuffix("_album")


def _diagnostic_value(value: Any) -> str:
    text = _text(value)
    return text if text else "<empty>"


def _primary_artwork_urls(album: AlbumInfo) -> list[str]:
    urls = []
    if album.musicbrainz_albumid:
        urls.append(f"https://coverartarchive.org/release/{album.musicbrainz_albumid}/front-500")
    if album.artwork_url:
        urls.append(album.artwork_url)
    return _unique_non_empty(urls)


def _musicbrainz_cdstub_to_album(stub: dict) -> AlbumInfo:
    info = AlbumInfo(
        artist=stub.get("artist", ""),
        album=stub.get("title", ""),
        metadata_source="musicbrainz-cdstub",
    )
    for i, tr in enumerate(stub.get("track-list", []), start=1):
        info.tracks.append(TrackInfo(number=i, title=tr.get("title", f"Track {i}")))
    return info


def _release_to_album(release: dict, discid: str | None = None) -> AlbumInfo:
    info = AlbumInfo(
        artist=_musicbrainz_artist(release),
        album=release.get("title", ""),
        date=release.get("date", ""),
        musicbrainz_albumid=release.get("id", ""),
        metadata_source="musicbrainz",
    )
    n = 1
    for medium in _matching_media(release.get("medium-list") or [], discid):
        disc_number = _safe_int(medium.get("position"), 1)
        for tr in medium.get("track-list", []) or []:
            rec = tr.get("recording", {}) or {}
            length_ms = _safe_int(tr.get("length") or rec.get("length"), 0)
            track_number = _safe_int(tr.get("position"), n)
            info.tracks.append(
                TrackInfo(
                    number=track_number,
                    title=rec.get("title") or tr.get("title") or f"Track {n}",
                    length_ms=length_ms,
                    artist=_musicbrainz_artist(rec) or info.artist,
                    disc_number=disc_number,
                )
            )
            n += 1
    return info


def _ctdb_meta_to_album(meta: ET.Element) -> Optional[AlbumInfo]:
    artist = (meta.get("artist") or "").strip()
    album = (meta.get("album") or "").strip()
    if not (artist or album):
        return None

    source = (meta.get("source") or "unknown").strip()
    info = AlbumInfo(
        artist=artist,
        album=album,
        date=_ctdb_date(meta),
        musicbrainz_albumid=_ctdb_musicbrainz_album_id(meta),
        genre=(meta.get("genre") or "").strip(),
        metadata_source=f"cuetools_db:{source}",
    )

    disc_number = _safe_int(meta.get("discnumber"), 1)
    for number, track in enumerate(_xml_children(meta, "track"), start=1):
        title = (track.get("name") or "").strip() or f"Track {number:02d}"
        info.tracks.append(
            TrackInfo(
                number=number,
                title=title,
                artist=(track.get("artist") or "").strip() or artist,
                disc_number=disc_number,
            )
        )

    info.artwork_url = _select_ctdb_cover(_xml_children(meta, "coverart"))
    return info


def _ctdb_date(meta: ET.Element) -> str:
    date = (meta.get("year") or "").strip()
    for release in _xml_children(meta, "release"):
        release_date = (release.get("date") or "").strip()
        if release_date:
            return release_date
    return date


def _ctdb_musicbrainz_album_id(meta: ET.Element) -> str:
    source = (meta.get("source") or "").strip().casefold()
    release_id = (meta.get("id") or "").strip()
    return release_id if source == "musicbrainz" else ""


def _select_ctdb_cover(covers: list[ET.Element]) -> str:
    if not covers:
        return ""
    ordered = sorted(
        covers, key=lambda c: _is_truthy_xml_value(c.get("primary", "")), reverse=True
    )
    for cover in ordered:
        uri = (cover.get("uri") or cover.get("uri150") or "").strip()
        if uri:
            return urljoin(CTDB_BASE_URL, uri)
    return ""


def _xml_descendants(element: ET.Element, local_name: str) -> list[ET.Element]:
    return [item for item in element.iter() if _xml_local_name(item.tag) == local_name]


def _xml_children(element: ET.Element, local_name: str) -> list[ET.Element]:
    return [item for item in element if _xml_local_name(item.tag) == local_name]


def _xml_local_name(tag: Any) -> str:
    text = str(tag)
    return text.rsplit("}", 1)[-1] if "}" in text else text


def _is_truthy_xml_value(value: Any) -> bool:
    return _text(value).casefold() in {"1", "true", "yes"}


def _theaudiodb_album_to_info(data: dict[str, Any], artist: str, album: str) -> AlbumInfo:
    musicbrainz_id = _text(
        data.get("strMusicBrainzID") or data.get("strMusicBrainzAlbumID")
    )
    release_date = _text(data.get("strReleaseDate"))
    year = _text(data.get("intYearReleased"))
    return AlbumInfo(
        artist=_text(data.get("strArtist")) or artist,
        album=_text(data.get("strAlbum")) or album,
        date=release_date or year,
        musicbrainz_albumid=musicbrainz_id,
        genre=_text(data.get("strGenre") or data.get("strStyle")),
        artwork_url=_theaudiodb_artwork_url(data),
        metadata_source="theaudiodb",
    )


def _theaudiodb_tracks(album_id: str, album_artist: str) -> list[TrackInfo]:
    payload = _get_json(_theaudiodb_url("track.php"), params={"m": album_id})
    tracks = _ensure_list(payload.get("track") or payload.get("tracks"))
    mapped = []
    for index, track in enumerate(tracks, start=1):
        if not isinstance(track, dict):
            continue
        number = _safe_int(track.get("intTrackNumber"), index)
        mapped.append(
            TrackInfo(
                number=number,
                title=_text(track.get("strTrack")) or f"Track {number:02d}",
                length_ms=_theaudiodb_duration_ms(track.get("intDuration")),
                artist=_text(track.get("strArtist")) or album_artist,
            )
        )
    return sorted(mapped, key=lambda item: item.number)


def _theaudiodb_artwork_url(data: dict[str, Any]) -> str:
    for key in ("strAlbumThumb", "strAlbumCDart", "strAlbum3DCase", "strAlbumSpine"):
        url = _text(data.get(key))
        if url:
            return url
    return ""


def _theaudiodb_artist_to_info(data: dict[str, Any], artist: str) -> ArtistInfo:
    return ArtistInfo(
        name=_text(data.get("strArtist")) or artist,
        biography=_text(
            data.get("strBiographyEN")
            or data.get("strBiography")
            or data.get("strDescriptionEN")
        ),
        image_url=_theaudiodb_artist_image_url(data),
        genre=_text(data.get("strGenre") or data.get("strStyle")),
        country=_text(data.get("strCountry")),
        formed_year=_safe_int(data.get("intFormedYear"), 0),
        website=_text(data.get("strWebsite") or data.get("strFacebook") or data.get("strTwitter")),
        similar_artists=_split_similar_artists(data.get("strSimilarArtists") or data.get("strSimilar")),
        metadata_source="theaudiodb",
    )


def _theaudiodb_artist_image_url(data: dict[str, Any]) -> str:
    for key in ("strArtistThumb", "strArtistFanart", "strArtistLogo", "strArtistBanner"):
        url = _text(data.get(key))
        if url:
            return url
    return ""


def _split_similar_artists(value: Any) -> list[str]:
    text = _text(value)
    if not text:
        return []
    # Do not split on '/' — band names like "AC/DC" contain a slash.
    return [
        item.strip()
        for item in re.split(r"[,;|]", text)
        if item.strip()
    ][:8]


def _with_theaudiodb_enrichment(info: AlbumInfo | None) -> AlbumInfo | None:
    if not info or not (info.artist and info.album):
        return info
    if info.tracks and info.artwork_url:
        return info

    fallback = search_theaudiodb_album(info.artist, info.album)
    if not fallback:
        return info
    return _merge_album_info(info, fallback)


def _merge_album_info(primary: AlbumInfo, fallback: AlbumInfo) -> AlbumInfo:
    supplemented = False
    if not primary.tracks and fallback.tracks:
        primary.tracks = fallback.tracks
        supplemented = True
    if not primary.artwork_url and fallback.artwork_url:
        primary.artwork_url = fallback.artwork_url
        supplemented = True
    if not primary.genre and fallback.genre:
        primary.genre = fallback.genre
        supplemented = True
    if not primary.date and fallback.date:
        primary.date = fallback.date
        supplemented = True
    if not primary.musicbrainz_albumid and fallback.musicbrainz_albumid:
        primary.musicbrainz_albumid = fallback.musicbrainz_albumid
        supplemented = True
    if supplemented and "theaudiodb" not in primary.metadata_source:
        primary.metadata_source = f"{primary.metadata_source}+theaudiodb"
    return primary


def _fetch_artwork_url(url: str) -> bytes | None:
    import requests

    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        _log_metadata_diagnostic("Artwork request skipped for unsupported URL: %s", url)
        return None
    try:
        response = _http_get(url, timeout=HTTP_TIMEOUT_SECONDS, stream=True)
        byte_count = 0
        if response.status_code == 200:
            content_length = response.headers.get("Content-Length") if hasattr(response, "headers") else None
            if content_length and _safe_int(content_length, 0) > MAX_ARTWORK_BYTES:
                _log_metadata_diagnostic(
                    "Artwork request skipped for %s: Content-Length exceeds %s bytes",
                    url,
                    MAX_ARTWORK_BYTES,
                )
                return None
            content = _limited_response_content(response, MAX_ARTWORK_BYTES)
            byte_count = len(content)
            if content:
                return content
        _log_metadata_diagnostic(
            "Artwork request failed for %s: HTTP %s %s (bytes=%s)",
            url,
            response.status_code,
            _text(getattr(response, "reason", "")),
            byte_count,
        )
    except requests.RequestException as exc:
        _log_metadata_diagnostic("Artwork request failed for %s: %s", url, exc)
    return None


def _limited_response_content(response: requests.Response, limit: int) -> bytes:
    """Read response bytes with an upper bound; supports simple test doubles too."""
    if hasattr(response, "iter_content"):
        data = bytearray()
        for chunk in response.iter_content(chunk_size=64 * 1024):
            if not chunk:
                continue
            data.extend(chunk)
            if len(data) > limit:
                _log_metadata_diagnostic(
                    "Artwork response exceeded %s bytes and was discarded",
                    limit,
                )
                return b""
        return bytes(data)

    content = getattr(response, "content", b"") or b""
    if len(content) <= limit:
        return content
    _log_metadata_diagnostic(
        "Artwork response exceeded %s bytes and was discarded",
        limit,
    )
    return b""


def _get_json(
    url: str,
    params: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    import requests

    try:
        response = _http_get(
            url, params=params, headers=headers, timeout=HTTP_TIMEOUT_SECONDS
        )
        if response.status_code != 200:
            _log_metadata_diagnostic(
                "JSON metadata request failed for %s params=%s: HTTP %s %s",
                url,
                params or {},
                response.status_code,
                _text(getattr(response, "reason", "")),
            )
            return {}
        payload = response.json()
    except ValueError as exc:
        _log_metadata_diagnostic(
            "JSON metadata request returned invalid JSON for %s params=%s: %s",
            url,
            params or {},
            exc,
        )
        return {}
    except requests.RequestException as exc:
        _log_metadata_diagnostic(
            "JSON metadata request failed for %s params=%s: %s",
            url,
            params or {},
            exc,
        )
        return {}
    return payload if isinstance(payload, dict) else {}


def _musicbrainz_artist(entity: dict) -> str:
    artist_credit = entity.get("artist-credit") or []
    if artist_credit:
        first = artist_credit[0]
        if isinstance(first, dict):
            return first.get("artist", {}).get("name", "")
        return str(first)
    return entity.get("artist-credit-phrase", "")


def _is_theaudiodb_album_match(item: dict[str, Any], artist: str, album: str) -> bool:
    title = _text(item.get("strAlbum"))
    artist_name = _text(item.get("strArtist"))
    return _normalize(album) in _normalize(title) and (
        not artist or _normalize(artist) in _normalize(artist_name)
    )


def _is_theaudiodb_artist_match(item: dict[str, Any], artist: str) -> bool:
    artist_name = _text(item.get("strArtist"))
    if not artist_name:
        return False
    needle = _normalize(artist)
    haystack = _normalize(artist_name)
    if not needle or not haystack:
        return False
    if needle == haystack:
        return True
    # Accept "Beatles" / "The Beatles" by comparing whole-token suffixes;
    # reject substring overlaps like "Dre" inside "Dreadnoughts".
    haystack_tokens = haystack.split()
    needle_tokens = needle.split()
    if len(needle_tokens) > len(haystack_tokens):
        return False
    return needle_tokens == haystack_tokens[-len(needle_tokens):]


def _musicbrainz_toc_to_ctdb_toc(toc: str | None) -> str:
    """Convert a MusicBrainz TOC string into CTDB's colon-delimited layout."""
    if not toc:
        return ""
    try:
        parts = [int(part) for part in toc.replace("+", " ").split()]
    except ValueError:
        return ""
    if len(parts) < 4:
        return ""

    first_track, last_track, leadout = parts[:3]
    offsets = parts[3:]
    track_count = last_track - first_track + 1
    if first_track != 1 or track_count < 1 or len(offsets) < track_count:
        return ""

    ctdb_offsets = offsets[:track_count] + [leadout]
    if any(offset < 150 for offset in ctdb_offsets):
        return ""
    return ":".join(str(offset - 150) for offset in ctdb_offsets)


def sanitize_ctdb_layout(ctdb_toc: str | None) -> str:
    """Return a validated, normalised CTDB TOC layout string, or '' if invalid."""
    if not ctdb_toc:
        return ""

    tokens = [token.strip() for token in ctdb_toc.strip().split(":")]
    if len(tokens) < 2 or any(not token for token in tokens):
        return ""

    cleaned = []
    for index, token in enumerate(tokens):
        is_data_track = token.startswith("-")
        if is_data_track and index == len(tokens) - 1:
            return ""

        offset_text = token[1:] if is_data_track else token
        if not offset_text.isdigit():
            return ""

        offset = int(offset_text, 10)
        cleaned.append(f"-{offset}" if is_data_track else str(offset))
    return ":".join(cleaned)


def _ctdb_album_score(info: AlbumInfo) -> tuple[int, int, int]:
    source = info.metadata_source.lower()
    source_score = 3 if "musicbrainz" in source else 2 if "theaudiodb" in source else 1
    return source_score, len(info.tracks), 1 if info.artwork_url else 0


def _matching_media(media: list[dict], discid: str | None) -> list[dict]:
    if not discid:
        return media
    matches = []
    for medium in media:
        for disc in medium.get("disc-list", []) or []:
            if disc.get("id") == discid:
                matches.append(medium)
                break
    return matches or media


def _theaudiodb_url(endpoint: str) -> str:
    return f"{THEAUDIODB_API_BASE}/{_theaudiodb_api_key()}/{endpoint}"


def _theaudiodb_api_key() -> str:
    """Return the configured TheAudioDB API key, or '' if none is set."""
    settings = _current_settings()
    return (getattr(settings, "theaudiodb_api_key", "") or "").strip()


def _use_cuetools_db(value: bool | None) -> bool:
    if value is not None:
        return value
    settings = _current_settings()
    return bool(getattr(settings, "cuetools_db_metadata_enabled", True))


def _has_usable_metadata(info: AlbumInfo | None) -> bool:
    return _has_basic_metadata(info)


def _has_basic_metadata(info: AlbumInfo | None) -> bool:
    return bool(info and (info.artist or info.album or info.tracks or info.artwork_url))


def _has_track_metadata(info: AlbumInfo | None) -> bool:
    return bool(info and info.tracks)


def _user_agent() -> str:
    s = _current_settings()
    return f"{s.musicbrainz_app}/{s.musicbrainz_version} ({s.musicbrainz_contact})"


def _normalize(value: str) -> str:
    return " ".join(value.casefold().replace("&", "and").split())


def _unique_non_empty(values: list[str]) -> list[str]:
    seen = set()
    unique = []
    for value in values:
        if value and value not in seen:
            unique.append(value)
            seen.add(value)
    return unique


def _ensure_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return [value]
    return []


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _theaudiodb_duration_ms(value: Any) -> int:
    text = _text(value)
    if not text:
        return 0
    if ":" in text:
        return _duration_to_ms(text)
    return _safe_int(text, 0)


def _duration_to_ms(value: str) -> int:
    if not value or ":" not in value:
        return 0
    try:
        parts = [int(part) for part in value.split(":")]
    except ValueError:
        return 0
    seconds = 0
    for part in parts:
        seconds = seconds * 60 + part
    return seconds * 1000


def _safe_int(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default

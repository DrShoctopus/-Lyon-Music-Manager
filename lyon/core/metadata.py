"""Album metadata and artwork lookups from the supported provider fallbacks."""
from __future__ import annotations

import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Optional
from urllib.parse import urljoin

import musicbrainzngs
import requests

from . import settings as _settings


CTDB_LOOKUP_URL = "http://db.cuetools.net/lookup2.php"
CTDB_BASE_URL = "http://db.cuetools.net/"
CTDB_TIMEOUT_SECONDS = 20
THEAUDIODB_API_BASE = "https://www.theaudiodb.com/api/v1/json"
THEAUDIODB_DEFAULT_API_KEY = "123"
HTTP_TIMEOUT_SECONDS = 15
DISC_METADATA_PROVIDER_ORDER = ("cuetools_db", "musicbrainz", "theaudiodb")
ALBUM_METADATA_PROVIDER_ORDER = ("musicbrainz", "theaudiodb")
ARTWORK_PROVIDER_ORDER = ("cover_art_archive", "album_artwork_url", "theaudiodb")
METADATA_PROVIDER_ORDER = ALBUM_METADATA_PROVIDER_ORDER


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

    @property
    def year(self) -> int:
        if self.date and self.date[:4].isdigit():
            return int(self.date[:4])
        return 0


_initialised = False


def _init() -> None:
    global _initialised
    if _initialised:
        return
    s = _settings.Settings.load()
    musicbrainzngs.set_useragent(s.musicbrainz_app, s.musicbrainz_version, s.musicbrainz_contact)
    _initialised = True


def lookup_disc(
    discid_str: str,
    toc: str | None = None,
    *,
    ctdb_toc: str | None = None,
    use_cuetools_db: bool | None = None,
) -> Optional[AlbumInfo]:
    """Look up an album by disc identity using the supported provider order."""
    providers: list[Callable[[], Optional[AlbumInfo]]] = []
    if _use_cuetools_db(use_cuetools_db):
        providers.append(lambda: lookup_cuetools_db_disc(toc, ctdb_toc=ctdb_toc))
    if discid_str:
        providers.append(lambda: lookup_musicbrainz_disc(discid_str, toc))

    for provider in providers:
        info = provider()
        if _has_usable_metadata(info):
            return _with_theaudiodb_enrichment(info)
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
    if not discid_str:
        return None
    _init()
    try:
        result = musicbrainzngs.get_releases_by_discid(
            discid_str, includes=["recordings", "artists"], toc=toc, cdstubs=True
        )
    except (musicbrainzngs.ResponseError, musicbrainzngs.NetworkError):
        return None

    release = None
    if "disc" in result and result["disc"].get("release-list"):
        release = result["disc"]["release-list"][0]
    elif "cdstub" in result:
        return _musicbrainz_cdstub_to_album(result["cdstub"])

    if not release:
        return None
    return _release_to_album(release, discid_str)


def lookup_cuetools_db_disc(
    toc: str | None,
    *,
    ctdb_toc: str | None = None,
) -> Optional[AlbumInfo]:
    """Look up album metadata through the CUETools Database metadata endpoint."""
    layouts = _unique_non_empty(
        [_sanitize_ctdb_layout(ctdb_toc), _musicbrainz_toc_to_ctdb_toc(toc)]
    )
    if not layouts:
        return None

    for fuzzy in (False, True):
        for layout in layouts:
            info = lookup_cuetools_db_layout(layout, fuzzy=fuzzy)
            if _has_usable_metadata(info):
                return info
    return None


def lookup_ctdb_disc(toc: str | None, *, fuzzy: bool = False) -> Optional[AlbumInfo]:
    """Compatibility wrapper for older CTDB lookup call sites."""
    layout = _musicbrainz_toc_to_ctdb_toc(toc)
    return lookup_cuetools_db_layout(layout, fuzzy=fuzzy)


def lookup_cuetools_db_layout(ctdb_toc: str | None, *, fuzzy: bool = False) -> Optional[AlbumInfo]:
    """Look up album metadata from a CUETools-style CTDB TOC layout."""
    layout = _sanitize_ctdb_layout(ctdb_toc)
    if not layout:
        return None

    try:
        response = requests.get(
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
        if response.status_code != 200 or not response.content:
            return None
    except requests.RequestException:
        return None

    try:
        root = ET.fromstring(response.content)
    except ET.ParseError:
        return None

    candidates = [_ctdb_meta_to_album(meta) for meta in root.findall(".//metadata")]
    candidates = [info for info in candidates if info is not None]
    if not candidates:
        return None

    candidates.sort(key=_ctdb_album_score, reverse=True)
    return candidates[0]


def search_album(artist: str, album: str) -> Optional[AlbumInfo]:
    """Search album metadata providers, preferring results with track data."""
    fallback_info = None
    for provider in _album_search_providers():
        info = provider(artist, album)
        if _has_track_metadata(info):
            return info
        if fallback_info is None and _has_basic_metadata(info):
            fallback_info = info
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
    _init()
    try:
        result = musicbrainzngs.search_releases(artist=artist, release=album, limit=1)
    except (musicbrainzngs.ResponseError, musicbrainzngs.NetworkError):
        return None
    rels = result.get("release-list") or []
    if not rels:
        return None
    rid = rels[0]["id"]
    try:
        full = musicbrainzngs.get_release_by_id(
            rid, includes=["recordings", "artists"]
        )["release"]
    except (musicbrainzngs.ResponseError, musicbrainzngs.NetworkError):
        return None
    return _release_to_album(full)


def search_theaudiodb_album(artist: str, album: str) -> Optional[AlbumInfo]:
    """Search TheAudioDB by album and optional artist name."""
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


def _album_search_providers() -> tuple[Callable[[str, str], Optional[AlbumInfo]], ...]:
    return (search_musicbrainz_album, search_theaudiodb_album)


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

    info = AlbumInfo(
        artist=artist,
        album=album,
        date=_ctdb_date(meta),
        genre=(meta.get("genre") or "").strip(),
        metadata_source=f"cuetools_db:{(meta.get('source') or 'unknown').strip()}",
    )

    disc_number = _safe_int(meta.get("discnumber"), 1)
    for number, track in enumerate(meta.findall("track"), start=1):
        title = (track.get("name") or "").strip() or f"Track {number:02d}"
        info.tracks.append(
            TrackInfo(
                number=number,
                title=title,
                artist=(track.get("artist") or "").strip() or artist,
                disc_number=disc_number,
            )
        )

    info.artwork_url = _select_ctdb_cover(meta.findall("coverart"))
    return info


def _ctdb_date(meta: ET.Element) -> str:
    date = (meta.get("year") or "").strip()
    for release in meta.findall("release"):
        release_date = (release.get("date") or "").strip()
        if release_date:
            return release_date
    return date


def _select_ctdb_cover(covers: list[ET.Element]) -> str:
    if not covers:
        return ""
    ordered = sorted(
        covers, key=lambda c: c.get("primary", "").lower() == "true", reverse=True
    )
    for cover in ordered:
        uri = (cover.get("uri") or cover.get("uri150") or "").strip()
        if uri:
            return urljoin(CTDB_BASE_URL, uri)
    return ""


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
    try:
        response = requests.get(url, timeout=HTTP_TIMEOUT_SECONDS)
        if response.status_code == 200 and response.content:
            return response.content
    except requests.RequestException:
        return None
    return None


def _get_json(
    url: str,
    params: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    try:
        response = requests.get(
            url, params=params, headers=headers, timeout=HTTP_TIMEOUT_SECONDS
        )
        if response.status_code != 200:
            return {}
        payload = response.json()
    except (ValueError, requests.RequestException):
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


def _sanitize_ctdb_layout(ctdb_toc: str | None) -> str:
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
    settings = _settings.Settings.load()
    return getattr(settings, "theaudiodb_api_key", "") or THEAUDIODB_DEFAULT_API_KEY


def _use_cuetools_db(value: bool | None) -> bool:
    if value is not None:
        return value
    settings = _settings.Settings.load()
    return bool(getattr(settings, "cuetools_db_metadata_enabled", True))


def _has_usable_metadata(info: AlbumInfo | None) -> bool:
    return _has_basic_metadata(info)


def _has_basic_metadata(info: AlbumInfo | None) -> bool:
    return bool(info and (info.artist or info.album or info.tracks or info.artwork_url))


def _has_track_metadata(info: AlbumInfo | None) -> bool:
    return bool(info and info.tracks)


def _user_agent() -> str:
    s = _settings.Settings.load()
    return f"{s.musicbrainz_app}/{s.musicbrainz_version} ({s.musicbrainz_contact})"


def _metadata_headers() -> dict[str, str]:
    return {"User-Agent": _user_agent()}


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
    text = str(value).strip()
    return "" if text.lower() == "none" else text


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

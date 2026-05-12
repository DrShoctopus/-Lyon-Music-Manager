"""Album metadata and artwork lookups from prioritized provider fallbacks."""
from __future__ import annotations

import os
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
ITUNES_SEARCH_URL = "https://itunes.apple.com/search"
DISCOGS_DATABASE_SEARCH_URL = "https://api.discogs.com/database/search"
DISCOGS_MASTER_URL = "https://api.discogs.com/masters/{discogs_id}"
DISCOGS_RELEASE_URL = "https://api.discogs.com/releases/{discogs_id}"
DEEZER_ALBUM_SEARCH_URL = "https://api.deezer.com/search/album"
DEEZER_ALBUM_URL = "https://api.deezer.com/album/{album_id}"
LASTFM_API_URL = "https://ws.audioscrobbler.com/2.0/"
HTTP_TIMEOUT_SECONDS = 15
LASTFM_API_KEY_ENV = "LASTFM_API_KEY"
DISC_METADATA_PROVIDER_ORDER = ("musicbrainz", "ctdb")
ALBUM_METADATA_PROVIDER_ORDER = ("musicbrainz", "discogs", "itunes", "deezer", "lastfm")
ARTWORK_PROVIDER_ORDER = (
    "cover_art_archive",
    "album_artwork_url",
    "discogs",
    "itunes",
    "deezer",
    "lastfm",
)
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


def lookup_disc(discid_str: str, toc: str | None = None) -> Optional[AlbumInfo]:
    """Look up an album by disc identity using MusicBrainz before fallback sources."""
    for provider in (_disc_musicbrainz_provider, _disc_ctdb_provider):
        info = provider(discid_str, toc)
        if _has_usable_metadata(info):
            return info
    return None


def lookup_disc_with_fallback(discid_str: str, toc: str | None = None) -> Optional[AlbumInfo]:
    """Compatibility wrapper for disc lookup with provider fallbacks."""
    return lookup_disc(discid_str, toc)


def lookup_musicbrainz_disc(discid_str: str, toc: str | None = None) -> Optional[AlbumInfo]:
    """Look up an album by MusicBrainz disc ID."""
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


def lookup_ctdb_disc(toc: str | None, *, fuzzy: bool = False) -> Optional[AlbumInfo]:
    """Look up album metadata through the CUETools Database metadata endpoint.

    CTDB fuzzy matches may describe a similar, but not identical, disc TOC.
    Keep the default lookup exact so fallback metadata cannot mask an exact
    MusicBrainz disc ID resolution in the automatic metadata flow.
    """
    ctdb_toc = _musicbrainz_toc_to_ctdb_toc(toc)
    if not ctdb_toc:
        return None

    user_agent = _user_agent()
    try:
        response = requests.get(
            CTDB_LOOKUP_URL,
            params={
                "version": "3",
                "ctdb": "0",
                "metadata": "extensive",
                "fuzzy": "1" if fuzzy else "0",
                "toc": ctdb_toc,
            },
            headers={"User-Agent": user_agent},
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
    """Fetch artwork lazily from primary URLs before provider lookups."""
    for url in _primary_artwork_urls(album):
        artwork = _fetch_artwork_url(url)
        if artwork:
            return artwork

    if not (album.artist and album.album):
        return None

    for provider in _artwork_search_providers():
        info = provider(album.artist, album.album)
        if not info or not info.artwork_url:
            continue
        artwork = _fetch_artwork_url(info.artwork_url)
        if artwork:
            return artwork
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


def search_discogs_album(artist: str, album: str) -> Optional[AlbumInfo]:
    """Search Discogs for album tracks and artwork."""
    result = _search_discogs_album_result(artist, album, "master")
    if result is None:
        result = _search_discogs_album_result(artist, album, "release")
    if result is None:
        return None

    detail = _discogs_detail(result)
    data = detail or result
    artist_name = _discogs_artist_name(data) or artist
    album_title = str(data.get("title") or _discogs_result_album_title(result) or album)
    artwork_url = _discogs_artwork_url(data) or str(result.get("cover_image") or "")
    genres = data.get("genres") if isinstance(data.get("genres"), list) else []

    info = AlbumInfo(
        artist=artist_name,
        album=album_title,
        date=str(data.get("year") or result.get("year") or ""),
        genre=str(genres[0]) if genres else "",
        artwork_url=artwork_url,
        metadata_source="discogs",
    )
    for index, track in enumerate(data.get("tracklist") or [], start=1):
        if not isinstance(track, dict) or track.get("type_") == "heading":
            continue
        track_number, disc_number = _discogs_track_numbers(track.get("position"), index)
        info.tracks.append(
            TrackInfo(
                number=track_number,
                title=str(track.get("title") or f"Track {index}"),
                length_ms=_duration_to_ms(str(track.get("duration") or "")),
                artist=artist_name,
                disc_number=disc_number,
            )
        )
    return info


def search_itunes_album(artist: str, album: str) -> Optional[AlbumInfo]:
    """Search iTunes for album tracks and artwork."""
    payload = _get_json(
        ITUNES_SEARCH_URL,
        params={
            "term": f"{artist} {album}",
            "entity": "song",
            "media": "music",
            "limit": "50",
        },
    )
    results = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(results, list):
        return None

    matches = [
        song for song in results if _is_album_match(song, artist, album)
    ]
    if not matches:
        return None
    matches.sort(
        key=lambda song: (
            _safe_int(song.get("discNumber"), 1),
            _safe_int(song.get("trackNumber"), 0),
        )
    )

    first = matches[0]
    info = AlbumInfo(
        artist=str(first.get("artistName") or artist),
        album=str(first.get("collectionName") or album),
        date=str(first.get("releaseDate") or "")[:10],
        genre=str(first.get("primaryGenreName") or ""),
        artwork_url=_itunes_artwork_url(str(first.get("artworkUrl100") or "")),
        metadata_source="itunes",
    )
    for index, song in enumerate(matches, start=1):
        info.tracks.append(
            TrackInfo(
                number=_safe_int(song.get("trackNumber"), index),
                title=str(song.get("trackName") or f"Track {index}"),
                length_ms=_safe_int(song.get("trackTimeMillis"), 0),
                artist=str(song.get("artistName") or info.artist),
                disc_number=_safe_int(song.get("discNumber"), 1),
            )
        )
    return info


def search_deezer_album(artist: str, album: str) -> Optional[AlbumInfo]:
    """Search Deezer for album tracks and artwork."""
    payload = _get_json(
        DEEZER_ALBUM_SEARCH_URL,
        params={"q": f'artist:"{artist}" album:"{album}"', "limit": "5"},
    )
    albums = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(albums, list):
        return None

    match = next(
        (candidate for candidate in albums if _is_album_match(candidate, artist, album)),
        None,
    )
    if not match:
        return None

    album_id = match.get("id")
    detail = _get_json(DEEZER_ALBUM_URL.format(album_id=album_id)) if album_id else {}
    data = detail if isinstance(detail, dict) and detail.get("id") else match
    artist_data = data.get("artist") if isinstance(data.get("artist"), dict) else {}
    tracks_data = (
        data.get("tracks", {}).get("data", [])
        if isinstance(data.get("tracks"), dict)
        else []
    )

    info = AlbumInfo(
        artist=str(artist_data.get("name") or artist),
        album=str(data.get("title") or album),
        date=str(data.get("release_date") or ""),
        genre=_deezer_genre(data),
        artwork_url=str(
            data.get("cover_xl") or data.get("cover_big") or data.get("cover_medium") or ""
        ),
        metadata_source="deezer",
    )
    for index, track in enumerate(tracks_data, start=1):
        track_artist = track.get("artist") if isinstance(track.get("artist"), dict) else {}
        info.tracks.append(
            TrackInfo(
                number=_safe_int(track.get("track_position"), index),
                title=str(track.get("title") or f"Track {index}"),
                length_ms=_safe_int(track.get("duration"), 0) * 1000,
                artist=str(track_artist.get("name") or info.artist),
                disc_number=_safe_int(track.get("disk_number"), 1),
            )
        )
    return info


def search_lastfm_album(artist: str, album: str) -> Optional[AlbumInfo]:
    """Search Last.fm album metadata when LASTFM_API_KEY is configured."""
    api_key = os.environ.get(LASTFM_API_KEY_ENV, "").strip()
    if not api_key:
        return None

    payload = _get_json(
        LASTFM_API_URL,
        params={
            "method": "album.getinfo",
            "api_key": api_key,
            "artist": artist,
            "album": album,
            "format": "json",
        },
    )
    data = payload.get("album") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        return None

    tracks = (
        data.get("tracks", {}).get("track", [])
        if isinstance(data.get("tracks"), dict)
        else []
    )
    if isinstance(tracks, dict):
        tracks = [tracks]
    tags = data.get("tags", {}).get("tag", []) if isinstance(data.get("tags"), dict) else []
    images = data.get("image", []) if isinstance(data.get("image"), list) else []

    info = AlbumInfo(
        artist=str(data.get("artist") or artist),
        album=str(data.get("name") or album),
        genre=_lastfm_genre(tags),
        artwork_url=_lastfm_artwork_url(images),
        metadata_source="lastfm",
    )
    for index, track in enumerate(tracks, start=1):
        if not isinstance(track, dict):
            continue
        info.tracks.append(
            TrackInfo(
                number=_safe_int(
                    track.get("@attr", {}).get("rank")
                    if isinstance(track.get("@attr"), dict)
                    else None,
                    index,
                ),
                title=str(track.get("name") or f"Track {index}"),
                length_ms=_safe_int(track.get("duration"), 0) * 1000,
                artist=info.artist,
            )
        )
    return info


def _disc_musicbrainz_provider(discid_str: str, toc: str | None) -> Optional[AlbumInfo]:
    return lookup_musicbrainz_disc(discid_str, toc)


def _disc_ctdb_provider(_discid_str: str, toc: str | None) -> Optional[AlbumInfo]:
    return lookup_ctdb_disc(toc)


def _album_search_providers() -> tuple[Callable[[str, str], Optional[AlbumInfo]], ...]:
    return (
        search_musicbrainz_album,
        search_discogs_album,
        search_itunes_album,
        search_deezer_album,
        search_lastfm_album,
    )


def _artwork_search_providers() -> tuple[Callable[[str, str], Optional[AlbumInfo]], ...]:
    return (
        search_discogs_album,
        search_itunes_album,
        search_deezer_album,
        search_lastfm_album,
    )


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
        metadata_source=f"ctdb:{(meta.get('source') or 'unknown').strip()}",
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


def _search_discogs_album_result(artist: str, album: str, result_type: str) -> dict[str, Any] | None:
    payload = _get_json(
        DISCOGS_DATABASE_SEARCH_URL,
        params={
            "artist": artist,
            "release_title": album,
            "type": result_type,
            "per_page": "5",
        },
        headers=_metadata_headers(),
    )
    results = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(results, list):
        return None
    return next(
        (result for result in results if _is_discogs_match(result, artist, album)),
        None,
    )


def _discogs_detail(result: dict[str, Any]) -> dict[str, Any]:
    discogs_id = result.get("master_id") or result.get("id")
    if not discogs_id:
        return {}
    if result.get("master_id") or result.get("type") == "master":
        url = DISCOGS_MASTER_URL.format(discogs_id=discogs_id)
    else:
        url = DISCOGS_RELEASE_URL.format(discogs_id=discogs_id)
    return _get_json(url, headers=_metadata_headers())


def _discogs_artist_name(data: dict[str, Any]) -> str:
    artists = data.get("artists")
    if isinstance(artists, list) and artists and isinstance(artists[0], dict):
        return str(artists[0].get("name") or "")
    return ""


def _discogs_artwork_url(data: dict[str, Any]) -> str:
    images = data.get("images")
    if isinstance(images, list):
        for image in images:
            if not isinstance(image, dict):
                continue
            uri = image.get("uri") or image.get("resource_url")
            if uri:
                return str(uri)
    return ""


def _discogs_result_album_title(result: dict[str, Any]) -> str:
    title = str(result.get("title") or "")
    if " - " in title:
        return title.split(" - ", 1)[1].strip()
    return title


def _is_discogs_match(result: dict[str, Any], artist: str, album: str) -> bool:
    result_title = _discogs_result_album_title(result)
    full_title = str(result.get("title") or "")
    return _normalize(album) in _normalize(result_title or full_title) and (
        not artist or _normalize(artist) in _normalize(full_title)
    )


def _discogs_track_numbers(position: Any, fallback: int) -> tuple[int, int]:
    text = str(position or "").strip()
    if not text:
        return fallback, 1
    parts = text.replace("-", ".").split(".")
    numbers = [part for part in parts if part.isdigit()]
    if len(numbers) >= 2:
        return int(numbers[-1]), int(numbers[0])
    digits = "".join(char for char in text if char.isdigit())
    return (int(digits), 1) if digits else (fallback, 1)


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


def _musicbrainz_artist(entity: dict) -> str:
    artist_credit = entity.get("artist-credit") or []
    if artist_credit:
        first = artist_credit[0]
        if isinstance(first, dict):
            return first.get("artist", {}).get("name", "")
        return str(first)
    return entity.get("artist-credit-phrase", "")


def _is_album_match(item: dict, artist: str, album: str) -> bool:
    title = item.get("collectionName") or item.get("title") or item.get("name") or ""
    artist_name = _provider_artist_name(item)
    return _normalize(album) in _normalize(str(title)) and (
        not artist or _normalize(artist) in _normalize(artist_name)
    )


def _provider_artist_name(item: dict) -> str:
    if item.get("artistName"):
        return str(item["artistName"])
    artist = item.get("artist")
    if isinstance(artist, dict):
        return str(artist.get("name") or "")
    return str(artist or "")


def _itunes_artwork_url(url: str) -> str:
    return url.replace("100x100bb", "600x600bb") if url else ""


def _deezer_genre(data: dict) -> str:
    genres = data.get("genres", {}).get("data", []) if isinstance(data.get("genres"), dict) else []
    if genres and isinstance(genres[0], dict):
        return str(genres[0].get("name") or "")
    return ""


def _lastfm_genre(tags: list) -> str:
    if tags and isinstance(tags[0], dict):
        return str(tags[0].get("name") or "")
    return ""


def _lastfm_artwork_url(images: list) -> str:
    for image in reversed(images):
        if isinstance(image, dict) and image.get("#text"):
            return str(image["#text"])
    return ""


def _musicbrainz_toc_to_ctdb_toc(toc: str | None) -> str:
    """Convert a MusicBrainz TOC string into CTDB's colon-delimited offsets."""
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

    sector_zero = offsets[0]
    ctdb_offsets = offsets[:track_count] + [leadout]
    return ":".join(str(offset - sector_zero) for offset in ctdb_offsets)


def _ctdb_album_score(info: AlbumInfo) -> tuple[int, int, int]:
    source = info.metadata_source.lower()
    source_score = 3 if "musicbrainz" in source else 2 if "discogs" in source else 1
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


def _safe_int(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default

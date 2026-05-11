"""MusicBrainz, CTDB, and Cover Art Archive lookups."""
from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urljoin

import musicbrainzngs
import requests

from . import settings as _settings


CTDB_LOOKUP_URL = "http://db.cuetools.net/lookup2.php"
CTDB_BASE_URL = "http://db.cuetools.net/"
CTDB_TIMEOUT_SECONDS = 20


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


def _init():
    global _initialised
    if _initialised:
        return
    s = _settings.Settings.load()
    musicbrainzngs.set_useragent(s.musicbrainz_app, s.musicbrainz_version, s.musicbrainz_contact)
    _initialised = True


def lookup_disc(discid_str: str, toc: str | None = None) -> Optional[AlbumInfo]:
    """Look up an album from CTDB first, falling back to MusicBrainz."""
    ctdb_info = lookup_ctdb_disc(toc)
    if ctdb_info is not None:
        return ctdb_info
    return lookup_musicbrainz_disc(discid_str, toc)


def lookup_disc_with_fallback(discid_str: str, toc: str | None = None) -> Optional[AlbumInfo]:
    """Try CTDB metadata first, then MusicBrainz if CTDB has no match."""
    return lookup_disc(discid_str, toc)


def lookup_musicbrainz_disc(discid_str: str, toc: str | None = None) -> Optional[AlbumInfo]:
    """Look up an album by MusicBrainz disc ID."""
    _init()
    try:
        result = musicbrainzngs.get_releases_by_discid(
            discid_str, includes=["recordings", "artists"], toc=toc, cdstubs=True
        )
    except musicbrainzngs.ResponseError:
        return None
    except musicbrainzngs.NetworkError:
        return None

    release = None
    if "disc" in result and result["disc"].get("release-list"):
        release = result["disc"]["release-list"][0]
    elif "cdstub" in result:
        stub = result["cdstub"]
        info = AlbumInfo(
            artist=stub.get("artist", ""),
            album=stub.get("title", ""),
            metadata_source="musicbrainz-cdstub",
        )
        for i, tr in enumerate(stub.get("track-list", []), start=1):
            info.tracks.append(TrackInfo(number=i, title=tr.get("title", f"Track {i}")))
        return info

    if not release:
        return None
    return _release_to_album(release, discid_str)


def lookup_disc_with_fallback(discid_str: str, toc: str | None = None) -> Optional[AlbumInfo]:
    """Try MusicBrainz first, then CTDB metadata if MusicBrainz has no match."""
    return lookup_disc(discid_str, toc)


def lookup_ctdb_disc(toc: str | None, *, fuzzy: bool = False) -> Optional[AlbumInfo]:
    """Look up album metadata through the CUETools Database metadata endpoint.

    CTDB fuzzy matches may describe a similar, but not identical, disc TOC.
    Keep the default lookup exact so CTDB metadata cannot mask an exact
    MusicBrainz disc ID resolution elsewhere in the automatic metadata flow.
    """
    ctdb_toc = _musicbrainz_toc_to_ctdb_toc(toc)
    if not ctdb_toc:
        return None

    s = _settings.Settings.load()
    user_agent = f"{s.musicbrainz_app}/{s.musicbrainz_version} ({s.musicbrainz_contact})"
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


def fetch_artwork(album: AlbumInfo) -> bytes | None:
    url = ""
    if album.musicbrainz_albumid:
        url = f"https://coverartarchive.org/release/{album.musicbrainz_albumid}/front-500"
    elif album.artwork_url:
        url = album.artwork_url
    if not url:
        return None
    try:
        r = requests.get(url, timeout=15)
        if r.status_code == 200 and r.content:
            return r.content
    except requests.RequestException:
        return None
    return None


def _release_to_album(release: dict, discid: str | None = None) -> AlbumInfo:
    artist_credit = release.get("artist-credit") or []
    artist = ""
    if artist_credit:
        first = artist_credit[0]
        if isinstance(first, dict):
            artist = first.get("artist", {}).get("name", "")
        else:
            artist = str(first)
    info = AlbumInfo(
        artist=artist or release.get("artist-credit-phrase", ""),
        album=release.get("title", ""),
        date=release.get("date", ""),
        musicbrainz_albumid=release.get("id", ""),
    )
    media = _matching_media(release.get("medium-list") or [], discid)
    n = 1
    for medium in media:
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

    date = (meta.get("year") or "").strip()
    for release in meta.findall("release"):
        release_date = (release.get("date") or "").strip()
        if release_date:
            date = release_date
            break

    info = AlbumInfo(
        artist=artist,
        album=album,
        date=date,
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

    cover = _select_ctdb_cover(meta.findall("coverart"))
    if cover:
        info.artwork_url = cover
    return info


def _select_ctdb_cover(covers: list[ET.Element]) -> str:
    if not covers:
        return ""
    ordered = sorted(covers, key=lambda c: c.get("primary", "").lower() == "true", reverse=True)
    for cover in ordered:
        uri = (cover.get("uri") or cover.get("uri150") or "").strip()
        if uri:
            return urljoin(CTDB_BASE_URL, uri)
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


def _safe_int(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default

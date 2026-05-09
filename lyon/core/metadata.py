"""MusicBrainz + Cover Art Archive lookups."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import musicbrainzngs
import requests

from . import settings as _settings


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
        )
        for i, tr in enumerate(stub.get("track-list", []), start=1):
            info.tracks.append(TrackInfo(number=i, title=tr.get("title", f"Track {i}")))
        return info

    if not release:
        return None
    return _release_to_album(release, discid_str)


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
    if not album.musicbrainz_albumid:
        return None
    url = f"https://coverartarchive.org/release/{album.musicbrainz_albumid}/front-500"
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

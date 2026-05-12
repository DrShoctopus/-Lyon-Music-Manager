"""MusicBrainz, CTDB, Microsoft FAI, and Cover Art Archive lookups."""
from __future__ import annotations

import html
import re
import uuid
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
MICROSOFT_FAI_BASE_URL = "https://fai.music.metaservices.microsoft.com/"
MICROSOFT_FAI_LOOKUP_URL = urljoin(MICROSOFT_FAI_BASE_URL, "FAI/AlbumMatch.aspx")
MICROSOFT_FAI_TIMEOUT_SECONDS = 12
MICROSOFT_FAI_COMMON_PARAMS = {
    "locale": "409",
    "geoid": "f4",
    "version": "12.0.7601.17514",
    "userlocale": "409",
}


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
    """Look up an album from CTDB, then MusicBrainz, then Microsoft FAI."""
    ctdb_info = lookup_ctdb_disc(toc)
    if ctdb_info is not None:
        return ctdb_info

    musicbrainz_info = lookup_musicbrainz_disc(discid_str, toc)
    if musicbrainz_info is not None:
        return musicbrainz_info

    return lookup_microsoft_fai_disc(toc)


def lookup_disc_with_fallback(discid_str: str, toc: str | None = None) -> Optional[AlbumInfo]:
    """Try each automatic metadata provider in the normal lookup order."""
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


def lookup_microsoft_fai_disc(toc: str | None) -> Optional[AlbumInfo]:
    """Look up disc metadata through the legacy Microsoft FAI endpoint."""
    fai_toc = _musicbrainz_toc_to_microsoft_fai_toc(toc)
    if not fai_toc:
        return None
    return _request_microsoft_fai({"cdtoc": fai_toc, "toc": fai_toc})


def search_microsoft_fai_album(artist: str, album: str) -> Optional[AlbumInfo]:
    """Search the legacy Microsoft FAI endpoint by artist and album text."""
    artist = artist.strip()
    album = album.strip()
    if not (artist and album):
        return None
    return _request_microsoft_fai(
        {
            "artist": artist,
            "album": album,
            "AlbumArtist": artist,
            "AlbumTitle": album,
        }
    )


def search_album(artist: str, album: str) -> Optional[AlbumInfo]:
    _init()
    try:
        result = musicbrainzngs.search_releases(artist=artist, release=album, limit=1)
    except (musicbrainzngs.ResponseError, musicbrainzngs.NetworkError):
        return search_microsoft_fai_album(artist, album)

    rels = result.get("release-list") or []
    if not rels:
        return search_microsoft_fai_album(artist, album)

    rid = rels[0]["id"]
    try:
        full = musicbrainzngs.get_release_by_id(
            rid, includes=["recordings", "artists"]
        )["release"]
    except (musicbrainzngs.ResponseError, musicbrainzngs.NetworkError):
        return search_microsoft_fai_album(artist, album)
    return _release_to_album(full)


def fetch_artwork(album: AlbumInfo) -> bytes | None:
    urls = []
    if album.musicbrainz_albumid:
        urls.append(f"https://coverartarchive.org/release/{album.musicbrainz_albumid}/front-500")
    if album.artwork_url:
        urls.append(album.artwork_url)

    seen = set()
    for url in urls:
        if not url or url in seen:
            continue
        seen.add(url)
        try:
            r = requests.get(url, timeout=15)
            if r.status_code == 200 and r.content:
                return r.content
        except requests.RequestException:
            continue
    return None


def _request_microsoft_fai(params: dict[str, str]) -> Optional[AlbumInfo]:
    s = _settings.Settings.load()
    user_agent = f"{s.musicbrainz_app}/{s.musicbrainz_version} ({s.musicbrainz_contact})"
    request_params = {
        **MICROSOFT_FAI_COMMON_PARAMS,
        "requestid": str(uuid.uuid4()).upper(),
        **params,
    }
    try:
        response = requests.get(
            MICROSOFT_FAI_LOOKUP_URL,
            params=request_params,
            headers={"User-Agent": user_agent},
            timeout=MICROSOFT_FAI_TIMEOUT_SECONDS,
        )
        if response.status_code != 200 or not response.content:
            return None
    except requests.RequestException:
        return None
    return _microsoft_fai_response_to_album(response.content)


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


def _microsoft_fai_response_to_album(content: bytes | str) -> Optional[AlbumInfo]:
    text = content.decode("utf-8-sig", errors="ignore") if isinstance(content, bytes) else str(content)
    text = text.strip()
    if not text:
        return None

    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        root = None

    if root is not None:
        album_element = _microsoft_fai_find_album_element(root)
        if album_element is not None:
            info = _microsoft_fai_xml_album_to_info(album_element)
            if info is not None:
                return info

    return _microsoft_fai_html_to_album(text)


def _microsoft_fai_find_album_element(root: ET.Element) -> ET.Element | None:
    album_tags = {"album", "albuminfo", "albummatch", "release"}
    for element in root.iter():
        if _normalise_field_name(element.tag) in album_tags and (
            _microsoft_fai_text(element, _MICROSOFT_FAI_ALBUM_FIELDS)
            or _microsoft_fai_text(element, _MICROSOFT_FAI_ARTIST_FIELDS)
        ):
            return element
    if _microsoft_fai_text(root, _MICROSOFT_FAI_ALBUM_FIELDS) or _microsoft_fai_text(
        root, _MICROSOFT_FAI_ARTIST_FIELDS
    ):
        return root
    return None


def _microsoft_fai_xml_album_to_info(element: ET.Element) -> Optional[AlbumInfo]:
    artist = _microsoft_fai_text(element, _MICROSOFT_FAI_ARTIST_FIELDS)
    album = _microsoft_fai_text(element, _MICROSOFT_FAI_ALBUM_FIELDS)
    if not (artist or album):
        return None

    info = AlbumInfo(
        artist=artist,
        album=album,
        date=_microsoft_fai_text(element, _MICROSOFT_FAI_DATE_FIELDS),
        genre=_microsoft_fai_text(element, _MICROSOFT_FAI_GENRE_FIELDS),
        metadata_source="microsoft-fai",
    )

    cover = _microsoft_fai_find_artwork_url(element)
    if cover:
        info.artwork_url = cover

    for number, track in enumerate(_microsoft_fai_track_elements(element), start=1):
        track_number = _safe_int(
            _microsoft_fai_text(track, _MICROSOFT_FAI_TRACK_NUMBER_FIELDS),
            number,
        )
        title = _microsoft_fai_text(track, _MICROSOFT_FAI_TRACK_TITLE_FIELDS)
        if not title:
            title = f"Track {track_number:02d}"
        info.tracks.append(
            TrackInfo(
                number=track_number,
                title=title,
                length_ms=_safe_int(_microsoft_fai_text(track, _MICROSOFT_FAI_LENGTH_FIELDS), 0),
                artist=_microsoft_fai_text(track, _MICROSOFT_FAI_ARTIST_FIELDS) or artist,
            )
        )
    return info


def _microsoft_fai_track_elements(element: ET.Element) -> list[ET.Element]:
    return [
        child
        for child in element.iter()
        if child is not element and _normalise_field_name(child.tag) in {"track", "song"}
    ]


def _microsoft_fai_text(element: ET.Element, names: set[str]) -> str:
    for key, value in element.attrib.items():
        if _normalise_field_name(key) in names:
            value = str(value).strip()
            if value:
                return html.unescape(value)

    for child in list(element):
        if _normalise_field_name(child.tag) in names:
            value = "".join(child.itertext()).strip()
            if value:
                return html.unescape(value)
    return ""


def _microsoft_fai_find_artwork_url(element: ET.Element) -> str:
    cover = _microsoft_fai_text(element, _MICROSOFT_FAI_ARTWORK_FIELDS)
    if cover:
        return urljoin(MICROSOFT_FAI_BASE_URL, cover)

    for child in element.iter():
        for key, value in child.attrib.items():
            key_name = _normalise_field_name(key)
            candidate = str(value).strip()
            lowered = candidate.lower()
            if key_name in {"src", "href", "url", "image"} and _looks_like_artwork_url(lowered):
                return urljoin(MICROSOFT_FAI_BASE_URL, html.unescape(candidate))
    return ""


def _microsoft_fai_html_to_album(text: str) -> Optional[AlbumInfo]:
    artist = _microsoft_fai_html_field(text, ("AlbumArtist", "albumArtist", "artist", "performer"))
    album = _microsoft_fai_html_field(text, ("AlbumTitle", "albumTitle", "album", "title"))
    if not (artist or album):
        return None

    info = AlbumInfo(
        artist=artist,
        album=album,
        date=_microsoft_fai_html_field(text, ("Year", "year", "ReleaseDate", "date")),
        genre=_microsoft_fai_html_field(text, ("Genre", "genre")),
        metadata_source="microsoft-fai",
    )
    cover = _microsoft_fai_html_artwork_url(text)
    if cover:
        info.artwork_url = cover
    return info


def _microsoft_fai_html_field(text: str, aliases: tuple[str, ...]) -> str:
    for alias in aliases:
        escaped = re.escape(alias)
        patterns = (
            rf"<(?:input|meta)\b[^>]*(?:name|id|property)=[\"']{escaped}[\"'][^>]*(?:value|content)=[\"']([^\"']+)[\"']",
            rf"<(?:input|meta)\b[^>]*(?:value|content)=[\"']([^\"']+)[\"'][^>]*(?:name|id|property)=[\"']{escaped}[\"']",
            rf"[\"']{escaped}[\"']\s*[:=]\s*[\"']([^\"']+)[\"']",
            rf"\b{escaped}\b\s*[:=]\s*[\"']([^\"']+)[\"']",
        )
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                return html.unescape(match.group(1).strip())
    return ""


def _microsoft_fai_html_artwork_url(text: str) -> str:
    for match in re.finditer(r"<img\b[^>]*\bsrc=[\"']([^\"']+)[\"']", text, flags=re.IGNORECASE):
        src = html.unescape(match.group(1).strip())
        if _looks_like_artwork_url(src.lower()):
            return urljoin(MICROSOFT_FAI_BASE_URL, src)

    for match in re.finditer(
        r"[\"']([^\"']*(?:cover|albumart)[^\"']*\.(?:jpg|jpeg|png))[\"']",
        text,
        flags=re.IGNORECASE,
    ):
        return urljoin(MICROSOFT_FAI_BASE_URL, html.unescape(match.group(1).strip()))
    return ""


def _looks_like_artwork_url(value: str) -> bool:
    return (
        "cover" in value
        or "albumart" in value
        or value.endswith((".jpg", ".jpeg", ".png"))
    )


def _normalise_field_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", _local_name(str(name)).lower())


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].split(":", 1)[-1]


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


def _musicbrainz_toc_to_microsoft_fai_toc(toc: str | None) -> str:
    """Normalise a MusicBrainz TOC string for the legacy FAI query string."""
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
    return "+".join(str(part) for part in (first_track, last_track, leadout, *offsets[:track_count]))


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


_MICROSOFT_FAI_ALBUM_FIELDS = {"album", "albumtitle", "title", "name"}
_MICROSOFT_FAI_ARTIST_FIELDS = {"artist", "albumartist", "albumartistname", "performer"}
_MICROSOFT_FAI_DATE_FIELDS = {"date", "year", "releasedate", "releaseyear"}
_MICROSOFT_FAI_GENRE_FIELDS = {"genre"}
_MICROSOFT_FAI_ARTWORK_FIELDS = {
    "artworkurl",
    "coverarturl",
    "albumarturl",
    "largecoverarturl",
    "image",
    "imageurl",
    "thumbnail",
}
_MICROSOFT_FAI_TRACK_NUMBER_FIELDS = {"number", "tracknumber", "tracknum", "sequence", "index"}
_MICROSOFT_FAI_TRACK_TITLE_FIELDS = {"title", "tracktitle", "name"}
_MICROSOFT_FAI_LENGTH_FIELDS = {"length", "duration", "lengthms", "durationms"}

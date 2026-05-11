"""FLAC tag writer."""
from __future__ import annotations

from pathlib import Path

from mutagen.flac import FLAC, Picture
from mutagen.id3 import PictureType

from .metadata import AlbumInfo, TrackInfo


def write_flac_tags(
    path: Path,
    album: AlbumInfo,
    track: TrackInfo,
    artwork: bytes | None,
) -> bool:
    try:
        f = FLAC(str(path))
    except Exception:
        return False

    f["title"] = track.title
    f["artist"] = track.artist or album.artist
    f["albumartist"] = album.artist
    f["album"] = album.album
    if album.date:
        f["date"] = album.date
    f["tracknumber"] = str(track.number)
    f["tracktotal"] = str(len(album.tracks))
    if track.disc_number > 0:
        f["discnumber"] = str(track.disc_number)
    disc_total = max((tr.disc_number for tr in album.tracks), default=0)
    if disc_total > 1:
        f["disctotal"] = str(disc_total)
    if album.musicbrainz_albumid:
        f["musicbrainz_albumid"] = album.musicbrainz_albumid
    if album.genre:
        f["genre"] = album.genre

    if artwork:
        pic = Picture()
        pic.type = PictureType.COVER_FRONT
        pic.mime = "image/jpeg" if artwork[:3] == b"\xff\xd8\xff" else "image/png"
        pic.desc = "Front Cover"
        pic.data = artwork
        f.clear_pictures()
        f.add_picture(pic)

    try:
        f.save()
    except Exception:
        return False
    return True

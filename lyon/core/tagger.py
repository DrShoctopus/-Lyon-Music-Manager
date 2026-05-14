"""FLAC tag writer."""
from __future__ import annotations

from pathlib import Path

import mutagen
from mutagen.flac import FLAC, Picture
from mutagen.id3 import PictureType

from .metadata import AlbumInfo, TrackInfo

_PNG_MAGIC = b"\x89PNG"


def write_flac_tags(
    path: Path,
    album: AlbumInfo,
    track: TrackInfo,
    artwork: bytes | None,
) -> bool:
    try:
        f = FLAC(str(path))
    except (mutagen.MutagenError, OSError):
        return False

    f["title"] = track.title
    f["artist"] = track.artist or album.artist
    f["albumartist"] = album.artist
    f["album"] = album.album
    if album.date:
        f["date"] = album.date
    f["tracknumber"] = str(track.number)
    f["tracktotal"] = str(len(album.tracks))
    if album.musicbrainz_albumid:
        f["musicbrainz_albumid"] = album.musicbrainz_albumid
    if album.genre:
        f["genre"] = album.genre

    if artwork:
        pic = Picture()
        pic.type = PictureType.COVER_FRONT
        pic.mime = "image/png" if artwork[:4] == _PNG_MAGIC else "image/jpeg"
        pic.desc = "Front Cover"
        pic.data = artwork
        f.clear_pictures()
        f.add_picture(pic)

    try:
        f.save()
    except (mutagen.MutagenError, OSError):
        return False
    return True

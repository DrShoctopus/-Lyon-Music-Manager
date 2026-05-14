"""Multi-format audio tag writer."""
from __future__ import annotations

import base64
from pathlib import Path

import mutagen
from mutagen.flac import FLAC, Picture
from mutagen.id3 import PictureType

from .metadata import AlbumInfo, TrackInfo

_PNG_MAGIC = b"\x89PNG"


def write_tags(
    path: Path,
    album: AlbumInfo,
    track: TrackInfo,
    artwork: bytes | None,
) -> bool:
    """Write tags to *path* using the appropriate format handler."""
    ext = path.suffix.lower()
    if ext == ".flac":
        return write_flac_tags(path, album, track, artwork)
    if ext == ".mp3":
        return _write_id3_tags(path, album, track, artwork)
    if ext == ".m4a":
        return _write_mp4_tags(path, album, track, artwork)
    if ext in (".ogg", ".opus"):
        return _write_vorbis_comment_tags(path, album, track, artwork)
    if ext in (".wav", ".aiff", ".aif"):
        return _write_id3_tags(path, album, track, artwork)
    if ext == ".wma":
        return _write_asf_tags(path, album, track, artwork)
    return True  # unsupported container — rip succeeded, tags silently skipped


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


def _write_id3_tags(
    path: Path,
    album: AlbumInfo,
    track: TrackInfo,
    artwork: bytes | None,
) -> bool:
    try:
        from mutagen.id3 import ID3, ID3NoHeaderError, APIC, TALB, TDRC, TIT2, TCON, TRCK, TPE1, TPE2
        try:
            audio = ID3(str(path))
        except ID3NoHeaderError:
            audio = ID3()

        audio["TIT2"] = TIT2(encoding=3, text=track.title)
        audio["TPE1"] = TPE1(encoding=3, text=track.artist or album.artist)
        audio["TPE2"] = TPE2(encoding=3, text=album.artist)
        audio["TALB"] = TALB(encoding=3, text=album.album)
        if album.date:
            audio["TDRC"] = TDRC(encoding=3, text=album.date)
        audio["TRCK"] = TRCK(encoding=3, text=f"{track.number}/{len(album.tracks)}")
        if album.genre:
            audio["TCON"] = TCON(encoding=3, text=album.genre)
        if artwork:
            mime = "image/png" if artwork[:4] == _PNG_MAGIC else "image/jpeg"
            audio["APIC"] = APIC(encoding=3, mime=mime, type=3, desc="Cover", data=artwork)

        audio.save(str(path))
        return True
    except (mutagen.MutagenError, OSError):
        return False


def _write_mp4_tags(
    path: Path,
    album: AlbumInfo,
    track: TrackInfo,
    artwork: bytes | None,
) -> bool:
    try:
        from mutagen.mp4 import MP4, MP4Cover
        audio = MP4(str(path))
        audio["\xa9nam"] = [track.title]
        audio["\xa9ART"] = [track.artist or album.artist]
        audio["aART"] = [album.artist]
        audio["\xa9alb"] = [album.album]
        if album.date:
            audio["\xa9day"] = [album.date]
        audio["trkn"] = [(track.number, len(album.tracks))]
        if album.genre:
            audio["\xa9gen"] = [album.genre]
        if artwork:
            fmt = MP4Cover.FORMAT_PNG if artwork[:4] == _PNG_MAGIC else MP4Cover.FORMAT_JPEG
            audio["covr"] = [MP4Cover(artwork, imageformat=fmt)]
        audio.save()
        return True
    except (mutagen.MutagenError, OSError):
        return False


def _write_vorbis_comment_tags(
    path: Path,
    album: AlbumInfo,
    track: TrackInfo,
    artwork: bytes | None,
) -> bool:
    try:
        audio = mutagen.File(str(path))
        if audio is None:
            return False
        audio["title"] = [track.title]
        audio["artist"] = [track.artist or album.artist]
        audio["albumartist"] = [album.artist]
        audio["album"] = [album.album]
        if album.date:
            audio["date"] = [album.date]
        audio["tracknumber"] = [str(track.number)]
        audio["tracktotal"] = [str(len(album.tracks))]
        if album.genre:
            audio["genre"] = [album.genre]
        if artwork:
            pic = Picture()
            pic.type = PictureType.COVER_FRONT
            pic.mime = "image/png" if artwork[:4] == _PNG_MAGIC else "image/jpeg"
            pic.desc = "Front Cover"
            pic.data = artwork
            audio["metadata_block_picture"] = [
                base64.b64encode(pic.write()).decode("ascii")
            ]
        audio.save()
        return True
    except (mutagen.MutagenError, OSError):
        return False


def _write_asf_tags(
    path: Path,
    album: AlbumInfo,
    track: TrackInfo,
    artwork: bytes | None,
) -> bool:
    try:
        from mutagen.asf import ASF
        audio = ASF(str(path))
        audio["Title"] = [track.title]
        audio["Author"] = [track.artist or album.artist]
        audio["WM/AlbumArtist"] = [album.artist]
        audio["WM/AlbumTitle"] = [album.album]
        if album.date:
            audio["WM/Year"] = [album.date]
        audio["WM/TrackNumber"] = [str(track.number)]
        if album.genre:
            audio["WM/Genre"] = [album.genre]
        audio.save()
        return True
    except (mutagen.MutagenError, OSError):
        return False

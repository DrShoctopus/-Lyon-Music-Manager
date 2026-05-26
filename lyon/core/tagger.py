"""Multi-format audio tag writer."""
from __future__ import annotations

import base64
from pathlib import Path

import mutagen
from mutagen.flac import FLAC, Picture
from mutagen.id3 import PictureType

from .metadata import AlbumInfo, TrackInfo

_PNG_MAGIC = b"\x89PNG"


_VORBIS_KEYS: dict[str, str] = {
    "title": "title",
    "artist": "artist",
    "album_artist": "albumartist",
    "album": "album",
    "track_no": "tracknumber",
    "disc_no": "discnumber",
    "year": "date",
    "genre": "genre",
    "grouping": "grouping",
}

_ASF_KEYS: dict[str, str] = {
    "title": "Title",
    "artist": "Author",
    "album_artist": "WM/AlbumArtist",
    "album": "WM/AlbumTitle",
    "track_no": "WM/TrackNumber",
    "disc_no": "WM/PartOfSet",
    "year": "WM/Year",
    "genre": "WM/Genre",
    "grouping": "WM/ContentGroupDescription",
}


def write_partial_tags(path: Path, fields: dict) -> bool:
    """Write only the supplied fields to *path*, preserving all other existing tags.

    *fields* uses the library field names: title, artist, album_artist, album,
    track_no, disc_no, year, genre, grouping.  Empty dict is a no-op.
    Returns True on success (including no-op), False on any I/O or format error.
    """
    if not fields:
        return True
    ext = path.suffix.lower()
    if ext == ".flac":
        return _partial_vorbis(path, fields)
    if ext == ".mp3":
        return _partial_id3(path, fields)
    if ext == ".m4a":
        return _partial_mp4(path, fields)
    if ext in (".ogg", ".opus"):
        return _partial_vorbis(path, fields)
    if ext in (".wav", ".aiff", ".aif"):
        return _partial_id3(path, fields)
    if ext == ".wma":
        return _partial_asf(path, fields)
    return True


def _partial_vorbis(path: Path, fields: dict) -> bool:
    try:
        audio = mutagen.File(str(path))
        if audio is None:
            return False
        for lib_key, tag_key in _VORBIS_KEYS.items():
            if lib_key in fields:
                audio[tag_key] = [str(fields[lib_key] or "")]
        audio.save()
        return True
    except (mutagen.MutagenError, OSError):
        return False


def _partial_id3(path: Path, fields: dict) -> bool:
    try:
        from mutagen.id3 import TALB, TDRC, TIT1, TIT2, TCON, TRCK, TPOS, TPE1, TPE2
        audio = mutagen.File(str(path))
        if audio is None:
            return False
        if audio.tags is None:
            audio.add_tags()
        tags = audio.tags
        _ID3 = {
            "title": (TIT2, str),
            "artist": (TPE1, str),
            "album_artist": (TPE2, str),
            "album": (TALB, str),
            "track_no": (TRCK, str),
            "disc_no": (TPOS, str),
            "year": (TDRC, str),
            "genre": (TCON, str),
            "grouping": (TIT1, str),
        }
        for lib_key, (frame_cls, cast) in _ID3.items():
            if lib_key in fields:
                tags[frame_cls.__name__] = frame_cls(encoding=3, text=cast(fields[lib_key] or ""))
        audio.save()
        return True
    except (mutagen.MutagenError, OSError):
        return False


def _partial_mp4(path: Path, fields: dict) -> bool:
    try:
        from mutagen.mp4 import MP4
        audio = MP4(str(path))
        _ATOMS: dict[str, str] = {
            "title": "\xa9nam",
            "artist": "\xa9ART",
            "album_artist": "aART",
            "album": "\xa9alb",
            "year": "\xa9day",
            "genre": "\xa9gen",
            "grouping": "\xa9grp",
        }
        for lib_key, atom in _ATOMS.items():
            if lib_key in fields:
                audio[atom] = [str(fields[lib_key] or "")]
        if "track_no" in fields:
            existing = audio.get("trkn", [(0, 0)])
            total = existing[0][1] if existing else 0
            audio["trkn"] = [(int(fields["track_no"] or 0), total)]
        if "disc_no" in fields:
            existing = audio.get("disk", [(0, 0)])
            total = existing[0][1] if existing else 0
            audio["disk"] = [(int(fields["disc_no"] or 0), total)]
        audio.save()
        return True
    except (mutagen.MutagenError, OSError):
        return False


def _partial_asf(path: Path, fields: dict) -> bool:
    try:
        from mutagen.asf import ASF
        audio = ASF(str(path))
        for lib_key, tag_key in _ASF_KEYS.items():
            if lib_key in fields:
                audio[tag_key] = [str(fields[lib_key] or "")]
        audio.save()
        return True
    except (mutagen.MutagenError, OSError):
        return False


def write_tags(
    path: Path,
    album: AlbumInfo,
    track: TrackInfo,
    artwork: bytes | None,
    disc_id: str = "",
) -> bool:
    """Write tags to *path* using the appropriate format handler."""
    ext = path.suffix.lower()
    if ext == ".flac":
        return write_flac_tags(path, album, track, artwork, disc_id=disc_id)
    if ext == ".mp3":
        return _write_id3_tags(path, album, track, artwork, disc_id=disc_id)
    if ext == ".m4a":
        return _write_mp4_tags(path, album, track, artwork, disc_id=disc_id)
    if ext in (".ogg", ".opus"):
        return _write_vorbis_comment_tags(path, album, track, artwork, disc_id=disc_id)
    if ext in (".wav", ".aiff", ".aif"):
        return _write_id3_tags(path, album, track, artwork, disc_id=disc_id)
    if ext == ".wma":
        return _write_asf_tags(path, album, track, artwork, disc_id=disc_id)
    return True  # unsupported container — rip succeeded, tags silently skipped


def write_flac_tags(
    path: Path,
    album: AlbumInfo,
    track: TrackInfo,
    artwork: bytes | None,
    disc_id: str = "",
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
    if disc_id:
        f["musicbrainz_discid"] = disc_id
    if album.genre:
        f["genre"] = album.genre
    if album.grouping:
        f["grouping"] = album.grouping

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
    disc_id: str = "",
) -> bool:
    """Write ID3v2 tags into an MP3, WAV, or AIFF container.

    Uses ``mutagen.File`` so the correct container wrapper
    (MP3 / WAVE / AIFF) handles chunk placement -- calling
    ``ID3.save(path)`` directly would corrupt WAV/AIFF files.
    """
    try:
        from mutagen.id3 import APIC, TALB, TDRC, TIT1, TIT2, TCON, TRCK, TPE1, TPE2, TXXX
        audio = mutagen.File(str(path))
        if audio is None:
            return False
        if audio.tags is None:
            audio.add_tags()
        tags = audio.tags

        tags["TIT2"] = TIT2(encoding=3, text=track.title)
        tags["TPE1"] = TPE1(encoding=3, text=track.artist or album.artist)
        tags["TPE2"] = TPE2(encoding=3, text=album.artist)
        tags["TALB"] = TALB(encoding=3, text=album.album)
        if album.date:
            tags["TDRC"] = TDRC(encoding=3, text=album.date)
        tags["TRCK"] = TRCK(encoding=3, text=f"{track.number}/{len(album.tracks)}")
        if album.genre:
            tags["TCON"] = TCON(encoding=3, text=album.genre)
        if album.grouping:
            tags["TIT1"] = TIT1(encoding=3, text=album.grouping)
        if disc_id:
            tags["TXXX:MusicBrainz Disc Id"] = TXXX(
                encoding=3, desc="MusicBrainz Disc Id", text=disc_id,
            )
        if artwork:
            mime = "image/png" if artwork[:4] == _PNG_MAGIC else "image/jpeg"
            tags["APIC"] = APIC(encoding=3, mime=mime, type=3, desc="Cover", data=artwork)

        audio.save()
        return True
    except (mutagen.MutagenError, OSError):
        return False


def _write_mp4_tags(
    path: Path,
    album: AlbumInfo,
    track: TrackInfo,
    artwork: bytes | None,
    disc_id: str = "",
) -> bool:
    try:
        from mutagen.mp4 import MP4, MP4Cover, MP4FreeForm
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
        if album.grouping:
            audio["\xa9grp"] = [album.grouping]
        if disc_id:
            audio["----:com.apple.iTunes:MusicBrainz Disc Id"] = [
                MP4FreeForm(disc_id.encode("utf-8"), MP4FreeForm.FORMAT_UTF8)
            ]
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
    disc_id: str = "",
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
        if disc_id:
            audio["musicbrainz_discid"] = [disc_id]
        if album.genre:
            audio["genre"] = [album.genre]
        if album.grouping:
            audio["grouping"] = [album.grouping]
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
    disc_id: str = "",
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
        if disc_id:
            audio["MusicBrainz/Disc Id"] = [disc_id]
        if album.genre:
            audio["WM/Genre"] = [album.genre]
        if album.grouping:
            audio["WM/ContentGroupDescription"] = [album.grouping]
        audio.save()
        return True
    except (mutagen.MutagenError, OSError):
        return False

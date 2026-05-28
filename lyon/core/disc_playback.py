"""Helpers for optical-disc playback sources.

The ripping stack owns accurate Audio CD TOC reads. This module keeps playback
concerns small: drive normalization, VLC MRL construction, light video-disc
probing, and transient Track objects for Audio CD queues.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from .cd_detect import DiscToc
from .library import Track
from .metadata import AlbumInfo

CD_SECTORS_PER_SECOND = 75


class DiscKind(Enum):
    AUDIO_CD = "audio_cd"
    DVD = "dvd"
    VCD = "vcd"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class VideoDiscSource:
    drive: str
    kind: DiscKind
    uri: str
    fallback_uri: str | None = None
    label: str = "Video disc"


def drive_root(drive: str) -> str:
    """Return a Windows drive root suitable for filesystem checks."""
    text = (drive or "").strip().strip('"')
    if not text:
        return ""
    if text.startswith("\\\\.\\"):
        letter = text.rstrip("\\/")[-2:-1]
        return f"{letter.upper()}:\\" if letter.isalpha() else text
    letter = text[:1]
    if len(text) >= 2 and text[1] == ":" and letter.isalpha():
        rest = text[2:]
        if rest and rest.strip("\\/"):
            return text.rstrip("\\/")
        return f"{letter.upper()}:\\"
    if len(text) == 1 and letter.isalpha():
        return f"{letter.upper()}:\\"
    if "\\" in text or "/" in text:
        return text.rstrip("\\/")
    return text.rstrip("\\/") + os.sep


def vlc_device(drive: str) -> str:
    """Return a slash-normalized device string for VLC MRLs."""
    root = drive_root(drive)
    if len(root) >= 3 and root[1:3] == ":\\":
        return root[:2] + "/"
    return root.replace("\\", "/")


def cdda_uri(drive: str) -> str:
    device = vlc_device(drive)
    if device.startswith("/"):
        # macOS: drive is "/dev/diskN"; VLC accepts "cdda:///dev/diskN"
        return f"cdda://{device}"
    return f"cdda:///{device}"


def dvd_uri(drive: str, *, menus: bool = True) -> str:
    scheme = "dvd" if menus else "dvdsimple"
    return f"{scheme}:///{vlc_device(drive)}"


def vcd_uri(drive: str) -> str:
    return f"vcd:///{vlc_device(drive)}"


def cdda_track_options(track_number: int) -> tuple[str, ...]:
    return (f":cdda-track={max(1, int(track_number))}",)


def probe_video_disc(drive: str, forced: DiscKind | None = None) -> VideoDiscSource:
    """Best-effort video-disc source detection.

    Optical drives can be slow or unreadable until media spins up. When probing
    fails, callers may pass a forced kind from the UI and we still produce a VLC
    source so libVLC can perform the authoritative open.
    """
    if forced in (DiscKind.DVD, DiscKind.VCD):
        kind = forced
    else:
        kind = _detect_video_kind(drive)
    if kind == DiscKind.VCD:
        return VideoDiscSource(drive, kind, vcd_uri(drive), label="VCD/SVCD")
    if kind == DiscKind.DVD:
        return VideoDiscSource(
            drive,
            kind,
            dvd_uri(drive, menus=True),
            fallback_uri=dvd_uri(drive, menus=False),
            label="DVD",
        )
    return VideoDiscSource(
        drive,
        DiscKind.UNKNOWN,
        dvd_uri(drive, menus=True),
        fallback_uri=dvd_uri(drive, menus=False),
        label="Video disc",
    )


def _detect_video_kind(drive: str) -> DiscKind:
    root = Path(drive_root(drive))
    try:
        names = {p.name.upper() for p in root.iterdir()}
    except OSError:
        return DiscKind.UNKNOWN
    if "VIDEO_TS" in names:
        return DiscKind.DVD
    if {"MPEGAV", "VCD"} & names or {"SVCD", "EXT", "SEGMENT"} & names:
        return DiscKind.VCD
    return DiscKind.UNKNOWN


def tracks_from_audio_cd(toc: DiscToc, album: AlbumInfo | None = None) -> list[Track]:
    """Create transient queue tracks for an Audio CD TOC."""
    track_count = _audio_track_count(toc, album)
    album_tracks = {track.number: track for track in (album.tracks if album else [])}
    out: list[Track] = []
    for number in range(1, track_count + 1):
        info = album_tracks.get(number)
        duration = _track_duration_seconds(toc, number)
        if info and info.length_ms > 0:
            duration = info.length_ms / 1000
        title = info.title if info and info.title else f"Track {number:02d}"
        artist = info.artist if info and info.artist else (album.artist if album else "")
        out.append(
            Track(
                id=0,
                path=f"{cdda_uri(toc.drive)}#{number:02d}",
                title=title,
                artist=artist,
                album_artist=album.artist if album else "",
                album=album.album if album else "Audio CD",
                track_no=number,
                disc_no=info.disc_number if info else 1,
                year=album.year if album else 0,
                genre=album.genre if album else "",
                duration=duration,
                media_type="audio",
                disc_id=toc.discid or None,
                playback_uri=cdda_uri(toc.drive),
                playback_is_location=True,
                playback_options=cdda_track_options(number),
                is_library_item=False,
            )
        )
    return out


def _audio_track_count(toc: DiscToc, album: AlbumInfo | None) -> int:
    if toc.track_count:
        return max(0, int(toc.track_count))
    if album and album.tracks:
        return len(album.tracks)
    return len(toc.track_offsets)


def _track_duration_seconds(toc: DiscToc, track_number: int) -> float:
    index = track_number - 1
    if index < 0 or index >= len(toc.track_offsets):
        return 0.0
    start = toc.track_offsets[index]
    if index + 1 < len(toc.track_offsets):
        end = toc.track_offsets[index + 1]
    else:
        end = toc.sectors
    if end <= start:
        return 0.0
    return (end - start) / CD_SECTORS_PER_SECOND

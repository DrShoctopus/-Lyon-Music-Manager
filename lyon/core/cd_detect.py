"""Disc detection helpers backed by libdiscid when available."""
from __future__ import annotations

from dataclasses import dataclass
import ctypes
from ctypes import wintypes
from pathlib import Path
from typing import List, Optional


@dataclass
class DiscToc:
    drive: str
    discid: str
    toc_string: str
    first_track: int
    last_track: int
    sectors: int
    track_offsets: List[int]
    track_count: int
    mcn: str | None = None
    ctdb_toc_string: str | None = None


@dataclass(frozen=True)
class _CtdbTocEntry:
    track_number: int
    offset: int
    is_audio: bool
    is_leadout: bool = False


def read_disc(drive: str | None = None) -> Optional[DiscToc]:
    """Read a disc TOC from ``drive``.

    Returns ``None`` when no compatible disc reader is available or no disc is
    present. On Windows, a CUETools-compatible raw TOC is also collected so
    metadata lookups can fall back to CTDB's native layout format.
    """

    discid = _load_discid()
    if drive is None:
        drive = _default_drive()
    if not drive:
        return None

    ctdb_entries = _read_windows_ctdb_entries(drive)
    ctdb_toc = _ctdb_toc_from_track_data(ctdb_entries)
    ctdb_fallback = _disc_toc_from_ctdb_entries(drive, ctdb_entries)

    if discid is None:
        return ctdb_fallback

    try:
        disc = discid.read(drive, features=["mcn"])  # type: ignore[attr-defined]
    except discid.DiscError:
        return ctdb_fallback
    except Exception:
        return ctdb_fallback

    track_offsets = list(getattr(disc, "track_offsets", []) or [])
    track_count = int(getattr(disc, "tracks", len(track_offsets)) or len(track_offsets))
    first_track = int(getattr(disc, "first_track_num", 1) or 1)
    last_track = int(getattr(disc, "last_track_num", first_track + track_count - 1) or track_count)
    sectors = int(getattr(disc, "sectors", 0) or 0)
    return DiscToc(
        drive=drive,
        discid=str(getattr(disc, "id", "")),
        toc_string=str(getattr(disc, "toc_string", "")),
        first_track=first_track,
        last_track=last_track,
        sectors=sectors,
        track_offsets=track_offsets,
        track_count=track_count,
        mcn=getattr(disc, "mcn", None),
        ctdb_toc_string=ctdb_toc,
    )


def _load_discid():
    try:
        import discid  # type: ignore

        return discid
    except Exception:
        return None


def _default_drive() -> str | None:
    for letter in "DEFGHIJKLMNOPQRSTUVWXYZ":
        drive = f"{letter}:\\"
        if Path(drive).exists():
            return drive
    return None


def _read_windows_ctdb_toc(drive: str) -> str | None:
    entries = _read_windows_ctdb_entries(drive)
    return _ctdb_toc_from_track_data(entries)


def _read_windows_ctdb_entries(drive: str) -> List[_CtdbTocEntry]:
    if not drive:
        return []
    if not drive.startswith("\\\\.\\"):
        device = "\\\\.\\" + drive.rstrip("\\/")
    else:
        device = drive.rstrip("\\/")
    try:
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    except Exception:
        return []

    handle = k32.CreateFileW(
        device,
        0x80000000,  # GENERIC_READ
        0x00000001 | 0x00000002,  # FILE_SHARE_READ | FILE_SHARE_WRITE
        None,
        3,  # OPEN_EXISTING
        0,
        None,
    )
    if handle == wintypes.HANDLE(-1).value:
        return []

    try:
        return _windows_toc_entries_from_handle(k32, handle)
    finally:
        k32.CloseHandle(handle)


def _windows_toc_entries_from_handle(k32, handle) -> List[_CtdbTocEntry]:
    IOCTL_CDROM_READ_TOC_EX = 0x00024054
    CDROM_READ_TOC_EX_FORMAT_FULL_TOC = 0x02

    class CDROM_READ_TOC_EX(ctypes.Structure):
        _fields_ = [
            ("Format", ctypes.c_ubyte, 4),
            ("Reserved1", ctypes.c_ubyte, 3),
            ("Msf", ctypes.c_ubyte, 1),
            ("SessionTrack", ctypes.c_ubyte),
            ("Reserved2", ctypes.c_ubyte),
            ("Reserved3", ctypes.c_ubyte),
        ]

    inbuf = CDROM_READ_TOC_EX()
    inbuf.Format = CDROM_READ_TOC_EX_FORMAT_FULL_TOC
    inbuf.Msf = 0
    inbuf.SessionTrack = 1
    outbuf = ctypes.create_string_buffer(4096)
    returned = wintypes.DWORD()
    ok = k32.DeviceIoControl(
        handle,
        IOCTL_CDROM_READ_TOC_EX,
        ctypes.byref(inbuf),
        ctypes.sizeof(inbuf),
        outbuf,
        ctypes.sizeof(outbuf),
        ctypes.byref(returned),
        None,
    )
    if not ok or returned.value < 4:
        return []
    return _ctdb_entries_from_windows_toc(outbuf.raw[: returned.value])


def _ctdb_entries_from_windows_toc(raw: bytes) -> List[_CtdbTocEntry]:
    if len(raw) < 4:
        return []
    descriptors = raw[4:]
    entries: list[_CtdbTocEntry] = []
    for idx in range(0, len(descriptors) - 10, 11):
        desc = descriptors[idx : idx + 11]
        point = desc[3]
        control_adr = desc[5]
        track_number = desc[6]
        offset = int.from_bytes(desc[7:11], "big", signed=False)
        is_leadout = point == 0xA2
        if point >= 0xA0 and not is_leadout:
            continue
        if not is_leadout and (track_number == 0 or offset <= 0):
            continue
        control = (control_adr & 0x0F) | (control_adr >> 4)
        is_audio = not bool(control & 0x04)
        entries.append(
            _CtdbTocEntry(
                track_number=track_number,
                offset=offset,
                is_audio=is_audio,
                is_leadout=is_leadout,
            )
        )
    return entries


def _ctdb_toc_from_track_data(entries: list[_CtdbTocEntry]) -> str | None:
    if not entries:
        return None
    tracks = sorted((entry for entry in entries if not entry.is_leadout), key=lambda item: item.track_number)
    leadouts = [entry.offset for entry in entries if entry.is_leadout]
    if not tracks or not leadouts:
        return None
    parts: list[str] = []
    for entry in tracks:
        prefix = "" if entry.is_audio else "-"
        parts.append(f"{prefix}{entry.offset}")
    parts.append(str(max(leadouts)))
    return ":".join(parts)


def _disc_toc_from_ctdb_entries(drive: str, entries: list[_CtdbTocEntry]) -> DiscToc | None:
    ctdb_toc = _ctdb_toc_from_track_data(entries)
    if not ctdb_toc:
        return None

    audio_tracks = sorted(
        (entry for entry in entries if entry.is_audio and not entry.is_leadout),
        key=lambda item: item.track_number,
    )
    leadouts = [entry.offset for entry in entries if entry.is_leadout]
    if not audio_tracks or not leadouts:
        return None

    first_track = audio_tracks[0].track_number
    last_track = audio_tracks[-1].track_number
    track_offsets = [entry.offset for entry in audio_tracks]
    return DiscToc(
        drive=drive,
        discid="",
        toc_string="",
        first_track=first_track,
        last_track=last_track,
        sectors=max(leadouts),
        track_offsets=track_offsets,
        track_count=len(audio_tracks),
        ctdb_toc_string=ctdb_toc,
    )

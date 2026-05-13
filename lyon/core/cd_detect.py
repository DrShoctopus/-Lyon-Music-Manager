"""Optical drive detection and disc ID computation.

Windows-only paths are guarded so the module can be imported on any platform
during development. At runtime on Windows we use ctypes to enumerate drives
and call libdiscid (bundled DLL) for identification.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import importlib
import importlib.util
import os
import string
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .settings import bundled_bin_dir

DRIVE_CDROM = 5  # GetDriveTypeW return value
GENERIC_READ = 0x80000000
FILE_SHARE_READ = 0x00000001
FILE_SHARE_WRITE = 0x00000002
OPEN_EXISTING = 3
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
IOCTL_CDROM_READ_TOC_EX = 0x00024054
CDROM_TOC_SIZE = 804
CDROM_TOC_HEADER_SIZE = 4
CDROM_TOC_TRACK_DATA_SIZE = 8
CDROM_LEADOUT_TRACK = 0xAA


def _bind_winapi() -> None:
    """Bind argtypes/restype on the few Windows APIs we use via ctypes.

    Without this, ctypes assumes int args and int returns, which is unsafe
    for pointer arguments on 64-bit Windows.
    """
    if sys.platform != "win32":
        return
    k32 = ctypes.windll.kernel32
    k32.GetLogicalDrives.argtypes = []
    k32.GetLogicalDrives.restype = ctypes.c_ulong
    k32.GetDriveTypeW.argtypes = [ctypes.c_wchar_p]
    k32.GetDriveTypeW.restype = ctypes.c_uint
    k32.CreateFileW.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
    ]
    k32.CreateFileW.restype = wintypes.HANDLE
    k32.DeviceIoControl.argtypes = [
        wintypes.HANDLE,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_uint32),
        ctypes.c_void_p,
    ]
    k32.DeviceIoControl.restype = wintypes.BOOL
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    k32.CloseHandle.restype = wintypes.BOOL
    winmm = ctypes.windll.winmm
    winmm.mciSendStringW.argtypes = [
        ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint, ctypes.c_void_p,
    ]
    winmm.mciSendStringW.restype = ctypes.c_uint


_bind_winapi()


@dataclass
class DiscToc:
    drive: str                  # e.g. "D:"
    discid: str = ""
    freedb_id: str = ""
    toc_string: str = ""        # "1 LAST FIRST_OFFSET LEAD_OFFSET ..."
    track_count: int = 0
    track_offsets: list[int] = field(default_factory=list)
    sectors: int = 0
    ctdb_toc_string: str = ""   # CUETools layout, including data tracks when available.


@dataclass(frozen=True)
class _CtdbTocEntry:
    track_number: int
    offset: int
    is_audio: bool
    is_leadout: bool = False


def list_cd_drives() -> list[str]:
    """Return a list of optical drive letters with media (best-effort)."""
    if sys.platform != "win32":
        return []
    drives: list[str] = []
    bitmask = ctypes.windll.kernel32.GetLogicalDrives()
    for i, letter in enumerate(string.ascii_uppercase):
        if bitmask & (1 << i):
            root = f"{letter}:\\"
            try:
                kind = ctypes.windll.kernel32.GetDriveTypeW(root)
            except OSError:
                kind = 0
            if kind == DRIVE_CDROM:
                drives.append(f"{letter}:")
    return drives


def has_audio_cd(drive: str) -> bool:
    """True if the disc in `drive` looks like an audio CD."""
    if sys.platform != "win32":
        return False
    # Audio CDs typically expose .cda virtual files at the drive root.
    try:
        for entry in os.listdir(f"{drive}\\"):
            if entry.lower().endswith(".cda"):
                return True
    except OSError:
        return False
    return False


def read_disc(drive: str | None = None) -> DiscToc | None:
    """Read TOC + MusicBrainz disc ID for a drive."""
    if sys.platform != "win32":
        return None
    if drive is None:
        drives = list_cd_drives()
        if not drives:
            return None
        drive = drives[0]

    # Make bundled libdiscid.dll discoverable before importing.
    bin_dir = bundled_bin_dir()
    if bin_dir.exists():
        os.environ["PATH"] = str(bin_dir) + os.pathsep + os.environ.get("PATH", "")
        try:
            os.add_dll_directory(str(bin_dir))  # type: ignore[attr-defined]
        except (AttributeError, OSError):
            pass

    discid = _load_discid()
    if discid is None:
        return None

    device = drive.rstrip("\\:") + ":"
    try:
        d = discid.read(device, features=["mcn", "isrc"])
    except discid.DiscError:
        return None

    return DiscToc(
        drive=drive,
        discid=d.id,
        freedb_id=getattr(d, "freedb_id", "") or "",
        toc_string=d.toc_string,
        track_count=len(d.tracks),
        track_offsets=[t.offset for t in d.tracks],
        sectors=getattr(d, "sectors", 0) or 0,
        ctdb_toc_string=_read_windows_ctdb_toc(drive),
    )


def _load_discid():
    if importlib.util.find_spec("discid") is None:
        return None
    try:
        return importlib.import_module("discid")
    except OSError:
        return None


def _read_windows_ctdb_toc(drive: str) -> str:
    """Read the full Windows TOC and return a CUETools/CTDB layout string."""
    if sys.platform != "win32":
        return ""
    drive_letter = drive.rstrip("\\:")[:1]
    if not drive_letter:
        return ""

    device_path = f"\\\\.\\{drive_letter}:"
    k32 = ctypes.windll.kernel32
    handle = k32.CreateFileW(
        device_path,
        GENERIC_READ,
        FILE_SHARE_READ | FILE_SHARE_WRITE,
        None,
        OPEN_EXISTING,
        0,
        None,
    )
    if handle == INVALID_HANDLE_VALUE:
        return ""

    try:
        request = (ctypes.c_ubyte * 4)()
        buffer = ctypes.create_string_buffer(CDROM_TOC_SIZE)
        bytes_returned = ctypes.c_uint32(0)
        ok = k32.DeviceIoControl(
            handle,
            IOCTL_CDROM_READ_TOC_EX,
            ctypes.byref(request),
            ctypes.sizeof(request),
            buffer,
            ctypes.sizeof(buffer),
            ctypes.byref(bytes_returned),
            None,
        )
        if not ok:
            return ""
        used = bytes_returned.value or ctypes.sizeof(buffer)
        entries = _ctdb_entries_from_windows_toc(bytes(buffer.raw[:used]))
        return _ctdb_toc_from_track_data(entries)
    except OSError:
        return ""
    finally:
        k32.CloseHandle(handle)


def _ctdb_entries_from_windows_toc(raw: bytes) -> list[_CtdbTocEntry]:
    if len(raw) < CDROM_TOC_HEADER_SIZE:
        return []

    toc_length = int.from_bytes(raw[:2], "big", signed=False)
    track_data_length = min(len(raw) - CDROM_TOC_HEADER_SIZE, max(0, toc_length - 2))
    track_count = min(100, track_data_length // CDROM_TOC_TRACK_DATA_SIZE)
    entries: list[_CtdbTocEntry] = []
    for index in range(track_count):
        start = CDROM_TOC_HEADER_SIZE + (index * CDROM_TOC_TRACK_DATA_SIZE)
        end = start + CDROM_TOC_TRACK_DATA_SIZE
        data = raw[start:end]
        if len(data) < CDROM_TOC_TRACK_DATA_SIZE:
            break

        control_adr = data[1]
        track_number = data[2]
        offset = int.from_bytes(data[4:8], "big", signed=True)
        if offset < 0:
            continue

        control_bits = (control_adr & 0x0F) | (control_adr >> 4)
        is_audio = (control_bits & 0x04) == 0
        is_leadout = track_number == CDROM_LEADOUT_TRACK
        entries.append(
            _CtdbTocEntry(
                track_number=track_number,
                offset=offset,
                is_audio=is_audio,
                is_leadout=is_leadout,
            )
        )
    return entries


def _ctdb_toc_from_track_data(entries: list[_CtdbTocEntry]) -> str:
    tracks = [entry for entry in entries if not entry.is_leadout]
    leadouts = [entry for entry in entries if entry.is_leadout]
    if not tracks or not leadouts:
        return ""

    tokens = []
    for entry in sorted(tracks, key=lambda item: item.track_number):
        if entry.offset < 0:
            return ""
        prefix = "" if entry.is_audio else "-"
        tokens.append(f"{prefix}{entry.offset}")

    leadout = max(leadouts, key=lambda item: item.offset)
    if leadout.offset < 0:
        return ""
    tokens.append(str(leadout.offset))
    return ":".join(tokens)


def eject(drive: str) -> None:
    if sys.platform != "win32":
        return
    mci = ctypes.windll.winmm.mciSendStringW
    drive_letter = drive.rstrip(":")
    # Close any leftover alias from an earlier interrupted call, then reopen.
    mci("close lyon_cd", None, 0, None)
    if mci(f'open {drive_letter}: type cdaudio alias lyon_cd', None, 0, None) == 0:
        mci("set lyon_cd door open", None, 0, None)
        mci("close lyon_cd", None, 0, None)

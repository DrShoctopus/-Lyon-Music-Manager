"""Optical drive detection and disc ID computation.

Windows-only paths are guarded so the module can be imported on any platform
during development. At runtime on Windows we use ctypes to enumerate drives,
read a CUETools-compatible TOC layout, and call libdiscid when available.
On macOS, drive enumeration delegates to disc_macos and libdiscid is preloaded
from the bundle's Contents/Frameworks before the discid package is imported.
"""
from __future__ import annotations

import ctypes
import ctypes.util
from ctypes import wintypes
import importlib
import importlib.util
import logging
import os
import string
import sys
from dataclasses import dataclass, field
from typing import Any

from .settings import bundled_bin_dir, bundled_frameworks_dir

LOG = logging.getLogger(__name__)

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
MAX_CD_TRACKS = 100  # CD-DA spec: up to 99 audio tracks + leadout


def _preload_libdiscid_darwin() -> None:
    """Pre-load bundled libdiscid.0.dylib on macOS so the discid package finds it."""
    if sys.platform != "darwin":
        return
    fw = bundled_frameworks_dir()
    if fw is None:
        return
    candidate = fw / "libdiscid.0.dylib"
    if candidate.exists():
        try:
            ctypes.CDLL(str(candidate), mode=ctypes.RTLD_GLOBAL)
        except OSError as exc:
            LOG.warning("Could not preload bundled libdiscid: %s", exc)


_preload_libdiscid_darwin()


def _bind_winapi() -> None:
    """Bind argtypes/restype on the few Windows APIs we use via ctypes."""
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

# Guard against repeated PATH mutation across successive read_disc calls.
_bin_dir_on_path = False
_DLL_DIRECTORY_HANDLES: list[Any] = []


@dataclass
class DiscToc:
    drive: str                  # e.g. "D:"
    discid: str = ""
    freedb_id: str = ""
    toc_string: str = ""        # MusicBrainz TOC string.
    track_count: int = 0
    track_offsets: list[int] = field(default_factory=list)
    sectors: int = 0
    ctdb_toc_string: str = ""   # CUETools layout, including data tracks when available.
    first_track: int = 1
    last_track: int = 0
    mcn: str | None = None


@dataclass(frozen=True)
class _CtdbTocEntry:
    track_number: int
    offset: int
    is_audio: bool
    is_leadout: bool = False


def list_cd_drives() -> list[str]:
    """Return a list of optical drive paths with media (best-effort)."""
    if sys.platform == "darwin":
        from . import disc_macos
        return [d.device_path for d in disc_macos.list_optical_drives()]
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
    if sys.platform == "darwin":
        from . import disc_macos
        from .disc_macos import MacOpticalDrive
        # drive is a device path like "/dev/disk4"
        name = drive.removeprefix("/dev/")
        fake = MacOpticalDrive(
            bsd_name=name,
            device_path=drive,
            raw_path=f"/dev/r{name}",
            vendor="",
            product="",
            is_ejectable=True,
        )
        return disc_macos.has_audio_disc(fake)
    if sys.platform != "win32":
        return False
    try:
        for entry in os.listdir(f"{drive}\\"):
            if entry.lower().endswith(".cda"):
                return True
    except OSError:
        return False
    return False


def _ensure_bin_dir_on_path() -> None:
    """Prepend the bundled bin dir to PATH once per process lifetime."""
    global _bin_dir_on_path
    if _bin_dir_on_path:
        return
    bin_dir = bundled_bin_dir()
    if bin_dir.exists():
        path_str = str(bin_dir)
        current = os.environ.get("PATH", "")
        if path_str not in current.split(os.pathsep):
            os.environ["PATH"] = path_str + (os.pathsep + current if current else "")
        add_dll_directory = getattr(os, "add_dll_directory", None)
        if add_dll_directory is not None:
            try:
                _DLL_DIRECTORY_HANDLES.append(add_dll_directory(path_str))
            except OSError as exc:
                LOG.debug("Could not add libdiscid DLL directory %s: %s", bin_dir, exc)
    _bin_dir_on_path = True


def close_dll_handles() -> None:
    """Release Windows DLL directory handles acquired for bundled libdiscid."""
    for handle in _DLL_DIRECTORY_HANDLES:
        try:
            handle.close()
        except Exception as exc:
            LOG.debug("Could not close libdiscid DLL directory handle: %s", exc)
    _DLL_DIRECTORY_HANDLES.clear()


def read_disc(drive: str | None = None) -> DiscToc | None:
    """Read the best available CD TOC identity for a drive."""
    if sys.platform == "darwin":
        return _read_disc_darwin(drive)
    if sys.platform != "win32":
        return None
    if drive is None:
        drives = list_cd_drives()
        if not drives:
            return None
        drive = drives[0]

    ctdb_entries = _read_windows_ctdb_entries(drive)
    ctdb_toc = _ctdb_toc_from_track_data(ctdb_entries)
    ctdb_fallback = _disc_toc_from_ctdb_entries(drive, ctdb_entries)

    _ensure_bin_dir_on_path()

    discid = _load_discid()
    if discid is None:
        return ctdb_fallback

    device = drive[:2]  # keep exactly "X:" — no trailing slashes
    try:
        d = discid.read(device, features=["mcn", "isrc"])
    except discid.DiscError:
        return ctdb_fallback
    except Exception:
        return ctdb_fallback

    tracks = list(getattr(d, "tracks", []) or [])
    return DiscToc(
        drive=drive,
        discid=getattr(d, "id", "") or "",
        freedb_id=getattr(d, "freedb_id", "") or "",
        toc_string=getattr(d, "toc_string", "") or "",
        track_count=len(tracks),
        track_offsets=[int(getattr(track, "offset", 0) or 0) for track in tracks],
        sectors=int(getattr(d, "sectors", 0) or 0),
        ctdb_toc_string=ctdb_toc,
        first_track=int(getattr(d, "first_track_num", 1) or 1),
        last_track=int(getattr(d, "last_track_num", len(tracks)) or len(tracks)),
        mcn=getattr(d, "mcn", None),
    )


def _read_disc_darwin(drive: str | None) -> DiscToc | None:
    """Read disc TOC on macOS using libdiscid (pre-loaded from bundle)."""
    if drive is None:
        drives = list_cd_drives()
        if not drives:
            return None
        drive = drives[0]

    discid = _load_discid()
    if discid is None:
        return None

    # libdiscid on macOS accepts "/dev/diskN" directly
    device = drive if drive.startswith("/dev/") else f"/dev/{drive}"
    try:
        d = discid.read(device, features=["mcn", "isrc"])
    except Exception:
        return None

    tracks = list(getattr(d, "tracks", []) or [])
    return DiscToc(
        drive=drive,
        discid=getattr(d, "id", "") or "",
        freedb_id=getattr(d, "freedb_id", "") or "",
        toc_string=getattr(d, "toc_string", "") or "",
        track_count=len(tracks),
        track_offsets=[int(getattr(track, "offset", 0) or 0) for track in tracks],
        sectors=int(getattr(d, "sectors", 0) or 0),
        ctdb_toc_string="",
        first_track=int(getattr(d, "first_track_num", 1) or 1),
        last_track=int(getattr(d, "last_track_num", len(tracks)) or len(tracks)),
        mcn=getattr(d, "mcn", None),
    )


def _load_discid():
    if importlib.util.find_spec("discid") is None:
        return None
    try:
        if sys.platform == "darwin" and getattr(sys, "frozen", False):
            bundle_dylib = None
            fw = bundled_frameworks_dir()
            if fw is not None:
                for name in ("libdiscid.0.dylib", "libdiscid.dylib"):
                    candidate = fw / name
                    if candidate.exists():
                        bundle_dylib = candidate
                        break
            original_find_library = ctypes.util.find_library

            def _find_library(name: str):
                if bundle_dylib is not None and name == "discid":
                    return str(bundle_dylib)
                return original_find_library(name)

            try:
                ctypes.util.find_library = _find_library
                return importlib.import_module("discid")
            finally:
                ctypes.util.find_library = original_find_library
        return importlib.import_module("discid")
    except Exception:
        return None


def _read_windows_ctdb_entries(drive: str) -> list[_CtdbTocEntry]:
    if sys.platform != "win32":
        return []
    if not drive:
        return []

    if drive.startswith("\\\\.\\"):
        device_path = drive.rstrip("\\/")
    else:
        drive_letter = drive[:1]  # take the first character only to avoid rstrip surprises
        if not drive_letter or not drive_letter.isalpha():
            return []
        device_path = f"\\\\.\\{drive_letter.upper()}:"

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
        return []

    try:
        return _windows_toc_entries_from_handle(k32, handle)
    except OSError:
        return []
    finally:
        k32.CloseHandle(handle)


def _windows_toc_entries_from_handle(k32, handle) -> list[_CtdbTocEntry]:
    class CDROM_READ_TOC_EX(ctypes.Structure):
        _fields_ = [
            ("Format", ctypes.c_ubyte, 4),
            ("Reserved1", ctypes.c_ubyte, 3),
            ("Msf", ctypes.c_ubyte, 1),
            ("SessionTrack", ctypes.c_ubyte),
            ("Reserved2", ctypes.c_ubyte),
            ("Reserved3", ctypes.c_ubyte),
        ]

    request = CDROM_READ_TOC_EX()
    request.Format = 0  # CDROM_READ_TOC_EX_FORMAT_TOC
    request.Msf = 0  # LBA addressing, which matches CTDB's offset layout.
    request.SessionTrack = 1
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
        return []
    used = bytes_returned.value or ctypes.sizeof(buffer)
    return _ctdb_entries_from_windows_toc(bytes(buffer.raw[:used]))


def _ctdb_entries_from_windows_toc(raw: bytes) -> list[_CtdbTocEntry]:
    if len(raw) < CDROM_TOC_HEADER_SIZE:
        return []

    toc_length = int.from_bytes(raw[:2], "big", signed=False)
    track_data_length = min(len(raw) - CDROM_TOC_HEADER_SIZE, max(0, toc_length - 2))
    track_count = min(MAX_CD_TRACKS, track_data_length // CDROM_TOC_TRACK_DATA_SIZE)
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
        is_leadout = track_number == CDROM_LEADOUT_TRACK
        if not is_leadout and track_number == 0:
            continue
        if offset < 0:
            continue

        # Windows TRACK_DATA exposes Control in the low nibble; accept either
        # nibble so raw MMC-order bytes are handled defensively too.
        control = (control_adr & 0x0F) | (control_adr >> 4)
        is_audio = (control & 0x04) == 0
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
        prefix = "" if entry.is_audio else "-"
        tokens.append(f"{prefix}{entry.offset}")

    leadout = max(leadouts, key=lambda item: item.offset)
    tokens.append(str(leadout.offset))
    return ":".join(tokens)


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

    return DiscToc(
        drive=drive,
        track_count=len(audio_tracks),
        track_offsets=[entry.offset for entry in audio_tracks],
        sectors=max(leadouts),
        ctdb_toc_string=ctdb_toc,
        first_track=audio_tracks[0].track_number,
        last_track=audio_tracks[-1].track_number,
    )


def eject(drive: str) -> None:
    if sys.platform == "darwin":
        from . import disc_macos
        from .disc_macos import MacOpticalDrive
        name = drive.removeprefix("/dev/")
        fake = MacOpticalDrive(
            bsd_name=name, device_path=drive,
            raw_path=f"/dev/r{name}", vendor="", product="", is_ejectable=True,
        )
        disc_macos.eject_drive(fake)
        return
    if sys.platform != "win32":
        return
    # Validate that drive is a single letter to prevent MCI command injection.
    drive_letter = drive.strip()[:1].upper()
    if not drive_letter or not drive_letter.isalpha():
        return
    mci = ctypes.windll.winmm.mciSendStringW
    mci("close lyon_cd", None, 0, None)
    if mci(f'open {drive_letter}: type cdaudio alias lyon_cd', None, 0, None) == 0:
        mci("set lyon_cd door open", None, 0, None)
        mci("close lyon_cd", None, 0, None)

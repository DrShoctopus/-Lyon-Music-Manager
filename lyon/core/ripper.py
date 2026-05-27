"""CD audio ripping using bundled ffmpeg.

FFmpeg's libcdio input exposes an audio CD as one audio stream with chapter
metadata, not as one stream per CD track. We use the libdiscid TOC offsets read
by ``cd_detect`` to seek and trim that one stream for each output file.

Most Windows ffmpeg builds do not include the libcdio input device. When that
happens we read CD-DA sectors directly from Windows and pipe the raw stereo PCM
into ffmpeg for encoding.
"""
from __future__ import annotations

import ctypes
import datetime as _dt
import platform
import re
import shlex
import subprocess
import sys
import threading
import time
from ctypes import wintypes
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Sequence

from PySide6.QtCore import QObject, QThread, Signal

from .ffmpeg import find_ffmpeg_binary
from .metadata import AlbumInfo, TrackInfo, fetch_artwork
from .settings import Settings


SAFE_CHARS_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
# Windows refuses to create files whose basename (with or without extension)
# matches one of these reserved device names, even on NTFS via Win32.
_WINDOWS_RESERVED_NAMES = frozenset({
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
})
CD_SECTORS_PER_SECOND = 75
CDDA_SECTOR_SIZE = 2352
CDDA_COOKED_SECTOR_SIZE = 2048
CDDA_SAMPLE_RATE = 44100
CDDA_CHANNELS = 2
WINDOWS_CDDA_INITIAL_READ_CHUNK_SECTORS = CD_SECTORS_PER_SECOND
WINDOWS_CDDA_FALLBACK_READ_CHUNK_SECTORS = 16
WINDOWS_CDDA_READ_CHUNK_SECTORS = WINDOWS_CDDA_INITIAL_READ_CHUNK_SECTORS
IOCTL_CDROM_RAW_READ = 0x0002403E
TRACK_MODE_CDDA = 2
FFMPEG_ERROR_LINES = 8
FAILURE_LOG_OUTPUT_LINES = 40
MAX_UNKNOWN_ALBUM_VARIANTS = 1000  # upper bound on de-duplicated "Unknown Album" folders
MAX_CAPTURED_STDOUT_BYTES = 64 * 1024  # cap in-memory ffmpeg output to 64 KB

# Maps rip_format setting value → (file extension, ffmpeg codec, kind)
# kind: "lossless_compressed" | "lossless" | "lossy"
_FORMAT_INFO: dict[str, tuple[str, str, str]] = {
    "flac": (".flac", "flac",        "lossless_compressed"),
    "mp3":  (".mp3",  "libmp3lame",  "lossy"),
    "aac":  (".m4a",  "aac",         "lossy"),
    "opus": (".opus", "libopus",     "lossy"),
    "ogg":  (".ogg",  "libvorbis",   "lossy"),
    "alac": (".m4a",  "alac",        "lossless"),
    "wav":  (".wav",  "pcm_s16le",   "lossless"),
    "aiff": (".aiff", "pcm_s16be",   "lossless"),
    "wma":  (".wma",  "wmav2",       "lossy"),
}

# Suppress the console window ffmpeg would otherwise pop up per track on Windows.
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


class _RawReadInfo(ctypes.Structure):
    _fields_ = [
        ("DiskOffset", ctypes.c_longlong),
        ("SectorCount", wintypes.ULONG),
        ("TrackMode", wintypes.ULONG),
    ]


class _WindowsCddaReadError(OSError):
    """Raised when Windows cannot return raw CD-DA sectors."""


def format_extension(fmt: str) -> str:
    return _FORMAT_INFO.get(fmt.lower(), _FORMAT_INFO["flac"])[0]


def _codec_args(settings: Settings) -> list[str]:
    """Return the ffmpeg codec + options args for the configured rip format."""
    fmt = (settings.rip_format or "flac").lower()
    _ext, codec, kind = _FORMAT_INFO.get(fmt, _FORMAT_INFO["flac"])
    args = ["-c:a", codec]
    if kind == "lossless_compressed":
        try:
            level = max(0, min(8, int(settings.flac_compression)))
        except (TypeError, ValueError):
            level = 4
        args += ["-compression_level", str(level)]
    elif kind == "lossy":
        try:
            br = max(32, min(1411, int(settings.rip_audio_bitrate)))
        except (TypeError, ValueError):
            br = 320
        args += ["-b:a", f"{br}k"]
    return args


def safe_path_component(name: str) -> str:
    # Trailing dots and spaces are silently stripped by Win32 path APIs and
    # would make "Foo." and "Foo" collide; strip them first so the result is
    # stable across rips of the same album.
    name = name.strip().rstrip(" .")
    name = SAFE_CHARS_RE.sub("_", name)
    if not name or name in {".", ".."}:
        return "Unknown"
    stem, dot, ext = name.partition(".")
    if stem in {".", ".."}:
        return "Unknown"
    if stem.upper() in _WINDOWS_RESERVED_NAMES:
        name = f"{stem}_{dot}{ext}" if dot else f"{stem}_"
    return name


def find_ffmpeg() -> Optional[str]:
    binary = find_ffmpeg_binary()
    return str(binary) if binary is not None else None


def _stop_process(proc, *, timeout: float = 2.0) -> None:
    """Terminate a subprocess, escalating to kill if it does not exit promptly."""
    if proc.poll() is not None:
        return
    try:
        proc.terminate()
    except OSError:
        pass
    try:
        proc.wait(timeout=timeout)
        return
    except (OSError, subprocess.TimeoutExpired):
        pass
    if proc.poll() is None:
        try:
            proc.kill()
        except OSError:
            pass
        try:
            proc.wait(timeout=timeout)
        except (OSError, subprocess.TimeoutExpired):
            pass


def target_folder(settings: Settings, album: AlbumInfo, create: bool = False) -> Path:
    """Compute the destination folder for an album rip.

    Pure path arithmetic by default -- pass ``create=True`` only when you
    actually intend to rip. The UI calls this on every keystroke to
    preview the path, which is why we never mkdir on the preview path.
    """
    folder = _album_folder_base(settings, album)
    if create:
        folder.mkdir(parents=True, exist_ok=True)
    return folder


def unique_target_folder(settings: Settings, album: AlbumInfo, create: bool = False) -> Path:
    """Return a safe rip folder, suffixing repeated unknown albums.

    Known albums keep their stable destination so the existing overwrite
    confirmation can protect deliberate re-rips. Unknown albums do not have a
    reliable identity, so a second unknown disc should land in a new folder
    instead of overwriting the first unknown rip.
    """
    base = target_folder(settings, album)
    folder = base
    if _album_needs_unique_unknown_folder(album):
        folder = _first_available_unknown_album_folder(base)
    if create:
        folder.mkdir(parents=True, exist_ok=True)
    return folder


def _album_folder_base(settings: Settings, album: AlbumInfo) -> Path:
    artist = safe_path_component(album.artist or "Unknown Artist")
    name = safe_path_component(album.album or "Unknown Album")
    if album.year:
        name = f"{album.year} - {name}"
    return _assert_under_music_root(Path(settings.music_root) / artist / name, settings)


def _assert_under_music_root(path: Path, settings: Settings) -> Path:
    root = Path(settings.music_root).expanduser().resolve(strict=False)
    resolved = path.expanduser().resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError("Rip destination must stay inside the music folder.") from exc
    return path


def _album_needs_unique_unknown_folder(album: AlbumInfo) -> bool:
    return safe_path_component(album.album or "Unknown Album") == "Unknown Album"


def _first_available_unknown_album_folder(base: Path) -> Path:
    if not _unknown_album_folder_has_rip_content(base):
        return base

    for number in range(2, MAX_UNKNOWN_ALBUM_VARIANTS + 1):
        candidate = base.with_name(f"{base.name} ({number})")
        if not _unknown_album_folder_has_rip_content(candidate):
            return candidate
    raise RuntimeError(f"Could not find an available unknown album folder under {base.parent}")


def _unknown_album_folder_has_rip_content(folder: Path) -> bool:
    if not folder.exists():
        return False
    if not folder.is_dir():
        return True
    try:
        return any(child.is_file() for child in folder.iterdir())
    except OSError:
        return True


def target_file(folder: Path, track: TrackInfo, total: int, ext: str = ".flac") -> Path:
    width = max(2, len(str(total)))
    base = f"{track.number:0{width}d} - {safe_path_component(track.title)}{ext}"
    return folder / base


def _sector_seconds(sectors: int) -> str:
    text = f"{sectors / CD_SECTORS_PER_SECOND:.6f}".rstrip("0").rstrip(".")
    return text or "0"


def _track_sector_span(
    track_no: int,
    track_offsets: Sequence[int],
    leadout_sector: int,
) -> Optional[tuple[int, int]]:
    """Return a track's start/end sector relative to the first audio track."""
    if track_no < 1 or track_no > len(track_offsets) or leadout_sector <= 0:
        return None

    try:
        offsets = [int(offset) for offset in track_offsets]
        leadout = int(leadout_sector)
    except (TypeError, ValueError):
        return None

    first_offset = offsets[0]
    start = offsets[track_no - 1] - first_offset
    end_absolute = offsets[track_no] if track_no < len(offsets) else leadout
    end = end_absolute - first_offset

    if start < 0 or end <= start:
        return None
    return start, end


def _build_libcdio_track_command(
    ffmpeg: str,
    drive: str,
    out: Path,
    codec_args: list[str],
    sector_span: tuple[int, int],
    *,
    input_seek: bool,
) -> list[str]:
    start, end = sector_span
    duration = end - start
    seek = _sector_seconds(start)
    length = _sector_seconds(duration)
    # Use info level so ffmpeg's -stats output (printed at info level) reaches
    # the progress parser. -hide_banner suppresses the version/build preamble.
    cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "info", "-stats"]
    if input_seek:
        cmd += ["-f", "libcdio", "-ss", seek, "-i", drive]
    else:
        cmd += ["-f", "libcdio", "-i", drive, "-ss", seek]
    cmd += ["-t", length, "-map", "0:a:0", "-vn"] + codec_args + [str(out)]
    return cmd


def _build_raw_cdda_ffmpeg_command(
    ffmpeg: str,
    out: Path,
    codec_args: list[str],
) -> list[str]:
    return [
        ffmpeg,
        "-y",
        "-hide_banner",
        "-loglevel", "error",
        "-nostats",
        "-f", "s16le",
        "-ar", str(CDDA_SAMPLE_RATE),
        "-ac", str(CDDA_CHANNELS),
        "-i", "pipe:0",
        "-vn",
    ] + codec_args + [str(out)]


def _ffmpeg_format_listing_has_demuxer(format_listing: str, name: str) -> bool:
    for line in format_listing.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("---") or stripped.startswith("D.."):
            continue
        parts = stripped.split()
        if len(parts) < 2 or "D" not in parts[0]:
            continue
        format_name_index = 2 if len(parts) > 2 and parts[1] == "d" else 1
        format_names = parts[format_name_index].split(",")
        if name in format_names:
            return True
    return False


def _ffmpeg_supports_demuxer(ffmpeg: str, name: str) -> bool:
    try:
        proc = subprocess.run(
            [ffmpeg, "-hide_banner", "-formats"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            creationflags=_NO_WINDOW,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return proc.returncode == 0 and _ffmpeg_format_listing_has_demuxer(proc.stdout, name)


def _windows_cdda_drive_path(drive: str) -> str:
    drive = drive.strip().rstrip("\\/")
    if drive.startswith("\\\\.\\"):
        return drive
    if len(drive) == 1:
        drive = f"{drive}:"
    if len(drive) == 2 and drive[1] == ":":
        return f"\\\\.\\{drive.upper()}"
    return drive


def _decode_process_output(data: bytes) -> list[str]:
    text = data.decode(errors="replace")
    return [line.strip() for line in text.splitlines() if line.strip()]


def _ctypes_last_error() -> int:
    get_last_error = getattr(ctypes, "get_last_error", None)
    return int(get_last_error()) if get_last_error is not None else 0


def _bind_raw_read_kernel32(kernel32) -> None:
    kernel32.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.DeviceIoControl.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        wintypes.LPVOID,
    ]
    kernel32.DeviceIoControl.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL


class _WindowsCddaReader:
    """Reusable raw CD-DA sector reader for Windows optical drives."""

    def __init__(
        self,
        drive: str,
        *,
        chunk_sectors: int = WINDOWS_CDDA_INITIAL_READ_CHUNK_SECTORS,
        fallback_chunk_sectors: int = WINDOWS_CDDA_FALLBACK_READ_CHUNK_SECTORS,
        kernel32=None,
    ):
        self.drive = drive
        self.drive_path = _windows_cdda_drive_path(drive)
        self.chunk_sectors = max(1, int(chunk_sectors))
        self.fallback_chunk_sectors = max(1, int(fallback_chunk_sectors))
        self._kernel32 = kernel32
        self._handle = None
        self._using_fallback_chunk = False

    @property
    def active_chunk_sectors(self) -> int:
        if self._using_fallback_chunk:
            return self.fallback_chunk_sectors
        return self.chunk_sectors

    @property
    def using_fallback_chunk(self) -> bool:
        return self._using_fallback_chunk

    def __enter__(self) -> "_WindowsCddaReader":
        if sys.platform != "win32":
            raise _WindowsCddaReadError("raw CD reads are only available on Windows")
        if self._kernel32 is None:
            self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            _bind_raw_read_kernel32(self._kernel32)

        generic_read = 0x80000000
        file_share_read = 0x00000001
        file_share_write = 0x00000002
        open_existing = 3
        invalid_handle = wintypes.HANDLE(-1).value

        handle = self._kernel32.CreateFileW(
            self.drive_path,
            generic_read,
            file_share_read | file_share_write,
            None,
            open_existing,
            0,
            None,
        )
        if handle == invalid_handle:
            err = _ctypes_last_error()
            raise _WindowsCddaReadError(
                f"could not open {self.drive_path}: Windows error {err}"
            )
        self._handle = handle
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        if self._handle is None or self._kernel32 is None:
            return
        try:
            self._kernel32.CloseHandle(self._handle)
        finally:
            self._handle = None

    def read_sectors(self, start_sector: int, sector_count: int):
        if self._handle is None:
            raise _WindowsCddaReadError("raw CD reader is not open")
        remaining = int(sector_count)
        next_sector = int(start_sector)
        while remaining > 0:
            count = min(self.active_chunk_sectors, remaining)
            chunk = self._read_chunk(next_sector, count)
            yield chunk
            sectors_read = len(chunk) // CDDA_SECTOR_SIZE
            next_sector += sectors_read
            remaining -= sectors_read

    def _read_chunk(self, start_sector: int, sector_count: int) -> bytes:
        try:
            return self._read_chunk_once(start_sector, sector_count)
        except _WindowsCddaReadError:
            if (
                self._using_fallback_chunk
                or sector_count <= self.fallback_chunk_sectors
            ):
                raise
            self._using_fallback_chunk = True
            return self._read_chunk_once(
                start_sector,
                min(self.fallback_chunk_sectors, sector_count),
            )

    def _read_chunk_once(self, start_sector: int, sector_count: int) -> bytes:
        assert self._kernel32 is not None
        buffer = ctypes.create_string_buffer(sector_count * CDDA_SECTOR_SIZE)
        info = _RawReadInfo(
            start_sector * CDDA_COOKED_SECTOR_SIZE,
            sector_count,
            TRACK_MODE_CDDA,
        )
        bytes_returned = wintypes.DWORD(0)
        ok = self._kernel32.DeviceIoControl(
            self._handle,
            IOCTL_CDROM_RAW_READ,
            ctypes.byref(info),
            ctypes.sizeof(info),
            buffer,
            ctypes.sizeof(buffer),
            ctypes.byref(bytes_returned),
            None,
        )
        if not ok:
            err = _ctypes_last_error()
            raise _WindowsCddaReadError(
                f"could not read CD audio sector {start_sector}: Windows error {err}"
            )
        expected = sector_count * CDDA_SECTOR_SIZE
        if bytes_returned.value != expected:
            raise _WindowsCddaReadError(
                f"read {bytes_returned.value} bytes from sector {start_sector}; expected {expected}"
            )
        return buffer.raw[:bytes_returned.value]


def _read_windows_cdda_sectors(
    drive: str,
    start_sector: int,
    sector_count: int,
    *,
    chunk_sectors: int = WINDOWS_CDDA_READ_CHUNK_SECTORS,
):
    if sector_count <= 0:
        return
    with _WindowsCddaReader(drive, chunk_sectors=chunk_sectors) as reader:
        yield from reader.read_sectors(start_sector, sector_count)


# ---------------------------------------------------------------- worker
@dataclass
class RipRequest:
    drive: str
    album: AlbumInfo
    target_dir: Path
    track_offsets: tuple[int, ...] = ()
    leadout_sector: int = 0
    ctdb_toc: str = ""
    track_numbers: tuple[int, ...] = ()
    disc_id: str = ""


@dataclass
class FfmpegAttemptFailure:
    command: list[str]
    returncode: Optional[int]
    reason: str
    output: list[str] = field(default_factory=list)


@dataclass
class RipFailure:
    track_no: Optional[int]
    title: str
    output_path: Optional[Path]
    reason: str
    attempts: list[FfmpegAttemptFailure] = field(default_factory=list)


def _quote_command(cmd: Sequence[str]) -> str:
    if sys.platform == "win32":
        return subprocess.list2cmdline([str(part) for part in cmd])
    return shlex.join(str(part) for part in cmd)


def _summarize_ffmpeg_failure(output: Sequence[str], returncode: Optional[int]) -> str:
    combined = "\n".join(output).lower()
    has_libcdio_format_error = (
        "unknown input format" in combined or "no input format" in combined
    ) and "libcdio" in combined
    if has_libcdio_format_error:
        return (
            "ffmpeg does not recognize the libcdio CD input format. "
            "Lyon will use the Windows raw CD reader when available; otherwise "
            "bundle an ffmpeg build compiled with libcdio/CDDA support."
        )
    if "no such file or directory" in combined:
        return "ffmpeg could not open the CD drive or output path."
    if "permission denied" in combined:
        return "ffmpeg was denied access to the CD drive or output path."
    if "invalid argument" in combined and "libcdio" in combined:
        return "ffmpeg rejected the libcdio input arguments for this drive."
    if output:
        return f"ffmpeg exited with code {returncode}; see captured output below."
    return f"ffmpeg exited with code {returncode} without producing diagnostic output."


def _write_failure_log(
    folder: Path,
    request: RipRequest,
    ffmpeg: Optional[str],
    failures: Sequence[RipFailure],
    *,
    message: str,
) -> Optional[Path]:
    if not failures:
        return None

    timestamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%d-%H%M%SZ")
    path = folder / f"rip-failed-{timestamp}.log"
    album = request.album
    lines = [
        "Sea Lyon Media Manager rip failure log",
        "Generated (UTC): "
        f"{_dt.datetime.now(_dt.timezone.utc).isoformat(timespec='seconds')}",
        f"Summary: {message}",
        "",
        "Environment",
        f"  Python: {platform.python_version()}",
        f"  Platform: {platform.platform()}",
        f"  ffmpeg: {ffmpeg or 'not found'}",
        "",
        "Album",
        f"  Artist: {album.artist or 'Unknown Artist'}",
        f"  Album: {album.album or 'Unknown Album'}",
        f"  Year: {album.year or 'Unknown'}",
        f"  Tracks: {len(album.tracks)}",
        "",
        "Disc",
        f"  Drive: {request.drive}",
        f"  Target folder: {folder}",
        "  Track offsets: "
        f"{', '.join(str(o) for o in request.track_offsets) or 'unavailable'}",
        f"  Leadout sector: {request.leadout_sector or 'unavailable'}",
        "",
        "Failures",
    ]

    for failure in failures:
        label = f"Track {failure.track_no}" if failure.track_no is not None else "Rip setup"
        lines += [
            "",
            f"{label}: {failure.title}",
            f"  Reason: {failure.reason}",
        ]
        if failure.output_path is not None:
            lines.append(f"  Intended output: {failure.output_path}")
        for idx, attempt in enumerate(failure.attempts, start=1):
            lines += [
                f"  Attempt {idx}:",
                f"    Command: {_quote_command(attempt.command)}",
                f"    Return code: {attempt.returncode}",
                f"    Reason: {attempt.reason}",
            ]
            if attempt.output:
                lines.append("    Captured output:")
                for line in attempt.output[-FAILURE_LOG_OUTPUT_LINES:]:
                    lines.append(f"      {line}")
            else:
                lines.append("    Captured output: <none>")

    lines.append("")
    try:
        folder.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines), encoding="utf-8")
        return path
    except OSError:
        return None


class RipWorker(QObject):
    """Background worker. Emits granular progress so UI can drive a WMP-style bar."""

    track_started = Signal(int, str)            # (1-based, title)
    track_progress = Signal(int, int)           # (track_no, percent 0-100)
    track_finished = Signal(int, str)           # (track_no, output_path)
    track_failed = Signal(int, str)             # (track_no, reason)
    finished = Signal(bool, str)                # (success, message)
    log = Signal(str)

    def __init__(self, settings: Settings, request: RipRequest):
        super().__init__()
        self.settings = settings
        self.request = request
        self._track_offsets = tuple(request.track_offsets)
        self._leadout_sector = request.leadout_sector
        self._ffmpeg_has_libcdio: Optional[bool] = None
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        album = self.request.album
        folder = self.request.target_dir
        failures: list[RipFailure] = []

        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            self.finished.emit(False, f"Could not create rip folder: {e}")
            return

        ff = find_ffmpeg()
        if not ff:
            message = "ffmpeg not found. Bundle it in /bin or install on PATH."
            failures.append(RipFailure(None, "Rip setup", None, message))
            self._emit_failure_log(folder, None, failures, message)
            self.finished.emit(False, message)
            return

        if not self._track_offsets or self._leadout_sector <= 0:
            self.log.emit("Reading disc TOC for track timing...")
            from .cd_detect import read_disc
            toc = read_disc(self.request.drive)
            if toc is not None:
                self._track_offsets = tuple(toc.track_offsets)
                self._leadout_sector = toc.sectors
                self.request.track_offsets = self._track_offsets
                self.request.leadout_sector = self._leadout_sector

        # Save artwork once per album
        art_bytes = album.artwork
        if art_bytes is None and self.settings.download_artwork:
            self.log.emit("Fetching cover art...")
            art_bytes = fetch_artwork(album)
        art_path: Optional[Path] = None
        if art_bytes:
            art_path = folder / "cover.jpg"
            try:
                art_path.write_bytes(art_bytes)
            except OSError as e:
                self.log.emit(f"Could not save cover art: {e}")
                art_path = None

        if not self._track_offsets or self._leadout_sector <= 0:
            message = (
                "Could not read disc track timing. Try detecting the disc again, "
                "then restart the rip."
            )
            failures.append(RipFailure(None, "Disc TOC", None, message))
            self._emit_failure_log(folder, ff, failures, message)
            self.finished.emit(False, message)
            return

        self._ffmpeg_has_libcdio = _ffmpeg_supports_demuxer(ff, "libcdio")
        if self._ffmpeg_has_libcdio:
            self.log.emit("Using ffmpeg libcdio for CD audio input.")
        elif sys.platform == "win32":
            self.log.emit(
                "ffmpeg does not include libcdio; using the Windows raw CD reader."
            )
        else:
            message = (
                "ffmpeg does not include libcdio CD input support, and the raw CD "
                "reader fallback is only available on Windows."
            )
            failures.append(RipFailure(None, "Rip setup", None, message))
            self._emit_failure_log(folder, ff, failures, message)
            self.finished.emit(False, message)
            return

        track_filter = set(self.request.track_numbers)
        tracks_to_rip = [
            track for track in album.tracks
            if not track_filter or track.number in track_filter
        ]
        if track_filter and not tracks_to_rip:
            self.finished.emit(False, "No matching tracks were found to rip.")
            return

        total = len(album.tracks) or 1
        ext = format_extension(self.settings.rip_format)
        success = True
        ripped_files: dict[int, Path] = {}
        output_paths = track_output_files(folder, tracks_to_rip, total, ext)
        raw_reader: _WindowsCddaReader | None = None
        logged_raw_fallback = False
        if not self._ffmpeg_has_libcdio and sys.platform == "win32":
            try:
                raw_reader = _WindowsCddaReader(self.request.drive)
                raw_reader.__enter__()
                self.log.emit(
                    "Raw CD reader opened "
                    f"({raw_reader.active_chunk_sectors} sectors per read)."
                )
            except _WindowsCddaReadError as e:
                message = f"Windows raw CD reader failed: {e}"
                failures.append(RipFailure(None, "Rip setup", None, message))
                self._emit_failure_log(folder, ff, failures, message)
                self.finished.emit(False, message)
                return

        try:
            for tr, out in zip(tracks_to_rip, output_paths):
                if self._cancel:
                    self.finished.emit(False, "Cancelled")
                    return

                self.track_started.emit(tr.number, tr.title)
                self.log.emit(f"Ripping track {tr.number}: {tr.title}")
                failure = self._rip_track(
                    ff,
                    tr.number,
                    tr.title,
                    out,
                    raw_reader=raw_reader,
                )
                if (
                    raw_reader is not None
                    and raw_reader.using_fallback_chunk
                    and not logged_raw_fallback
                ):
                    logged_raw_fallback = True
                    self.log.emit(
                        "Raw CD reader fell back to "
                        f"{raw_reader.active_chunk_sectors} sectors per read for compatibility."
                    )
                if failure is not None:
                    success = False
                    failures.append(failure)
                    self.log.emit(f"Track {tr.number} failed: {failure.reason}")
                    self.track_failed.emit(tr.number, failure.reason)
                    continue

                from .tagger import write_tags
                if not write_tags(out, album, tr, art_bytes, disc_id=self.request.disc_id):
                    success = False
                    reason = "Track ripped but audio tags could not be written."
                    failures.append(RipFailure(tr.number, tr.title, out, reason))
                    self.log.emit(f"Track {tr.number} {reason.lower()}")
                    self.track_failed.emit(tr.number, reason)
                    continue
                self.track_finished.emit(tr.number, str(out))
                ripped_files[tr.number] = out
        finally:
            if raw_reader is not None:
                raw_reader.close()

        if (
            self.settings.ctdb_verify_rips
            and ripped_files
            and self.request.ctdb_toc
            and (self.settings.rip_format or "flac").lower() == "flac"
        ):
            self._verify_rips(ff, ripped_files, total)

        message = "Rip complete." if success else "Rip finished with errors."
        if not success:
            self._emit_failure_log(folder, ff, failures, message)
        self.finished.emit(success, message)

    def _verify_rips(
        self,
        ffmpeg: str,
        ripped_files: dict[int, Path],
        total_tracks: int,
    ) -> None:
        from .ctdb_verify import verify_rips
        self.log.emit("Verifying rips against CUETools DB...")
        started_at = time.perf_counter()
        results = verify_rips(
            ripped_files,
            self.request.ctdb_toc,
            ffmpeg,
            total_tracks,
        )
        elapsed = time.perf_counter() - started_at
        self.log.emit(f"CUETools verification finished in {elapsed:.1f}s.")
        for r in results:
            self.log.emit(r.message)

    def _emit_failure_log(
        self,
        folder: Path,
        ffmpeg: Optional[str],
        failures: Sequence[RipFailure],
        message: str,
    ) -> None:
        log_path = _write_failure_log(
            folder,
            self.request,
            ffmpeg,
            failures,
            message=message,
        )
        if log_path is not None:
            self.log.emit(f"Rip failure details saved to: {log_path}")
        else:
            self.log.emit("Could not write rip failure details log.")

    def _rip_track(
        self,
        ffmpeg: str,
        track_no: int,
        title: str,
        out: Path,
        *,
        raw_reader: _WindowsCddaReader | None = None,
    ) -> Optional[RipFailure]:
        drive = self.request.drive
        codec_args = _codec_args(self.settings)
        span = _track_sector_span(track_no, self._track_offsets, self._leadout_sector)
        if span is None:
            reason = "Disc TOC offsets are unavailable or invalid for this track."
            self.log.emit(f"Track {track_no} failed: {reason}")
            return RipFailure(track_no, title, out, reason)

        has_libcdio = self._ffmpeg_has_libcdio
        if has_libcdio is None:
            has_libcdio = _ffmpeg_supports_demuxer(ffmpeg, "libcdio")
            self._ffmpeg_has_libcdio = has_libcdio

        if has_libcdio:
            attempts = [
                _build_libcdio_track_command(ffmpeg, drive, out, codec_args, span, input_seek=True),
                _build_libcdio_track_command(ffmpeg, drive, out, codec_args, span, input_seek=False),
            ]
            failures: list[FfmpegAttemptFailure] = []
            total_seconds = (span[1] - span[0]) / CD_SECTORS_PER_SECOND
            for cmd in attempts:
                attempt_failure = self._run_ffmpeg(cmd, track_no, out, total_seconds)
                if attempt_failure is None:
                    return None
                failures.append(attempt_failure)
            reason = failures[-1].reason if failures else "Track rip failed for an unknown reason."
            return RipFailure(track_no, title, out, reason, failures)

        if sys.platform != "win32":
            reason = (
                "ffmpeg does not include libcdio CD input support, and the raw CD "
                "reader fallback is only available on Windows."
            )
            return RipFailure(track_no, title, out, reason)

        attempt_failure = self._run_windows_cdda_ffmpeg(
            ffmpeg,
            track_no,
            out,
            codec_args,
            span,
            raw_reader=raw_reader,
        )
        if attempt_failure is None:
            return None
        return RipFailure(track_no, title, out, attempt_failure.reason, [attempt_failure])

    def _run_windows_cdda_ffmpeg(
        self,
        ffmpeg: str,
        track_no: int,
        out: Path,
        codec_args: list[str],
        sector_span: tuple[int, int],
        *,
        raw_reader: _WindowsCddaReader | None = None,
    ) -> Optional[FfmpegAttemptFailure]:
        start, end = sector_span
        total_sectors = end - start
        cmd = _build_raw_cdda_ffmpeg_command(ffmpeg, out, codec_args)
        started_at = time.perf_counter()
        try:
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                creationflags=_NO_WINDOW,
            )
        except OSError as e:
            reason = f"ffmpeg launch error: {e}"
            self.log.emit(reason)
            return FfmpegAttemptFailure(cmd, None, reason)

        # Drain ffmpeg's stdout in a background thread to prevent pipe-buffer
        # deadlock on long rips. The buffer is capped to avoid unbounded growth.
        stdout_buffer = bytearray()
        stdout_lock = threading.Lock()

        def _drain_stdout() -> None:
            if proc.stdout is None:
                return
            try:
                for chunk in iter(lambda: proc.stdout.read(4096), b""):
                    with stdout_lock:
                        stdout_buffer.extend(chunk)
                        if len(stdout_buffer) > MAX_CAPTURED_STDOUT_BYTES:
                            del stdout_buffer[:-MAX_CAPTURED_STDOUT_BYTES]
            except OSError:
                pass

        reader = threading.Thread(target=_drain_stdout, name="ffmpeg-stdout-drain", daemon=True)
        reader.start()

        def _collected_output() -> list[str]:
            with stdout_lock:
                data = bytes(stdout_buffer)
            return _decode_process_output(data)[-FFMPEG_ERROR_LINES:]

        def _cleanup_partial() -> None:
            try:
                out.unlink(missing_ok=True)
            except OSError:
                pass

        read_sectors = 0
        try:
            if proc.stdin is None:
                raise OSError("ffmpeg stdin pipe was not created")
            chunks = (
                raw_reader.read_sectors(start, total_sectors)
                if raw_reader is not None
                else _read_windows_cdda_sectors(self.request.drive, start, total_sectors)
            )
            for chunk in chunks:
                if self._cancel:
                    try:
                        proc.stdin.close()
                    except OSError:
                        pass
                    _stop_process(proc)
                    reader.join(timeout=2)
                    _cleanup_partial()
                    return FfmpegAttemptFailure(
                        cmd, proc.returncode, "Cancelled by user.", _collected_output()
                    )
                proc.stdin.write(chunk)
                read_sectors += len(chunk) // CDDA_SECTOR_SIZE
                if total_sectors > 0:
                    pct = max(0, min(99, int(read_sectors * 100 / total_sectors)))
                    self.track_progress.emit(track_no, pct)
            try:
                proc.stdin.close()
            except OSError:
                pass
            proc.wait()
            reader.join(timeout=2)
            output = _collected_output()
        except _WindowsCddaReadError as e:
            reason = f"Windows raw CD reader failed: {e}"
            self.log.emit(reason)
            _stop_process(proc)
            reader.join(timeout=2)
            _cleanup_partial()
            return FfmpegAttemptFailure(cmd, proc.returncode, reason, _collected_output())
        except (BrokenPipeError, OSError) as e:
            _stop_process(proc)
            reader.join(timeout=2)
            output = _collected_output()
            reason = _summarize_ffmpeg_failure(output, proc.returncode)
            if not output:
                reason = f"ffmpeg raw CD audio pipe failed: {e}"
            self.log.emit(reason)
            _cleanup_partial()
            return FfmpegAttemptFailure(cmd, proc.returncode, reason, output)

        if proc.returncode == 0 and out.exists() and out.stat().st_size > 0:
            self.track_progress.emit(track_no, 100)
            elapsed = time.perf_counter() - started_at
            chunk_size = (
                raw_reader.active_chunk_sectors
                if raw_reader is not None
                else WINDOWS_CDDA_READ_CHUNK_SECTORS
            )
            self.log.emit(
                f"Track {track_no} raw read and encode finished in "
                f"{elapsed:.1f}s ({chunk_size}-sector reads)."
            )
            return None

        _cleanup_partial()
        reason = _summarize_ffmpeg_failure(output, proc.returncode)
        if output:
            self.log.emit("ffmpeg: " + " | ".join(output))
        else:
            self.log.emit(f"ffmpeg exited with code {proc.returncode}.")
        return FfmpegAttemptFailure(cmd, proc.returncode, reason, output)

    def _run_ffmpeg(
        self,
        cmd: list[str],
        track_no: int,
        out: Path,
        total_seconds: float,
    ) -> Optional[FfmpegAttemptFailure]:
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                creationflags=_NO_WINDOW,
            )
        except OSError as e:
            reason = f"ffmpeg launch error: {e}"
            self.log.emit(reason)
            return FfmpegAttemptFailure(cmd, None, reason)

        output_chunks: list[str] = []
        output_lock = threading.Lock()
        recent_output: list[str] = []

        def _drain_output() -> None:
            if proc.stdout is None:
                return
            try:
                for chunk in iter(lambda: proc.stdout.read(4096), b""):
                    text = chunk.decode("utf-8", errors="replace")
                    with output_lock:
                        output_chunks.append(text)
            except OSError:
                pass

        def _consume_output() -> None:
            nonlocal recent_output
            with output_lock:
                chunks = list(output_chunks)
                output_chunks.clear()
            for chunk in chunks:
                for part in re.split(r"[\r\n]+", chunk):
                    line = part.strip()
                    if not line:
                        continue
                    recent_output.append(line)
                    recent_output = recent_output[-FFMPEG_ERROR_LINES:]
                    pct = _parse_progress(line, total_seconds)
                    if pct is not None:
                        self.track_progress.emit(track_no, pct)

        def _cleanup_partial() -> None:
            try:
                out.unlink(missing_ok=True)
            except OSError:
                pass

        reader = threading.Thread(target=_drain_output, name="ffmpeg-output-drain", daemon=True)
        reader.start()

        while proc.poll() is None:
            _consume_output()
            if self._cancel:
                _stop_process(proc)
                reader.join(timeout=2)
                _consume_output()
                _cleanup_partial()
                return FfmpegAttemptFailure(
                    cmd, proc.returncode, "Cancelled by user.", recent_output
                )
            try:
                proc.wait(timeout=0.1)
            except subprocess.TimeoutExpired:
                pass

        reader.join(timeout=2)
        _consume_output()

        if proc.returncode == 0 and out.exists() and out.stat().st_size > 0:
            self.track_progress.emit(track_no, 100)
            return None

        _cleanup_partial()

        reason = _summarize_ffmpeg_failure(recent_output, proc.returncode)
        if recent_output:
            self.log.emit("ffmpeg: " + " | ".join(recent_output))
        else:
            self.log.emit(f"ffmpeg exited with code {proc.returncode}.")
        return FfmpegAttemptFailure(cmd, proc.returncode, reason, recent_output)


def _parse_progress(line: str, total_seconds: float) -> Optional[int]:
    # ffmpeg writes lines like "size=  ... time=00:01:23.45 bitrate= ..."
    # while encoding. Convert that timestamp to a bounded per-track percentage.
    if total_seconds <= 0:
        return None
    m = re.search(r"time=(\d+):(\d+):(\d+(?:\.\d+)?)", line)
    if not m:
        return None
    h, mn, s = m.groups()
    seconds = int(h) * 3600 + int(mn) * 60 + float(s)
    return max(0, min(99, int(seconds * 100 / total_seconds)))


def _unique_track_output(
    folder: Path,
    track: TrackInfo,
    total: int,
    ext: str,
    used_outputs: set[Path],
) -> Path:
    """Return a same-run unique target path for a track."""
    base = target_file(folder, track, total, ext)
    candidate = base
    suffix = 2
    while candidate in used_outputs:
        candidate = base.with_name(f"{base.stem} ({suffix}){base.suffix}")
        suffix += 1
    used_outputs.add(candidate)
    return candidate


def track_output_files(
    folder: Path,
    tracks: Sequence[TrackInfo],
    total: int,
    ext: str,
) -> list[Path]:
    """Return target paths with duplicate same-run filenames made unique."""
    used_outputs: set[Path] = set()
    return [
        _unique_track_output(folder, track, total, ext, used_outputs)
        for track in tracks
    ]


# ---------------------------------------------------------------- runner
class Ripper(QObject):
    """Owns a QThread + RipWorker so the UI just calls `start(...)`."""

    track_started = Signal(int, str)
    track_progress = Signal(int, int)
    track_finished = Signal(int, str)
    track_failed = Signal(int, str)
    finished = Signal(bool, str)
    log = Signal(str)

    def __init__(self, settings: Settings, parent: Optional[QObject] = None):
        super().__init__(parent)
        self.settings = settings
        self._thread: Optional[QThread] = None
        self._worker: Optional[RipWorker] = None

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.isRunning()

    def start(self, request: RipRequest) -> None:
        if self.is_running():
            return
        self._thread = QThread()
        self._worker = RipWorker(self.settings, request)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        # Schedule QThread cleanup when the thread's event loop exits.
        self._thread.finished.connect(self._thread.deleteLater)
        self._worker.finished.connect(self._worker.deleteLater)
        self._worker.track_started.connect(self.track_started)
        self._worker.track_progress.connect(self.track_progress)
        self._worker.track_finished.connect(self.track_finished)
        self._worker.track_failed.connect(self.track_failed)
        self._worker.log.connect(self.log)
        self._worker.finished.connect(self._on_finished)
        self._thread.start()

    def cancel(self) -> None:
        if self._worker:
            self._worker.cancel()

    def shutdown(self, timeout_ms: int = 10000) -> None:
        """Cancel any in-flight rip and join the worker thread.

        Used by the main window's closeEvent. The normal cancel path
        relies on _on_finished firing as a queued slot, but during a
        close the main event loop is blocked, so we drive quit/wait
        directly here. Falls back to terminate() if the worker is wedged
        (e.g. ffmpeg unresponsive) past the timeout.
        """
        if self._thread is None:
            return
        self.cancel()
        self._thread.quit()
        if not self._thread.wait(timeout_ms):
            self.log.emit(
                "Warning: rip worker did not exit cleanly; forcing termination. "
                "Any partially written track file has been removed."
            )
            self._thread.terminate()
            self._thread.wait(2000)
        self._thread = None
        self._worker = None

    def _on_finished(self, ok: bool, msg: str) -> None:
        self.finished.emit(ok, msg)
        if self._thread:
            self._thread.quit()
            if not self._thread.wait(5000):
                self.log.emit("Warning: rip worker thread did not exit within 5 seconds.")
        self._thread = None
        self._worker = None

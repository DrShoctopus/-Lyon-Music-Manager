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
import shutil
import subprocess
import sys
import threading
from ctypes import wintypes
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Sequence

from PySide6.QtCore import QObject, QThread, Signal

from .metadata import AlbumInfo, TrackInfo, fetch_artwork
from .settings import Settings, bundled_bin_dir


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
WINDOWS_CDDA_READ_CHUNK_SECTORS = 16
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


def _format_ext(fmt: str) -> str:
    return _FORMAT_INFO.get(fmt.lower(), _FORMAT_INFO["flac"])[0]


def _codec_args(settings: "Settings") -> list[str]:
    """Return the ffmpeg codec + options args for the configured rip format."""
    fmt = (settings.rip_format or "flac").lower()
    ext, codec, kind = _FORMAT_INFO.get(fmt, _FORMAT_INFO["flac"])
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
    if not name:
        return "Unknown"
    stem, dot, ext = name.partition(".")
    if stem.upper() in _WINDOWS_RESERVED_NAMES:
        name = f"{stem}_{dot}{ext}" if dot else f"{stem}_"
    return name


def find_ffmpeg() -> Optional[str]:
    bundled = bundled_bin_dir() / ("ffmpeg.exe" if sys.platform == "win32" else "ffmpeg")
    if bundled.exists():
        return str(bundled)
    found = shutil.which("ffmpeg")
    return found


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
    return Path(settings.music_root) / artist / name


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


def _read_windows_cdda_sectors(
    drive: str,
    start_sector: int,
    sector_count: int,
    *,
    chunk_sectors: int = WINDOWS_CDDA_READ_CHUNK_SECTORS,
):
    if sys.platform != "win32":
        raise _WindowsCddaReadError("raw CD reads are only available on Windows")
    if sector_count <= 0:
        return

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
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

    generic_read = 0x80000000
    file_share_read = 0x00000001
    file_share_write = 0x00000002
    open_existing = 3
    invalid_handle = wintypes.HANDLE(-1).value

    drive_path = _windows_cdda_drive_path(drive)
    handle = kernel32.CreateFileW(
        drive_path,
        generic_read,
        file_share_read | file_share_write,
        None,
        open_existing,
        0,
        None,
    )
    if handle == invalid_handle:
        err = ctypes.get_last_error()
        raise _WindowsCddaReadError(f"could not open {drive_path}: Windows error {err}")

    remaining = int(sector_count)
    next_sector = int(start_sector)
    try:
        while remaining > 0:
            count = min(chunk_sectors, remaining)
            buffer = ctypes.create_string_buffer(count * CDDA_SECTOR_SIZE)
            info = _RawReadInfo(
                next_sector * CDDA_COOKED_SECTOR_SIZE,
                count,
                TRACK_MODE_CDDA,
            )
            bytes_returned = wintypes.DWORD(0)
            ok = kernel32.DeviceIoControl(
                handle,
                IOCTL_CDROM_RAW_READ,
                ctypes.byref(info),
                ctypes.sizeof(info),
                buffer,
                ctypes.sizeof(buffer),
                ctypes.byref(bytes_returned),
                None,
            )
            if not ok:
                err = ctypes.get_last_error()
                raise _WindowsCddaReadError(
                    f"could not read CD audio sector {next_sector}: Windows error {err}"
                )
            expected = count * CDDA_SECTOR_SIZE
            if bytes_returned.value != expected:
                raise _WindowsCddaReadError(
                    f"read {bytes_returned.value} bytes from sector {next_sector}; expected {expected}"
                )
            yield buffer.raw[:bytes_returned.value]
            next_sector += count
            remaining -= count
    finally:
        kernel32.CloseHandle(handle)


# ---------------------------------------------------------------- worker
@dataclass
class RipRequest:
    drive: str
    album: AlbumInfo
    target_dir: Path
    track_offsets: tuple[int, ...] = ()
    leadout_sector: int = 0
    ctdb_toc: str = ""


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
        "Lyon Music Manager rip failure log",
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

        total = len(album.tracks) or 1
        ext = _format_ext(self.settings.rip_format)
        success = True
        ripped_files: dict[int, Path] = {}
        for tr in album.tracks:
            if self._cancel:
                self.finished.emit(False, "Cancelled")
                return

            self.track_started.emit(tr.number, tr.title)
            out = target_file(folder, tr, total, ext)
            self.log.emit(f"Ripping track {tr.number}: {tr.title}")
            failure = self._rip_track(ff, tr.number, tr.title, out)
            if failure is not None:
                success = False
                failures.append(failure)
                self.log.emit(f"Track {tr.number} failed: {failure.reason}")
                continue

            from .tagger import write_tags
            if not write_tags(out, album, tr, art_bytes):
                success = False
                reason = "Track ripped but audio tags could not be written."
                failures.append(RipFailure(tr.number, tr.title, out, reason))
                self.log.emit(f"Track {tr.number} {reason.lower()}")
            self.track_finished.emit(tr.number, str(out))
            ripped_files[tr.number] = out

        if (
            self.settings.ctdb_verify_rips
            and ripped_files
            and self.request.ctdb_toc
            and (self.settings.rip_format or "flac").lower() == "flac"
        ):
            self._verify_rips(ff, ripped_files)

        message = "Rip complete." if success else "Rip finished with errors."
        if not success:
            self._emit_failure_log(folder, ff, failures, message)
        self.finished.emit(success, message)

    def _verify_rips(self, ffmpeg: str, ripped_files: dict[int, Path]) -> None:
        from .ctdb_verify import verify_rips
        self.log.emit("Verifying rips against CUETools DB...")
        results = verify_rips(
            ripped_files,
            self.request.ctdb_toc,
            ffmpeg,
            len(ripped_files),
        )
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
    ) -> Optional[FfmpegAttemptFailure]:
        start, end = sector_span
        total_sectors = end - start
        cmd = _build_raw_cdda_ffmpeg_command(ffmpeg, out, codec_args)
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
            for chunk in _read_windows_cdda_sectors(self.request.drive, start, total_sectors):
                if self._cancel:
                    try:
                        proc.stdin.close()
                    except OSError:
                        pass
                    proc.kill()
                    proc.wait()
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
            if proc.poll() is None:
                proc.kill()
            proc.wait()
            reader.join(timeout=2)
            _cleanup_partial()
            return FfmpegAttemptFailure(cmd, proc.returncode, reason, _collected_output())
        except (BrokenPipeError, OSError) as e:
            if proc.poll() is None:
                proc.kill()
            proc.wait()
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
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1,
                encoding="utf-8", errors="replace",
                creationflags=_NO_WINDOW,
            )
        except OSError as e:
            reason = f"ffmpeg launch error: {e}"
            self.log.emit(reason)
            return FfmpegAttemptFailure(cmd, None, reason)

        recent_output: list[str] = []
        if proc.stdout is not None:
            for line in proc.stdout:
                if self._cancel:
                    proc.kill()
                    proc.wait()
                    return FfmpegAttemptFailure(
                        cmd, proc.returncode, "Cancelled by user.", recent_output
                    )
                line = line.strip()
                if line:
                    recent_output.append(line)
                    recent_output = recent_output[-FFMPEG_ERROR_LINES:]
                pct = _parse_progress(line, total_seconds)
                if pct is not None:
                    self.track_progress.emit(track_no, pct)
        proc.wait()

        if proc.returncode == 0 and out.exists() and out.stat().st_size > 0:
            self.track_progress.emit(track_no, 100)
            return None

        try:
            out.unlink(missing_ok=True)
        except OSError:
            pass

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


# ---------------------------------------------------------------- runner
class Ripper(QObject):
    """Owns a QThread + RipWorker so the UI just calls `start(...)`."""

    track_started = Signal(int, str)
    track_progress = Signal(int, int)
    track_finished = Signal(int, str)
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
        self._worker.track_started.connect(self.track_started)
        self._worker.track_progress.connect(self.track_progress)
        self._worker.track_finished.connect(self.track_finished)
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
                self._thread.terminate()
                self._thread.wait(2000)
        self._thread = None
        self._worker = None

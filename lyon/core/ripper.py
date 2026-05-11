"""CD -> FLAC ripping using bundled ffmpeg.

The preferred CD extraction path mirrors JACK's architecture: use a dedicated
Digital Audio Extraction helper (cdparanoia, cdda2wav/icedax, tosha, or dagrab)
to produce a WAV, then encode/tag that WAV inside Lyon. FFmpeg/libcdio and the
Windows raw CD reader remain as fallbacks for machines without helper binaries.
"""
from __future__ import annotations

import ctypes
import os
import re
import shutil
import subprocess
import sys
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator, Optional, Sequence

from PySide6.QtCore import QObject, QThread, Signal

from .metadata import AlbumInfo, TrackInfo, fetch_artwork
from .settings import Settings, bundled_bin_dir


SAFE_CHARS_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
CD_SECTORS_PER_SECOND = 75
CD_COOKED_SECTOR_SIZE = 2048
CD_RAW_AUDIO_SECTOR_SIZE = 2352
CD_RAW_READ_CHUNK_SECTORS = 75
FFMPEG_ERROR_LINES = 8
IOCTL_CDROM_RAW_READ = 0x0002403E
TRACK_MODE_CDDA = 2

# Suppress the console window helpers would otherwise pop up per track on Windows.
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

JACK_STYLE_RIPPERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("cdparanoia", ("cdparanoia",)),
    ("cdda2wav", ("cdda2wav", "icedax")),
    ("tosha", ("tosha",)),
    ("dagrab", ("dagrab",)),
)


class _RawReadInfo(ctypes.Structure):
    _fields_ = [
        ("DiskOffset", ctypes.c_longlong),
        ("SectorCount", ctypes.c_ulong),
        ("TrackMode", ctypes.c_int),
    ]


def safe_path_component(name: str) -> str:
    name = name.strip().rstrip(".")
    name = SAFE_CHARS_RE.sub("_", name)
    return name or "Unknown"


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
    artist = safe_path_component(album.artist or "Unknown Artist")
    name = safe_path_component(album.album or "Unknown Album")
    if album.year:
        name = f"{album.year} - {name}"
    folder = Path(settings.music_root) / artist / name
    if create:
        folder.mkdir(parents=True, exist_ok=True)
    return folder


def target_file(folder: Path, track: TrackInfo, total: int) -> Path:
    width = max(2, len(str(total)))
    number = f"{track.number:0{width}d}"
    if track.disc_number > 1:
        number = f"{track.disc_number}-{number}"
    base = f"{number} - {safe_path_component(track.title)}.flac"
    return folder / base


def artwork_file_name(artwork: bytes) -> str:
    if artwork.startswith(b"\x89PNG\r\n\x1a\n"):
        return "cover.png"
    return "cover.jpg"


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
    compression: int,
    sector_span: tuple[int, int],
    *,
    input_seek: bool,
) -> list[str]:
    start, end = sector_span
    duration = end - start
    seek = _sector_seconds(start)
    length = _sector_seconds(duration)
    cmd = [ffmpeg, "-y", "-nostdin", "-loglevel", "error"]
    if input_seek:
        cmd += ["-f", "libcdio", "-ss", seek, "-i", drive]
    else:
        cmd += ["-f", "libcdio", "-i", drive, "-ss", seek]
    cmd += [
        "-t", length,
        "-map", "0:a:0",
        "-vn",
        "-c:a", "flac",
        "-compression_level", str(compression),
        str(out),
    ]
    return cmd


def _cdda_track_uri(drive: str, track_no: int) -> str:
    device = drive.rstrip("\\/")
    return f"cdda://{device}?track={track_no}"


def _build_cdda_track_command(
    ffmpeg: str,
    drive: str,
    out: Path,
    compression: int,
    track_no: int,
) -> list[str]:
    return [
        ffmpeg, "-y", "-nostdin", "-loglevel", "error",
        "-i", _cdda_track_uri(drive, track_no),
        "-vn",
        "-c:a", "flac",
        "-compression_level", str(compression),
        str(out),
    ]


def _build_external_ripper_command(
    ripper_name: str,
    executable: str,
    drive: str,
    track_no: int,
    wav_path: Path,
) -> list[str]:
    track = str(track_no)
    out = str(wav_path)
    if ripper_name == "cdparanoia":
        return [executable, "--abort-on-skip", "-d", drive, track, out]
    if ripper_name == "cdda2wav":
        return [
            executable, "--no-infofile", "-H", "-v", "1",
            "-D", drive, "-O", "wav", "-t", track, out,
        ]
    if ripper_name == "tosha":
        return [executable, "-d", drive, "-f", "wav", "-t", track, "-o", out]
    if ripper_name == "dagrab":
        return [executable, "-d", drive, "-f", out, track]
    raise ValueError(f"Unsupported ripper helper: {ripper_name}")


def _build_wav_to_flac_command(
    ffmpeg: str,
    wav_path: Path,
    out: Path,
    compression: int,
) -> list[str]:
    return [
        ffmpeg, "-y", "-nostdin", "-loglevel", "error",
        "-i", str(wav_path),
        "-vn",
        "-c:a", "flac",
        "-compression_level", str(compression),
        str(out),
    ]


def _candidate_executable_names(name: str) -> Iterator[str]:
    yield name
    if sys.platform == "win32" and not Path(name).suffix:
        for ext in (".exe", ".cmd", ".bat"):
            yield name + ext


def _find_helper_executable(names: Sequence[str]) -> str | None:
    bundled = bundled_bin_dir()
    for name in names:
        for candidate in _candidate_executable_names(name):
            path = bundled / candidate
            if path.exists() and path.is_file():
                return str(path)
    for name in names:
        found = shutil.which(name)
        if found:
            return found
    return None


def _available_external_rippers() -> list[tuple[str, str]]:
    available: list[tuple[str, str]] = []
    for ripper_name, executable_names in JACK_STYLE_RIPPERS:
        executable = _find_helper_executable(executable_names)
        if executable:
            available.append((ripper_name, executable))
    return available


def _ffmpeg_supports_input_format(ffmpeg: str, input_format: str) -> bool:
    try:
        proc = subprocess.run(
            [ffmpeg, "-hide_banner", "-formats"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            creationflags=_NO_WINDOW,
            check=False,
        )
    except OSError:
        return False
    pattern = rf"^\s*D\s+{re.escape(input_format)}\b"
    return re.search(pattern, proc.stdout or "", re.MULTILINE) is not None


def _windows_cd_device_path(drive: str) -> str:
    device = drive.strip().rstrip("\\/")
    if len(device) == 1:
        device += ":"
    return f"\\\\.\\{device}"


def _iter_windows_raw_cdda_chunks(
    drive: str,
    sector_span: tuple[int, int],
    should_cancel: Callable[[], bool] | None = None,
) -> Iterator[bytes]:
    if sys.platform != "win32":
        raise OSError("Windows raw CD reading is only available on Windows.")

    from ctypes import wintypes

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
    invalid_handle_value = ctypes.c_void_p(-1).value

    handle = kernel32.CreateFileW(
        _windows_cd_device_path(drive),
        generic_read,
        file_share_read | file_share_write,
        None,
        open_existing,
        0,
        None,
    )
    if handle == invalid_handle_value:
        raise ctypes.WinError(ctypes.get_last_error())

    start, end = sector_span
    sector = start
    try:
        while sector < end:
            if should_cancel is not None and should_cancel():
                return
            count = min(CD_RAW_READ_CHUNK_SECTORS, end - sector)
            info = _RawReadInfo(
                sector * CD_COOKED_SECTOR_SIZE,
                count,
                TRACK_MODE_CDDA,
            )
            out_size = count * CD_RAW_AUDIO_SECTOR_SIZE
            out_buf = ctypes.create_string_buffer(out_size)
            returned = wintypes.DWORD(0)
            ok = kernel32.DeviceIoControl(
                handle,
                IOCTL_CDROM_RAW_READ,
                ctypes.byref(info),
                ctypes.sizeof(info),
                out_buf,
                out_size,
                ctypes.byref(returned),
                None,
            )
            if not ok:
                raise ctypes.WinError(ctypes.get_last_error())
            yield out_buf.raw[:returned.value]
            sector += count
    finally:
        kernel32.CloseHandle(handle)


def _write_windows_cdda_wav(
    drive: str,
    sector_span: tuple[int, int],
    wav_path: Path,
    should_cancel: Callable[[], bool] | None = None,
) -> None:
    with wave.open(str(wav_path), "wb") as wav:
        wav.setnchannels(2)
        wav.setsampwidth(2)
        wav.setframerate(44100)
        for chunk in _iter_windows_raw_cdda_chunks(drive, sector_span, should_cancel):
            wav.writeframesraw(chunk)


# ---------------------------------------------------------------- worker
@dataclass
class RipRequest:
    drive: str
    album: AlbumInfo
    target_dir: Path
    track_offsets: tuple[int, ...] = ()
    leadout_sector: int = 0


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
        self._external_rippers: list[tuple[str, str]] = []
        self._ffmpeg_has_libcdio: bool | None = None
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        ff = find_ffmpeg()
        if not ff:
            self.finished.emit(False, "ffmpeg not found. Bundle it in /bin or install on PATH.")
            return
        self._external_rippers = _available_external_rippers()
        if self._external_rippers:
            helpers = ", ".join(name for name, _ in self._external_rippers)
            self.log.emit(f"Using JACK-style CD ripper helper fallback: {helpers}.")
        else:
            self.log.emit(
                "No JACK-style CD ripper helper found. Put cdparanoia, "
                "cdda2wav/icedax, tosha, or dagrab in the app bin folder or PATH."
            )
        self._ffmpeg_has_libcdio = _ffmpeg_supports_input_format(ff, "libcdio")
        if not self._ffmpeg_has_libcdio:
            self.log.emit("FFmpeg does not include libcdio input support.")

        album = self.request.album
        folder = self.request.target_dir
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            self.finished.emit(False, f"Could not create rip folder: {e}")
            return

        if not self._track_offsets or self._leadout_sector <= 0:
            self.log.emit("Reading disc TOC for track timing...")
            from .cd_detect import read_disc
            toc = read_disc(self.request.drive)
            if toc is not None:
                self._track_offsets = tuple(toc.track_offsets)
                self._leadout_sector = toc.sectors

        # Save artwork once per album
        art_bytes = album.artwork
        if art_bytes is None and self.settings.download_artwork:
            self.log.emit("Fetching cover art...")
            art_bytes = fetch_artwork(album)
        art_path: Optional[Path] = None
        if art_bytes:
            art_path = folder / artwork_file_name(art_bytes)
            try:
                art_path.write_bytes(art_bytes)
            except OSError as e:
                self.log.emit(f"Could not save cover art: {e}")
                art_path = None

        total = len(album.tracks) or 1
        success = True
        for tr in album.tracks:
            if self._cancel:
                self.finished.emit(False, "Cancelled")
                return

            self.track_started.emit(tr.number, tr.title)
            out = target_file(folder, tr, total)
            self.log.emit(f"Ripping track {tr.number}: {tr.title}")
            ok = self._rip_track(ff, tr.number, out)
            if not ok:
                success = False
                self.log.emit(f"Track {tr.number} failed.")
                continue

            from .tagger import write_flac_tags
            if not write_flac_tags(out, album, tr, art_bytes):
                success = False
                self.log.emit(f"Track {tr.number} ripped but tags could not be written.")
            self.track_finished.emit(tr.number, str(out))

        self.finished.emit(success, "Rip complete." if success else "Rip finished with errors.")

    def _rip_track(self, ffmpeg: str, track_no: int, out: Path) -> bool:
        drive = self.request.drive
        try:
            compression = int(self.settings.flac_compression)
        except (TypeError, ValueError):
            compression = 8
        compression = max(0, min(8, compression))
        span = _track_sector_span(track_no, self._track_offsets, self._leadout_sector)
        has_libcdio = bool(self._ffmpeg_has_libcdio)

        if self._external_rippers:
            if self._rip_track_external_helper(ffmpeg, track_no, out, compression):
                return True
            if self._cancel:
                return False
            self.log.emit(
                f"Track {track_no}: JACK-style ripper helpers failed; "
                "trying built-in fallback."
            )

        if span is not None and sys.platform == "win32" and not has_libcdio:
            if self._rip_track_windows_raw(ffmpeg, track_no, out, compression, span):
                return True
            if self._cancel:
                return False
            self.log.emit(
                f"Track {track_no}: Windows CD reader fallback failed; "
                "trying direct track access."
            )

        attempts: list[list[str]] = []
        if span is None:
            self.log.emit(
                f"Track {track_no}: disc TOC offsets are unavailable or invalid; "
                "trying direct track access."
            )
        elif has_libcdio:
            attempts.extend([
                _build_libcdio_track_command(
                    ffmpeg, drive, out, compression, span, input_seek=True
                ),
                _build_libcdio_track_command(
                    ffmpeg, drive, out, compression, span, input_seek=False
                ),
            ])
        elif sys.platform != "win32":
            self.log.emit(
                f"Track {track_no}: FFmpeg lacks libcdio input support, "
                "and the raw CD reader fallback is Windows-only."
            )

        attempts.append(_build_cdda_track_command(ffmpeg, drive, out, compression, track_no))

        for cmd in attempts:
            if self._run_ffmpeg(cmd, track_no, out):
                return True
        return False

    def _rip_track_external_helper(
        self,
        ffmpeg: str,
        track_no: int,
        out: Path,
        compression: int,
    ) -> bool:
        for ripper_name, executable in self._external_rippers:
            wav_path = out.with_name(f".{out.stem}.{ripper_name}.wav")
            try:
                wav_path.unlink(missing_ok=True)
            except OSError:
                pass
            cmd = _build_external_ripper_command(
                ripper_name, executable, self.request.drive, track_no, wav_path
            )
            self.log.emit(f"Trying {ripper_name} for track {track_no}.")
            if not self._run_command(cmd, track_no, wav_path, ripper_name):
                try:
                    wav_path.unlink(missing_ok=True)
                except OSError:
                    pass
                if self._cancel:
                    return False
                continue
            if self._cancel:
                return False
            encode_cmd = _build_wav_to_flac_command(ffmpeg, wav_path, out, compression)
            try:
                if self._run_ffmpeg(encode_cmd, track_no, out):
                    return True
            finally:
                try:
                    wav_path.unlink(missing_ok=True)
                except OSError:
                    pass
        return False

    def _rip_track_windows_raw(
        self,
        ffmpeg: str,
        track_no: int,
        out: Path,
        compression: int,
        sector_span: tuple[int, int],
    ) -> bool:
        wav_path = out.with_name(f".{out.stem}.rip.wav")
        try:
            _write_windows_cdda_wav(
                self.request.drive,
                sector_span,
                wav_path,
                should_cancel=lambda: self._cancel,
            )
            if self._cancel:
                return False
            cmd = _build_wav_to_flac_command(ffmpeg, wav_path, out, compression)
            return self._run_ffmpeg(cmd, track_no, out)
        except OSError as e:
            self.log.emit(f"Windows CD read failed: {e}")
            return False
        finally:
            try:
                wav_path.unlink(missing_ok=True)
            except OSError:
                pass

    def _run_ffmpeg(self, cmd: list[str], track_no: int, out: Path) -> bool:
        return self._run_command(cmd, track_no, out, "ffmpeg", emit_progress=True)

    def _run_command(
        self,
        cmd: list[str],
        track_no: int,
        out: Path,
        label: str,
        *,
        emit_progress: bool = False,
    ) -> bool:
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1,
                creationflags=_NO_WINDOW,
            )
        except OSError as e:
            self.log.emit(f"{label} launch error: {e}")
            return False

        recent_output: list[str] = []
        if proc.stdout is not None:
            for line in proc.stdout:
                if self._cancel:
                    proc.kill()
                    proc.wait()
                    return False
                line = line.strip()
                if line:
                    recent_output.append(line)
                    recent_output = recent_output[-FFMPEG_ERROR_LINES:]
                if emit_progress:
                    pct = _parse_progress(line)
                    if pct is not None:
                        self.track_progress.emit(track_no, pct)
        proc.wait()

        if proc.returncode == 0 and out.exists() and out.stat().st_size > 0:
            if emit_progress:
                self.track_progress.emit(track_no, 100)
            return True

        try:
            out.unlink(missing_ok=True)
        except OSError:
            pass

        if recent_output:
            self.log.emit(f"{label}: " + " | ".join(recent_output))
        else:
            self.log.emit(f"{label} exited with code {proc.returncode}.")
        return False


def _parse_progress(line: str) -> Optional[int]:
    # ffmpeg writes lines like "size=  ... time=00:01:23.45 bitrate= ..."
    m = re.search(r"time=(\d+):(\d+):(\d+(?:\.\d+)?)", line)
    if not m:
        return None
    h, mn, s = m.groups()
    seconds = int(h) * 3600 + int(mn) * 60 + float(s)
    # We don't know the per-track length cheaply here; UI uses an indeterminate
    # spinner per track and overall progress by track count. Return None.
    return None


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
            self._thread.terminate()
            self._thread.wait(2000)
        self._thread = None
        self._worker = None

    def _on_finished(self, ok: bool, msg: str) -> None:
        self.finished.emit(ok, msg)
        if self._thread:
            self._thread.quit()
            self._thread.wait()
        self._thread = None
        self._worker = None

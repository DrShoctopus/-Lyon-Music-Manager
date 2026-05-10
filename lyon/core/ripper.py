"""CD -> FLAC ripping using bundled ffmpeg.

FFmpeg's libcdio input exposes an audio CD as one audio stream with chapter
metadata, not as one stream per CD track. We use the libdiscid TOC offsets read
by ``cd_detect`` to seek and trim that one stream for each FLAC output file.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

from PySide6.QtCore import QObject, QThread, Signal

from .metadata import AlbumInfo, TrackInfo, fetch_artwork
from .settings import Settings, bundled_bin_dir


SAFE_CHARS_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
CD_SECTORS_PER_SECOND = 75
FFMPEG_ERROR_LINES = 8

# Suppress the console window ffmpeg would otherwise pop up per track on Windows.
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


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
    base = f"{track.number:0{width}d} - {safe_path_component(track.title)}.flac"
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
    compression: int,
    sector_span: tuple[int, int],
    *,
    input_seek: bool,
) -> list[str]:
    start, end = sector_span
    duration = end - start
    seek = _sector_seconds(start)
    length = _sector_seconds(duration)
    cmd = [ffmpeg, "-y", "-loglevel", "error", "-stats"]
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
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        ff = find_ffmpeg()
        if not ff:
            self.finished.emit(False, "ffmpeg not found. Bundle it in /bin or install on PATH.")
            return

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
            art_path = folder / "cover.jpg"
            try:
                art_path.write_bytes(art_bytes)
            except OSError as e:
                self.log.emit(f"Could not save cover art: {e}")
                art_path = None

        if not self._track_offsets or self._leadout_sector <= 0:
            self.finished.emit(
                False,
                "Could not read disc track timing. Try detecting the disc again, "
                "then restart the rip.",
            )
            return

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
        if span is None:
            self.log.emit(
                f"Track {track_no} failed: disc TOC offsets are unavailable or invalid."
            )
            return False

        attempts = [
            _build_libcdio_track_command(ffmpeg, drive, out, compression, span, input_seek=True),
            _build_libcdio_track_command(ffmpeg, drive, out, compression, span, input_seek=False),
        ]
        for cmd in attempts:
            if self._run_ffmpeg(cmd, track_no, out):
                return True
        return False

    def _run_ffmpeg(self, cmd: list[str], track_no: int, out: Path) -> bool:
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1,
                creationflags=_NO_WINDOW,
            )
        except OSError as e:
            self.log.emit(f"ffmpeg launch error: {e}")
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
                pct = _parse_progress(line)
                if pct is not None:
                    self.track_progress.emit(track_no, pct)
        proc.wait()

        if proc.returncode == 0 and out.exists() and out.stat().st_size > 0:
            self.track_progress.emit(track_no, 100)
            return True

        try:
            out.unlink(missing_ok=True)
        except OSError:
            pass

        if recent_output:
            self.log.emit("ffmpeg: " + " | ".join(recent_output))
        else:
            self.log.emit(f"ffmpeg exited with code {proc.returncode}.")
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

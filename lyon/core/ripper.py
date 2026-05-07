"""CD -> FLAC ripping using bundled ffmpeg.

ffmpeg supports CDDA on Windows via libcdio. We invoke it once per track
with `-f libcdio -i <DRIVE> -map 0:a -ss/-to` style arguments isn't ideal,
so instead we use ffmpeg's CDDA "track=N" syntax which exposes individual
tracks. If that's not available, we fall back to reading the whole disc and
splitting by TOC offsets.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import QObject, QThread, Signal

from .metadata import AlbumInfo, TrackInfo, fetch_artwork
from .settings import Settings, bundled_bin_dir


SAFE_CHARS_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


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


def target_folder(settings: Settings, album: AlbumInfo) -> Path:
    artist = safe_path_component(album.artist or "Unknown Artist")
    name = safe_path_component(album.album or "Unknown Album")
    if album.year:
        name = f"{album.year} - {name}"
    folder = Path(settings.music_root) / artist / name
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def target_file(folder: Path, track: TrackInfo, total: int) -> Path:
    width = max(2, len(str(total)))
    base = f"{track.number:0{width}d} - {safe_path_component(track.title)}.flac"
    return folder / base


# ---------------------------------------------------------------- worker
@dataclass
class RipRequest:
    drive: str
    album: AlbumInfo
    target_dir: Path


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
        folder.mkdir(parents=True, exist_ok=True)

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
            except OSError:
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
            write_flac_tags(out, album, tr, art_bytes)
            self.track_finished.emit(tr.number, str(out))

        self.finished.emit(success, "Rip complete." if success else "Rip finished with errors.")

    def _rip_track(self, ffmpeg: str, track_no: int, out: Path) -> bool:
        # ffmpeg CDDA input: "cdda://<DRIVE>?track=N" works on builds with libcdio.
        # Some builds prefer `-f libcdio -i D:`. We try the modern form first.
        drive = self.request.drive
        compression = max(0, min(8, int(self.settings.flac_compression)))
        attempts = [
            [
                ffmpeg, "-y", "-loglevel", "error", "-stats",
                "-f", "libcdio", "-i", drive,
                "-map", f"0:a:{track_no - 1}",
                "-c:a", "flac", "-compression_level", str(compression),
                str(out),
            ],
            [
                ffmpeg, "-y", "-loglevel", "error", "-stats",
                "-i", f"cdda://{drive}?track={track_no}",
                "-c:a", "flac", "-compression_level", str(compression),
                str(out),
            ],
        ]
        for cmd in attempts:
            try:
                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, bufsize=1,
                )
            except OSError as e:
                self.log.emit(f"ffmpeg launch error: {e}")
                continue

            assert proc.stdout is not None
            for line in proc.stdout:
                if self._cancel:
                    proc.kill()
                    return False
                pct = _parse_progress(line)
                if pct is not None:
                    self.track_progress.emit(track_no, pct)
            proc.wait()
            if proc.returncode == 0 and out.exists() and out.stat().st_size > 0:
                self.track_progress.emit(track_no, 100)
                return True
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

    def _on_finished(self, ok: bool, msg: str) -> None:
        self.finished.emit(ok, msg)
        if self._thread:
            self._thread.quit()
            self._thread.wait()
        self._thread = None
        self._worker = None

"""yt-dlp download worker thread."""
from __future__ import annotations

import shutil
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from .settings import bundled_bin_dir


def _find_ffmpeg() -> Path | None:
    """Return path to ffmpeg binary, checking bundled bin dir first, then PATH."""
    bin_dir = bundled_bin_dir()
    for name in ("ffmpeg.exe", "ffmpeg"):
        candidate = bin_dir / name
        if candidate.exists():
            return candidate
    found = shutil.which("ffmpeg.exe") or shutil.which("ffmpeg")
    return Path(found) if found else None


def _video_postprocessors(fmt: str) -> list[dict]:
    """Postprocessors for video downloads with a persistent catalog thumbnail."""
    postprocessors = [
        {
            "key": "FFmpegThumbnailsConvertor",
            "format": "jpg",
            "when": "before_dl",
        },
    ]
    # yt-dlp cannot embed thumbnails in WebM containers.  The converted JPG
    # sidecar above is still enough for Lyon's video catalog thumbnail.
    if fmt != "webm":
        postprocessors.append({"key": "EmbedThumbnail", "already_have_thumbnail": True})
    postprocessors.extend([
        {"key": "FFmpegMetadata", "add_metadata": True},
        {"key": "FFmpegEmbedSubtitle"},
    ])
    return postprocessors


class _YtLogger:
    """Forwards yt-dlp log messages to the worker's progress signal."""

    def __init__(self, worker: "YtDownloadWorker") -> None:
        self._worker = worker

    def debug(self, msg: str) -> None:
        if msg.startswith("[debug]"):
            return
        self._worker.progress.emit(msg)

    def info(self, msg: str) -> None:
        self._worker.progress.emit(msg)

    def warning(self, msg: str) -> None:
        self._worker.progress.emit(f"WARNING: {msg}")

    def error(self, msg: str) -> None:
        self._worker.progress.emit(f"ERROR: {msg}")


class YtDownloadWorker(QThread):
    """Downloads a URL via yt-dlp in a background thread.

    Signals
    -------
    progress(str)      -- log / status line suitable for display
    track_ready(str)   -- absolute path of each completed output file
    download_finished(int, int) -- (succeeded, failed) counts when done
    error(str)         -- emitted on a fatal error before finished
    """

    progress = Signal(str)
    track_ready = Signal(str)
    download_finished = Signal(int, int)
    error = Signal(str)

    def __init__(
        self,
        url: str,
        mode: str,          # 'audio' | 'video'
        fmt: str,           # 'flac' | 'mp3'  or  'mp4' | 'mkv' | 'webm'
        output_dir: str,
        playlist: bool = False,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.url = url
        self.mode = mode
        self.fmt = fmt
        self.output_dir = output_dir
        self.playlist = playlist
        self._cancelled = False
        self._succeeded = 0
        self._failed = 0
        self._emitted_paths: set[str] = set()

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        try:
            import yt_dlp  # noqa: PLC0415
        except ImportError:
            self.error.emit(
                "yt-dlp is not installed. Run:  pip install yt-dlp"
            )
            self.download_finished.emit(0, 1)
            return

        out_template = str(
            Path(self.output_dir) / "%(uploader)s" / "%(title)s.%(ext)s"
        )

        ffmpeg_path = _find_ffmpeg()

        if self.mode == "audio":
            if not ffmpeg_path:
                self.error.emit(
                    "ffmpeg is required for audio conversion but was not found. "
                    "Install ffmpeg and place it on PATH (or in the app bin folder), then retry."
                )
                self.download_finished.emit(0, 1)
                return
            postprocessors = [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": self.fmt,
                    "preferredquality": "0",
                },
                {"key": "EmbedThumbnail"},
                {"key": "FFmpegMetadata", "add_metadata": True},
            ]
            fmt_selector = "bestaudio/best"
            merge_fmt = None
        else:
            if ffmpeg_path:
                postprocessors = _video_postprocessors(self.fmt)
                fmt_selector = "bestvideo+bestaudio/best"
                merge_fmt = self.fmt
            else:
                self.progress.emit(
                    "WARNING: ffmpeg not found — downloading best available pre-merged stream "
                    "(quality capped at ~720p). Install ffmpeg for full quality and metadata embedding."
                )
                postprocessors = []
                fmt_selector = f"best[ext={self.fmt}]/best[ext=mp4]/best"
                merge_fmt = None

        ydl_opts: dict = {
            "format": fmt_selector,
            "outtmpl": out_template,
            "postprocessors": postprocessors,
            "logger": _YtLogger(self),
            "progress_hooks": [self._on_progress],
            "post_hooks": [self._on_post_hook],
            "noplaylist": not self.playlist,
            "writethumbnail": True,
            # Video downloads need a persistent, Qt-friendly sidecar thumbnail
            # for the catalog card.  EmbedThumbnail deletes it unless the
            # postprocessor is told the thumbnail is intentionally kept.
            # Keep going through playlist errors rather than aborting.
            "ignoreerrors": self.playlist,
        }
        if merge_fmt:
            ydl_opts["merge_output_format"] = merge_fmt
        if ffmpeg_path:
            ydl_opts["ffmpeg_location"] = str(ffmpeg_path.parent)

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([self.url])
        except Exception as exc:  # noqa: BLE001
            if not self._cancelled:
                if self._succeeded == 0 and self._failed == 0:
                    self._failed = 1
                self.error.emit(str(exc))
        finally:
            self.download_finished.emit(self._succeeded, self._failed)

    # ------------------------------------------------------------------ hooks

    def _on_progress(self, d: dict) -> None:
        if self._cancelled:
            from yt_dlp.utils import DownloadCancelled
            raise DownloadCancelled()
        status = d.get("status", "")
        if status == "downloading":
            pct = d.get("_percent_str", "").strip()
            speed = d.get("_speed_str", "").strip()
            eta = d.get("_eta_str", "").strip()
            filename = Path(d.get("filename", "")).name
            self.progress.emit(f"  {filename}  {pct}  {speed}  ETA {eta}")
        elif status == "error":
            self._failed += 1

    def _on_post_hook(self, path: str) -> None:
        """Emit the final downloaded file path after yt-dlp has moved it."""
        if path and Path(path).exists():
            self._emit_track_ready(path)

    def _emit_track_ready(self, path: str) -> None:
        """Emit track_ready exactly once per output file across all postprocessors."""
        if path in self._emitted_paths:
            return
        self._emitted_paths.add(path)
        self._succeeded += 1
        self.track_ready.emit(path)

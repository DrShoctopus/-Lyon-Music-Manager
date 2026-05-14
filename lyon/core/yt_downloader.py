"""yt-dlp download worker thread."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, Signal


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
    finished(int, int) -- (succeeded, failed) counts when done
    error(str)         -- emitted on a fatal error before finished
    """

    progress = Signal(str)
    track_ready = Signal(str)
    finished = Signal(int, int)
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
            return

        out_template = str(
            Path(self.output_dir) / "%(uploader)s" / "%(title)s.%(ext)s"
        )

        if self.mode == "audio":
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
            postprocessors = [
                {"key": "EmbedThumbnail"},
                {"key": "FFmpegMetadata", "add_metadata": True},
                {"key": "FFmpegEmbedSubtitle"},
            ]
            fmt_selector = "bestvideo+bestaudio/best"
            merge_fmt = self.fmt

        ydl_opts: dict = {
            "format": fmt_selector,
            "outtmpl": out_template,
            "postprocessors": postprocessors,
            "logger": _YtLogger(self),
            "progress_hooks": [self._on_progress],
            "postprocessor_hooks": [self._on_postprocessor],
            "noplaylist": not self.playlist,
            "writethumbnail": True,
            # Keep going through playlist errors rather than aborting.
            "ignoreerrors": self.playlist,
        }
        if merge_fmt:
            ydl_opts["merge_output_format"] = merge_fmt

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([self.url])
        except Exception as exc:  # noqa: BLE001
            if not self._cancelled:
                self.error.emit(str(exc))
        finally:
            self.finished.emit(self._succeeded, self._failed)

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

    def _on_postprocessor(self, d: dict) -> None:
        if d.get("status") != "finished":
            return
        info = d.get("info_dict", {})
        # After all postprocessors the final path lives in requested_downloads.
        for dl in info.get("requested_downloads", []):
            path = dl.get("filepath", "")
            if path and Path(path).exists():
                self._emit_track_ready(path)
                return
        # Fallback: use filepath directly on the info_dict
        path = info.get("filepath", "")
        if path and Path(path).exists():
            self._emit_track_ready(path)

    def _emit_track_ready(self, path: str) -> None:
        """Emit track_ready exactly once per output file across all postprocessors."""
        if path in self._emitted_paths:
            return
        self._emitted_paths.add(path)
        self._succeeded += 1
        self.track_ready.emit(path)

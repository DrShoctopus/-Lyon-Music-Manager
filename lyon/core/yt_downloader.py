"""yt-dlp download worker thread."""
from __future__ import annotations

import logging
import re
import shutil
import sys
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from .ffmpeg import find_ffmpeg_binary
from .settings import bundled_bin_dir

LOG = logging.getLogger(__name__)
_YT_QUALITY_HEIGHT = {"1080p": 1080, "2k": 1440, "4k": 2160}
_YT_BROWSER_COOKIE_BROWSERS = {
    "brave",
    "chrome",
    "chromium",
    "edge",
    "firefox",
    "opera",
    "safari",
    "vivaldi",
    "whale",
}
_JS_RUNTIMES = ("deno", "node")
_MACOS_RUNTIME_DIRS = (Path("/opt/homebrew/bin"), Path("/usr/local/bin"))
_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_SAFARI_COOKIE_PERMISSION_MESSAGE = (
    "macOS blocked access to Safari cookies. Grant Full Disk Access to Sea Lyon "
    "or choose another signed-in browser in Settings -> YouTube."
)
_YOUTUBE_BROWSER_SESSION_SETTINGS_MESSAGE = (
    "Enable browser in Settings > YouTube."
)
_YOUTUBE_JS_CHALLENGE_MESSAGE = (
    "Sea Lyon could not solve YouTube's player JavaScript challenge. "
    "Install Deno or Node, or use a build that bundles a JavaScript runtime "
    "and yt-dlp-ejs, then retry."
)


def _format_eta(seconds) -> str:
    try:
        total = max(0, int(seconds))
    except (TypeError, ValueError):
        return ""
    minutes, secs = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def _download_percent(info: dict) -> int | None:
    downloaded = info.get("downloaded_bytes")
    total = info.get("total_bytes") or info.get("total_bytes_estimate")
    try:
        if downloaded is not None and total:
            return max(0, min(100, int(float(downloaded) * 100 / float(total))))
    except (TypeError, ValueError, ZeroDivisionError):
        pass

    match = re.search(r"(\d+(?:\.\d+)?)\s*%", str(info.get("_percent_str", "")))
    if not match:
        return None
    try:
        return max(0, min(100, int(float(match.group(1)))))
    except ValueError:
        return None


def _video_format_selector(quality: str, has_ffmpeg: bool, container: str) -> str:
    if not has_ffmpeg:
        return f"best[ext={container}]/best[ext=mp4]/best"
    if quality in _YT_QUALITY_HEIGHT:
        h = _YT_QUALITY_HEIGHT[quality]
        return f"bestvideo[height<={h}]+bestaudio/best[height<={h}]"
    return "bestvideo+bestaudio/best"


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


def _browser_cookies_option(browser: str) -> tuple[str] | None:
    browser_name = str(browser or "").strip().lower()
    if browser_name not in _YT_BROWSER_COOKIE_BROWSERS:
        return None
    return (browser_name,)


def _clean_error_message(message: object) -> str:
    text = _ANSI_ESCAPE_RE.sub("", str(message or ""))
    return " ".join(text.split())


def _user_facing_error_message(exc: BaseException) -> str:
    text = _clean_error_message(exc)
    if (
        "Sign in to confirm your age" in text
        and (
            "--cookies-from-browser" in text
            or "--cookies" in text
            or "cookies" in text.lower()
        )
    ):
        return _YOUTUBE_BROWSER_SESSION_SETTINGS_MESSAGE
    if (
        "Operation not permitted" in text
        and "com.apple.Safari" in text
        and "Cookies.binarycookies" in text
    ):
        return _SAFARI_COOKIE_PERMISSION_MESSAGE
    return text


def _is_youtube_js_challenge_warning(message: object) -> bool:
    text = _clean_error_message(message)
    return (
        "Signature solving failed" in text
        or "n challenge solving failed" in text
        or "No supported JavaScript runtime could be found" in text
    )


def _find_js_runtime_binary(name: str) -> Path | None:
    executable_names = (f"{name}.exe", name) if sys.platform == "win32" else (name,)
    bin_dir = bundled_bin_dir()
    for executable in executable_names:
        candidate = bin_dir / executable
        if candidate.exists():
            return candidate
    found = shutil.which(f"{name}.exe") if sys.platform == "win32" else shutil.which(name)
    if found:
        return Path(found)
    if sys.platform == "darwin":
        for runtime_dir in _MACOS_RUNTIME_DIRS:
            candidate = runtime_dir / name
            if candidate.exists():
                return candidate
    return None


def _js_runtime_options() -> dict[str, dict]:
    runtimes = {name: {} for name in _JS_RUNTIMES}
    for name in _JS_RUNTIMES:
        if path := _find_js_runtime_binary(name):
            runtimes[name]["path"] = str(path)
    return runtimes


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
        LOG.warning("yt-dlp warning: %s", msg)
        self._worker._record_yt_dlp_warning(msg)
        self._worker.progress.emit(f"WARNING: {msg}")

    def error(self, msg: str) -> None:
        LOG.warning("yt-dlp error: %s", msg)
        self._worker.progress.emit(f"ERROR: {msg}")


class YtDownloadWorker(QThread):
    """Downloads a URL via yt-dlp in a background thread.

    Signals
    -------
    progress(str)      -- log / status line suitable for diagnostics
    download_progress(int, str) -- current item percent and formatted ETA
    track_ready(str)   -- absolute path of each completed output file
    download_finished(int, int) -- (succeeded, failed) counts when done
    error(str)         -- emitted on a fatal error before finished
    """

    progress = Signal(str)
    download_progress = Signal(int, str)
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
        quality: str = "best",   # 'best' | '1080p' | '2k' | '4k'
        parent=None,
        *,
        browser_cookies_browser: str = "",
    ) -> None:
        super().__init__(parent)
        self.url = url
        self.mode = mode
        self.fmt = fmt
        self.output_dir = output_dir
        self.playlist = playlist
        self.quality = quality
        self.browser_cookies_browser = browser_cookies_browser
        self._cancelled = False
        self._succeeded = 0
        self._failed = 0
        self._emitted_paths: set[str] = set()
        self._youtube_js_challenge_failed = False

    def cancel(self) -> None:
        self._cancelled = True

    def _record_yt_dlp_warning(self, message: object) -> None:
        if _is_youtube_js_challenge_warning(message):
            self._youtube_js_challenge_failed = True

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

        ffmpeg_path = find_ffmpeg_binary()

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
                fmt_selector = _video_format_selector(self.quality, True, self.fmt)
                merge_fmt = self.fmt
            else:
                self.progress.emit(
                    "WARNING: ffmpeg not found — downloading best available pre-merged stream "
                    "(quality capped at ~720p). Install ffmpeg for full quality and metadata embedding."
                )
                postprocessors = []
                fmt_selector = _video_format_selector(self.quality, False, self.fmt)
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
            # Deno is yt-dlp's default/recommended JS runtime. Node is also
            # supported but must be explicitly enabled; it gives source runs
            # and packaged builds another way to solve YouTube JS challenges.
            "js_runtimes": _js_runtime_options(),
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
        browser_cookies = _browser_cookies_option(self.browser_cookies_browser)
        if browser_cookies:
            ydl_opts["cookiesfrombrowser"] = browser_cookies
            ydl_opts["extractor_args"] = {
                "youtube": {"player_client": ["default", "-web_safari"]}
            }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([self.url])
        except Exception as exc:  # noqa: BLE001
            if not self._cancelled:
                if self._succeeded == 0 and self._failed == 0:
                    self._failed = 1
                LOG.warning("yt-dlp download failed: %s", _clean_error_message(exc))
                message = _user_facing_error_message(exc)
                if (
                    self._youtube_js_challenge_failed
                    and "Requested format is not available" in _clean_error_message(exc)
                ):
                    message = _YOUTUBE_JS_CHALLENGE_MESSAGE
                self.error.emit(message)
        finally:
            self.download_finished.emit(self._succeeded, self._failed)

    # ------------------------------------------------------------------ hooks

    def _on_progress(self, d: dict) -> None:
        if self._cancelled:
            from yt_dlp.utils import DownloadCancelled
            raise DownloadCancelled()
        status = d.get("status", "")
        if status == "downloading":
            pct_value = _download_percent(d)
            if pct_value is not None:
                self.download_progress.emit(pct_value, _format_eta(d.get("eta")))
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

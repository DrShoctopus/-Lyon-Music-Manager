import builtins
import sys
import types

from lyon.core.yt_downloader import YtDownloadWorker, _video_postprocessors


def test_video_postprocessors_keep_qt_friendly_thumbnail_sidecar():
    postprocessors = _video_postprocessors("mp4")

    assert postprocessors[0] == {
        "key": "FFmpegThumbnailsConvertor",
        "format": "jpg",
        "when": "before_dl",
    }
    assert postprocessors[1] == {
        "key": "EmbedThumbnail",
        "already_have_thumbnail": True,
    }


def test_webm_video_postprocessors_skip_unsupported_thumbnail_embedding():
    postprocessors = _video_postprocessors("webm")

    assert postprocessors[0]["key"] == "FFmpegThumbnailsConvertor"
    assert all(pp["key"] != "EmbedThumbnail" for pp in postprocessors)
    assert {pp["key"] for pp in postprocessors} == {
        "FFmpegThumbnailsConvertor",
        "FFmpegMetadata",
        "FFmpegEmbedSubtitle",
    }


def test_post_hook_emits_final_track_ready_path(tmp_path):
    video = tmp_path / "fallback.mp4"
    video.write_bytes(b"video")
    worker = YtDownloadWorker("https://example.invalid/video", "video", "mp4", str(tmp_path))
    emitted: list[str] = []
    worker.track_ready.connect(emitted.append)

    worker._on_post_hook(str(video))

    assert emitted == [str(video)]


def test_import_error_emits_download_finished(monkeypatch, tmp_path):
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "yt_dlp":
            raise ImportError("missing")
        return real_import(name, *args, **kwargs)

    worker = YtDownloadWorker("https://example.invalid/video", "video", "mp4", str(tmp_path))
    errors: list[str] = []
    finished: list[tuple[int, int]] = []
    worker.error.connect(errors.append)
    worker.download_finished.connect(lambda succeeded, failed: finished.append((succeeded, failed)))
    monkeypatch.setattr(builtins, "__import__", fake_import)

    worker.run()

    assert errors == ["yt-dlp is not installed. Run:  pip install yt-dlp"]
    assert finished == [(0, 1)]


def test_browser_cookies_are_disabled_by_default(monkeypatch, tmp_path):
    captured_opts: list[dict] = []

    class FakeYoutubeDL:
        def __init__(self, opts):
            captured_opts.append(opts)

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def download(self, _urls):
            return None

    monkeypatch.setitem(sys.modules, "yt_dlp", types.SimpleNamespace(YoutubeDL=FakeYoutubeDL))
    monkeypatch.setattr("lyon.core.yt_downloader.find_ffmpeg_binary", lambda: None)
    worker = YtDownloadWorker("https://example.invalid/video", "video", "mp4", str(tmp_path))

    worker.run()

    assert "cookiesfrombrowser" not in captured_opts[0]


def test_youtube_downloads_enable_deno_and_node_js_runtimes(monkeypatch, tmp_path):
    captured_opts: list[dict] = []

    class FakeYoutubeDL:
        def __init__(self, opts):
            captured_opts.append(opts)

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def download(self, _urls):
            return None

    monkeypatch.setitem(sys.modules, "yt_dlp", types.SimpleNamespace(YoutubeDL=FakeYoutubeDL))
    monkeypatch.setattr("lyon.core.yt_downloader.find_ffmpeg_binary", lambda: None)
    monkeypatch.setattr("lyon.core.yt_downloader._find_js_runtime_binary", lambda _name: None)
    worker = YtDownloadWorker("https://example.invalid/video", "video", "mp4", str(tmp_path))

    worker.run()

    assert captured_opts[0]["js_runtimes"] == {"deno": {}, "node": {}}


def test_youtube_downloads_prefer_bundled_js_runtime_paths(monkeypatch, tmp_path):
    captured_opts: list[dict] = []
    node = tmp_path / "bin" / "node"
    node.parent.mkdir()
    node.write_text("#!/bin/sh\n", encoding="utf-8")

    class FakeYoutubeDL:
        def __init__(self, opts):
            captured_opts.append(opts)

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def download(self, _urls):
            return None

    monkeypatch.setitem(sys.modules, "yt_dlp", types.SimpleNamespace(YoutubeDL=FakeYoutubeDL))
    monkeypatch.setattr("lyon.core.yt_downloader.find_ffmpeg_binary", lambda: None)
    monkeypatch.setattr("lyon.core.yt_downloader.bundled_bin_dir", lambda: node.parent)
    monkeypatch.setattr("lyon.core.yt_downloader.shutil.which", lambda _name: None)
    worker = YtDownloadWorker("https://example.invalid/video", "video", "mp4", str(tmp_path))

    worker.run()

    assert captured_opts[0]["js_runtimes"]["node"] == {"path": str(node)}


def test_browser_cookies_option_is_passed_to_ytdlp(monkeypatch, tmp_path):
    captured_opts: list[dict] = []

    class FakeYoutubeDL:
        def __init__(self, opts):
            captured_opts.append(opts)

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def download(self, _urls):
            return None

    monkeypatch.setitem(sys.modules, "yt_dlp", types.SimpleNamespace(YoutubeDL=FakeYoutubeDL))
    monkeypatch.setattr("lyon.core.yt_downloader.find_ffmpeg_binary", lambda: None)
    worker = YtDownloadWorker(
        "https://example.invalid/video",
        "video",
        "mp4",
        str(tmp_path),
        browser_cookies_browser="firefox",
    )

    worker.run()

    assert captured_opts[0]["cookiesfrombrowser"] == ("firefox",)


def test_browser_cookies_exclude_fragile_youtube_web_safari_client(monkeypatch, tmp_path):
    captured_opts: list[dict] = []

    class FakeYoutubeDL:
        def __init__(self, opts):
            captured_opts.append(opts)

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def download(self, _urls):
            return None

    monkeypatch.setitem(sys.modules, "yt_dlp", types.SimpleNamespace(YoutubeDL=FakeYoutubeDL))
    monkeypatch.setattr("lyon.core.yt_downloader.find_ffmpeg_binary", lambda: None)
    worker = YtDownloadWorker(
        "https://example.invalid/video",
        "video",
        "mp4",
        str(tmp_path),
        browser_cookies_browser="safari",
    )

    worker.run()

    assert captured_opts[0]["extractor_args"] == {
        "youtube": {"player_client": ["default", "-web_safari"]}
    }


def test_progress_hook_emits_structured_percent_and_eta(tmp_path):
    worker = YtDownloadWorker("https://example.invalid/video", "video", "mp4", str(tmp_path))
    emitted: list[tuple[int, str]] = []
    worker.download_progress.connect(lambda percent, eta: emitted.append((percent, eta)))

    worker._on_progress({
        "status": "downloading",
        "filename": str(tmp_path / "Example.mp4"),
        "downloaded_bytes": 250,
        "total_bytes": 1000,
        "eta": 125,
    })

    assert emitted == [(25, "2:05")]


def test_fatal_download_error_counts_as_failed(monkeypatch, tmp_path, caplog):
    class FakeYoutubeDL:
        def __init__(self, *_args, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def download(self, _urls):
            raise RuntimeError("network failed")

    monkeypatch.setitem(sys.modules, "yt_dlp", types.SimpleNamespace(YoutubeDL=FakeYoutubeDL))
    monkeypatch.setattr("lyon.core.yt_downloader.find_ffmpeg_binary", lambda: None)
    worker = YtDownloadWorker("https://example.invalid/video", "video", "mp4", str(tmp_path))
    errors: list[str] = []
    finished: list[tuple[int, int]] = []
    worker.error.connect(errors.append)
    worker.download_finished.connect(lambda succeeded, failed: finished.append((succeeded, failed)))
    caplog.set_level("WARNING", logger="lyon.core.yt_downloader")

    worker.run()

    assert errors == ["network failed"]
    assert finished == [(0, 1)]
    assert "yt-dlp download failed: network failed" in caplog.text


def test_safari_cookie_permission_error_is_user_actionable(monkeypatch, tmp_path, caplog):
    class FakeYoutubeDL:
        def __init__(self, *_args, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def download(self, _urls):
            raise RuntimeError(
                "\x1b[0;31mERROR:\x1b[0m [Errno 1] Operation not permitted: "
                "'/Users/example/Library/Containers/com.apple.Safari/Data/Library/"
                "Cookies/Cookies.binarycookies'"
            )

    monkeypatch.setitem(sys.modules, "yt_dlp", types.SimpleNamespace(YoutubeDL=FakeYoutubeDL))
    monkeypatch.setattr("lyon.core.yt_downloader.find_ffmpeg_binary", lambda: None)
    worker = YtDownloadWorker(
        "https://example.invalid/video",
        "video",
        "mp4",
        str(tmp_path),
        browser_cookies_browser="safari",
    )
    errors: list[str] = []
    worker.error.connect(errors.append)
    caplog.set_level("WARNING", logger="lyon.core.yt_downloader")

    worker.run()

    assert errors == [
        "macOS blocked access to Safari cookies. Grant Full Disk Access to Sea Lyon "
        "or choose another signed-in browser in Settings -> YouTube."
    ]
    assert "Operation not permitted" in caplog.text


def test_youtube_age_confirmation_error_points_to_settings(monkeypatch, tmp_path, caplog):
    class FakeYoutubeDL:
        def __init__(self, *_args, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def download(self, _urls):
            raise RuntimeError(
                "ERROR: [youtube] n3sEKLlFLzI: Sign in to confirm your age. "
                "This video may be inappropriate for some users. "
                "Use --cookies-from-browser or --cookies for the authentication."
            )

    monkeypatch.setitem(sys.modules, "yt_dlp", types.SimpleNamespace(YoutubeDL=FakeYoutubeDL))
    monkeypatch.setattr("lyon.core.yt_downloader.find_ffmpeg_binary", lambda: None)
    worker = YtDownloadWorker("https://example.invalid/video", "video", "mp4", str(tmp_path))
    errors: list[str] = []
    worker.error.connect(errors.append)
    caplog.set_level("WARNING", logger="lyon.core.yt_downloader")

    worker.run()

    assert errors == ["Enable browser in Settings > YouTube."]
    assert "Sign in to confirm your age" in caplog.text


def test_js_challenge_warning_makes_format_error_user_actionable(monkeypatch, tmp_path):
    class FakeYoutubeDL:
        def __init__(self, opts):
            self._logger = opts["logger"]

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def download(self, _urls):
            self._logger.warning(
                "Signature solving failed: Some formats may be missing. "
                "Ensure you have a supported JavaScript runtime and challenge solver "
                "script distribution installed."
            )
            raise RuntimeError("Requested format is not available")

    monkeypatch.setitem(sys.modules, "yt_dlp", types.SimpleNamespace(YoutubeDL=FakeYoutubeDL))
    monkeypatch.setattr("lyon.core.yt_downloader.find_ffmpeg_binary", lambda: None)
    worker = YtDownloadWorker("https://example.invalid/video", "video", "mp4", str(tmp_path))
    errors: list[str] = []
    worker.error.connect(errors.append)

    worker.run()

    assert errors == [
        "Sea Lyon could not solve YouTube's player JavaScript challenge. "
        "Install Deno or Node, or use a build that bundles a JavaScript runtime "
        "and yt-dlp-ejs, then retry."
    ]

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


def test_fatal_download_error_counts_as_failed(monkeypatch, tmp_path):
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

    worker.run()

    assert errors == ["network failed"]
    assert finished == [(0, 1)]

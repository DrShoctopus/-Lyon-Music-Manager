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


def test_progress_finished_emits_track_ready_without_postprocessors(tmp_path):
    video = tmp_path / "fallback.mp4"
    video.write_bytes(b"video")
    worker = YtDownloadWorker("https://example.invalid/video", "video", "mp4", str(tmp_path))
    emitted: list[str] = []
    worker.track_ready.connect(emitted.append)

    worker._uses_postprocessors = False
    worker._on_progress({"status": "finished", "filename": str(video)})

    assert emitted == [str(video)]

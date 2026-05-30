from __future__ import annotations

import re
from pathlib import Path


def test_read_tags_has_no_temp_duplicate_warning(monkeypatch, caplog, tmp_path):
    from lyon.core import library

    media_path = tmp_path / "song.flac"
    media_path.write_bytes(b"not real audio")
    monkeypatch.setattr(library, "MutagenFile", lambda *_, **__: None)

    caplog.set_level("WARNING", logger="lyon.core.library")
    library._read_tags(str(media_path))
    library._read_tags(str(media_path))

    assert "DIAG duplicate tag-read" not in caplog.text


def test_review_hotspots_do_not_swallow_exceptions_silently():
    root = Path(__file__).resolve().parents[1]
    hotspots = [
        "lyon/core/replaygain.py",
        "lyon/core/smart_playlist.py",
        "lyon/ui/duplicate_dialog.py",
        "lyon/ui/library_view.py",
        "lyon/ui/metadata_fetch_dialog.py",
        "lyon/ui/now_playing.py",
        "lyon/ui/video_player_view.py",
    ]

    silent_catch = re.compile(r"except Exception:\n[ \t]+(?:pass|return)\b")
    offenders = [
        path for path in hotspots
        if silent_catch.search((root / path).read_text(encoding="utf-8"))
    ]

    assert offenders == []

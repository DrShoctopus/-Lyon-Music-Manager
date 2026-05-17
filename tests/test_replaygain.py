from __future__ import annotations

import pytest

from lyon.core import replaygain


def test_read_track_gain_from_mp4_freeform_tag(monkeypatch):
    mutagen = pytest.importorskip("mutagen")
    mp4 = pytest.importorskip("mutagen.mp4")

    audio = mp4.MP4.__new__(mp4.MP4)
    audio.tags = {
        "----:com.apple.iTunes:REPLAYGAIN_TRACK_GAIN": [
            mp4.MP4FreeForm(b"+1.23 dB", mp4.AtomDataType.UTF8)
        ]
    }
    monkeypatch.setattr(mutagen, "File", lambda *_args, **_kwargs: audio)

    assert replaygain.read_track_gain("song.m4a") == pytest.approx(1.23)

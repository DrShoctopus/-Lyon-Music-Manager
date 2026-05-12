import pytest

from lyon.core.library import Track

pytest.importorskip("PySide6.QtGui", exc_type=ImportError)

from lyon.ui.library_view import LibraryView


def make_track(**overrides):
    values = {
        "id": 1,
        "path": r"C:\\Music\\Artist\\Album\\song.flac",
        "title": "Song",
        "artist": "Track Artist",
        "album_artist": "Album Artist",
        "album": "Album",
        "track_no": 1,
        "disc_no": 1,
        "year": 2026,
        "genre": "Rock",
        "duration": 185.0,
        "bitrate": 921600,
        "samplerate": 44100,
    }
    values.update(overrides)
    return Track(**values)


def test_track_tooltip_includes_audio_details_and_file_location():
    tooltip = LibraryView._track_tooltip(None, make_track(), "3:05")

    assert "Title: Song" in tooltip
    assert "Artist: Album Artist" in tooltip
    assert "Time: 3:05" in tooltip
    assert "Bitrate: 922 kbps" in tooltip
    assert "Sample rate: 44.1 kHz" in tooltip
    assert "File type: FLAC" in tooltip
    assert r"File location: C:\Music\Artist\Album\song.flac" in tooltip


def test_sample_rate_formatter_handles_unknown_and_whole_khz_values():
    assert LibraryView._format_sample_rate(0) == "Unknown"
    assert LibraryView._format_sample_rate(48000) == "48 kHz"

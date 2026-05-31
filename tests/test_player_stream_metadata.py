"""Player tests for ICY/HLS stream metadata applied via the backend signal."""
from __future__ import annotations

import pytest

QtCore = pytest.importorskip("PySide6.QtCore", exc_type=ImportError)
QObject = QtCore.QObject
Signal = QtCore.Signal

from lyon.core.library import Track
from lyon.core.player import Player


class FakeStreamBackend(QObject):
    state_changed = Signal(str)
    position_changed = Signal(int, int)
    end_reached = Signal()
    metadata_changed = Signal(dict)
    error_occurred = Signal(str)

    def __init__(self):
        super().__init__()
        self._playing = False

    def set_source(self, path, *, is_location=False, options=()):
        self._playing = False

    def play(self):
        self._playing = True

    def pause(self):
        self._playing = False

    def stop(self):
        self._playing = False

    def position(self):
        return 0

    def duration(self):
        return 0

    def set_position(self, _ms):
        pass

    def set_volume(self, _v):
        pass

    def volume(self):
        return 80

    def set_muted(self, _m):
        pass

    def is_muted(self):
        return False

    def is_playing(self):
        return self._playing

    def apply_equalizer(self, enabled, bands, preamp=0):
        pass

    def cleanup(self):
        self._playing = False


def _library_track() -> Track:
    return Track(
        id=42,
        path="C:/Music/song.flac",
        title="Existing Title",
        artist="Existing Artist",
        album_artist="",
        album="Existing Album",
        track_no=1,
        disc_no=1,
        year=2024,
        genre="Pop",
        duration=180.0,
        media_type="audio",
        is_library_item=True,
    )


def test_backend_metadata_updates_streaming_track_title_and_artist(qapp):
    backend = FakeStreamBackend()
    player = Player(backend=backend)
    track_changed_tracks = []
    stream_metadata_tracks = []
    player.track_changed.connect(track_changed_tracks.append)
    player.stream_metadata_changed.connect(stream_metadata_tracks.append)

    player.play_url("http://stream.example/audio", title="Sea Lyon Jazz")

    track_changed_tracks.clear()
    backend.metadata_changed.emit({
        "now_playing": "Daft Punk - One More Time",
        "title": "One More Time",
        "artist": "Daft Punk",
        "artwork_url": "",
    })

    track = player.current()
    assert track is not None
    assert track.title == "One More Time"
    assert track.artist == "Daft Punk"
    # Station name is preserved in album so the transport bar reads
    # "Daft Punk — Sea Lyon Jazz".
    assert track.album == "Sea Lyon Jazz"
    # ICY updates go via stream_metadata_changed, not track_changed (Fix 4).
    assert len(track_changed_tracks) == 0
    assert len(stream_metadata_tracks) == 1
    assert stream_metadata_tracks[0] is track


def test_backend_metadata_falls_back_to_now_playing_split(qapp):
    backend = FakeStreamBackend()
    player = Player(backend=backend)

    player.play_url("http://stream.example/audio", title="Late Night")
    backend.metadata_changed.emit({
        "now_playing": "Some Artist - Some Song",
        "title": "",
        "artist": "",
        "artwork_url": "",
    })

    track = player.current()
    assert track is not None
    assert track.artist == "Some Artist"
    assert track.title == "Some Song"


def test_backend_metadata_ignored_for_library_tracks(qapp):
    backend = FakeStreamBackend()
    player = Player(backend=backend)
    track = _library_track()
    player.set_queue([track], 0)

    backend.metadata_changed.emit({
        "now_playing": "Other Artist - Other Song",
        "title": "Other Song",
        "artist": "Other Artist",
        "artwork_url": "",
    })

    current = player.current()
    assert current is not None
    assert current.title == "Existing Title"
    assert current.artist == "Existing Artist"
    assert current.album == "Existing Album"


def test_library_metadata_refresh_updates_current_track_without_playback_change(qapp):
    backend = FakeStreamBackend()
    player = Player(backend=backend)
    old_track = _library_track()
    old_track.artwork_path = "old-cover.jpg"
    refreshed_track = _library_track()
    refreshed_track.title = "Retagged Title"
    refreshed_track.artwork_path = "new-cover.jpg"

    track_changes = []
    metadata_changes = []
    queue_changes = []
    player.track_changed.connect(track_changes.append)
    player.track_metadata_changed.connect(metadata_changes.append)
    player.queue_changed.connect(lambda: queue_changes.append(True))

    player.set_queue([old_track], 0)
    track_changes.clear()
    queue_changes.clear()

    assert player.update_library_tracks([refreshed_track]) is True

    assert player.current() is refreshed_track
    assert track_changes == []
    assert metadata_changes == [refreshed_track]
    assert queue_changes == [True]


def test_backend_metadata_with_only_now_playing_no_separator_sets_title_only(qapp):
    backend = FakeStreamBackend()
    player = Player(backend=backend)
    player.play_url("http://stream.example/audio", title="News Radio")

    backend.metadata_changed.emit({
        "now_playing": "Top of the hour newscast",
        "title": "",
        "artist": "",
        "artwork_url": "",
    })

    track = player.current()
    assert track is not None
    assert track.title == "Top of the hour newscast"
    assert track.artist == "Network Stream"  # unchanged placeholder

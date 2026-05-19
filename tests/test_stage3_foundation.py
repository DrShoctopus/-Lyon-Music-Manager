from __future__ import annotations

import pytest

QtCore = pytest.importorskip("PySide6.QtCore", exc_type=ImportError)

from lyon.core.player import Player
from lyon.core.settings import Settings, normalize_stream_urls
from lyon.ui.now_playing import NowPlayingView


class CaptureBackend(QtCore.QObject):
    state_changed = QtCore.Signal(str)
    position_changed = QtCore.Signal(int, int)
    end_reached = QtCore.Signal()

    def __init__(self):
        super().__init__()
        self.source_calls: list[tuple[str, bool, tuple[str, ...]]] = []
        self._volume = 80
        self._muted = False
        self._playing = False

    def set_source(self, path: str, *, is_location=False, options=()) -> None:
        self.source_calls.append((path, is_location, tuple(options)))

    def play(self) -> None:
        self._playing = True

    def pause(self) -> None:
        self._playing = False

    def stop(self) -> None:
        self._playing = False

    def position(self) -> int:
        return 0

    def duration(self) -> int:
        return 0

    def set_position(self, _ms: int) -> None:
        pass

    def set_volume(self, percent: int) -> None:
        self._volume = percent

    def volume(self) -> int:
        return self._volume

    def set_muted(self, muted: bool) -> None:
        self._muted = bool(muted)

    def is_muted(self) -> bool:
        return self._muted

    def is_playing(self) -> bool:
        return self._playing

    def apply_equalizer(self, *_args, **_kwargs) -> None:
        pass


def test_player_play_url_uses_vlc_location_source(qapp):
    backend = CaptureBackend()
    player = Player(backend=backend)

    player.play_url(
        "https://radio.example.test/live",
        title="Example Radio",
        options=(":network-caching=1000",),
    )

    track = player.current()
    assert track is not None
    assert track.title == "Example Radio"
    assert track.artist == "Network Stream"
    assert track.is_library_item is False
    assert track.playback_is_location is True
    assert track.playback_uri == "https://radio.example.test/live"
    assert backend.source_calls == [
        ("https://radio.example.test/live", True, (":network-caching=1000",))
    ]
    assert player.is_playing()


def test_player_play_url_derives_title_from_uri(qapp):
    backend = CaptureBackend()
    player = Player(backend=backend)

    player.play_url("https://streams.example.test/jazz/high.m3u8")

    assert player.current().title == "streams.example.test / high.m3u8"


def test_player_play_url_ignores_blank_uri(qapp):
    backend = CaptureBackend()
    player = Player(backend=backend)

    player.play_url("   ")

    assert player.current() is None
    assert backend.source_calls == []
    assert not player.is_playing()


def test_now_playing_labels_location_stream_without_file_extension():
    backend = CaptureBackend()
    player = Player(backend=backend)
    player.play_url("https://radio.example.test/live")

    assert NowPlayingView._format_strip_text(player.current()) == "Stream"


def test_recent_stream_urls_are_normalized_and_limited():
    urls = normalize_stream_urls(
        [
            "",
            "  https://radio.example.test/live  ",
            "HTTPS://radio.example.test/live",
            "mms://radio.example.test/live",
            "file:///tmp/song.flac",
            "notaurl",
            "rtsp://camera.example.test/channel",
        ],
        limit=3,
    )

    assert urls == [
        "https://radio.example.test/live",
        "mms://radio.example.test/live",
        "rtsp://camera.example.test/channel",
    ]


def test_stage3_settings_defaults_and_clamps():
    settings = Settings(
        recent_stream_urls=[
            "https://radio.example.test/live",
            "notaurl",
            "https://radio.example.test/live",
        ],
        dlna_enabled="yes",
        dlna_port=999_999,
        dlna_friendly_name="  ",
    )

    assert settings.recent_stream_urls == ["https://radio.example.test/live"]
    assert settings.dlna_enabled is True
    assert settings.dlna_port == 65535
    assert settings.dlna_friendly_name == "Sea Lyon Media Manager"


def test_remember_stream_url_moves_valid_url_to_front():
    settings = Settings(
        recent_stream_urls=[
            "https://one.example.test/live",
            "https://two.example.test/live",
        ],
    )

    settings.remember_stream_url(" https://two.example.test/live ")
    settings.remember_stream_url("not-a-url")
    settings.remember_stream_url("https://three.example.test/live")

    assert settings.recent_stream_urls == [
        "https://three.example.test/live",
        "https://two.example.test/live",
        "https://one.example.test/live",
    ]

"""Regression tests for the VLC-backed video player view."""
from __future__ import annotations

import sys
import time
import types

import pytest

QtCore = pytest.importorskip("PySide6.QtCore", exc_type=ImportError)
QtGui = pytest.importorskip("PySide6.QtGui", exc_type=ImportError)
QtWidgets = pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)


class _FakeMedia:
    def __init__(self) -> None:
        self.options: list[str] = []

    def add_option(self, option: str) -> None:
        self.options.append(option)

    def release(self) -> None:
        pass


class _FakeVlcPlayer:
    def __init__(self) -> None:
        self.operations: list[object] = []
        self._media = _FakeMedia()
        self._playing = True
        self._time = 37_000
        self._length = 120_000
        self._volume = 80
        self._muted = False
        self._audio_track = 2
        self._subtitle_track = 5

    def get_media(self):
        return self._media

    def set_media(self, media) -> None:
        self.operations.append("set_media")
        self._media = media

    def is_playing(self) -> bool:
        return self._playing

    def pause(self) -> None:
        self.operations.append("pause")
        self._playing = False

    def stop(self) -> None:
        self.operations.append("stop")
        self._playing = False

    def play(self) -> None:
        self.operations.append("play")
        self._playing = True

    def release(self) -> None:
        self.operations.append("release")

    def get_time(self) -> int:
        return self._time

    def set_time(self, value: int) -> None:
        self.operations.append(("set_time", value))
        self._time = value

    def get_length(self) -> int:
        return self._length

    def get_state(self):
        return "Playing" if self._playing else "Paused"

    def set_rate(self, value: float) -> None:
        self.operations.append(("set_rate", value))

    def audio_set_volume(self, value: int) -> None:
        self.operations.append(("audio_set_volume", value))
        self._volume = value

    def audio_set_mute(self, value: bool) -> None:
        self.operations.append(("audio_set_mute", value))
        self._muted = value

    def audio_get_mute(self) -> bool:
        return self._muted

    def audio_get_track(self) -> int:
        return self._audio_track

    def audio_set_track(self, value: int) -> None:
        self.operations.append(("audio_set_track", value))
        self._audio_track = value

    def audio_get_track_description(self):
        return []

    def video_get_spu(self) -> int:
        return self._subtitle_track

    def video_set_spu(self, value: int) -> None:
        self.operations.append(("video_set_spu", value))
        self._subtitle_track = value

    def video_get_spu_description(self):
        return []

    def video_get_size(self, _index: int):
        return 1920, 1080

    def set_hwnd(self, wid: int) -> None:
        self.operations.append(("set_hwnd", wid))

    def set_xwindow(self, wid: int) -> None:
        self.operations.append(("set_xwindow", wid))

    def set_nsobject(self, wid: int) -> None:
        self.operations.append(("set_nsobject", wid))

    def set_equalizer(self, equalizer) -> None:
        self.operations.append(("set_equalizer", equalizer))

    def video_take_snapshot(self, *_args) -> None:
        pass


class _FakeVlcInstance:
    def __init__(self, player: _FakeVlcPlayer) -> None:
        self._player = player
        self.location_calls: list[str] = []

    def media_player_new(self):
        return self._player

    def media_new_path(self, _path: str):
        return _FakeMedia()

    def media_new_location(self, _uri: str):
        self.location_calls.append(_uri)
        return _FakeMedia()

    def release(self) -> None:
        pass


def _install_fake_vlc(monkeypatch, player: _FakeVlcPlayer) -> None:
    fake_vlc = types.ModuleType("vlc")
    fake_vlc._instance = _FakeVlcInstance(player)
    fake_vlc.Instance = lambda: fake_vlc._instance
    fake_vlc.State = types.SimpleNamespace(Ended="Ended")
    fake_vlc.AudioEqualizer = lambda: None
    fake_vlc.MediaSlaveType = types.SimpleNamespace(Subtitle=0)
    monkeypatch.setitem(sys.modules, "vlc", fake_vlc)


def _process_events(app, duration_ms: int) -> None:
    deadline = time.monotonic() + duration_ms / 1000
    while time.monotonic() < deadline:
        app.processEvents(QtCore.QEventLoop.AllEvents, 50)
        QtCore.QThread.msleep(10)


def _first_output_attach_index(operations: list[object]) -> int:
    output_methods = {"set_hwnd", "set_xwindow", "set_nsobject"}
    return next(
        i
        for i, op in enumerate(operations)
        if isinstance(op, tuple) and op[0] in output_methods
    )


def test_thumbnail_cache_not_stale_when_sidecar_appears(qapp, tmp_path):
    from lyon.ui import video_player_view as video_mod

    video_mod._THUMB_CACHE.clear()
    video = tmp_path / "Clip.mp4"
    video.write_bytes(b"video")

    video_mod._thumb_pixmap(None, str(video), 16, 16)

    thumb = QtGui.QImage(4, 4, QtGui.QImage.Format_RGB32)
    thumb.fill(QtGui.QColor("red"))
    assert thumb.save(str(tmp_path / "Clip.png"))

    pixmap = video_mod._thumb_pixmap(None, str(video), 16, 16)
    color = pixmap.toImage().pixelColor(8, 8)

    assert color.red() > 200
    assert color.green() < 60
    assert color.blue() < 60


def test_fullscreen_handoff_rebuilds_vlc_output_before_resuming(qapp, monkeypatch):
    from lyon.ui import video_player_view as video_mod

    player = _FakeVlcPlayer()
    _install_fake_vlc(monkeypatch, player)
    monkeypatch.setattr(video_mod, "_configure_vlc_runtime_path", lambda: None)

    view = video_mod.VideoPlayerView()
    try:
        player.operations.clear()
        player._playing = True
        player._time = 37_000

        view._enter_fullscreen()
        _process_events(qapp, 350)

        output_idx = _first_output_attach_index(player.operations)
        assert player.operations.index("stop") < output_idx
        assert output_idx < player.operations.index("play")
        assert ("set_time", 37_000) in player.operations
        assert ("set_rate", 1.0) in player.operations
        assert ("audio_set_track", 2) in player.operations
        assert ("video_set_spu", 5) in player.operations
        assert player._playing is True
    finally:
        view.cleanup()
        view.deleteLater()


def test_video_view_can_load_disc_location(qapp, monkeypatch):
    from lyon.ui import video_player_view as video_mod

    player = _FakeVlcPlayer()
    _install_fake_vlc(monkeypatch, player)
    monkeypatch.setattr(video_mod, "_configure_vlc_runtime_path", lambda: None)

    view = video_mod.VideoPlayerView()
    try:
        view.load_location("dvd:///D:/", label="DVD")

        import sys as _sys
        fake_vlc = _sys.modules["vlc"]
        assert fake_vlc._instance.location_calls == ["dvd:///D:/"]
        assert "set_media" in player.operations
        assert "play" in player.operations
    finally:
        view.cleanup()
        view.deleteLater()


def test_fullscreen_handoff_restores_paused_state(qapp, monkeypatch):
    from lyon.ui import video_player_view as video_mod

    player = _FakeVlcPlayer()
    _install_fake_vlc(monkeypatch, player)
    monkeypatch.setattr(video_mod, "_configure_vlc_runtime_path", lambda: None)

    view = video_mod.VideoPlayerView()
    try:
        player.operations.clear()
        player._playing = False
        player._time = 12_000

        view._enter_fullscreen()
        _process_events(qapp, 350)

        assert player.operations.index("play") < player.operations.index("pause")
        assert ("set_time", 12_000) in player.operations
        assert player._playing is False
    finally:
        view.cleanup()
        view.deleteLater()

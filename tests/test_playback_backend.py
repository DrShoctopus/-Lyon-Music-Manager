from __future__ import annotations

import importlib

from lyon.core import playback_backend
from lyon.core.playback_backend import (
    UnavailablePlaybackBackend,
    VlcPlaybackBackend,
    create_playback_backend,
)


def test_create_playback_backend_returns_unavailable_backend_when_python_vlc_missing(monkeypatch):
    real_import_module = importlib.import_module

    def _import_module(name: str, *args, **kwargs):
        if name == "vlc":
            raise ImportError("No module named vlc")
        return real_import_module(name, *args, **kwargs)

    monkeypatch.setattr(playback_backend, "_configure_vlc_runtime_path", lambda: None)
    monkeypatch.setattr(playback_backend.importlib, "import_module", _import_module)

    backend = create_playback_backend()

    assert isinstance(backend, UnavailablePlaybackBackend)
    assert not backend.is_available()
    assert "python-vlc is not importable" in backend.unavailable_reason()


def test_create_playback_backend_returns_unavailable_backend_when_libvlc_fails(monkeypatch):
    class BrokenVlc:
        @staticmethod
        def Instance():
            raise RuntimeError("libVLC not found")

    monkeypatch.setattr(playback_backend, "_configure_vlc_runtime_path", lambda: None)
    monkeypatch.setattr(playback_backend.importlib, "import_module", lambda name: BrokenVlc)

    backend = create_playback_backend()

    assert isinstance(backend, UnavailablePlaybackBackend)
    assert not backend.is_available()
    assert "libVLC runtime could not be initialized" in backend.unavailable_reason()


def test_vlc_backend_uses_path_media_for_regular_files(qapp):
    class Media:
        def __init__(self):
            self.options = []

        def add_option(self, option):
            self.options.append(option)

        def release(self):
            pass

    class Player:
        def __init__(self):
            self.media = None

        def set_media(self, media):
            self.media = media

        def audio_set_volume(self, _value): pass
        def audio_set_mute(self, _value): pass
        def set_equalizer(self, _value): pass
        def stop(self): pass
        def release(self): pass

    class Vlc:
        class State:
            Ended = object()
            Playing = object()
            Paused = object()
            Stopped = object()
            Error = object()

        def __init__(self):
            self.player = Player()
            self.path_calls = []
            self.location_calls = []

        def Instance(self):
            return self

        def media_player_new(self):
            return self.player

        def media_new_path(self, path):
            self.path_calls.append(path)
            return Media()

        def media_new_location(self, uri):
            self.location_calls.append(uri)
            return Media()

        def release(self): pass

        def AudioEqualizer(self):
            return object()

    vlc = Vlc()
    backend = VlcPlaybackBackend(vlc)
    try:
        backend.set_source("C:/Music/song.flac")
        assert vlc.path_calls == ["C:/Music/song.flac"]
        assert vlc.location_calls == []
    finally:
        backend.cleanup()


def test_vlc_backend_uses_location_media_and_options(qapp):
    class Media:
        def __init__(self):
            self.options = []

        def add_option(self, option):
            self.options.append(option)

        def release(self):
            pass

    class Player:
        def __init__(self):
            self.media = None

        def set_media(self, media):
            self.media = media

        def audio_set_volume(self, _value): pass
        def audio_set_mute(self, _value): pass
        def set_equalizer(self, _value): pass
        def stop(self): pass
        def release(self): pass

    class Vlc:
        class State:
            Ended = object()
            Playing = object()
            Paused = object()
            Stopped = object()
            Error = object()

        def __init__(self):
            self.player = Player()
            self.location_calls = []

        def Instance(self):
            return self

        def media_player_new(self):
            return self.player

        def media_new_path(self, _path):
            raise AssertionError("path media should not be used")

        def media_new_location(self, uri):
            self.location_calls.append(uri)
            return Media()

        def release(self): pass

        def AudioEqualizer(self):
            return object()

    vlc = Vlc()
    backend = VlcPlaybackBackend(vlc)
    try:
        backend.set_source("cdda:///D:/", is_location=True, options=(":cdda-track=2",))
        assert vlc.location_calls == ["cdda:///D:/"]
        assert vlc.player.media.options == [":cdda-track=2"]
    finally:
        backend.cleanup()

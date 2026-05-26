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


def test_vlc_backend_stops_position_timer_while_paused(qapp):
    class Player:
        def __init__(self):
            self.calls = []

        def play(self):
            self.calls.append("play")

        def pause(self):
            self.calls.append("pause")

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

        def Instance(self):
            return self

        def media_player_new(self):
            return self.player

        def release(self): pass

        def AudioEqualizer(self):
            return object()

    vlc = Vlc()
    backend = VlcPlaybackBackend(vlc)
    try:
        assert backend._timer.interval() == 500
        assert not backend._timer.isActive()

        backend.play()
        assert backend._timer.isActive()

        backend.pause()
        assert not backend._timer.isActive()
        assert vlc.player.calls == ["play", "pause"]
    finally:
        backend.cleanup()


def test_vlc_backend_does_not_emit_end_for_zero_time_premature_ended_state(qapp):
    class Player:
        def __init__(self):
            self.state = Vlc.State.Ended

        def play(self): pass
        def pause(self): pass
        def stop(self): pass
        def release(self): pass
        def get_state(self): return self.state
        def get_time(self): return 0
        def get_length(self): return 0
        def audio_set_volume(self, _value): pass
        def audio_set_mute(self, _value): pass
        def set_equalizer(self, _value): pass

    class Vlc:
        class State:
            Ended = object()
            Playing = object()
            Paused = object()
            Stopped = object()
            Error = object()

        def __init__(self):
            self.player = Player()

        def Instance(self):
            return self

        def media_player_new(self):
            return self.player

        def release(self): pass

        def AudioEqualizer(self):
            return object()

    vlc = Vlc()
    backend = VlcPlaybackBackend(vlc)
    ended: list[bool] = []
    states: list[str] = []
    positions: list[tuple[int, int]] = []
    backend.end_reached.connect(lambda: ended.append(True))
    backend.state_changed.connect(states.append)
    backend.position_changed.connect(lambda pos, dur: positions.append((pos, dur)))

    try:
        backend.play()
        states.clear()
        backend._poll()

        assert ended == []
        assert states == ["stopped"]
        assert positions == [(0, 0)]
        assert not backend._timer.isActive()
    finally:
        backend.cleanup()


def test_vlc_backend_emits_end_after_playing_state_was_observed(qapp):
    class Player:
        def __init__(self):
            self.state = Vlc.State.Playing
            self.time = 1000
            self.length = 2000

        def play(self): pass
        def pause(self): pass
        def stop(self): pass
        def release(self): pass
        def get_state(self): return self.state
        def get_time(self): return self.time
        def get_length(self): return self.length
        def audio_set_volume(self, _value): pass
        def audio_set_mute(self, _value): pass
        def set_equalizer(self, _value): pass

    class Vlc:
        class State:
            Ended = object()
            Playing = object()
            Paused = object()
            Stopped = object()
            Error = object()

        def __init__(self):
            self.player = Player()

        def Instance(self):
            return self

        def media_player_new(self):
            return self.player

        def release(self): pass

        def AudioEqualizer(self):
            return object()

    vlc = Vlc()
    backend = VlcPlaybackBackend(vlc)
    ended: list[bool] = []
    backend.end_reached.connect(lambda: ended.append(True))

    try:
        backend._poll()
        vlc.player.state = Vlc.State.Ended
        vlc.player.time = 2000
        backend._poll()

        assert ended == [True]
    finally:
        backend.cleanup()


def test_vlc_backend_lists_audio_outputs_from_pointer_list(qapp):
    class Player:
        def stop(self): pass
        def release(self): pass

    class Pointer:
        def __init__(self, contents):
            self.contents = contents

        def __bool__(self):
            return True

    class Output:
        def __init__(self, name, description, next_node=None):
            self.name = name
            self.description = description
            self.next = next_node

    class Vlc:
        class State:
            Ended = object()
            Playing = object()
            Paused = object()
            Stopped = object()
            Error = object()

        def __init__(self):
            self.player = Player()
            self.released = None
            self.head = Pointer(Output(
                b"wasapi",
                b"Windows Audio",
                Pointer(Output(b"directsound", None)),
            ))

        def Instance(self):
            return self

        def media_player_new(self):
            return self.player

        def audio_output_list_get(self):
            return self.head

        def libvlc_audio_output_list_release(self, head):
            self.released = head

        def release(self): pass

    vlc = Vlc()
    backend = VlcPlaybackBackend(vlc)
    try:
        assert backend.list_audio_outputs() == [
            ("", "Default"),
            ("wasapi", "Windows Audio"),
            ("directsound", "directsound"),
        ]
        assert vlc.released is vlc.head
    finally:
        backend.cleanup()


def test_vlc_backend_lists_audio_devices_from_pointer_list(qapp):
    class Player:
        def stop(self): pass
        def release(self): pass

    class Pointer:
        def __init__(self, contents):
            self.contents = contents

        def __bool__(self):
            return True

    class Device:
        def __init__(self, device, description, next_node=None):
            self.device = device
            self.description = description
            self.next = next_node

    class Vlc:
        class State:
            Ended = object()
            Playing = object()
            Paused = object()
            Stopped = object()
            Error = object()

        def __init__(self):
            self.player = Player()
            self.requested_output = None
            self.released = None
            self.head = Pointer(Device(
                b"speaker-id",
                b"Speakers",
                Pointer(Device("hdmi-id", "")),
            ))

        def Instance(self):
            return self

        def media_player_new(self):
            return self.player

        def audio_output_device_list_get(self, audio_output):
            self.requested_output = audio_output
            return self.head

        def libvlc_audio_output_device_list_release(self, head):
            self.released = head

        def release(self): pass

    vlc = Vlc()
    backend = VlcPlaybackBackend(vlc)
    try:
        assert backend.list_audio_devices("wasapi") == [
            ("", "Default"),
            ("speaker-id", "Speakers"),
            ("hdmi-id", "hdmi-id"),
        ]
        assert vlc.requested_output == "wasapi"
        assert vlc.released is vlc.head
    finally:
        backend.cleanup()


# ---- ICY metadata + error event plumbing -----------------------------------


class _FakeEventManager:
    """Fake VLC event manager that records attach/detach calls."""

    def __init__(self):
        self.attached = []   # list[(event_type, callback)]
        self.detached = []   # list[event_type]

    def event_attach(self, event_type, callback):
        self.attached.append((event_type, callback))

    def event_detach(self, event_type):
        self.detached.append(event_type)


class _FakeMetaMedia:
    """Fake VLC media supporting get_meta + event_manager."""

    def __init__(self, meta=None):
        self._meta = dict(meta or {})
        self.event_mgr = _FakeEventManager()
        self.options = []
        self.released = False

    def add_option(self, option):
        self.options.append(option)

    def get_meta(self, attr):
        return self._meta.get(attr, "")

    def event_manager(self):
        return self.event_mgr

    def release(self):
        self.released = True


def _fake_meta_vlc(media_factory):
    """Build a fake vlc module wired with the given media factory."""

    class Player:
        def __init__(self):
            self.media = None
            self.state = Vlc.State.Playing

        def set_media(self, media):
            self.media = media

        def get_state(self):
            return self.state

        def get_time(self):
            return 0

        def get_length(self):
            return 0

        def play(self):
            return 0

        def pause(self): pass
        def stop(self): pass
        def release(self): pass
        def audio_set_volume(self, _value): pass
        def audio_set_mute(self, _value): pass
        def set_equalizer(self, _value): pass

    class MetaCls:
        NowPlaying = "now_playing"
        Title = "title"
        Artist = "artist"
        ArtworkURL = "artwork_url"

    class EventTypeCls:
        MediaMetaChanged = "media-meta-changed"

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
            return media_factory()

        def media_new_location(self, uri):
            self.location_calls.append(uri)
            return media_factory()

        def release(self): pass
        def AudioEqualizer(self):
            return object()

    Vlc.Meta = MetaCls
    Vlc.EventType = EventTypeCls
    return Vlc()


def test_vlc_backend_emits_metadata_on_meta_event(qapp):
    media_holder = {}

    def factory():
        media = _FakeMetaMedia({
            "now_playing": "Daft Punk - One More Time",
            "title": "One More Time",
            "artist": "Daft Punk",
        })
        media_holder["last"] = media
        return media

    vlc = _fake_meta_vlc(factory)
    backend = VlcPlaybackBackend(vlc)
    received = []
    backend.metadata_changed.connect(received.append)
    try:
        backend.set_source("http://stream.example/audio", is_location=True)
        media = media_holder["last"]
        assert media.event_mgr.attached, "media event handler should be attached"

        event_type, handler = media.event_mgr.attached[0]
        assert event_type == "media-meta-changed"

        # Simulate VLC firing the meta event and the QTimer dispatching.
        handler(object())
        backend._emit_pending_metadata()

        assert received == [{
            "now_playing": "Daft Punk - One More Time",
            "title": "One More Time",
            "artist": "Daft Punk",
            "artwork_url": "",
        }]
    finally:
        backend.cleanup()


def test_vlc_backend_does_not_re_emit_unchanged_metadata(qapp):
    def factory():
        return _FakeMetaMedia({"title": "Same Song", "artist": "Same Artist"})

    vlc = _fake_meta_vlc(factory)
    backend = VlcPlaybackBackend(vlc)
    received = []
    backend.metadata_changed.connect(received.append)
    try:
        backend.set_source("http://stream.example/audio", is_location=True)
        backend._emit_pending_metadata()
        backend._emit_pending_metadata()
        assert len(received) == 1
    finally:
        backend.cleanup()


def test_vlc_backend_detaches_meta_events_on_new_source(qapp):
    media_holder = {"all": []}

    def factory():
        media = _FakeMetaMedia()
        media_holder["all"].append(media)
        return media

    vlc = _fake_meta_vlc(factory)
    backend = VlcPlaybackBackend(vlc)
    try:
        backend.set_source("http://one.example/audio", is_location=True)
        backend.set_source("http://two.example/audio", is_location=True)
        first = media_holder["all"][0]
        assert first.event_mgr.detached == ["media-meta-changed"]
    finally:
        backend.cleanup()


def test_vlc_backend_emits_error_event_when_state_becomes_error(qapp):
    def factory():
        return _FakeMetaMedia()

    vlc = _fake_meta_vlc(factory)
    backend = VlcPlaybackBackend(vlc)
    received = []
    backend.error_occurred.connect(received.append)
    try:
        backend.set_source("http://broken.example/audio", is_location=True)
        vlc.player.state = vlc.State.Error
        backend._poll()
        backend._poll()  # second poll must not re-emit for the same source
        assert received == ["http://broken.example/audio"]

        backend.set_source("http://other.example/audio", is_location=True)
        vlc.player.state = vlc.State.Error
        backend._poll()
        assert received == [
            "http://broken.example/audio",
            "http://other.example/audio",
        ]
    finally:
        backend.cleanup()

from __future__ import annotations

import importlib

from lyon.core import playback_backend
from lyon.core.playback_backend import UnavailablePlaybackBackend, create_playback_backend


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

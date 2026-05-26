"""Shared test fixtures.

Phase 8 introduced two shared fixtures:
- `qapp`         module-scoped QApplication for any test that needs widgets.
- `fake_backend` factory for a Player-compatible stub that needs no libVLC.

Existing per-file FakeBackend definitions (test_transport.py,
test_dialog_consistency.py, test_player_equalizer.py) still work; the
shared fixture is the canonical version for new tests.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Make sure every Qt-based test runs headless before PySide6 is imported.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(autouse=True)
def isolated_app_data_dir(monkeypatch, tmp_path):
    """Keep tests from reading or writing the user's real app settings."""
    from lyon.core import library as library_mod
    from lyon.core import settings as settings_mod

    app_data = tmp_path / "app-data"
    app_data.mkdir()
    monkeypatch.setattr(settings_mod, "app_data_dir", lambda: app_data)
    monkeypatch.setattr(library_mod, "app_data_dir", lambda: app_data)
    settings_mod.invalidate_settings_cache()
    yield
    settings_mod.invalidate_settings_cache()


@pytest.fixture(scope="module")
def qapp():
    """Module-scoped QApplication — only one can exist per process."""
    QtWidgets = pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)
    existing = QtWidgets.QApplication.instance()
    if existing is not None:
        return existing
    return QtWidgets.QApplication([])


@pytest.fixture
def fake_backend():
    """Return a Player-compatible stub backend (no libVLC required)."""
    QtCore = pytest.importorskip("PySide6.QtCore", exc_type=ImportError)

    class FakeBackend(QtCore.QObject):
        state_changed = QtCore.Signal(str)
        position_changed = QtCore.Signal(int, int)
        end_reached = QtCore.Signal()

        def __init__(self):
            super().__init__()
            self._volume = 80
            self._muted = False
            self._playing = False
            self._position = 0
            self._duration = 0

        def set_source(self, _path, *, is_location=False, options=()): pass
        def play(self): self._playing = True
        def pause(self): self._playing = False
        def stop(self): self._playing = False
        def position(self): return self._position
        def duration(self): return self._duration
        def set_position(self, ms): self._position = ms
        def set_volume(self, percent): self._volume = percent
        def volume(self): return self._volume
        def set_muted(self, muted): self._muted = muted
        def is_muted(self): return self._muted
        def is_playing(self): return self._playing
        def apply_equalizer(self, *_a, **_k): pass

    return FakeBackend()

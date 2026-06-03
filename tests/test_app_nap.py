"""Tests for the macOS App Nap playback guard.

The guard must be safe and idempotent on every platform; off macOS it degrades
to a no-op. Cross-platform tests therefore assert behaviour that holds
everywhere (no exceptions, inactive after release); the macOS-only test proves
the Objective-C bridge actually takes an assertion.
"""
from __future__ import annotations

import sys

import pytest
from lyon.core.app_nap import PlaybackActivityGuard


def test_release_before_acquire_is_safe():
    guard = PlaybackActivityGuard()
    guard.release()  # must not raise
    assert guard.active is False


def test_acquire_release_idempotent():
    guard = PlaybackActivityGuard()
    guard.acquire()
    guard.acquire()  # second acquire is a no-op
    guard.release()
    guard.release()  # second release is a no-op
    assert guard.active is False


@pytest.mark.skipif(sys.platform != "darwin", reason="activity assertions are macOS-only")
def test_acquire_takes_assertion_on_macos():
    guard = PlaybackActivityGuard()
    guard.acquire()
    try:
        assert guard.active is True
    finally:
        guard.release()
    assert guard.active is False

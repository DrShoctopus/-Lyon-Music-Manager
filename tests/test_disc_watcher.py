from __future__ import annotations

import threading
import time


def test_macos_drive_poll_does_not_block_qt_thread(qapp, monkeypatch):
    from lyon.core import disc_macos, disc_watcher
    from lyon.core.disc_watcher import OpticalDriveWatcher

    monkeypatch.setattr(disc_watcher.sys, "platform", "darwin")
    release_scan = threading.Event()

    def slow_list_optical_drives():
        release_scan.wait(0.25)
        return []

    monkeypatch.setattr(disc_macos, "list_optical_drives", slow_list_optical_drives)
    monkeypatch.setattr(disc_macos, "has_audio_disc", lambda _drive: False)

    watcher = OpticalDriveWatcher()
    watcher._stopped = False
    started_at = time.perf_counter()
    try:
        watcher._poll()
        elapsed = time.perf_counter() - started_at
        assert elapsed < 0.05
    finally:
        release_scan.set()
        deadline = time.perf_counter() + 1.0
        while getattr(watcher, "_poll_in_flight", False) and time.perf_counter() < deadline:
            qapp.processEvents()
            time.sleep(0.01)
        watcher.stop()
        watcher.deleteLater()

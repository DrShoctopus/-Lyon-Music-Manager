"""Live optical-drive presence notifications for macOS.

Polls IOKit on a 1 s QTimer. Optical-media changes are not latency-critical
(drives take several seconds to spin up), so a simple poll is more robust than
wiring a DiskArbitration CFRunLoop into Qt's event loop.
"""
from __future__ import annotations

import sys
from typing import Optional

from PySide6.QtCore import QObject, Signal, QTimer


class OpticalDriveWatcher(QObject):
    """Emits signals when optical drive presence or media state changes."""

    drives_changed = Signal()   # a drive appeared or disappeared
    media_changed = Signal(str) # bsd_name of drive whose media state changed

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._poll_timer = QTimer(self)
        # Optical-media changes are not latency-critical (drives take several
        # seconds to spin up), so a 1 s poll is responsive enough.
        self._poll_timer.setInterval(1000)
        self._poll_timer.timeout.connect(self._poll)
        # Snapshot of (bsd_name, has_audio_disc) pairs from the last poll
        self._last_drives: set[str] = set()
        self._last_audio: dict[str, bool] = {}

    def start(self) -> None:
        if sys.platform != "darwin":
            return
        # Skip background polling during automated tests to avoid interfering
        # with other test cases running in the same process.
        import os
        if os.environ.get("PYTEST_CURRENT_TEST"):
            return
        self._poll_timer.start()

    def stop(self) -> None:
        self._poll_timer.stop()

    # ------------------------------------------------------------------
    # Polling
    # ------------------------------------------------------------------

    def _poll(self) -> None:
        if sys.platform != "darwin":
            return
        try:
            from .disc_macos import list_optical_drives, has_audio_disc
        except ImportError:
            return

        drives = list_optical_drives()
        current_bsds = {d.bsd_name for d in drives}

        if current_bsds != self._last_drives:
            self._last_drives = current_bsds
            self.drives_changed.emit()

        for drive in drives:
            audio = has_audio_disc(drive)
            prev = self._last_audio.get(drive.bsd_name)
            if prev != audio:
                self._last_audio[drive.bsd_name] = audio
                self.media_changed.emit(drive.bsd_name)

        # Remove entries for drives that have disappeared
        for gone in set(self._last_audio) - current_bsds:
            del self._last_audio[gone]

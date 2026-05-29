"""Live optical-drive presence notifications for macOS.

Polls diskutil on a 1 s QTimer. Optical-media changes are not latency-critical
(drives take several seconds to spin up), so a simple poll is more robust than
wiring a DiskArbitration CFRunLoop into Qt's event loop.
"""
from __future__ import annotations

import sys
import threading
from typing import Optional

from PySide6.QtCore import QObject, Signal, QTimer


class OpticalDriveWatcher(QObject):
    """Emits signals when optical drive presence or media state changes."""

    drives_changed = Signal()   # a drive appeared or disappeared
    media_changed = Signal(str) # bsd_name of drive whose media state changed
    _poll_finished = Signal(object, object)

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
        self._poll_in_flight = False
        self._stopped = True
        self._poll_thread: threading.Thread | None = None
        self._poll_finished.connect(self._on_poll_finished)

    def start(self) -> None:
        if sys.platform != "darwin":
            return
        # Skip background polling during automated tests to avoid interfering
        # with other test cases running in the same process.
        import os
        if os.environ.get("PYTEST_CURRENT_TEST"):
            return
        self._stopped = False
        self._poll_timer.start()

    def stop(self) -> None:
        self._stopped = True
        self._poll_timer.stop()

    # ------------------------------------------------------------------
    # Polling
    # ------------------------------------------------------------------

    def _poll(self) -> None:
        if sys.platform != "darwin" or self._stopped or self._poll_in_flight:
            return
        self._poll_in_flight = True
        self._poll_thread = threading.Thread(
            target=self._run_poll,
            name="LyonOpticalDrivePoll",
            daemon=True,
        )
        self._poll_thread.start()

    def _run_poll(self) -> None:
        drives = []
        audio: dict[str, bool] = {}
        try:
            from .disc_macos import list_optical_drives, has_audio_disc
        except ImportError:
            self._poll_finished.emit(drives, audio)
            return

        if sys.platform == "darwin" and not self._stopped:
            try:
                drives = list_optical_drives()
            except Exception:
                drives = []
            for drive in drives:
                if self._stopped:
                    break
                try:
                    audio[drive.bsd_name] = has_audio_disc(drive)
                except Exception:
                    audio[drive.bsd_name] = False

        self._poll_finished.emit(drives, audio)

    def _on_poll_finished(self, drives: object, audio: object) -> None:
        self._poll_in_flight = False
        self._poll_thread = None
        if self._stopped or sys.platform != "darwin":
            return
        if not isinstance(audio, dict):
            audio = {}
        current_bsds = {d.bsd_name for d in drives}

        if current_bsds != self._last_drives:
            self._last_drives = current_bsds
            self.drives_changed.emit()

        for drive in drives:
            has_audio = bool(audio.get(drive.bsd_name, False))
            prev = self._last_audio.get(drive.bsd_name)
            if prev != has_audio:
                self._last_audio[drive.bsd_name] = has_audio
                self.media_changed.emit(drive.bsd_name)

        # Remove entries for drives that have disappeared
        for gone in set(self._last_audio) - current_bsds:
            del self._last_audio[gone]

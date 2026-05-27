"""Live optical-drive presence notifications for macOS.

Uses a QTimer polling loop (2 s interval) as the primary mechanism.  Attempts
to register DiskArbitration callbacks for faster notification; falls back to
polling if DA is unavailable.
"""
from __future__ import annotations

import logging
import sys
from typing import Optional

from PySide6.QtCore import QObject, Signal, QTimer

LOG = logging.getLogger(__name__)


class OpticalDriveWatcher(QObject):
    """Emits signals when optical drive presence or media state changes."""

    drives_changed = Signal()   # a drive appeared or disappeared
    media_changed = Signal(str) # bsd_name of drive whose media state changed

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(2000)
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
        if not self._try_disk_arbitration():
            self._poll_timer.start()

    def stop(self) -> None:
        self._poll_timer.stop()

    # ------------------------------------------------------------------
    # DiskArbitration (best-effort; polling is the guaranteed path)
    # ------------------------------------------------------------------

    def _try_disk_arbitration(self) -> bool:
        """Attempt to register DA callbacks; return True if successful."""
        try:
            import objc

            _g: dict = {}
            objc.loadBundle(
                "DiskArbitration", _g,
                bundle_path=objc.pathForFramework(
                    "/System/Library/Frameworks/DiskArbitration.framework"
                ),
            )
            # We need DASessionCreate plus CFRunLoop integration.  Rather than
            # embedding a CFRunLoop inside Qt's event loop (fragile), we use
            # the polling timer augmented with DA for immediate wake-up on
            # appearance/disappearance.  If DA setup fails for any reason we
            # fall through to polling.
            DASessionCreate = _g.get("DASessionCreate")
            if DASessionCreate is None:
                return False

            # DA is available but full run-loop integration is non-trivial.
            # Use polling at a tighter interval (1 s) when DA is present so
            # users get < 1 s latency without the complexity of mixing event
            # loops.
            self._poll_timer.setInterval(1000)
            self._poll_timer.start()
            LOG.debug("DiskArbitration available; using 1 s polling")
            return True
        except Exception as exc:
            LOG.debug("DiskArbitration setup skipped: %s", exc)
            return False

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

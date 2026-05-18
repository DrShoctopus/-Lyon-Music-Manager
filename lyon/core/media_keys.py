"""macOS global media key handler.

Requires PyObjC (``pip install pyobjc-framework-Cocoa``).
Silently no-ops on other platforms or when PyObjC is not installed.
"""
from __future__ import annotations

import sys


def register_media_key_handler(player: object) -> object | None:
    """Install a global NSEvent monitor for media keys.

    Returns the opaque monitor handle (keep a reference to prevent GC),
    or ``None`` when not on macOS or PyObjC is unavailable.
    """
    if sys.platform != "darwin":
        return None
    try:
        import AppKit  # type: ignore[import]
    except ImportError:
        return None

    # NSSystemDefined = 14; subtype 8 = media key event
    _NSSystemDefined = 14

    def _handle(event) -> None:
        try:
            if event.subtype() != 8:
                return
            data1 = event.data1()
            key_code = (data1 & 0xFFFF0000) >> 16
            key_flags = data1 & 0x0000FFFF
            key_down = (key_flags & 0xFF00) >> 8
            if key_down != 0xA:  # key-down only
                return
            if key_code == 16:   # Play/Pause
                player.toggle()  # type: ignore[attr-defined]
            elif key_code == 17: # Fast-forward / Next
                player.next()    # type: ignore[attr-defined]
            elif key_code == 18: # Rewind / Previous
                player.previous()  # type: ignore[attr-defined]
        except Exception:
            pass

    try:
        monitor = AppKit.NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(
            1 << _NSSystemDefined, _handle
        )
        return monitor
    except Exception:
        return None

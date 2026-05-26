"""Global media key handlers for supported desktop platforms.

macOS uses PyObjC's NSEvent monitor when available. Windows uses Qt's
native event filter to handle WM_APPCOMMAND media keys.
"""
from __future__ import annotations

import sys

_WM_APPCOMMAND = 0x0319

_APPCOMMAND_MEDIA_NEXTTRACK = 11
_APPCOMMAND_MEDIA_PREVIOUSTRACK = 12
_APPCOMMAND_MEDIA_STOP = 13
_APPCOMMAND_MEDIA_PLAY_PAUSE = 14


def _command_from_lparam(lparam: int) -> int:
    """Return the APPCOMMAND value stored in the high word of LPARAM."""
    return (int(lparam) >> 16) & 0xFFFF


def _dispatch_app_command(player: object, command: int) -> bool:
    """Route a Windows APPCOMMAND media key to the player."""
    actions = {
        _APPCOMMAND_MEDIA_PLAY_PAUSE: "toggle",
        _APPCOMMAND_MEDIA_NEXTTRACK: "next",
        _APPCOMMAND_MEDIA_PREVIOUSTRACK: "previous",
        _APPCOMMAND_MEDIA_STOP: "stop",
    }
    method_name = actions.get(command)
    if method_name is None:
        return False
    try:
        getattr(player, method_name)()
    except Exception:
        pass
    return True


class _MacMediaKeyHandler:
    def __init__(self, appkit: object, monitor: object) -> None:
        self._appkit = appkit
        self._monitor = monitor

    def close(self) -> None:
        monitor = self._monitor
        if monitor is None:
            return
        self._monitor = None
        try:
            self._appkit.NSEvent.removeMonitor_(monitor)  # type: ignore[attr-defined]
        except Exception:
            pass


def _register_macos_media_key_handler(player: object) -> object | None:
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
        return _MacMediaKeyHandler(AppKit, monitor)
    except Exception:
        return None


def _windows_message_fields(message: object) -> tuple[int, int] | None:
    try:
        pointer = int(message)  # PySide exposes MSG* as an integer-like void pointer.
    except (TypeError, ValueError):
        return None
    if pointer == 0:
        return None

    import ctypes
    from ctypes import wintypes

    class _MSG(ctypes.Structure):
        _fields_ = [
            ("hwnd", wintypes.HWND),
            ("message", wintypes.UINT),
            ("wParam", wintypes.WPARAM),
            ("lParam", wintypes.LPARAM),
            ("time", wintypes.DWORD),
            ("pt", wintypes.POINT),
        ]

    try:
        msg = ctypes.cast(pointer, ctypes.POINTER(_MSG)).contents
    except Exception:
        return None
    return int(msg.message), int(msg.lParam)


def _build_windows_media_key_handler(player: object) -> object | None:
    try:
        from PySide6.QtCore import QAbstractNativeEventFilter, QCoreApplication
    except ImportError:
        return None

    class _WindowsMediaKeyHandler(QAbstractNativeEventFilter):
        def __init__(self, player: object) -> None:
            super().__init__()
            self._player = player
            self._installed = False

        def install(self) -> bool:
            app = QCoreApplication.instance()
            if app is None:
                return False
            app.installNativeEventFilter(self)
            self._installed = True
            return True

        def close(self) -> None:
            if not self._installed:
                return
            self._installed = False
            app = QCoreApplication.instance()
            if app is None:
                return
            try:
                app.removeNativeEventFilter(self)
            except Exception:
                pass

        def nativeEventFilter(self, event_type, message):  # noqa: N802
            del event_type
            fields = _windows_message_fields(message)
            if fields is None:
                return False, 0
            message_id, lparam = fields
            if message_id != _WM_APPCOMMAND:
                return False, 0
            command = _command_from_lparam(lparam)
            if _dispatch_app_command(self._player, command):
                return True, 1
            return False, 0

    return _WindowsMediaKeyHandler(player)


def _register_windows_media_key_handler(player: object) -> object | None:
    handler = _build_windows_media_key_handler(player)
    if handler is None:
        return None
    try:
        if handler.install():  # type: ignore[attr-defined]
            return handler
    except Exception:
        return None
    return None


def register_media_key_handler(player: object) -> object | None:
    """Install a platform media key handler.

    Returns the platform handler object (keep a reference to prevent GC),
    or ``None`` when the current platform is unsupported or unavailable.
    """
    if sys.platform == "darwin":
        return _register_macos_media_key_handler(player)
    if sys.platform == "win32":
        return _register_windows_media_key_handler(player)
    return None

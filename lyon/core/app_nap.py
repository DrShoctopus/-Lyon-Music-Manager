"""macOS App Nap suppression during audio playback.

A Finder/Dock-launched ``.app`` on macOS is eligible for App Nap: when the app
is occluded or looks idle, the system coalesces its timers and demotes thread
QoS. That intermittently starves libVLC's real-time audio feeder thread and
produces audible pops in the middle of a track. Processes launched from a
terminal are exempt, which is why running Lyon from source never reproduced it.

The supported, reliable way to opt out is an ``NSProcessInfo`` *activity
assertion* held for the duration of latency-critical work -- not the
``NSAppSleepDisabled`` Info.plist / user-default flag, which modern macOS often
ignores. We hold the assertion only while audio is actually playing, so the app
can still nap (and the Mac can still idle-sleep) when paused or stopped.

The Objective-C runtime is driven through :mod:`ctypes` so the bundle needs no
PyObjC dependency. Everything here is defensive: any failure degrades to a
no-op and never interrupts playback.
"""
from __future__ import annotations

import logging
import sys
from typing import Optional

LOG = logging.getLogger(__name__)

# NSActivityOptions, from <Foundation/NSProcessInfo.h>.
_NS_ACTIVITY_IDLE_SYSTEM_SLEEP_DISABLED = 1 << 20
_NS_ACTIVITY_USER_INITIATED = 0x00FFFFFF | _NS_ACTIVITY_IDLE_SYSTEM_SLEEP_DISABLED
_NS_ACTIVITY_LATENCY_CRITICAL = 0xFF00000000
# "User initiated, latency critical": opt out of App Nap and timer coalescing
# and flag the work as timing-sensitive. UserInitiated also holds off idle
# *system* sleep, which is what a music player wants mid-track.
_PLAYBACK_ACTIVITY_OPTIONS = _NS_ACTIVITY_USER_INITIATED | _NS_ACTIVITY_LATENCY_CRITICAL


class _ObjCRuntime:
    """Minimal ctypes bridge to ``[[NSProcessInfo processInfo] beginActivity...]``."""

    _instance: Optional[_ObjCRuntime] = None
    _resolved = False

    @classmethod
    def shared(cls) -> Optional[_ObjCRuntime]:
        if not cls._resolved:
            cls._resolved = True
            try:
                cls._instance = cls()
            except Exception as exc:  # noqa: BLE001 - never break playback
                LOG.debug("Obj-C runtime unavailable; App Nap guard disabled: %s", exc)
                cls._instance = None
        return cls._instance

    def __init__(self) -> None:
        import ctypes
        import ctypes.util

        objc_path = ctypes.util.find_library("objc")
        if objc_path is None:
            raise OSError("libobjc not found")
        objc = ctypes.CDLL(objc_path)
        # Ensure Foundation is loaded so NSProcessInfo / NSString are registered.
        foundation_path = ctypes.util.find_library("Foundation")
        if foundation_path is not None:
            ctypes.CDLL(foundation_path)

        objc.objc_getClass.restype = ctypes.c_void_p
        objc.objc_getClass.argtypes = [ctypes.c_char_p]
        objc.sel_registerName.restype = ctypes.c_void_p
        objc.sel_registerName.argtypes = [ctypes.c_char_p]

        self._ctypes = ctypes
        self._objc = objc

        process_info_cls = objc.objc_getClass(b"NSProcessInfo")
        if not process_info_cls:
            raise OSError("NSProcessInfo class not found")
        self._process_info = self._send(process_info_cls, b"processInfo", restype=ctypes.c_void_p)
        if not self._process_info:
            raise OSError("[NSProcessInfo processInfo] returned nil")
        self._ns_string_cls = objc.objc_getClass(b"NSString")
        if not self._ns_string_cls:
            raise OSError("NSString class not found")

    def _send(self, receiver, selector, *, restype, argtypes=(), args=()):
        # objc_msgSend is variadic; on arm64 every call MUST declare its exact
        # signature or arguments are passed incorrectly. Set it per call (safe
        # because all calls happen on the GUI thread).
        ctypes = self._ctypes
        msg = self._objc.objc_msgSend
        msg.restype = restype
        msg.argtypes = [ctypes.c_void_p, ctypes.c_void_p, *argtypes]
        return msg(receiver, self._objc.sel_registerName(selector), *args)

    def begin_activity(self, options: int, reason: str) -> int:
        ctypes = self._ctypes
        reason_obj = self._send(
            self._ns_string_cls,
            b"stringWithUTF8String:",
            restype=ctypes.c_void_p,
            argtypes=[ctypes.c_char_p],
            args=[reason.encode("utf-8")],
        )
        token = self._send(
            self._process_info,
            b"beginActivityWithOptions:reason:",
            restype=ctypes.c_void_p,
            argtypes=[ctypes.c_uint64, ctypes.c_void_p],
            args=[options, reason_obj],
        )
        if not token:
            raise OSError("beginActivityWithOptions:reason: returned nil")
        # The token is autoreleased; retain it so the assertion outlives this
        # call (the GUI run loop would otherwise drain the pool and free it).
        retained = self._send(token, b"retain", restype=ctypes.c_void_p)
        return retained or token

    def end_activity(self, token: int) -> None:
        self._send(
            self._process_info,
            b"endActivity:",
            restype=None,
            argtypes=[self._ctypes.c_void_p],
            args=[token],
        )
        # Balance the retain taken in begin_activity.
        self._send(token, b"release", restype=None)


class PlaybackActivityGuard:
    """Holds a macOS activity assertion while audio is playing.

    :meth:`acquire` and :meth:`release` are idempotent and cheap, so they are
    safe to call from the GUI thread on every play/pause/stop transition.
    Off macOS -- or if the Objective-C bridge can't be initialised -- every
    method is a no-op.
    """

    def __init__(self) -> None:
        self._runtime = _ObjCRuntime.shared() if sys.platform == "darwin" else None
        self._token: Optional[int] = None

    @property
    def active(self) -> bool:
        return self._token is not None

    def acquire(self, reason: str = "Audio playback") -> None:
        if self._runtime is None or self._token is not None:
            return
        try:
            self._token = self._runtime.begin_activity(_PLAYBACK_ACTIVITY_OPTIONS, reason)
        except Exception as exc:  # noqa: BLE001 - never break playback
            LOG.debug("Could not begin App Nap activity assertion: %s", exc)
            self._token = None

    def release(self) -> None:
        if self._runtime is None or self._token is None:
            return
        token, self._token = self._token, None
        try:
            self._runtime.end_activity(token)
        except Exception as exc:  # noqa: BLE001 - never break teardown
            LOG.debug("Could not end App Nap activity assertion: %s", exc)

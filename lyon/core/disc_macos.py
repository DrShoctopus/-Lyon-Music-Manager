"""macOS optical-drive detection via IOKit + DiskArbitration.

Imported only on darwin; all public symbols are import-safe on other platforms
(functions return empty/False, nothing crashes).
"""
from __future__ import annotations

import logging
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class MacOpticalDrive:
    bsd_name: str        # e.g. "disk4"
    device_path: str     # "/dev/disk4"
    raw_path: str        # "/dev/rdisk4"
    vendor: str
    product: str
    is_ejectable: bool


def list_optical_drives() -> list[MacOpticalDrive]:
    """Return all currently-attached optical drives (empty list on non-darwin)."""
    if sys.platform != "darwin":
        return []
    try:
        return _enumerate_via_iokit()
    except Exception as exc:
        LOG.debug("IOKit optical drive enumeration failed, trying diskutil: %s", exc)
        return _enumerate_via_diskutil()


def has_audio_disc(drive: MacOpticalDrive) -> bool:
    """True if the drive contains an Audio CD right now."""
    if sys.platform != "darwin":
        return False
    return _check_audio_cd(drive.device_path)


def eject_drive(drive: MacOpticalDrive) -> bool:
    if sys.platform != "darwin":
        return False
    try:
        subprocess.run(
            ["/usr/sbin/diskutil", "eject", drive.device_path],
            check=True, timeout=15,
        )
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        LOG.warning("diskutil eject failed for %s: %s", drive.bsd_name, exc)
        return False


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

# IOKit's framework bundle and its BridgeSupport-defined C functions are loaded
# once and cached here. The optical-drive watcher calls _enumerate_via_iokit()
# on a ~1 s poll for the life of the app; re-running objc.loadBundle on every
# call re-parses IOKit's BridgeSupport and allocates a fresh set of PyObjC
# function wrappers each time, which steadily grows resident memory. Loading the
# bundle a single time keeps the symbol table stable.
_IOKIT_SYMBOLS: dict | None = None


def _load_iokit() -> dict:
    """Load IOKit's C function table once and reuse it across enumerations."""
    global _IOKIT_SYMBOLS
    if _IOKIT_SYMBOLS is not None:
        return _IOKIT_SYMBOLS
    from Foundation import NSString  # noqa: F401  — forces PyObjC runtime bootstrap

    import objc

    symbols: dict = {}
    objc.loadBundle(
        "IOKit", symbols,
        bundle_path=objc.pathForFramework(
            "/System/Library/Frameworks/IOKit.framework"
        ),
    )
    _IOKIT_SYMBOLS = symbols
    return symbols


def _enumerate_via_iokit() -> list[MacOpticalDrive]:
    """Use IOKit (via PyObjC objc.loadBundle) to find optical block storage devices."""
    _g = _load_iokit()

    io_service_matching = _g["IOServiceMatching"]
    io_service_get_matching = _g["IOServiceGetMatchingServices"]
    io_iterator_next = _g["IOIteratorNext"]
    io_object_release = _g["IOObjectRelease"]
    io_entry_props = _g["IORegistryEntryCreateCFProperties"]
    io_child_iter = _g["IORegistryEntryGetChildIterator"]

    kIOMasterPortDefault = 0
    drives: list[MacOpticalDrive] = []
    seen: set[str] = set()

    for class_name in ("IOCDBlockStorageDevice", "IODVDBlockStorageDevice"):
        matching = io_service_matching(class_name.encode())
        err, it = io_service_get_matching(kIOMasterPortDefault, matching, None)
        if err or not it:
            continue
        try:
            while True:
                svc = io_iterator_next(it)
                if not svc:
                    break
                try:
                    err2, props = io_entry_props(svc, None, None, 0)
                    if err2 or not props:
                        continue
                    pdict = dict(props)
                    vendor = str(
                        pdict.get("Vendor Identification")
                        or pdict.get("Vendor Name")
                        or ""
                    ).strip()
                    product = str(
                        pdict.get("Product Identification")
                        or pdict.get("Product Name")
                        or ""
                    ).strip()
                    ejectable = bool(pdict.get("Ejectable", True))

                    bsd = _walk_iokit_tree_for_bsd(
                        svc, io_child_iter, io_iterator_next, io_object_release, io_entry_props
                    )
                    if bsd and bsd not in seen:
                        seen.add(bsd)
                        drives.append(MacOpticalDrive(
                            bsd_name=bsd,
                            device_path=f"/dev/{bsd}",
                            raw_path=f"/dev/r{bsd}",
                            vendor=vendor,
                            product=product,
                            is_ejectable=ejectable,
                        ))
                finally:
                    io_object_release(svc)
        finally:
            io_object_release(it)

    return drives


def _walk_iokit_tree_for_bsd(
    device,
    GetChildIter: Callable,
    IterNext: Callable,
    ObjRelease: Callable,
    GetProps: Callable,
) -> str | None:
    """Walk IOKit children two levels deep to find the BSD Name on an IOMedia node."""
    err, level1 = GetChildIter(device, b"IOService")
    if err or not level1:
        return None
    try:
        while True:
            child = IterNext(level1)
            if not child:
                break
            try:
                # Check this node
                err2, props = GetProps(child, None, None, 0)
                if not err2 and props:
                    bsd = props.get("BSD Name")
                    if bsd:
                        return str(bsd)

                # Go one level deeper (IOBlockStorageDriver -> IOMedia)
                err3, level2 = GetChildIter(child, b"IOService")
                if err3 or not level2:
                    continue
                try:
                    while True:
                        grandchild = IterNext(level2)
                        if not grandchild:
                            break
                        try:
                            err4, props2 = GetProps(grandchild, None, None, 0)
                            if not err4 and props2:
                                bsd = props2.get("BSD Name")
                                if bsd:
                                    return str(bsd)
                        finally:
                            ObjRelease(grandchild)
                finally:
                    ObjRelease(level2)
            finally:
                ObjRelease(child)
    finally:
        ObjRelease(level1)
    return None


def _enumerate_via_diskutil() -> list[MacOpticalDrive]:
    """Fallback: use diskutil list to find optical drives."""
    try:
        import plistlib
        raw = subprocess.check_output(
            ["/usr/sbin/diskutil", "list", "-plist"],
            timeout=10,
        )
        data = plistlib.loads(raw)
        drives: list[MacOpticalDrive] = []
        for bsd in data.get("WholeDisks", []):
            if not isinstance(bsd, str):
                continue
            if _is_optical_disk(bsd):
                drives.append(MacOpticalDrive(
                    bsd_name=bsd,
                    device_path=f"/dev/{bsd}",
                    raw_path=f"/dev/r{bsd}",
                    vendor="",
                    product="",
                    is_ejectable=True,
                ))
        return drives
    except Exception as exc:
        LOG.debug("diskutil fallback also failed: %s", exc)
        return []


def _is_optical_disk(bsd_name: str) -> bool:
    """Return True if diskutil info reports this disk as optical media."""
    try:
        out = subprocess.check_output(
            ["/usr/sbin/diskutil", "info", f"/dev/{bsd_name}"],
            text=True, timeout=8,
        )
        return "Optical" in out or "CD" in out or "DVD" in out
    except Exception:
        return False


def _check_audio_cd(device_path: str) -> bool:
    """Return True if the device contains an Audio CD (CD-DA)."""
    try:
        out = subprocess.check_output(
            ["/usr/sbin/diskutil", "info", device_path],
            text=True, timeout=10,
        )
        return "CD-DA" in out or "Audio CD" in out
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        return False

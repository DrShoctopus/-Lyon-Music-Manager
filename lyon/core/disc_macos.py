"""macOS optical-drive detection via diskutil.

Imported only on darwin; all public symbols are import-safe on other platforms
(functions return empty/False, nothing crashes).
"""
from __future__ import annotations

import logging
import subprocess
import sys
from dataclasses import dataclass

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


def _enumerate_via_diskutil() -> list[MacOpticalDrive]:
    """Use diskutil list to find optical drives."""
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
        LOG.debug("diskutil enumeration failed: %s", exc)
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

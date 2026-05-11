"""Startup health checks for optional runtime dependencies."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from .settings import bundled_bin_dir


@dataclass(frozen=True)
class HealthCheck:
    name: str
    ok: bool
    message: str


def _has_binary(name: str, bundled_name: str | None = None) -> bool:
    bundled = bundled_bin_dir() / (bundled_name or name)
    return bundled.exists() or shutil.which(name) is not None


def run_health_checks(music_root: str) -> list[HealthCheck]:
    """Return non-fatal app readiness checks shown during first-run setup."""
    root = Path(music_root).expanduser()
    checks = [
        HealthCheck(
            "Music folder",
            root.exists() or _can_create_parent(root),
            (
                f"Music folder is ready: {root}"
                if root.exists()
                else f"Music folder can be created: {root}"
            ),
        ),
        HealthCheck(
            "ffmpeg",
            _has_binary("ffmpeg", "ffmpeg.exe"),
            (
                "ffmpeg found for CD ripping"
                if _has_binary("ffmpeg", "ffmpeg.exe")
                else "ffmpeg not found; CD ripping will be disabled"
            ),
        ),
        HealthCheck(
            "libdiscid",
            (bundled_bin_dir() / "discid.dll").exists()
            or (bundled_bin_dir() / "libdiscid.dll").exists(),
            (
                "libdiscid found for disc IDs"
                if (bundled_bin_dir() / "discid.dll").exists()
                or (bundled_bin_dir() / "libdiscid.dll").exists()
                else "libdiscid not found; online CD lookup may be unavailable"
            ),
        ),
    ]
    return checks


def _can_create_parent(path: Path) -> bool:
    parent = path if path.suffix == "" else path.parent
    try:
        parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        return False
    return parent.exists()

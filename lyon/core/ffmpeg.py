"""Shared ffmpeg discovery helpers."""
from __future__ import annotations

import shutil
from pathlib import Path

from .settings import bundled_bin_dir


def find_ffmpeg_binary() -> Path | None:
    """Return the ffmpeg binary path, checking bundled bin dir before PATH."""
    bin_dir = bundled_bin_dir()
    for name in ("ffmpeg.exe", "ffmpeg"):
        candidate = bin_dir / name
        if candidate.exists():
            return candidate
    found = shutil.which("ffmpeg.exe") or shutil.which("ffmpeg")
    return Path(found) if found else None

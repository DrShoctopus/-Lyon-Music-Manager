"""ReplayGain loudness normalization — measurement, tag I/O, and background scanning."""
from __future__ import annotations

import re
import subprocess
import sys
from functools import lru_cache
from typing import Optional

from PySide6.QtCore import QObject, QThread, Signal

REPLAYGAIN_TARGET_LUFS = -18.0

# ──────────────────────────────────────────────── LUFS measurement ──────────


def measure_track_loudness(path: str, ffmpeg: str) -> Optional[float]:
    """Return integrated loudness in LUFS using ffmpeg ebur128, or None on error."""
    creation_flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    try:
        result = subprocess.run(
            [
                ffmpeg, "-hide_banner", "-nostats",
                "-i", path,
                "-af", "ebur128=framelog=verbose",
                "-f", "null", "-",
            ],
            capture_output=True,
            text=True,
            creationflags=creation_flags,
        )
        for line in reversed(result.stderr.splitlines()):
            m = re.search(r"\bI:\s+(-?\d+\.?\d*)\s+LUFS", line)
            if m:
                return float(m.group(1))
    except (OSError, ValueError):
        pass
    return None


def gain_for_lufs(lufs: float, target: float = REPLAYGAIN_TARGET_LUFS) -> float:
    """Return the dB adjustment needed to reach *target* from *lufs*."""
    return target - lufs


def gain_multiplier(
    gain_db: float,
    preamp_db: float = 0.0,
    prevent_clipping: bool = True,
) -> float:
    """Return the linear amplitude multiplier for a ReplayGain adjustment."""
    multiplier = 10.0 ** ((gain_db + preamp_db) / 20.0)
    if prevent_clipping:
        multiplier = min(multiplier, 1.0)
    return max(0.0, multiplier)


# ──────────────────────────────────────────────── Tag reading ───────────────


def read_track_gain(path: str) -> Optional[float]:
    """Return REPLAYGAIN_TRACK_GAIN in dB from file tags, or None if absent."""
    return _read_rg_tag(path, "track")


def read_album_gain(path: str) -> Optional[float]:
    """Return REPLAYGAIN_ALBUM_GAIN in dB from file tags, or None if absent."""
    return _read_rg_tag(path, "album")


@lru_cache(maxsize=512)
def _read_rg_tag(path: str, kind: str) -> Optional[float]:
    try:
        import mutagen
    except ImportError:
        return None
    try:
        f = mutagen.File(path, easy=False)
        if f is None:
            return None
        rg_key = f"replaygain_{kind}_gain"
        r128_key = f"r128_{kind}_gain"
        raw = _extract_tag(f, rg_key)
        if raw is not None:
            return _parse_rg_gain(raw)
        raw = _extract_tag(f, r128_key)
        if raw is not None:
            try:
                return int(raw) / 256.0
            except (ValueError, TypeError):
                return None
    except Exception:
        pass
    return None


def _extract_tag(f, key: str) -> Optional[str]:
    """Return the first string value for *key* (case-insensitive) from any tag format."""
    try:
        from mutagen.mp3 import MP3
        from mutagen.mp4 import MP4
        from mutagen.asf import ASF
    except ImportError:
        return None

    if isinstance(f, MP3):
        if not f.tags:
            return None
        for frame in f.tags.values():
            hk = getattr(frame, "HashKey", "")
            if hk.startswith("TXXX:") and hk[5:].lower() == key:
                text = getattr(frame, "text", [])
                return str(text[0]) if text else None
        return None

    if isinstance(f, MP4):
        if not f.tags:
            return None
        needle = key.lower()
        for atom_key, values in f.tags.items():
            atom_key_lower = atom_key.lower()
            tag_name = atom_key_lower.rsplit(":", 1)[-1] if ":" in atom_key_lower else atom_key_lower
            if tag_name == needle:
                return _tag_value_to_str(values[0]) if values else None
        return None

    if isinstance(f, ASF):
        if not f.tags:
            return None
        for wma_key, values in f.tags.items():
            if wma_key.lower() == key:
                return str(values[0]) if values else None
        return None

    # Vorbis comment (FLAC, OGG, Opus, …)
    if f.tags is None:
        return None
    for tag_key in f.tags.keys():
        if tag_key.lower() == key:
            v = f.tags[tag_key]
            return str(v[0]) if isinstance(v, list) else str(v)
    return None


def _tag_value_to_str(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _parse_rg_gain(raw: str) -> Optional[float]:
    m = re.search(r"([+-]?\d+\.?\d*)", raw.strip())
    return float(m.group(1)) if m else None


# ──────────────────────────────────────────────── Tag writing ───────────────


def write_replaygain_tags(
    path: str,
    track_gain_db: Optional[float],
    album_gain_db: Optional[float] = None,
) -> bool:
    """Write ReplayGain tags to *path*. Returns True on success."""
    try:
        import mutagen
        from mutagen.mp3 import MP3
        from mutagen.mp4 import MP4
        from mutagen.asf import ASF

        f = mutagen.File(path, easy=False)
        if f is None:
            return False
        if isinstance(f, MP3):
            _write_id3_rg(f, track_gain_db, album_gain_db)
        elif isinstance(f, MP4):
            _write_mp4_rg(f, track_gain_db, album_gain_db)
        elif isinstance(f, ASF):
            _write_asf_rg(f, track_gain_db, album_gain_db)
        else:
            _write_vorbis_rg(f, track_gain_db, album_gain_db)
        f.save()
        return True
    except Exception:
        return False


def _rg_str(gain_db: float) -> str:
    return f"{gain_db:+.2f} dB"


def _write_id3_rg(f, track_gain_db, album_gain_db) -> None:
    from mutagen.id3 import TXXX
    if f.tags is None:
        f.add_tags()
    for k in [k for k in f.tags.keys() if k.startswith("TXXX:REPLAYGAIN_")]:
        del f.tags[k]
    if track_gain_db is not None:
        f.tags.add(TXXX(encoding=3, desc="REPLAYGAIN_TRACK_GAIN", text=[_rg_str(track_gain_db)]))
    if album_gain_db is not None:
        f.tags.add(TXXX(encoding=3, desc="REPLAYGAIN_ALBUM_GAIN", text=[_rg_str(album_gain_db)]))


def _write_mp4_rg(f, track_gain_db, album_gain_db) -> None:
    from mutagen.mp4 import MP4FreeForm, AtomDataType
    if f.tags is None:
        f.add_tags()
    for k in [k for k in f.tags.keys() if "replaygain" in k.lower()]:
        del f.tags[k]
    if track_gain_db is not None:
        f.tags["----:com.apple.iTunes:REPLAYGAIN_TRACK_GAIN"] = [
            MP4FreeForm(_rg_str(track_gain_db).encode(), AtomDataType.UTF8)
        ]
    if album_gain_db is not None:
        f.tags["----:com.apple.iTunes:REPLAYGAIN_ALBUM_GAIN"] = [
            MP4FreeForm(_rg_str(album_gain_db).encode(), AtomDataType.UTF8)
        ]


def _write_asf_rg(f, track_gain_db, album_gain_db) -> None:
    from mutagen.asf import ASFUnicodeAttribute
    for k in [k for k in f.tags.keys() if "replaygain" in k.lower()]:
        del f.tags[k]
    if track_gain_db is not None:
        f.tags["REPLAYGAIN_TRACK_GAIN"] = [ASFUnicodeAttribute(_rg_str(track_gain_db))]
    if album_gain_db is not None:
        f.tags["REPLAYGAIN_ALBUM_GAIN"] = [ASFUnicodeAttribute(_rg_str(album_gain_db))]


def _write_vorbis_rg(f, track_gain_db, album_gain_db) -> None:
    if f.tags is None:
        f.add_tags()
    for k in [k for k in f.tags.keys() if k.upper().startswith("REPLAYGAIN_")]:
        del f.tags[k]
    if track_gain_db is not None:
        f.tags["REPLAYGAIN_TRACK_GAIN"] = _rg_str(track_gain_db)
    if album_gain_db is not None:
        f.tags["REPLAYGAIN_ALBUM_GAIN"] = _rg_str(album_gain_db)


# ──────────────────────────────────────────────── Background scanner ─────────


class ReplayGainScanner(QThread):
    """Measures integrated loudness via ffmpeg and writes ReplayGain tags."""

    progress = Signal(int, int, str)      # (done, total, current_path)
    track_done = Signal(str, float)       # (path, track_gain_db)
    finished_scanning = Signal(int, int)  # (written, failed)

    def __init__(
        self,
        paths: list[str],
        ffmpeg: str,
        album_mode: bool = False,
        parent: Optional[QObject] = None,
    ):
        super().__init__(parent)
        self._paths = list(paths)
        self._ffmpeg = ffmpeg
        self._album_mode = album_mode

    def run(self) -> None:
        total = len(self._paths)
        lufs_map: dict[str, float] = {}

        for i, path in enumerate(self._paths):
            if self.isInterruptionRequested():
                self.finished_scanning.emit(0, total - i)
                return
            self.progress.emit(i, total, path)
            lufs = measure_track_loudness(path, self._ffmpeg)
            if lufs is not None:
                lufs_map[path] = lufs

        album_gain_db: Optional[float] = None
        if self._album_mode and lufs_map:
            avg_lufs = sum(lufs_map.values()) / len(lufs_map)
            album_gain_db = gain_for_lufs(avg_lufs)

        written = 0
        failed = 0
        measured_items = list(lufs_map.items())
        for i, (path, lufs) in enumerate(measured_items):
            if self.isInterruptionRequested():
                failed += len(measured_items) - i
                failed += len(self._paths) - len(lufs_map)
                self.finished_scanning.emit(written, failed)
                return
            track_gain_db = gain_for_lufs(lufs)
            self.track_done.emit(path, track_gain_db)
            if write_replaygain_tags(path, track_gain_db, album_gain_db):
                written += 1
            else:
                failed += 1

        failed += len(self._paths) - len(lufs_map)
        self.progress.emit(total, total, "")
        self.finished_scanning.emit(written, failed)

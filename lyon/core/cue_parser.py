"""CUE sheet parser for single-image + CUE rips."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

LOG = logging.getLogger(__name__)
_MAX_CUE_BYTES = 8 * 1024 * 1024
_MAX_CUE_TEXT_LENGTH = 4096


@dataclass
class CueTrack:
    number: int
    title: str = ""
    performer: str = ""
    isrc: str = ""
    start_sectors: int = 0
    end_sectors: int | None = None  # None for the last track (open-ended)


@dataclass
class CueSheet:
    cue_path: Path
    image_path: Path | None       # None when the FILE line's target doesn't exist on disk
    album: str = ""
    performer: str = ""
    tracks: list[CueTrack] = field(default_factory=list)


def _parse_sectors(time_str: str) -> int:
    """Convert a CUE time string MM:SS:FF to sectors (75 frames/sec)."""
    parts = time_str.strip().split(":")
    if len(parts) != 3:
        raise ValueError(f"Invalid CUE timestamp: {time_str!r}")
    mm, ss, ff = int(parts[0]), int(parts[1]), int(parts[2])
    return mm * 60 * 75 + ss * 75 + ff


def _unquote(s: str) -> str:
    s = s.strip()
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        s = s[1:-1]
    return s[:_MAX_CUE_TEXT_LENGTH]


def parse_cue(cue_path: Path) -> CueSheet | None:
    """Parse a CUE sheet file and return a CueSheet, or None if the file has no tracks.

    Multi-file CUE sheets (more than one FILE directive) are partially supported:
    only tracks covered by the first FILE entry are returned.
    """
    try:
        if cue_path.stat().st_size > _MAX_CUE_BYTES:
            LOG.warning("Skipping oversized CUE sheet %s", cue_path)
            return None
        text = cue_path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        try:
            text = cue_path.read_text(encoding="latin-1")
        except OSError:
            return None
    except OSError:
        return None

    album = ""
    album_performer = ""
    image_path: Path | None = None
    file_count = 0
    tracks: list[CueTrack] = []
    current: CueTrack | None = None

    for raw_line in text.splitlines():
        line = raw_line.strip()
        upper = line.upper()

        if upper.startswith("PERFORMER "):
            val = _unquote(line[10:])
            if current is None:
                album_performer = val
            else:
                current.performer = val

        elif upper.startswith("TITLE "):
            val = _unquote(line[6:])
            if current is None:
                album = val
            else:
                current.title = val

        elif upper.startswith("FILE "):
            file_count += 1
            if file_count > 1:
                # Multi-file CUE: stop after the first FILE block.
                LOG.info(
                    "CUE %s references multiple FILE entries; only the first "
                    "is indexed (tracks under later FILE entries are skipped).",
                    cue_path,
                )
                break
            m = re.match(r'FILE\s+"(.+?)"\s+\S+', line, re.IGNORECASE)
            if m:
                name = m.group(1)
                candidate = Path(name) if Path(name).is_absolute() else cue_path.parent / name
                try:
                    resolved = candidate.resolve()
                    image_path = resolved if resolved.exists() else None
                except OSError:
                    image_path = None

        elif re.match(r'TRACK\s+\d+\s+AUDIO', line, re.IGNORECASE):
            if current is not None:
                tracks.append(current)
            m = re.match(r'TRACK\s+(\d+)', line, re.IGNORECASE)
            current = CueTrack(number=int(m.group(1))) if m else CueTrack(number=len(tracks) + 1)

        elif upper.startswith("INDEX 01") and current is not None:
            m = re.match(r'INDEX\s+01\s+(\d+:\d+:\d+)', line, re.IGNORECASE)
            if m:
                try:
                    current.start_sectors = _parse_sectors(m.group(1))
                except ValueError:
                    pass

        elif upper.startswith("ISRC") and current is not None:
            parts = line.split(None, 1)
            if len(parts) == 2:
                current.isrc = parts[1].strip()

    if current is not None:
        tracks.append(current)

    if not tracks:
        return None

    # Fill in end_sectors for all but the last track.
    for i in range(len(tracks) - 1):
        tracks[i].end_sectors = tracks[i + 1].start_sectors

    return CueSheet(
        cue_path=cue_path,
        image_path=image_path,
        album=album,
        performer=album_performer,
        tracks=tracks,
    )

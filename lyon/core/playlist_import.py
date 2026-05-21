"""M3U / PLS playlist import: parse file paths and match to library tracks."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from .library import Library


@dataclass
class ImportResult:
    playlist_id: int
    matched: int
    unmatched: list[str] = field(default_factory=list)


def _normalize(entry: str, base: Path) -> str:
    """Make *entry* absolute relative to *base*, normalizing without requiring existence.

    Path.resolve() can raise OSError on Windows reserved names (CON, NUL, …)
    or unreadable parents; os.path.abspath/normpath always succeed and produce
    a string that's good enough for exact + case-insensitive matching.
    """
    p = Path(entry)
    if not p.is_absolute():
        p = base / p
    try:
        return str(p.resolve())
    except OSError:
        return os.path.normpath(os.path.abspath(str(p)))


def parse_m3u(path: Path) -> list[str]:
    """Parse an M3U or M3U8 file; return resolved absolute file paths in order."""
    try:
        text = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        text = path.read_text(encoding="latin-1")

    results: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        results.append(_normalize(line, path.parent))
    return results


def parse_pls(path: Path) -> list[str]:
    """Parse a PLS file; return resolved absolute file paths in order."""
    try:
        text = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        text = path.read_text(encoding="latin-1")

    results: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        key, _, value = line.partition("=")
        key_lower = key.strip().lower()
        # Accept "FileN=" entries (e.g. File1=, File12=) only.
        if not key_lower.startswith("file") or not key_lower[4:].isdigit():
            continue
        value = value.strip()
        if not value:
            continue
        results.append(_normalize(value, path.parent))
    return results


def import_playlist(library: Library, file_path: Path) -> ImportResult:
    """Parse *file_path*, create a library playlist, and populate it with matched tracks.

    Exact path matching is tried first.  Paths that don't match exactly fall back to a
    case-insensitive comparison (useful on Windows where drive-letter case may differ
    between the playlist and the library).  Unmatched paths are reported in the result
    but are otherwise silently skipped so the import still succeeds.
    """
    suffix = file_path.suffix.lower()
    if suffix in {".m3u", ".m3u8"}:
        raw_paths = parse_m3u(file_path)
    elif suffix == ".pls":
        raw_paths = parse_pls(file_path)
    else:
        raise ValueError(f"Unsupported playlist format: {suffix!r}")

    playlist_id = library.create_playlist(file_path.stem)

    if not raw_paths:
        return ImportResult(playlist_id=playlist_id, matched=0)

    # --- exact match via a single SQL IN query --------------------------------
    exact_tracks = library.tracks_for_paths(raw_paths)
    exact_map: dict[str, int] = {t.path: t.id for t in exact_tracks}

    unmatched_raw = [p for p in raw_paths if p not in exact_map]

    # --- case-insensitive fallback for any paths that didn't exact-match -----
    lower_map: dict[str, int] = {}
    if unmatched_raw:
        lower_map = {
            os.path.normcase(t.path): t.id
            for t in library.all_tracks()
        }

    track_ids: list[int] = []
    unmatched: list[str] = []
    for raw in raw_paths:
        if raw in exact_map:
            track_ids.append(exact_map[raw])
        else:
            tid = lower_map.get(os.path.normcase(raw))
            if tid is not None:
                track_ids.append(tid)
            else:
                unmatched.append(raw)

    if track_ids:
        library.add_to_playlist(playlist_id, track_ids)

    return ImportResult(
        playlist_id=playlist_id,
        matched=len(track_ids),
        unmatched=unmatched,
    )

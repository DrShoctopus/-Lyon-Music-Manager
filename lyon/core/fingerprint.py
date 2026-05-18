"""AcoustID acoustic fingerprinting — identify tracks and detect audio duplicates.

Requires the ``pyacoustid`` package and the ``fpcalc`` binary (Chromaprint).
Both are optional; all public functions degrade gracefully when unavailable.

Register a free application API key at https://acoustid.org/new-application
and set ACOUSTID_API_KEY below.
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

LOG = logging.getLogger(__name__)

# Register your application at https://acoustid.org/new-application
ACOUSTID_API_KEY: str = ""


def _fpcalc_path() -> str | None:
    """Return the path to the fpcalc binary, checking the app bin/ dir first."""
    binary = "fpcalc.exe" if sys.platform == "win32" else "fpcalc"
    # Check alongside the executable (packaged) or in bin/ at the project root.
    candidates: list[Path] = []
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys._MEIPASS) / "bin" / binary)  # type: ignore[attr-defined]
    else:
        candidates.append(Path(__file__).resolve().parents[2] / "bin" / binary)
    for p in candidates:
        if p.is_file():
            return str(p)
    # Fall back to PATH — acoustid will also search PATH automatically.
    return None


def _set_fpcalc() -> None:
    """Point acoustid at our bundled fpcalc if present."""
    try:
        import acoustid
        bundled = _fpcalc_path()
        if bundled:
            acoustid.FPCALC_COMMAND = bundled
    except ImportError:
        pass


def is_available() -> bool:
    """Return True if pyacoustid is installed and fpcalc can be found."""
    try:
        import acoustid  # noqa: F401
    except ImportError:
        return False
    _set_fpcalc()
    # Try to locate fpcalc either bundled or on PATH.
    import shutil
    binary = "fpcalc.exe" if sys.platform == "win32" else "fpcalc"
    bundled = _fpcalc_path()
    return bool(bundled or shutil.which(binary))


def fingerprint_file(path: str | Path) -> tuple[int, str] | None:
    """Return (duration_seconds, fingerprint_string) or None on failure.

    The fingerprint is a compressed Chromaprint string suitable for AcoustID
    API lookups.  This call runs fpcalc as a subprocess — do not call from the
    main thread.
    """
    try:
        import acoustid
        _set_fpcalc()
        duration, fp = acoustid.fingerprint_file(str(path))
        return int(duration), fp
    except Exception as exc:
        LOG.debug("fingerprint_file(%s) failed: %s", path, exc)
        return None


def lookup_candidates(path: str | Path) -> list[dict]:
    """Fingerprint *path* and query the AcoustID API for matching recordings.

    Each returned dict has:
      score     float   0–1 confidence
      acoustid  str     AcoustID result UUID
      mbid      str     MusicBrainz recording ID (may be "")
      title     str     recording title (may be "")
      artist    str     artist name (may be "")
      album     str     first release title (may be "")

    Returns an empty list on any failure.
    """
    if not ACOUSTID_API_KEY:
        LOG.debug("ACOUSTID_API_KEY not configured — skipping lookup")
        return []

    result = fingerprint_file(path)
    if result is None:
        return []
    duration, fp = result

    try:
        import acoustid
        data = acoustid.lookup(
            ACOUSTID_API_KEY, fp, duration,
            meta=["recordings", "releases"],
            timeout=15,
        )
    except Exception as exc:
        LOG.debug("AcoustID lookup failed: %s", exc)
        return []

    candidates: list[dict] = []
    try:
        for score, mbid, title, artist in acoustid.parse_lookup_result(data):
            candidates.append({
                "score": score,
                "acoustid": "",
                "mbid": mbid or "",
                "title": title or "",
                "artist": artist or "",
                "album": "",
            })
    except Exception as exc:
        LOG.debug("parse_lookup_result failed: %s", exc)

    # Enrich with acoustid UUIDs and release titles from raw response.
    results = data.get("results") or []
    for i, result_obj in enumerate(results):
        acoustid_id = result_obj.get("id", "")
        recordings = result_obj.get("recordings") or []
        # Match by position — parse_lookup_result flattens recordings in order.
        for rec in recordings:
            releases = rec.get("releases") or []
            album = releases[0].get("title", "") if releases else ""
            # Find the matching candidate by mbid.
            mbid_match = rec.get("id", "")
            for c in candidates:
                if c["mbid"] == mbid_match and not c["acoustid"]:
                    c["acoustid"] = acoustid_id
                    if album and not c["album"]:
                        c["album"] = album
                    break

    candidates.sort(key=lambda c: c["score"], reverse=True)
    return candidates

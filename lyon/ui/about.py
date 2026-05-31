"""Shared About-screen content for Sea Lyon UI surfaces.

The About dialog (``about_dialog.AboutDialog``) renders an "Acknowledgements"
tab from :data:`ATTRIBUTIONS` and a "Licenses" tab from
:func:`licenses_full_text`.

When upgrading a bundled dependency, update the matching entry below so
the About dialog stays accurate. The bundled ``THIRD_PARTY_NOTICES.txt``
is the authoritative legal document; this module is the structured form
the UI consumes.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

COPYRIGHT_NOTICE = "© 2026 Shane Simmons. Released under the MIT License."


@dataclass(frozen=True)
class Attribution:
    """One third-party component shipped or relied on at runtime."""

    name: str
    version: str
    license: str
    url: str
    notes: str = ""


ATTRIBUTIONS: tuple[Attribution, ...] = (
    Attribution(
        "Python", f"{sys.version_info.major}.{sys.version_info.minor}", "PSF",
        "https://www.python.org/",
    ),
    Attribution(
        "Qt / PySide6", "6.11.x", "LGPL-3.0 with Qt LGPL Exception",
        "https://www.qt.io/qt-for-python",
    ),
    Attribution(
        "libVLC", "3.0.23", "LGPL-2.1+",
        "https://www.videolan.org/vlc/libvlc.html",
        notes="Some bundled VLC plugins are GPL-2.0+.",
    ),
    Attribution(
        "ffmpeg (gyan.dev essentials)", "7.1.1", "GPL-2.0+",
        "https://www.gyan.dev/ffmpeg/builds/",
        notes="Essentials build links libx264 / libx265, making the bundle GPL.",
    ),
    Attribution(
        "libdiscid", "0.6.4", "LGPL-2.1+",
        "https://musicbrainz.org/doc/libdiscid",
    ),
    Attribution(
        "Chromaprint / fpcalc", "1.5.1", "LGPL-2.1+",
        "https://acoustid.org/chromaprint",
    ),
    Attribution(
        "Deno", "2.8.1", "MIT",
        "https://github.com/denoland/deno",
        notes="Bundled JavaScript runtime for yt-dlp signature solving.",
    ),
    Attribution(
        "python-vlc", "3.0.21203", "LGPL-2.1+",
        "https://github.com/oaubert/python-vlc",
    ),
    Attribution(
        "Mutagen", "1.47.0", "GPL-2.0+",
        "https://github.com/quodlibet/mutagen",
    ),
    Attribution(
        "musicbrainzngs", "0.7.1", "BSD-2-Clause",
        "https://github.com/alastair/python-musicbrainzngs",
    ),
    Attribution(
        "yt-dlp", "2026.3.17", "Unlicense",
        "https://github.com/yt-dlp/yt-dlp",
    ),
    Attribution(
        "yt-dlp-ejs", "0.8.0", "Unlicense / MIT / ISC",
        "https://github.com/yt-dlp/ejs",
        notes="External JavaScript challenge solver package used by yt-dlp.",
    ),
    Attribution(
        "requests", "2.34.2", "Apache-2.0",
        "https://requests.readthedocs.io/",
    ),
    Attribution(
        "defusedxml", "0.7.1", "PSF",
        "https://github.com/tiran/defusedxml",
    ),
    Attribution(
        "watchdog", "6.0.0", "Apache-2.0",
        "https://github.com/gorakhargosh/watchdog",
    ),
    Attribution(
        "pyacoustid", "1.3.1", "MIT",
        "https://github.com/beetbox/pyacoustid",
    ),
    Attribution(
        "Pillow (build-time)", "n/a", "HPND",
        "https://github.com/python-pillow/Pillow",
    ),
    Attribution(
        "SQLite (via stdlib)", "n/a", "Public domain",
        "https://www.sqlite.org/",
    ),
)


NETWORK_SERVICES: tuple[Attribution, ...] = (
    Attribution("MusicBrainz", "API v2", "CC0 data / per-service ToS",
                "https://musicbrainz.org/"),
    Attribution("Cover Art Archive", "—", "Per-image rights",
                "https://coverartarchive.org/"),
    Attribution("CUETools DB (CTDB)", "—", "Per-service ToS",
                "http://db.cuetools.net/"),
    Attribution("AcoustID", "—", "Per-service ToS",
                "https://acoustid.org/"),
    Attribution("TheAudioDB", "v1", "Per-API-key terms",
                "https://www.theaudiodb.com/"),
    Attribution("LRCLIB", "—", "Per-service ToS",
                "https://lrclib.net/"),
    Attribution("Last.fm", "API v2", "https://www.last.fm/api/tos",
                "https://www.last.fm/"),
    Attribution("ListenBrainz", "v1", "Per-token terms",
                "https://listenbrainz.org/"),
    Attribution("YouTube (via yt-dlp)", "—", "Per-service ToS",
                "https://www.youtube.com/t/terms"),
)


def format_license_summary() -> str:
    """One-line-per-component summary suitable for a scrollable label."""
    lines: list[str] = []
    lines.append("Bundled or linked third-party components:")
    lines.append("")
    for attribution in ATTRIBUTIONS:
        version = f" {attribution.version}" if attribution.version not in ("", "n/a") else ""
        line = f"  • {attribution.name}{version}  —  {attribution.license}"
        lines.append(line)
        if attribution.notes:
            lines.append(f"      {attribution.notes}")
    lines.append("")
    lines.append("Networked services accessed at runtime when you take")
    lines.append("an action that requires them:")
    lines.append("")
    for service in NETWORK_SERVICES:
        lines.append(f"  • {service.name}  —  {service.url}")
    return "\n".join(lines)


def _candidate_notice_paths() -> list[Path]:
    """Return search paths for the bundled THIRD_PARTY_NOTICES.txt.

    Order:
      1. PyInstaller frozen extraction dir (``sys._MEIPASS``).
      2. Installer's app dir (sibling of the executable).
      3. Repo root (source runs and dev test runs).
    """
    paths: list[Path] = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        paths.append(Path(meipass) / "THIRD_PARTY_NOTICES.txt")
    if getattr(sys, "frozen", False):
        paths.append(Path(sys.executable).resolve().parent / "THIRD_PARTY_NOTICES.txt")
    paths.append(Path(__file__).resolve().parents[2] / "THIRD_PARTY_NOTICES.txt")
    return paths


def licenses_full_text() -> str:
    """Return the bundled THIRD_PARTY_NOTICES.txt verbatim, or a fallback."""
    for candidate in _candidate_notice_paths():
        try:
            if candidate.exists():
                return candidate.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
    return (
        "THIRD_PARTY_NOTICES.txt was not found in this build. "
        "See https://github.com/DrShoctopus/Sea-Lyon-Media-Manager for the "
        "canonical text.\n\n" + format_license_summary()
    )


# Kept for backward compatibility with code that imported the old string.
THIRD_PARTY_NOTICE = format_license_summary()

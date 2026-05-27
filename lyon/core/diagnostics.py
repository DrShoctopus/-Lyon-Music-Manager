"""Runtime dependency diagnostics for setup and support."""
from __future__ import annotations

import ctypes.util
import importlib.util
import json
import platform
import shutil
import socket
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from functools import lru_cache
from ipaddress import ip_address
from pathlib import Path

from .dlna_server import _local_ip
from .settings import app_data_dir, bundled_bin_dir

# Settings keys whose values are secrets and must be redacted from any
# diagnostics bundle a user might share with support.
_REDACTED_SETTINGS_KEYS = (
    "lastfm_session_key",
    "listenbrainz_token",
    "theaudiodb_api_key",
)
# Cap each embedded log to ~1 MB so the bundle stays paste-friendly.
_LOG_TAIL_BYTES = 1024 * 1024


class DiagnosticStatus(Enum):
    OK = "OK"
    WARNING = "Warning"
    MISSING = "Missing"


@dataclass(frozen=True)
class DependencyCheck:
    """One user-facing setup/dependency check."""

    name: str
    status: DiagnosticStatus
    detail: str
    fix: str

    @property
    def is_problem(self) -> bool:
        return self.status is not DiagnosticStatus.OK


@lru_cache(maxsize=None)
def _has_module(module: str) -> bool:
    return importlib.util.find_spec(module) is not None


def _bundled_tool(*names: str) -> Path | None:
    bin_dir = bundled_bin_dir()
    for name in names:
        candidate = bin_dir / name
        if candidate.exists():
            return candidate
    return None


def _path_tool(*names: str) -> str | None:
    for name in names:
        found = shutil.which(name)
        if found:
            return found
    return None


def _system_libvlc_present() -> bool:
    return ctypes.util.find_library("vlc") is not None


def check_ffmpeg() -> DependencyCheck:
    bundled = _bundled_tool("ffmpeg.exe", "ffmpeg")
    if bundled:
        return DependencyCheck(
            "ffmpeg",
            DiagnosticStatus.OK,
            f"Found bundled ffmpeg at {bundled}.",
            "No action needed.",
        )
    found = _path_tool("ffmpeg.exe", "ffmpeg")
    if found:
        return DependencyCheck(
            "ffmpeg",
            DiagnosticStatus.OK,
            f"Found ffmpeg on PATH at {found}.",
            "No action needed.",
        )
    return DependencyCheck(
        "ffmpeg",
        DiagnosticStatus.MISSING,
        "ffmpeg was not found. CD ripping is disabled and YouTube video downloads are limited to ~720p pre-merged streams.",
        "Place ffmpeg.exe in the app bin folder or install ffmpeg on PATH.",
    )


def check_libdiscid() -> DependencyCheck:
    if sys.platform != "win32":
        return DependencyCheck(
            "libdiscid / discid",
            DiagnosticStatus.WARNING,
            "Audio-CD detection is Windows-focused and disabled on this platform.",
            "Run on Windows with discid installed and discid.dll/libdiscid.dll in bin for CD support.",
        )
    bundled = _bundled_tool("discid.dll", "libdiscid.dll")
    python_pkg = _has_module("discid")
    if bundled and python_pkg:
        return DependencyCheck(
            "libdiscid / discid",
            DiagnosticStatus.OK,
            f"Found discid Python package and bundled DLL at {bundled}.",
            "No action needed.",
        )
    if bundled:
        return DependencyCheck(
            "libdiscid / discid",
            DiagnosticStatus.WARNING,
            f"Found {bundled}, but the discid Python package is not importable.",
            "Install the discid Python package in this environment.",
        )
    if python_pkg:
        return DependencyCheck(
            "libdiscid / discid",
            DiagnosticStatus.WARNING,
            "The discid Python package is installed, but no bundled discid.dll/libdiscid.dll was found.",
            "Place discid.dll or libdiscid.dll in the app bin folder for packaged/source runs.",
        )
    return DependencyCheck(
        "libdiscid / discid",
        DiagnosticStatus.MISSING,
        "Audio-CD detection needs the discid Python package and libdiscid DLL.",
        "Install discid and place discid.dll/libdiscid.dll in the app bin folder.",
    )


def check_vlc() -> DependencyCheck:
    python_pkg = _has_module("vlc")
    vlc_dir = bundled_bin_dir() / "vlc"
    bundled_runtime = (
        (vlc_dir / "plugins").exists()
        and any((vlc_dir / name).exists() for name in ("libvlc.dll", "libvlc.so", "libvlc.dylib"))
    )
    system_vlc = _path_tool("vlc.exe", "vlc")
    system_libvlc = _system_libvlc_present()
    if python_pkg and bundled_runtime:
        return DependencyCheck(
            "VLC playback backend",
            DiagnosticStatus.OK,
            f"Found python-vlc and bundled VLC runtime at {vlc_dir}.",
            "No action needed.",
        )
    if python_pkg and system_libvlc:
        return DependencyCheck(
            "VLC playback backend",
            DiagnosticStatus.OK,
            "Found python-vlc and a system libVLC library.",
            "No action needed.",
        )
    if python_pkg and system_vlc:
        return DependencyCheck(
            "VLC playback backend",
            DiagnosticStatus.WARNING,
            f"Found python-vlc and the VLC app at {system_vlc}, but libVLC was not found by the dynamic linker.",
            "Bundle VLC under bin/vlc or ensure libVLC is discoverable so EQ playback can use libVLC.",
        )
    if python_pkg:
        return DependencyCheck(
            "VLC playback backend",
            DiagnosticStatus.WARNING,
            "python-vlc is installed, but a bundled/system libVLC runtime was not found.",
            "Bundle VLC under bin/vlc or install libVLC so equalizer playback can use libVLC.",
        )
    return DependencyCheck(
        "VLC playback backend",
        DiagnosticStatus.WARNING,
        "python-vlc is not importable; local audio playback, video playback, and EQ require VLC/libVLC.",
        "Install python-vlc and provide a VLC runtime under bin/vlc for playback support.",
    )


def check_ytdlp() -> DependencyCheck:
    if _has_module("yt_dlp"):
        return DependencyCheck(
            "yt-dlp / YouTube",
            DiagnosticStatus.OK,
            "yt-dlp is available for YouTube search and downloads.",
            "No action needed.",
        )
    return DependencyCheck(
        "yt-dlp / YouTube",
        DiagnosticStatus.WARNING,
        "yt-dlp is not installed; the YouTube tab will be disabled.",
        "Run: pip install yt-dlp",
    )


def check_dlna_network() -> DependencyCheck:
    """Check whether DLNA can use local UDP/multicast discovery."""
    sock: socket.socket | None = None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        sock.bind(("", 0))
    except OSError as exc:
        return DependencyCheck(
            "DLNA local network",
            DiagnosticStatus.WARNING,
            f"Local UDP/multicast sockets are not available: {exc}. DLNA discovery and casting will not work.",
            "Allow Local Network access for Sea Lyon/Python and avoid launching it from a network-restricted sandbox.",
        )
    finally:
        if sock is not None:
            sock.close()

    advertised = _local_ip()
    try:
        address = ip_address(advertised.split("%", 1)[0])
    except ValueError:
        address = None
    if address is None or address.is_loopback:
        return DependencyCheck(
            "DLNA local network",
            DiagnosticStatus.WARNING,
            f"DLNA would advertise {advertised}, which other devices on the LAN cannot reach.",
            "Run Sea Lyon with LAN access on the same network as your devices, then restart DLNA sharing.",
        )

    return DependencyCheck(
        "DLNA local network",
        DiagnosticStatus.OK,
        f"DLNA can open a UDP discovery socket and advertise {advertised}.",
        "No action needed.",
    )


def run_dependency_checks() -> list[DependencyCheck]:
    """Return setup checks in the order users should review them."""
    return [
        check_ffmpeg(),
        check_libdiscid(),
        check_vlc(),
        check_ytdlp(),
        check_dlna_network(),
    ]


def logs_dir() -> Path:
    """Return the directory where the rotating application log is written."""
    path = app_data_dir() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _read_tail(path: Path, max_bytes: int = _LOG_TAIL_BYTES) -> str:
    """Return the last ``max_bytes`` of ``path`` as decoded UTF-8 text."""
    try:
        size = path.stat().st_size
    except OSError:
        return ""
    if size <= 0:
        return ""
    try:
        with path.open("rb") as fp:
            if size > max_bytes:
                fp.seek(size - max_bytes)
                # Skip a likely-partial first line so we don't show half-tokens.
                fp.readline()
            return fp.read().decode("utf-8", errors="replace")
    except OSError as exc:
        return f"<could not read {path}: {exc}>"


def _redacted_settings_json() -> str:
    """Return settings.json with secret keys redacted, as pretty-printed JSON."""
    path = app_data_dir() / "settings.json"
    if not path.exists():
        return "<no settings.json present>"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return f"<could not parse settings.json: {exc}>"
    if isinstance(data, dict):
        for key in _REDACTED_SETTINGS_KEYS:
            if data.get(key):
                data[key] = "<redacted>"
    return json.dumps(data, indent=2, ensure_ascii=False)


def collect_diagnostics_bundle() -> str:
    """Assemble a multi-section plain-text bundle for support / bug reports.

    Output sections (in order):
      1. Header  -- timestamp, app version, Python, Qt, OS
      2. Dependency checks
      3. Tail of sea-lyon.log (last ~1 MB)
      4. Tail of metadata-diagnostics.log (last ~1 MB, if present)
      5. Redacted settings.json

    Secret values (``_REDACTED_SETTINGS_KEYS``) appear as ``<redacted>``.
    Library paths, podcast URLs, and radio URLs are NOT redacted because
    they are typically necessary for debugging; review the bundle before
    sharing if those paths are sensitive.
    """
    from .. import __app_name__, __version__

    qt_version = "n/a"
    try:
        from PySide6 import __version__ as qt_version  # type: ignore[no-redef]
    except Exception:  # noqa: BLE001 — diagnostics must never crash
        pass

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    header = "\n".join((
        f"{__app_name__} diagnostics bundle",
        f"Generated:  {now}",
        f"Version:    {__version__}",
        f"Python:     {sys.version.splitlines()[0]}",
        f"PySide6:    {qt_version}",
        f"Platform:   {platform.platform()}",
        f"Executable: {sys.executable}",
        f"Frozen:     {bool(getattr(sys, 'frozen', False))}",
    ))

    check_lines = ["Dependency checks", "-" * 18]
    for check in run_dependency_checks():
        check_lines.append(f"[{check.status.value}] {check.name}")
        check_lines.append(f"  {check.detail}")
        if check.is_problem and check.fix:
            check_lines.append(f"  Fix: {check.fix}")
    check_lines.append("")
    check_lines.append(summarize_dependency_checks(run_dependency_checks()))

    logs_section: list[str] = []
    main_log = logs_dir() / "sea-lyon.log"
    metadata_log = app_data_dir() / "metadata-diagnostics.log"
    logs_section.append("sea-lyon.log (tail)")
    logs_section.append("-" * 19)
    logs_section.append(_read_tail(main_log) or "<empty or missing>")

    if metadata_log.exists():
        logs_section.append("")
        logs_section.append("metadata-diagnostics.log (tail)")
        logs_section.append("-" * 31)
        logs_section.append(_read_tail(metadata_log))

    settings_section = "\n".join((
        "settings.json (secrets redacted)",
        "-" * 32,
        _redacted_settings_json(),
    ))

    return "\n\n".join((
        header,
        "\n".join(check_lines),
        "\n".join(logs_section),
        settings_section,
    )) + "\n"


def summarize_dependency_checks(checks: list[DependencyCheck]) -> str:
    problems = [check for check in checks if check.is_problem]
    if not problems:
        return "All optional runtime dependencies look ready."
    missing = sum(1 for check in problems if check.status is DiagnosticStatus.MISSING)
    warnings = len(problems) - missing
    parts: list[str] = []
    if missing:
        parts.append(f"{missing} missing")
    if warnings:
        parts.append(f"{warnings} warning{'s' if warnings != 1 else ''}")
    return "Dependency checks need attention: " + ", ".join(parts) + "."

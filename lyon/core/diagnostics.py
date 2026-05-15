"""Runtime dependency diagnostics for setup and support."""
from __future__ import annotations

import ctypes.util
import importlib.util
import shutil
import sys
from dataclasses import dataclass
from enum import Enum
from functools import lru_cache
from pathlib import Path

from .settings import bundled_bin_dir


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
        "CD ripping cannot run because ffmpeg was not found.",
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
        "python-vlc is not importable; playback can fall back to Qt Multimedia, but EQ will be flat.",
        "Install python-vlc and provide a VLC runtime under bin/vlc for audible EQ support.",
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


def run_dependency_checks() -> list[DependencyCheck]:
    """Return setup checks in the order users should review them."""
    return [
        check_ffmpeg(),
        check_libdiscid(),
        check_vlc(),
        check_ytdlp(),
    ]


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

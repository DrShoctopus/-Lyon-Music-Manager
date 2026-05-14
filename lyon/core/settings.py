"""User settings and path management."""
from __future__ import annotations

import json
import logging
import os
import sys
from dataclasses import dataclass, asdict, field
from pathlib import Path

from .equalizer import (
    DEFAULT_EQ_CURVE_NAME,
    RESERVED_EQ_CURVE_NAMES,
    UNSAVED_EQ_CURVE_NAME,
    flat_equalizer_bands,
    normalize_equalizer_bands,
)

LOG = logging.getLogger(__name__)


def _default_music_root() -> Path:
    if sys.platform == "win32":
        # Use standard Windows Music folder
        userprofile = os.environ.get("USERPROFILE", os.path.expanduser("~"))
        return Path(userprofile) / "Music" / "Lyon"
    return Path.home() / "Music" / "Lyon"


def app_data_dir() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    p = Path(base) / "LyonMusicManager"
    p.mkdir(parents=True, exist_ok=True)
    return p


def bundled_bin_dir() -> Path:
    """Where ffmpeg.exe / libdiscid live when packaged or in-tree."""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "bin"  # type: ignore[attr-defined]
    return Path(__file__).resolve().parent.parent.parent / "bin"


def _app_version() -> str:
    # Imported lazily to avoid a circular import (lyon.__init__ imports nothing
    # heavy, but settings is imported by lyon.core which __init__ may touch).
    from .. import __version__
    return __version__


def _is_custom_curve_name(name: str) -> bool:
    return bool(name) and name not in RESERVED_EQ_CURVE_NAMES


def normalize_library_paths(paths: object) -> list[str]:
    """Return non-empty library paths without exact duplicates, preserving order."""
    if not isinstance(paths, list | tuple):
        return []

    normalized: list[str] = []
    seen: set[str] = set()
    for value in paths:
        path = str(value).strip()
        if not path or path in seen:
            continue
        normalized.append(path)
        seen.add(path)
    return normalized


@dataclass
class Settings:
    music_root: str = field(default_factory=lambda: str(_default_music_root()))
    rip_format: str = "flac"           # flac is the only supported output today
    flac_compression: int = 8           # 0-8
    cd_drive: str = ""                 # e.g. "D:" - blank means auto-pick first
    musicbrainz_app: str = "LyonMusicManager"
    musicbrainz_version: str = field(default_factory=_app_version)
    musicbrainz_contact: str = "https://example.invalid/lyon"
    theaudiodb_api_key: str = "123"
    eject_after_rip: bool = True
    auto_lookup_metadata: bool = True
    cuetools_db_metadata_enabled: bool = True
    download_artwork: bool = True
    metadata_diagnostics_enabled: bool = False
    last_volume: int = 80
    library_paths: list[str] = field(default_factory=list)
    equalizer_enabled: bool = False
    equalizer_bands: list[int] = field(default_factory=flat_equalizer_bands)
    equalizer_curve_name: str = DEFAULT_EQ_CURVE_NAME
    equalizer_custom_curves: dict[str, list[int]] = field(default_factory=dict)
    first_run_completed: bool = False

    def __post_init__(self) -> None:
        self.library_paths = normalize_library_paths(self.library_paths)
        self.equalizer_bands = normalize_equalizer_bands(self.equalizer_bands)
        custom_curves = self.equalizer_custom_curves if isinstance(self.equalizer_custom_curves, dict) else {}
        self.equalizer_custom_curves = {
            str(name).strip(): normalize_equalizer_bands(curve)
            for name, curve in custom_curves.items()
            if _is_custom_curve_name(str(name).strip())
        }
        self.equalizer_curve_name = str(self.equalizer_curve_name or DEFAULT_EQ_CURVE_NAME).strip()
        custom_curve_selected = self.equalizer_curve_name in self.equalizer_custom_curves
        built_in_curve_selected = self.equalizer_curve_name in RESERVED_EQ_CURVE_NAMES
        if self.equalizer_curve_name == UNSAVED_EQ_CURVE_NAME or not (
            custom_curve_selected or built_in_curve_selected
        ):
            self.equalizer_curve_name = DEFAULT_EQ_CURVE_NAME

    @classmethod
    def load(cls) -> "Settings":
        path = app_data_dir() / "settings.json"
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                # Drop unknown keys so older configs don't crash on upgrade
                known = {f for f in cls.__dataclass_fields__}
                data = {k: v for k, v in data.items() if k in known}
                return cls(**data)
            except (json.JSONDecodeError, TypeError, ValueError):
                backup = path.with_suffix(".json.bad")
                try:
                    path.replace(backup)
                except OSError:
                    pass
                LOG.warning(
                    "settings.json was corrupt; reset to defaults. Bad file saved to %s",
                    backup,
                )
        return cls()

    def save(self) -> None:
        path = app_data_dir() / "settings.json"
        data = json.dumps(asdict(self), indent=2)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(data, encoding="utf-8")
        os.replace(tmp, path)
        invalidate_settings_cache()


# ---------------------------------------------------------------------------
# Module-level settings cache so repeated hot-path calls (metadata lookups,
# diagnostics checks) avoid redundant file I/O on every invocation.
# ---------------------------------------------------------------------------
_settings_cache: "Settings | None" = None


def get_cached_settings() -> "Settings":
    """Return cached Settings, loading from disk on first call."""
    global _settings_cache
    if _settings_cache is None:
        _settings_cache = Settings.load()
    return _settings_cache


def invalidate_settings_cache() -> None:
    """Discard the cached Settings so the next call re-reads from disk."""
    global _settings_cache
    _settings_cache = None

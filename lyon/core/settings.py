"""User settings and path management."""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, asdict, field
from pathlib import Path


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


@dataclass
class Settings:
    music_root: str = field(default_factory=lambda: str(_default_music_root()))
    rip_format: str = "flac"           # flac is the only supported output today
    flac_compression: int = 8           # 0-8
    cd_drive: str = ""                 # e.g. "D:" - blank means auto-pick first
    musicbrainz_app: str = "LyonMusicManager"
    musicbrainz_version: str = field(default_factory=_app_version)
    musicbrainz_contact: str = "https://example.invalid/lyon"
    eject_after_rip: bool = True
    auto_lookup_metadata: bool = True
    download_artwork: bool = True
    last_volume: int = 80
    library_paths: list[str] = field(default_factory=list)

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
            except (json.JSONDecodeError, TypeError):
                pass
        return cls()

    def save(self) -> None:
        path = app_data_dir() / "settings.json"
        path.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")

"""Centralized icon loader.

Prefers SVG assets from docs/brand/icons/<name>.svg when present, falls
back to Qt's QStyle.standardIcon mapping, and finally returns a blank
QIcon so callers can still wire the button without crashing.
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PySide6.QtGui import QIcon

_REPO_ROOT = Path(__file__).resolve().parents[2]
_ICONS_DIR = _REPO_ROOT / "docs" / "brand" / "icons"

_QSTYLE_FALLBACK = {
    "play":         "SP_MediaPlay",
    "pause":        "SP_MediaPause",
    "stop":         "SP_MediaStop",
    "prev":         "SP_MediaSkipBackward",
    "next":         "SP_MediaSkipForward",
    "seek-back":    "SP_MediaSeekBackward",
    "seek-fwd":     "SP_MediaSeekForward",
    "volume":       "SP_MediaVolume",
    "volume-muted": "SP_MediaVolumeMuted",
    "settings":     "SP_FileDialogDetailedView",
    "search":       "SP_FileDialogContentsView",
    "add":          "SP_FileDialogNewFolder",
    "open-folder":  "SP_DirOpenIcon",
    "refresh":      "SP_BrowserReload",
    "close":        "SP_DialogCloseButton",
    "info":         "SP_MessageBoxInformation",
    "warning":      "SP_MessageBoxWarning",
}


def has_asset(name: str) -> bool:
    return (_ICONS_DIR / f"{name}.svg").exists()


def icon(name: str) -> "QIcon":
    from PySide6.QtGui import QIcon
    svg = _ICONS_DIR / f"{name}.svg"
    if svg.exists():
        return QIcon(str(svg))
    standard = _QSTYLE_FALLBACK.get(name)
    if standard is not None:
        from PySide6.QtWidgets import QApplication, QStyle
        app = QApplication.instance()
        if app is not None:
            pixmap_enum = getattr(QStyle.StandardPixmap, standard, None)
            if pixmap_enum is not None:
                return app.style().standardIcon(pixmap_enum)
    return QIcon()

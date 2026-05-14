"""Lyon Media Manager startup branding helpers."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PySide6.QtGui import QIcon, QPixmap
    from PySide6.QtWidgets import QApplication, QMainWindow, QSplashScreen


_REPO_ROOT = Path(__file__).resolve().parents[2]
_BRAND_SUBDIRS = (
    Path("docs") / "brand",
    Path("Docs") / "brand",
)
_ICON_ASSET_NAME = "lyon-app-icon.png"
_SPLASH_ASSET_NAME = "lyon-splash.png"
_ICON_SIZES = (32, 64, 128, 256)


def _resource_roots() -> tuple[Path, ...]:
    """Return possible roots for source-tree and PyInstaller-bundled resources."""
    roots: list[Path] = []
    pyinstaller_root = getattr(sys, "_MEIPASS", None)
    if pyinstaller_root:
        roots.append(Path(pyinstaller_root))
    roots.append(_REPO_ROOT)
    roots.append(Path.cwd())

    unique_roots: list[Path] = []
    for root in roots:
        if root not in unique_roots:
            unique_roots.append(root)
    return tuple(unique_roots)


def _brand_asset_path(asset_name: str) -> Path:
    """Return the first available checked-in branding asset path."""
    candidates = [
        root / subdir / asset_name
        for root in _resource_roots()
        for subdir in _BRAND_SUBDIRS
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def _load_pixmap(path: Path) -> "QPixmap":
    """Load a project branding image from disk."""
    from PySide6.QtGui import QPixmap

    return QPixmap(str(path))


def app_icon() -> "QIcon":
    """Return the application icon from the checked-in branding image."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QIcon

    source = _load_pixmap(_brand_asset_path(_ICON_ASSET_NAME))
    icon = QIcon()
    if source.isNull():
        return icon
    for size in _ICON_SIZES:
        icon.addPixmap(
            source.scaled(
                size,
                size,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )
        )
    return icon


def startup_splash_pixmap() -> "QPixmap":
    """Return the startup splash from the checked-in branding image."""
    return _load_pixmap(_brand_asset_path(_SPLASH_ASSET_NAME))


def create_startup_splash(app: "QApplication") -> "QSplashScreen | None":
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QSplashScreen

    splash_pixmap = startup_splash_pixmap()
    if splash_pixmap.isNull():
        return None

    max_w, max_h = 640, 400
    if splash_pixmap.width() > max_w or splash_pixmap.height() > max_h:
        splash_pixmap = splash_pixmap.scaled(
            max_w, max_h, Qt.KeepAspectRatio, Qt.SmoothTransformation
        )

    splash = QSplashScreen(splash_pixmap, Qt.WindowStaysOnTopHint)

    screen = app.primaryScreen()
    if screen is not None:
        center = screen.availableGeometry().center()
        splash.move(center.x() - splash.width() // 2, center.y() - splash.height() // 2)

    splash.show()
    app.processEvents()
    app._lyon_startup_splash = splash
    return splash


def finish_startup_splash(
    app: "QApplication", window: "QMainWindow", duration_ms: int = 1400
) -> None:
    from PySide6.QtCore import QTimer

    splash = getattr(app, "_lyon_startup_splash", None)
    if splash is None:
        return

    def finish() -> None:
        current = getattr(app, "_lyon_startup_splash", None)
        if current is None:
            return
        current.finish(window)
        app._lyon_startup_splash = None

    QTimer.singleShot(duration_ms, finish)

"""Lyon Media Manager startup branding helpers."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import QApplication, QMainWindow, QSplashScreen


_REPO_ROOT = Path(__file__).resolve().parents[2]
_BRAND_DIR = _REPO_ROOT / "docs" / "brand"
_ICON_ASSET = _BRAND_DIR / "lyon-app-icon.png"
_SPLASH_ASSET = _BRAND_DIR / "lyon-splash.png"
_ICON_SIZES = (32, 64, 128, 256)


def _load_pixmap(path: Path) -> QPixmap:
    """Load a project branding image from disk."""
    return QPixmap(str(path))


def app_icon() -> QIcon:
    """Return the application icon from the checked-in branding image."""
    source = _load_pixmap(_ICON_ASSET)
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


def startup_splash_pixmap() -> QPixmap:
    """Return the startup splash from the checked-in branding image."""
    return _load_pixmap(_SPLASH_ASSET)


def create_startup_splash(app: QApplication) -> QSplashScreen | None:
    splash_pixmap = startup_splash_pixmap()
    if splash_pixmap.isNull():
        return None
    splash = QSplashScreen(splash_pixmap, Qt.WindowStaysOnTopHint)
    splash.show()
    app.processEvents()
    app._lyon_startup_splash = splash
    return splash


def finish_startup_splash(app: QApplication, window: QMainWindow, duration_ms: int = 1400) -> None:
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

"""Application entry point."""
from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from . import __app_name__
from .ui.branding import app_icon, create_startup_splash, finish_startup_splash
from .ui.main_window import MainWindow


def main() -> int:
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setApplicationName(__app_name__)
    app.setOrganizationName("Lyon")
    if sys.platform == "win32":
        app.setFont(QFont("Segoe UI", 9))
    elif sys.platform == "darwin":
        app.setFont(QFont("SF Pro Text", 13))
    else:
        app.setFont(QFont("Ubuntu", 10))

    icon = app_icon()
    app.setWindowIcon(icon)
    create_startup_splash(app)

    win = MainWindow()
    win.setWindowIcon(icon)
    win.show()
    finish_startup_splash(app, win)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())

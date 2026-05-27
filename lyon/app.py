"""Application entry point."""
from __future__ import annotations

import logging
import logging.handlers
import sys
import threading
import traceback
from pathlib import Path
from types import TracebackType
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from . import __app_name__
from .core.settings import app_data_dir, migrate_macos_app_data
from .ui.branding import app_icon, create_startup_splash, finish_startup_splash
from .ui.main_window import MainWindow

LOG = logging.getLogger(__name__)

_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
_LOG_MAX_BYTES = 10 * 1024 * 1024  # 10 MB
_LOG_BACKUP_COUNT = 5


def _logs_dir() -> Path:
    path = app_data_dir() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _configure_logging() -> None:
    """Attach a rotating file handler + stderr handler to the root logger.

    Idempotent: skips setup if a RotatingFileHandler is already attached, so
    repeated imports (pytest, tooling) don't multiply handlers.
    """
    root = logging.getLogger()
    for handler in root.handlers:
        if isinstance(handler, logging.handlers.RotatingFileHandler):
            return

    root.setLevel(logging.INFO)

    try:
        log_path = _logs_dir() / "sea-lyon.log"
        file_handler = logging.handlers.RotatingFileHandler(
            log_path,
            maxBytes=_LOG_MAX_BYTES,
            backupCount=_LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(logging.Formatter(_LOG_FORMAT))
        root.addHandler(file_handler)
    except OSError as exc:
        print(f"warning: could not open log file: {exc}", file=sys.stderr)

    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setLevel(logging.WARNING)
    stderr_handler.setFormatter(logging.Formatter(_LOG_FORMAT))
    root.addHandler(stderr_handler)


def _install_excepthooks() -> None:
    """Route uncaught exceptions through the logging system before defaulting."""
    original_excepthook = sys.excepthook

    def _log_uncaught(
        exc_type: type[BaseException],
        exc_value: BaseException,
        exc_tb: TracebackType | None,
    ) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            original_excepthook(exc_type, exc_value, exc_tb)
            return
        LOG.critical(
            "Uncaught exception:\n%s",
            "".join(traceback.format_exception(exc_type, exc_value, exc_tb)),
        )
        original_excepthook(exc_type, exc_value, exc_tb)

    sys.excepthook = _log_uncaught

    def _log_thread_exception(args: Any) -> None:
        LOG.critical(
            "Uncaught exception in thread %s:\n%s",
            getattr(args.thread, "name", "<unknown>"),
            "".join(
                traceback.format_exception(
                    args.exc_type, args.exc_value, args.exc_traceback
                )
            ),
        )

    threading.excepthook = _log_thread_exception


def main() -> int:
    migrate_macos_app_data()
    _configure_logging()
    _install_excepthooks()
    LOG.info("Starting %s", __app_name__)

    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setApplicationName(__app_name__)
    app.setOrganizationName("Lyon")
    if sys.platform == "win32":
        app.setFont(QFont("Segoe UI", 9))
    elif sys.platform == "darwin":
        app.setFont(QFont(".AppleSystemUIFont", 13))
    else:
        app.setFont(QFont("Ubuntu", 10))

    icon = app_icon()
    app.setWindowIcon(icon)
    create_startup_splash(app)

    win = MainWindow()
    win.setWindowIcon(icon)
    if sys.platform == "darwin":
        win.show()
    else:
        win.showMaximized()
    finish_startup_splash(app, win)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())

"""Application entry point."""
from __future__ import annotations

import faulthandler
import logging
import logging.handlers
import sys
import threading
import traceback
from datetime import datetime, timezone
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
_NATIVE_FAULT_LOG_STREAM: Any | None = None


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


def _configure_native_fault_logging() -> None:
    """Capture native Qt/Python faults that bypass normal exception logging."""
    global _NATIVE_FAULT_LOG_STREAM
    if _NATIVE_FAULT_LOG_STREAM is not None:
        return
    try:
        stream = (_logs_dir() / "native-fault.log").open("a", encoding="utf-8")
        stream.write(
            "\n--- startup "
            f"{datetime.now(timezone.utc).isoformat(timespec='seconds')} ---\n"
        )
        stream.flush()
        faulthandler.enable(file=stream, all_threads=True)
        _NATIVE_FAULT_LOG_STREAM = stream
    except (OSError, RuntimeError) as exc:
        LOG.warning("Could not enable native fault logging: %s", exc)


def _close_native_fault_logging() -> None:
    global _NATIVE_FAULT_LOG_STREAM
    stream = _NATIVE_FAULT_LOG_STREAM
    _NATIVE_FAULT_LOG_STREAM = None
    if stream is None:
        return
    try:
        faulthandler.disable()
    finally:
        stream.close()


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
    _configure_native_fault_logging()
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
    try:
        return app.exec()
    finally:
        _close_native_fault_logging()


if __name__ == "__main__":
    sys.exit(main())

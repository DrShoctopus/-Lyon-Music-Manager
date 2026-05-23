"""Tabbed About dialog for Sea Lyon Media Manager.

Tabs:
  1. About            -- app name, version, copyright, brief description.
  2. Acknowledgements -- structured list of bundled deps + networked services.
  3. Licenses         -- full THIRD_PARTY_NOTICES.txt in a scrollable view.
  4. System Info      -- Python / Qt / OS, log folder, "Open" + "Copy
                         Diagnostics" buttons.
"""
from __future__ import annotations

import platform
import sys
from pathlib import Path

from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QClipboard, QDesktopServices, QGuiApplication, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .. import __app_name__, __version__
from ..core.diagnostics import collect_diagnostics_bundle, logs_dir
from .about import (
    ATTRIBUTIONS,
    COPYRIGHT_NOTICE,
    NETWORK_SERVICES,
    format_license_summary,
    licenses_full_text,
)
from .branding import app_icon


def _bundled_file_paths(filename: str) -> list[Path]:
    """Search paths for a bundled docs file at runtime."""
    paths: list[Path] = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        paths.append(Path(meipass) / filename)
    if getattr(sys, "frozen", False):
        paths.append(Path(sys.executable).resolve().parent / filename)
    # source-run / dev tests: repo root
    paths.append(Path(__file__).resolve().parents[2] / filename)
    return paths


def _find_bundled_file(filename: str) -> Path | None:
    for candidate in _bundled_file_paths(filename):
        if candidate.exists():
            return candidate
    return None


class AboutDialog(QDialog):
    """Tabbed About / Acknowledgements / Licenses / System Info dialog."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"About {__app_name__}")
        self.setMinimumSize(640, 520)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(10)

        tabs = QTabWidget(self)
        tabs.addTab(self._build_about_tab(), "About")
        tabs.addTab(self._build_acknowledgements_tab(), "Acknowledgements")
        tabs.addTab(self._build_licenses_tab(), "Licenses")
        tabs.addTab(self._build_system_info_tab(), "System Info")
        outer.addWidget(tabs, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        close_btn = buttons.button(QDialogButtonBox.StandardButton.Close)
        if close_btn is not None:
            close_btn.clicked.connect(self.accept)
        outer.addWidget(buttons)

    # -- tabs --------------------------------------------------------------

    def _build_about_tab(self) -> QWidget:
        widget = QWidget(self)
        layout = QVBoxLayout(widget)
        layout.setSpacing(12)

        icon_row = QHBoxLayout()
        icon_label = QLabel(widget)
        icon_label.setPixmap(app_icon().pixmap(72, 72))
        icon_row.addWidget(icon_label, 0, Qt.AlignTop)

        text_col = QVBoxLayout()
        title = QLabel(f"<h2>{__app_name__}</h2>", widget)
        title.setTextFormat(Qt.RichText)
        version = QLabel(f"Version {__version__}", widget)
        version.setStyleSheet("color: #888;")
        text_col.addWidget(title)
        text_col.addWidget(version)
        text_col.addStretch(1)
        icon_row.addLayout(text_col, 1)
        layout.addLayout(icon_row)

        description = QLabel(
            "Sea Lyon is a music library manager, CD ripper, podcast / radio "
            "player, and video player for Windows 10 and 11.",
            widget,
        )
        description.setWordWrap(True)
        layout.addWidget(description)

        copyright_label = QLabel(COPYRIGHT_NOTICE, widget)
        copyright_label.setWordWrap(True)
        layout.addWidget(copyright_label)

        links_row = QHBoxLayout()
        homepage_btn = QPushButton("Open Project Page", widget)
        homepage_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(
                QUrl("https://github.com/DrShoctopus/Sea-Lyon-Media-Manager")
            )
        )
        releases_btn = QPushButton("Releases / Changelog", widget)
        releases_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(
                QUrl("https://github.com/DrShoctopus/Sea-Lyon-Media-Manager/releases")
            )
        )
        links_row.addWidget(homepage_btn)
        links_row.addWidget(releases_btn)
        links_row.addStretch(1)
        layout.addLayout(links_row)

        layout.addStretch(1)
        return widget

    def _build_acknowledgements_tab(self) -> QWidget:
        widget = QWidget(self)
        layout = QVBoxLayout(widget)

        intro = QLabel(
            "Sea Lyon stands on the shoulders of the following open-source "
            "components. The full license texts are in the Licenses tab; "
            "the privacy policy lists every networked endpoint.",
            widget,
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        summary = QPlainTextEdit(widget)
        summary.setReadOnly(True)
        summary.setPlainText(format_license_summary())
        summary.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        layout.addWidget(summary, 1)

        privacy_row = QHBoxLayout()
        privacy_btn = QPushButton("Open Privacy Policy", widget)
        privacy_btn.clicked.connect(self._open_privacy_policy)
        privacy_btn.setToolTip("Open PRIVACY.md in your default app")
        privacy_row.addWidget(privacy_btn)

        eula_btn = QPushButton("Open EULA", widget)
        eula_btn.clicked.connect(self._open_eula)
        privacy_row.addWidget(eula_btn)
        privacy_row.addStretch(1)
        layout.addLayout(privacy_row)

        # Indicate component count so users can compare against THIRD_PARTY_NOTICES.
        count_label = QLabel(
            f"{len(ATTRIBUTIONS)} bundled components, "
            f"{len(NETWORK_SERVICES)} networked services.",
            widget,
        )
        count_label.setStyleSheet("color: #888;")
        layout.addWidget(count_label)
        return widget

    def _build_licenses_tab(self) -> QWidget:
        widget = QWidget(self)
        layout = QVBoxLayout(widget)

        intro = QLabel(
            "Full text of every license shipped with this build. Where a "
            "license text is referenced by URL rather than included inline, "
            "see THIRD_PARTY_NOTICES.txt in the install folder for the "
            "authoritative copy.",
            widget,
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        viewer = QPlainTextEdit(widget)
        viewer.setReadOnly(True)
        viewer.setPlainText(licenses_full_text())
        viewer.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        layout.addWidget(viewer, 1)
        return widget

    def _build_system_info_tab(self) -> QWidget:
        widget = QWidget(self)
        layout = QVBoxLayout(widget)

        qt_version = "n/a"
        try:
            from PySide6 import __version__ as qt_version  # type: ignore[no-redef]
        except Exception:  # noqa: BLE001
            pass

        info_lines = [
            f"App:        {__app_name__} {__version__}",
            f"Python:     {sys.version.splitlines()[0]}",
            f"PySide6:    {qt_version}",
            f"Platform:   {platform.platform()}",
            f"Executable: {sys.executable}",
            f"Frozen:     {bool(getattr(sys, 'frozen', False))}",
        ]
        info = QPlainTextEdit(widget)
        info.setReadOnly(True)
        info.setPlainText("\n".join(info_lines))
        info.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        info.setMaximumHeight(140)
        layout.addWidget(info)

        # D5: log folder display + open button.
        log_path = logs_dir()
        log_row = QHBoxLayout()
        log_label = QLabel(f"<b>Log folder:</b> {log_path}", widget)
        log_label.setTextFormat(Qt.RichText)
        log_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        log_row.addWidget(log_label, 1)
        open_logs_btn = QPushButton("Open", widget)
        open_logs_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(log_path)))
        )
        log_row.addWidget(open_logs_btn)
        layout.addLayout(log_row)

        # D4-mirror: also expose a Copy Diagnostics button here so power-users
        # who go to About → System Info can grab a bundle without leaving
        # the dialog.
        diag_row = QHBoxLayout()
        copy_btn = QPushButton("Copy Diagnostics to Clipboard", widget)
        copy_btn.setToolTip(
            "Build a multi-section text bundle (versions, dependency checks, "
            "log tails, redacted settings) and copy it to the clipboard.")
        copy_btn.clicked.connect(self._copy_diagnostics)
        diag_row.addWidget(copy_btn)
        diag_row.addStretch(1)
        layout.addLayout(diag_row)

        layout.addStretch(1)
        return widget

    # -- helpers -----------------------------------------------------------

    def _open_privacy_policy(self) -> None:
        path = _find_bundled_file("PRIVACY.md")
        if path is None:
            QDesktopServices.openUrl(
                QUrl(
                    "https://github.com/DrShoctopus/Sea-Lyon-Media-Manager/"
                    "blob/main/PRIVACY.md"
                )
            )
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _open_eula(self) -> None:
        path = _find_bundled_file("EULA.txt")
        if path is None:
            QDesktopServices.openUrl(
                QUrl(
                    "https://github.com/DrShoctopus/Sea-Lyon-Media-Manager/"
                    "blob/main/EULA.txt"
                )
            )
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _copy_diagnostics(self) -> None:
        bundle = collect_diagnostics_bundle()
        clipboard: QClipboard | None = QGuiApplication.clipboard()
        if clipboard is None:
            clipboard = QApplication.clipboard()
        clipboard.setText(bundle)
        # Surface a confirmation by re-titling the button briefly.
        sender = self.sender()
        if isinstance(sender, QPushButton):
            original = sender.text()
            sender.setText("Copied!")
            sender.setEnabled(False)
            from PySide6.QtCore import QTimer
            QTimer.singleShot(
                1500,
                lambda b=sender, t=original: (b.setText(t), b.setEnabled(True)),
            )

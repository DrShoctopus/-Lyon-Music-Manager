"""Non-modal "An update is available" dialog.

Shown by ``MainWindow`` when the startup update check returns an
:class:`~lyon.core.updater.UpdateInfo` newer than the running build and
the user hasn't already chosen "Skip This Version" for that specific
release.

The dialog **does not** download or apply the update — it opens the
enclosure URL in the user's default browser and the user runs the
installer manually. In-place patching is post-1.0.
"""
from __future__ import annotations

import sys
from urllib.parse import urlparse

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from .. import __version__
from ..core.updater import UpdateInfo

_OPENABLE_UPDATE_SCHEMES = {"https"}


def _open_update_url(value: str | QUrl) -> bool:
    url = value.toString() if isinstance(value, QUrl) else str(value or "").strip()
    parsed = urlparse(url)
    if parsed.scheme.casefold() not in _OPENABLE_UPDATE_SCHEMES or not parsed.netloc:
        return False
    return QDesktopServices.openUrl(QUrl(url))


class UpdateAvailableDialog(QDialog):
    """Three-button release notice: Download Now / Skip This Version / Later."""

    # Emitted with the version string when the user chooses "Skip This Version".
    version_skipped = Signal(str)

    def __init__(self, info: UpdateInfo, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._info = info
        self.setWindowTitle("Update Available")
        self.setMinimumSize(540, 420)
        # Modeless — let the user keep using the app while they think about it.
        self.setModal(False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        header = QLabel(
            f"<h3>Sea Lyon Media Manager {info.version} is available</h3>"
            f"<div style='color:#888'>You're running version {__version__}.</div>",
            self,
        )
        header.setTextFormat(Qt.RichText)
        layout.addWidget(header)

        notes_label = QLabel("Release notes:", self)
        layout.addWidget(notes_label)

        notes = QTextBrowser(self)
        notes.setOpenExternalLinks(False)
        notes.anchorClicked.connect(_open_update_url)
        notes.setHtml(info.release_notes_html or "<i>No release notes provided.</i>")
        layout.addWidget(notes, 1)

        button_row = QHBoxLayout()

        if sys.platform == "darwin":
            dl_label = "Download Disk Image"
        else:
            dl_label = "Download Installer"
        download_btn = QPushButton(dl_label, self)
        download_btn.setDefault(True)
        download_btn.clicked.connect(self._on_download)
        button_row.addWidget(download_btn)

        if info.release_url:
            view_btn = QPushButton("View Release Page", self)
            view_btn.clicked.connect(lambda: _open_update_url(info.release_url))
            button_row.addWidget(view_btn)

        button_row.addStretch(1)

        skip_btn = QPushButton("Skip This Version", self)
        skip_btn.clicked.connect(self._on_skip)
        button_row.addWidget(skip_btn)

        later_btn = QPushButton("Remind Me Later", self)
        later_btn.clicked.connect(self.reject)
        button_row.addWidget(later_btn)

        layout.addLayout(button_row)

    def _on_download(self) -> None:
        for target in (self._info.download_url, self._info.release_url):
            if _open_update_url(target):
                break
        self.accept()

    def _on_skip(self) -> None:
        self.version_skipped.emit(self._info.version)
        self.reject()

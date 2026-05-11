"""First-run setup and health-check dialog."""
from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QPushButton, QVBoxLayout, QWidget,
)

from ..core import cd_detect
from ..core.ripper import find_ffmpeg
from ..core.settings import Settings, bundled_bin_dir
from .youtube_view import HAS_WEBENGINE


@dataclass(frozen=True)
class HealthCheck:
    label: str
    detail: str
    ok: bool
    required: bool = False

    @property
    def icon(self) -> str:
        if self.ok:
            return "✓"
        return "!" if self.required else "i"

    @property
    def status(self) -> str:
        if self.ok:
            return "Ready"
        return "Needs attention" if self.required else "Optional"


def build_health_checks(settings: Settings) -> list[HealthCheck]:
    music_root = Path(settings.music_root).expanduser()
    ffmpeg = find_ffmpeg()
    bin_dir = bundled_bin_dir()
    discid_dll = bin_dir / "discid.dll"
    libdiscid_dll = bin_dir / "libdiscid.dll"
    discid_python = importlib.util.find_spec("discid") is not None
    contact_ok = (
        bool(settings.musicbrainz_contact.strip())
        and "example.invalid" not in settings.musicbrainz_contact
    )
    drives = cd_detect.list_cd_drives()

    return [
        HealthCheck(
            "Music folder",
            str(music_root) if music_root.exists() else f"Create or choose a folder: {music_root}",
            music_root.exists(),
            required=True,
        ),
        HealthCheck(
            "FFmpeg",
            ffmpeg or "Put ffmpeg.exe in bin/ or add ffmpeg to PATH before ripping CDs.",
            ffmpeg is not None,
            required=True,
        ),
        HealthCheck(
            "libdiscid",
            "Python discid package and DLL are available."
            if discid_python and (discid_dll.exists() or libdiscid_dll.exists())
            else "Install the discid package and place discid.dll in bin/ for disc IDs.",
            discid_python and (discid_dll.exists() or libdiscid_dll.exists()),
            required=True,
        ),
        HealthCheck(
            "MusicBrainz contact",
            settings.musicbrainz_contact
            if contact_ok
            else "Set a real contact value before heavy metadata lookup.",
            contact_ok,
        ),
        HealthCheck(
            "CD drive",
            ", ".join(drives) if drives else "No optical drive detected right now.",
            bool(drives),
        ),
        HealthCheck(
            "YouTube tab",
            "Qt WebEngine is installed." if HAS_WEBENGINE else "Install PySide6-Addons to enable embedded YouTube.",
            HAS_WEBENGINE,
        ),
    ]


class SetupDialog(QDialog):
    """Shows first-run setup status and lets users jump to Settings."""

    open_settings_requested = Signal()

    def __init__(self, settings: Settings, parent: QWidget | None = None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("Setup & Health Check")
        self.resize(680, 460)

        title = QLabel("Finish setting up Lyon Music Manager")
        font = title.font()
        font.setPointSize(16)
        font.setBold(True)
        title.setFont(font)
        title.setStyleSheet("color:#72f4ff;")

        body = QLabel(
            "Review the items below before ripping CDs or doing metadata lookups. "
            "You can keep using the library and player while optional items are incomplete."
        )
        body.setWordWrap(True)

        self.list = QListWidget()
        self.list.setAlternatingRowColors(True)

        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.refresh)
        settings_btn = QPushButton("Open Settings")
        settings_btn.setObjectName("accent")
        settings_btn.clicked.connect(lambda: self.open_settings_requested.emit())
        action_row = QHBoxLayout()
        action_row.addWidget(refresh)
        action_row.addStretch(1)
        action_row.addWidget(settings_btn)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok)
        buttons.accepted.connect(self.accept)

        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addWidget(body)
        layout.addWidget(self.list, 1)
        layout.addLayout(action_row)
        layout.addWidget(buttons)
        self.refresh()

    def refresh(self) -> None:
        self.list.clear()
        for check in build_health_checks(self.settings):
            item = QListWidgetItem(
                f"{check.icon}  {check.label} — {check.status}\n{check.detail}"
            )
            item.setToolTip(check.detail)
            if check.ok:
                item.setForeground(QColor("#8af27c"))
            elif check.required:
                item.setForeground(QColor("#ffd866"))
            self.list.addItem(item)

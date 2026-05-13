"""Settings dialog."""
from __future__ import annotations

from dataclasses import replace

from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout,
    QLineEdit, QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

from ..core.settings import Settings


class SettingsDialog(QDialog):
    def __init__(self, settings: Settings, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.resize(520, 360)
        self.result_settings = replace(settings)

        form = QFormLayout()

        # Music root
        root_row = QHBoxLayout()
        self.root_edit = QLineEdit(settings.music_root)
        browse = QPushButton("Browse...")
        browse.clicked.connect(self._browse_root)
        root_row.addWidget(self.root_edit, 1)
        root_row.addWidget(browse)
        root_w = QWidget(); root_w.setLayout(root_row)
        form.addRow("Music folder:", root_w)

        # FLAC compression
        self.compression = QSpinBox()
        self.compression.setRange(0, 8)
        self.compression.setValue(settings.flac_compression)
        form.addRow("FLAC compression (0=fast, 8=best):", self.compression)

        # CD drive
        self.drive = QLineEdit(settings.cd_drive)
        self.drive.setPlaceholderText("e.g. D: (leave blank for auto)")
        form.addRow("Default CD drive:", self.drive)

        # Toggles
        self.eject = QCheckBox("Eject disc after rip")
        self.eject.setChecked(settings.eject_after_rip)
        form.addRow("", self.eject)

        self.lookup = QCheckBox("Look up metadata online")
        self.lookup.setChecked(settings.auto_lookup_metadata)
        form.addRow("", self.lookup)

        self.cuetools_db = QCheckBox("Use CUETools DB Metadata Plugin lookup")
        self.cuetools_db.setChecked(settings.cuetools_db_metadata_enabled)
        form.addRow("", self.cuetools_db)

        self.artwork = QCheckBox("Download cover art")
        self.artwork.setChecked(settings.download_artwork)
        form.addRow("", self.artwork)

        self.metadata_diagnostics = QCheckBox("Log detailed metadata lookup diagnostics")
        self.metadata_diagnostics.setChecked(settings.metadata_diagnostics_enabled)
        form.addRow("", self.metadata_diagnostics)

        # Provider settings
        self.contact = QLineEdit(settings.musicbrainz_contact)
        form.addRow("MusicBrainz contact:", self.contact)

        self.audiodb_key = QLineEdit(settings.theaudiodb_api_key)
        self.audiodb_key.setPlaceholderText("123")
        form.addRow("TheAudioDB API key:", self.audiodb_key)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._accept)
        bb.rejected.connect(self.reject)
        layout.addWidget(bb)

    def _browse_root(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Choose music folder", self.root_edit.text())
        if d:
            self.root_edit.setText(d)

    def _accept(self) -> None:
        self.result_settings.music_root = self.root_edit.text().strip() or self.result_settings.music_root
        self.result_settings.flac_compression = self.compression.value()
        self.result_settings.cd_drive = self.drive.text().strip()
        self.result_settings.eject_after_rip = self.eject.isChecked()
        self.result_settings.auto_lookup_metadata = self.lookup.isChecked()
        self.result_settings.cuetools_db_metadata_enabled = self.cuetools_db.isChecked()
        self.result_settings.download_artwork = self.artwork.isChecked()
        self.result_settings.metadata_diagnostics_enabled = self.metadata_diagnostics.isChecked()
        self.result_settings.musicbrainz_contact = self.contact.text().strip() or self.result_settings.musicbrainz_contact
        self.result_settings.theaudiodb_api_key = self.audiodb_key.text().strip() or "123"
        self.accept()

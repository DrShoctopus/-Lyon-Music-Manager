"""Settings dialog."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QPushButton, QSpinBox,
    QTabWidget, QVBoxLayout, QWidget,
)

from .. import __app_name__, __version__
from ..core.settings import Settings, normalize_library_paths


class SettingsDialog(QDialog):
    def __init__(self, settings: Settings, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.resize(540, 420)
        self.result_settings = replace(settings)
        self.result_settings.library_paths = normalize_library_paths(settings.library_paths)

        tabs = QTabWidget()
        tabs.addTab(self._build_library_tab(settings), "Library")
        tabs.addTab(self._build_ripping_tab(settings), "CD Ripping")
        tabs.addTab(self._build_metadata_tab(settings), "Metadata")
        tabs.addTab(self._build_youtube_tab(settings), "YouTube")
        tabs.addTab(self._build_about_tab(), "About")

        layout = QVBoxLayout(self)
        layout.addWidget(tabs)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._accept)
        bb.rejected.connect(self.reject)
        layout.addWidget(bb)

    # ------------------------------------------------------------------ tabs

    def _build_library_tab(self, settings: Settings) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        form.setContentsMargins(12, 12, 12, 12)
        form.setVerticalSpacing(8)

        root_row = QHBoxLayout()
        self.root_edit = QLineEdit(settings.music_root)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse_root)
        root_row.addWidget(self.root_edit, 1)
        root_row.addWidget(browse)
        root_w = QWidget(); root_w.setLayout(root_row)
        form.addRow("Music folder:", root_w)

        folders_box = QVBoxLayout()
        self.library_paths = QListWidget()
        self.library_paths.setMinimumHeight(100)
        for folder in normalize_library_paths(settings.library_paths):
            self.library_paths.addItem(folder)
        folder_buttons = QHBoxLayout()
        add_folder_btn = QPushButton("Add…")
        remove_folder_btn = QPushButton("Remove")
        add_folder_btn.clicked.connect(self._add_library_folder)
        remove_folder_btn.clicked.connect(self._remove_library_folder)
        folder_buttons.addWidget(add_folder_btn)
        folder_buttons.addWidget(remove_folder_btn)
        folder_buttons.addStretch(1)
        folders_box.addWidget(self.library_paths)
        folders_box.addLayout(folder_buttons)
        folders_w = QWidget(); folders_w.setLayout(folders_box)
        form.addRow("Library folders:", folders_w)

        return w

    def _build_ripping_tab(self, settings: Settings) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        form.setContentsMargins(12, 12, 12, 12)
        form.setVerticalSpacing(8)

        self.drive = QLineEdit(settings.cd_drive)
        self.drive.setPlaceholderText("e.g. D:  (leave blank for auto)")
        form.addRow("CD drive:", self.drive)

        self.compression = QSpinBox()
        self.compression.setRange(0, 8)
        self.compression.setValue(settings.flac_compression)
        self.compression.setToolTip("0 = fastest encode, 8 = smallest file size")
        form.addRow("FLAC compression:", self.compression)

        self.eject = QCheckBox("Eject disc after rip")
        self.eject.setChecked(settings.eject_after_rip)
        form.addRow("", self.eject)

        self.ctdb_verify = QCheckBox("Verify rip accuracy against CUETools DB")
        self.ctdb_verify.setChecked(settings.ctdb_verify_rips)
        form.addRow("", self.ctdb_verify)

        return w

    def _build_metadata_tab(self, settings: Settings) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        form.setContentsMargins(12, 12, 12, 12)
        form.setVerticalSpacing(8)

        self.lookup = QCheckBox("Look up metadata online automatically")
        self.lookup.setChecked(settings.auto_lookup_metadata)
        form.addRow("", self.lookup)

        self.cuetools_db = QCheckBox("Use CUETools DB plugin for metadata")
        self.cuetools_db.setChecked(settings.cuetools_db_metadata_enabled)
        form.addRow("", self.cuetools_db)

        self.artwork = QCheckBox("Download cover art")
        self.artwork.setChecked(settings.download_artwork)
        form.addRow("", self.artwork)

        self.metadata_diagnostics = QCheckBox("Log detailed metadata diagnostics")
        self.metadata_diagnostics.setChecked(settings.metadata_diagnostics_enabled)
        form.addRow("", self.metadata_diagnostics)

        self.contact = QLineEdit(settings.musicbrainz_contact)
        form.addRow("MusicBrainz contact:", self.contact)

        self.audiodb_key = QLineEdit(settings.theaudiodb_api_key)
        self.audiodb_key.setPlaceholderText("123")
        form.addRow("TheAudioDB API key:", self.audiodb_key)

        return w

    def _build_youtube_tab(self, settings: Settings) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        form.setContentsMargins(12, 12, 12, 12)
        form.setVerticalSpacing(8)

        self.yt_audio_fmt = QComboBox()
        self.yt_audio_fmt.addItems(["flac", "mp3"])
        self.yt_audio_fmt.setCurrentText(settings.yt_audio_format)
        form.addRow("Audio-only format:", self.yt_audio_fmt)

        self.yt_video_fmt = QComboBox()
        self.yt_video_fmt.addItems(["mp4", "mkv", "webm"])
        self.yt_video_fmt.setCurrentText(settings.yt_video_format)
        form.addRow("Video format (video + audio):", self.yt_video_fmt)

        save_dir_row = QHBoxLayout()
        default_save = settings.yt_output_dir or str(Path(settings.music_root) / "YouTube")
        self.yt_save_dir = QLineEdit(settings.yt_output_dir)
        self.yt_save_dir.setPlaceholderText(default_save)
        browse_save = QPushButton("Browse…")
        browse_save.clicked.connect(lambda: self._browse_yt_dir(self.yt_save_dir))
        save_dir_row.addWidget(self.yt_save_dir, 1)
        save_dir_row.addWidget(browse_save)
        save_dir_w = QWidget(); save_dir_w.setLayout(save_dir_row)
        form.addRow("Save folder:", save_dir_w)

        self.yt_auto_add = QCheckBox("Automatically add downloads to library")
        self.yt_auto_add.setChecked(settings.yt_auto_add)
        form.addRow("", self.yt_auto_add)

        return w

    def _build_about_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(6)

        name_label = QLabel(__app_name__)
        name_label.setStyleSheet("font-size:18px;font-weight:700;")
        layout.addWidget(name_label)

        version_label = QLabel(f"Version {__version__}")
        version_label.setStyleSheet("font-size:12px;color:#888;")
        layout.addWidget(version_label)

        layout.addSpacing(12)

        desc = QLabel(
            "Lyon is a music library manager, CD ripper, and player\n"
            "for Windows, macOS, and Linux."
        )
        desc.setWordWrap(True)
        layout.addWidget(desc)

        layout.addSpacing(12)

        license_label = QLabel("Released under the MIT License.")
        license_label.setStyleSheet("color:#888;")
        layout.addWidget(license_label)

        layout.addStretch(1)
        return w

    # ------------------------------------------------------------------ helpers

    def _browse_root(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Choose music folder", self.root_edit.text())
        if d:
            self.root_edit.setText(d)

    def _browse_yt_dir(self, line_edit: QLineEdit) -> None:
        start = line_edit.text() or self.root_edit.text()
        d = QFileDialog.getExistingDirectory(self, "Choose folder", start)
        if d:
            line_edit.setText(d)

    def _add_library_folder(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Add library folder", self.root_edit.text())
        if d and not self._library_folder_exists(d):
            self.library_paths.addItem(d)

    def _remove_library_folder(self) -> None:
        for item in self.library_paths.selectedItems():
            self.library_paths.takeItem(self.library_paths.row(item))

    def _library_folder_exists(self, folder: str) -> bool:
        return any(self.library_paths.item(row).text() == folder for row in range(self.library_paths.count()))

    # ------------------------------------------------------------------ accept

    def _accept(self) -> None:
        self.result_settings.music_root = self.root_edit.text().strip() or self.result_settings.music_root
        self.result_settings.flac_compression = self.compression.value()
        self.result_settings.cd_drive = self.drive.text().strip()
        self.result_settings.library_paths = normalize_library_paths([
            self.library_paths.item(row).text()
            for row in range(self.library_paths.count())
        ])
        self.result_settings.eject_after_rip = self.eject.isChecked()
        self.result_settings.auto_lookup_metadata = self.lookup.isChecked()
        self.result_settings.cuetools_db_metadata_enabled = self.cuetools_db.isChecked()
        self.result_settings.download_artwork = self.artwork.isChecked()
        self.result_settings.metadata_diagnostics_enabled = self.metadata_diagnostics.isChecked()
        self.result_settings.ctdb_verify_rips = self.ctdb_verify.isChecked()
        self.result_settings.musicbrainz_contact = self.contact.text().strip() or self.result_settings.musicbrainz_contact
        self.result_settings.theaudiodb_api_key = self.audiodb_key.text().strip() or "123"
        self.result_settings.yt_audio_format = self.yt_audio_fmt.currentText()
        self.result_settings.yt_video_format = self.yt_video_fmt.currentText()
        self.result_settings.yt_output_dir = self.yt_save_dir.text().strip()
        self.result_settings.yt_auto_add = self.yt_auto_add.isChecked()
        self.accept()

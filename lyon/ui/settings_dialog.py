"""Settings dialog."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog,
    QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QMessageBox,
    QPushButton, QSpinBox, QTabWidget, QVBoxLayout, QWidget,
)

from .. import __app_name__, __version__
from ..core.settings import Settings, normalize_library_paths
from .branding import app_icon

# (display label, settings key) pairs — order matches the combo box
_RIP_FORMATS = [
    ("FLAC (Lossless)",          "flac"),
    ("MP3",                      "mp3"),
    ("AAC / M4A",                "aac"),
    ("Opus",                     "opus"),
    ("OGG Vorbis",               "ogg"),
    ("ALAC (Apple Lossless)",    "alac"),
    ("WAV (Uncompressed)",       "wav"),
    ("AIFF",                     "aiff"),
    ("WMA",                      "wma"),
]
_LOSSY_FORMATS = {"mp3", "aac", "opus", "ogg", "wma"}
_FLAC_FORMAT = "flac"


class SettingsDialog(QDialog):
    def __init__(self, settings: Settings, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.resize(540, 420)
        self.result_settings = replace(settings)
        self.result_settings.library_paths = normalize_library_paths(settings.library_paths)
        self._initial_music_root = settings.music_root.strip()
        self._initial_library_paths = set(self.result_settings.library_paths)

        tabs = QTabWidget()
        tabs.addTab(self._build_library_tab(settings), "Library")
        tabs.addTab(self._build_playback_tab(settings), "Playback")
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

        self._root_warn = QLabel("")
        self._root_warn.setObjectName("warningLabel")
        self._root_warn.setVisible(False)
        form.addRow("", self._root_warn)
        self.root_edit.textChanged.connect(self._check_root_path)

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

        self.watch_library_folders = QCheckBox("Watch library folders for changes")
        self.watch_library_folders.setChecked(settings.watch_library_folders)
        self.watch_library_folders.setToolTip(
            "Automatically add, refresh, and remove library records when files change "
            "inside saved library folders."
        )
        form.addRow("", self.watch_library_folders)

        return w

    def _build_playback_tab(self, settings: Settings) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        form.setContentsMargins(12, 12, 12, 12)
        form.setVerticalSpacing(8)

        rg_label = QLabel("ReplayGain")
        rg_label.setObjectName("sectionHeader")
        form.addRow(rg_label)

        self.rg_mode = QComboBox()
        self.rg_mode.addItem("Off", "off")
        self.rg_mode.addItem("Track Gain", "track")
        self.rg_mode.addItem("Album Gain", "album")
        for i in range(self.rg_mode.count()):
            if self.rg_mode.itemData(i) == settings.replaygain_mode:
                self.rg_mode.setCurrentIndex(i)
                break
        form.addRow("Normalization mode:", self.rg_mode)

        self.rg_preamp = QDoubleSpinBox()
        self.rg_preamp.setRange(-6.0, 6.0)
        self.rg_preamp.setSingleStep(0.5)
        self.rg_preamp.setDecimals(1)
        self.rg_preamp.setSuffix(" dB")
        self.rg_preamp.setValue(settings.replaygain_preamp_db)
        self.rg_preamp.setToolTip(
            "Additional offset applied after the ReplayGain adjustment. "
            "Use a negative value to add headroom."
        )
        form.addRow("Pre-amp:", self.rg_preamp)

        self.rg_prevent_clipping = QCheckBox("Prevent clipping (never boost above original volume)")
        self.rg_prevent_clipping.setChecked(settings.replaygain_prevent_clipping)
        form.addRow("", self.rg_prevent_clipping)

        return w

    def _build_ripping_tab(self, settings: Settings) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        form.setContentsMargins(12, 12, 12, 12)
        form.setVerticalSpacing(8)

        self.drive = QLineEdit(settings.cd_drive)
        self.drive.setPlaceholderText("e.g. D:  (leave blank for auto)")
        form.addRow("CD drive:", self.drive)

        self.rip_fmt = QComboBox()
        for label, key in _RIP_FORMATS:
            self.rip_fmt.addItem(label, key)
        current_fmt = settings.rip_format or "flac"
        for i in range(self.rip_fmt.count()):
            if self.rip_fmt.itemData(i) == current_fmt:
                self.rip_fmt.setCurrentIndex(i)
                break
        form.addRow("Output format:", self.rip_fmt)

        self.compression = QSpinBox()
        self.compression.setRange(0, 8)
        self.compression.setValue(settings.flac_compression)
        self.compression.setToolTip("0 = fastest encode, 8 = smallest file size")
        self._compression_label = QLabel("FLAC compression:")
        form.addRow(self._compression_label, self.compression)

        self.bitrate_combo = QComboBox()
        self.bitrate_combo.addItems(["128", "192", "256", "320", "512"])
        self.bitrate_combo.setCurrentText(str(settings.rip_audio_bitrate))
        self.bitrate_combo.setToolTip("Audio bitrate in kilobits per second")
        self._bitrate_label = QLabel("Bitrate (kbps):")
        form.addRow(self._bitrate_label, self.bitrate_combo)

        self.eject = QCheckBox("Eject disc after rip")
        self.eject.setChecked(settings.eject_after_rip)
        form.addRow("", self.eject)

        self.ctdb_verify = QCheckBox("Verify rip accuracy against CUETools DB")
        self.ctdb_verify.setChecked(settings.ctdb_verify_rips)
        self.ctdb_verify.setToolTip("Only applies when ripping to FLAC")
        form.addRow("", self.ctdb_verify)

        self.rip_fmt.currentIndexChanged.connect(self._on_rip_format_changed)
        self._on_rip_format_changed()
        return w

    def _on_rip_format_changed(self) -> None:
        fmt = self.rip_fmt.currentData() or "flac"
        is_flac = fmt == _FLAC_FORMAT
        is_lossy = fmt in _LOSSY_FORMATS
        self._compression_label.setVisible(is_flac)
        self.compression.setVisible(is_flac)
        self._bitrate_label.setVisible(is_lossy)
        self.bitrate_combo.setVisible(is_lossy)

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

        self.fetch_lyrics_online = QCheckBox("Fetch lyrics online (LRCLIB)")
        self.fetch_lyrics_online.setChecked(settings.fetch_lyrics_online)
        self.fetch_lyrics_online.setToolTip(
            "When a track has no .lrc sidecar or embedded lyrics, query lrclib.net "
            "(free, no API key). Disable to keep all lyrics lookups local."
        )
        form.addRow("", self.fetch_lyrics_online)

        self.contact = QLineEdit(settings.musicbrainz_contact)
        form.addRow("MusicBrainz contact:", self.contact)

        self._contact_warn = QLabel("Contact still uses the placeholder 'example.invalid' — metadata lookups may be rate-limited or rejected.")
        self._contact_warn.setObjectName("warningLabel")
        self._contact_warn.setWordWrap(True)
        self._contact_warn.setVisible("example.invalid" in settings.musicbrainz_contact)
        form.addRow("", self._contact_warn)
        self.contact.textChanged.connect(self._check_contact)

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

        # Branding header: icon + app name + version stacked beside it.
        brand = QHBoxLayout()
        brand.setSpacing(14)
        icon_label = QLabel()
        icon_pixmap = app_icon().pixmap(64, 64)
        if not icon_pixmap.isNull():
            icon_label.setPixmap(icon_pixmap)
            icon_label.setFixedSize(64, 64)
            brand.addWidget(icon_label, 0, Qt.AlignTop)
        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        name_label = QLabel(__app_name__)
        name_label.setObjectName("dialogTitle")
        text_col.addWidget(name_label)
        version_label = QLabel(f"Version {__version__}")
        version_label.setObjectName("dialogSubtitle")
        text_col.addWidget(version_label)
        text_col.addStretch(1)
        brand.addLayout(text_col, 1)
        layout.addLayout(brand)

        layout.addSpacing(12)

        desc = QLabel(
            "Sea Lyon is a music library manager, CD ripper, and audio/video player\n"
            "for Windows,Coming Soon to macOS"
        )
        desc.setWordWrap(True)
        layout.addWidget(desc)

        layout.addSpacing(12)

        license_label = QLabel("Released under the MIT License.")
        license_label.setObjectName("mutedText")
        layout.addWidget(license_label)

        layout.addStretch(1)
        return w

    # ------------------------------------------------------------------ inline validators

    def _check_root_path(self, text: str) -> None:
        stripped = text.strip()
        if stripped and not Path(stripped).exists():
            self._root_warn.setText(f"Path does not exist: {stripped}")
            self._root_warn.setVisible(True)
        else:
            self._root_warn.setVisible(False)

    def _check_contact(self, text: str) -> None:
        self._contact_warn.setVisible("example.invalid" in text)

    def _new_missing_paths(self, root_text: str, library_paths: list[str]) -> list[str]:
        missing: list[str] = []
        if (
            root_text
            and root_text != self._initial_music_root
            and not Path(root_text).exists()
        ):
            missing.append(root_text)
        for path in library_paths:
            if path not in self._initial_library_paths and not Path(path).exists():
                missing.append(path)
        return missing

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
        root_text = self.root_edit.text().strip()
        library_paths = normalize_library_paths([
            self.library_paths.item(row).text()
            for row in range(self.library_paths.count())
        ])
        missing = self._new_missing_paths(root_text, library_paths)
        if missing:
            shown = "\n".join(missing[:6])
            if len(missing) > 6:
                shown += f"\n...and {len(missing) - 6} more"
            answer = QMessageBox.question(
                self,
                "Some paths do not exist",
                f"The following paths were not found on disk:\n\n{shown}\n\nSave anyway?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return

        self.result_settings.replaygain_mode = self.rg_mode.currentData() or "off"
        self.result_settings.replaygain_preamp_db = self.rg_preamp.value()
        self.result_settings.replaygain_prevent_clipping = self.rg_prevent_clipping.isChecked()
        self.result_settings.music_root = self.root_edit.text().strip() or self.result_settings.music_root
        self.result_settings.rip_format = self.rip_fmt.currentData() or "flac"
        self.result_settings.flac_compression = self.compression.value()
        try:
            self.result_settings.rip_audio_bitrate = int(self.bitrate_combo.currentText())
        except ValueError:
            self.result_settings.rip_audio_bitrate = 320
        self.result_settings.cd_drive = self.drive.text().strip()
        self.result_settings.library_paths = library_paths
        self.result_settings.watch_library_folders = self.watch_library_folders.isChecked()
        self.result_settings.eject_after_rip = self.eject.isChecked()
        self.result_settings.auto_lookup_metadata = self.lookup.isChecked()
        self.result_settings.cuetools_db_metadata_enabled = self.cuetools_db.isChecked()
        self.result_settings.download_artwork = self.artwork.isChecked()
        self.result_settings.metadata_diagnostics_enabled = self.metadata_diagnostics.isChecked()
        self.result_settings.fetch_lyrics_online = self.fetch_lyrics_online.isChecked()
        self.result_settings.ctdb_verify_rips = self.ctdb_verify.isChecked()
        self.result_settings.musicbrainz_contact = self.contact.text().strip() or self.result_settings.musicbrainz_contact
        self.result_settings.theaudiodb_api_key = self.audiodb_key.text().strip() or "123"
        self.result_settings.yt_audio_format = self.yt_audio_fmt.currentText()
        self.result_settings.yt_video_format = self.yt_video_fmt.currentText()
        self.result_settings.yt_output_dir = self.yt_save_dir.text().strip()
        self.result_settings.yt_auto_add = self.yt_auto_add.isChecked()
        self.accept()

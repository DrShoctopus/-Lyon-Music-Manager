"""Settings dialog."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog,
    QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QMessageBox,
    QPushButton, QSpinBox, QTabWidget, QVBoxLayout, QWidget,
)

from .. import __app_name__, __version__
from ..core.settings import Settings, normalize_library_paths
from .about import COPYRIGHT_NOTICE, THIRD_PARTY_NOTICE
from .branding import app_icon

if TYPE_CHECKING:
    from ..core.scrobbler import ScrobblerService

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
_DIALOG_DEFAULT_HEIGHT = 460


class SettingsDialog(QDialog):
    def __init__(
        self,
        settings: Settings,
        parent: QWidget | None = None,
        *,
        audio_outputs: list[tuple[str, str]] | None = None,
        audio_devices_map: dict[str, list[tuple[str, str]]] | None = None,
        scrobbler: "ScrobblerService | None" = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.result_settings = replace(settings)
        self.result_settings.library_paths = normalize_library_paths(settings.library_paths)
        self._initial_music_root = settings.music_root.strip()
        self._initial_library_paths = set(self.result_settings.library_paths)
        self._audio_outputs: list[tuple[str, str]] = audio_outputs or [("", "Default")]
        self._audio_devices_map: dict[str, list[tuple[str, str]]] = audio_devices_map or {}

        self._scrobbler = scrobbler
        self._lastfm_poll_timer: QTimer | None = None

        tabs = QTabWidget()
        tabs.addTab(self._build_library_tab(settings), "Library")
        tabs.addTab(self._build_playback_tab(settings), "Playback")
        tabs.addTab(self._build_ripping_tab(settings), "CD Ripping")
        tabs.addTab(self._build_metadata_tab(settings), "Metadata")
        tabs.addTab(self._build_youtube_tab(settings), "YouTube")
        tabs.addTab(self._build_scrobbling_tab(settings), "Scrobbling")
        tabs.addTab(self._build_dlna_tab(settings), "DLNA")
        tabs.addTab(self._build_updates_tab(settings), "Updates")
        tabs.addTab(self._build_about_tab(), "About")

        layout = QVBoxLayout(self)
        layout.addWidget(tabs)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._accept)
        bb.rejected.connect(self.reject)
        layout.addWidget(bb)
        self._fit_width_to_tabs(tabs)

    # ------------------------------------------------------------------ tabs

    def _fit_width_to_tabs(self, tabs: QTabWidget) -> None:
        """Open the dialog no wider than the complete top tab strip."""
        margins = self.layout().contentsMargins()
        tab_width = tabs.tabBar().sizeHint().width()
        dialog_width = tab_width + margins.left() + margins.right()
        self.setMinimumWidth(dialog_width)
        self.resize(dialog_width, _DIALOG_DEFAULT_HEIGHT)

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

        # ---- Audio Output section
        ao_label = QLabel("Audio Output")
        ao_label.setObjectName("sectionHeader")
        form.addRow(ao_label)

        self.audio_output_combo = QComboBox()
        for out_id, out_desc in self._audio_outputs:
            self.audio_output_combo.addItem(out_desc, out_id)
        current_output = settings.audio_output
        for i in range(self.audio_output_combo.count()):
            if self.audio_output_combo.itemData(i) == current_output:
                self.audio_output_combo.setCurrentIndex(i)
                break
        form.addRow("Output module:", self.audio_output_combo)

        self.audio_device_combo = QComboBox()
        self._repopulate_device_combo(settings.audio_output, settings.audio_output_device)
        form.addRow("Output device:", self.audio_device_combo)

        self.audio_output_combo.currentIndexChanged.connect(self._on_audio_output_changed)

        note = QLabel("Changes take effect on the next track.")
        note.setObjectName("mutedText")
        form.addRow("", note)

        # ---- ReplayGain section
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

        # ---- Crossfade section
        cf_label = QLabel("Crossfade")
        cf_label.setObjectName("sectionHeader")
        form.addRow(cf_label)

        self.crossfade_seconds = QSpinBox()
        self.crossfade_seconds.setRange(0, 60)
        self.crossfade_seconds.setSingleStep(1)
        self.crossfade_seconds.setSpecialValueText("Off")
        self.crossfade_seconds.setSuffix(" seconds")
        self.crossfade_seconds.setValue(settings.crossfade_seconds)
        self.crossfade_seconds.setToolTip(
            "Overlap the end of the current track with the start of the next track. "
            "Set to 0 to disable crossfade."
        )
        form.addRow("Duration:", self.crossfade_seconds)

        # ---- Gapless section
        gl_label = QLabel("Gapless Playback")
        gl_label.setObjectName("sectionHeader")
        form.addRow(gl_label)

        self.gapless_playback = QCheckBox("Enable gapless playback")
        self.gapless_playback.setChecked(settings.gapless_playback)
        self.gapless_playback.setToolTip(
            "Pre-buffers the next track to minimize the gap between songs. "
            "Has no effect when crossfade is enabled."
        )
        form.addRow("", self.gapless_playback)

        gl_note = QLabel("Works only when crossfade is set to 0 seconds.")
        gl_note.setObjectName("mutedText")
        form.addRow("", gl_note)

        return w

    def _repopulate_device_combo(self, audio_output: str, current_device: str) -> None:
        self.audio_device_combo.blockSignals(True)
        self.audio_device_combo.clear()
        devices = self._audio_devices_map.get(audio_output, [("", "Default")])
        if not devices:
            devices = [("", "Default")]
        for dev_id, dev_desc in devices:
            self.audio_device_combo.addItem(dev_desc, dev_id)
        # Select current device
        for i in range(self.audio_device_combo.count()):
            if self.audio_device_combo.itemData(i) == current_device:
                self.audio_device_combo.setCurrentIndex(i)
                break
        self.audio_device_combo.blockSignals(False)

    def _on_audio_output_changed(self) -> None:
        selected_output = self.audio_output_combo.currentData() or ""
        self._repopulate_device_combo(selected_output, "")

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
        self.audiodb_key.setPlaceholderText("e.g. 123 (free tier)")
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

        _QUALITY_LABELS = [
            ("Best available", "best"),
            ("1080p (Full HD)", "1080p"),
            ("2K (1440p)",      "2k"),
            ("4K (2160p)",      "4k"),
        ]
        self.yt_video_quality = QComboBox()
        for label, key in _QUALITY_LABELS:
            self.yt_video_quality.addItem(label, key)
        current_q = settings.yt_video_quality
        for i in range(self.yt_video_quality.count()):
            if self.yt_video_quality.itemData(i) == current_q:
                self.yt_video_quality.setCurrentIndex(i)
                break
        self.yt_video_quality.setToolTip(
            "Maximum resolution for video downloads. Requires ffmpeg for splitting and merging streams."
        )
        form.addRow("Video quality:", self.yt_video_quality)

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

    def _build_scrobbling_tab(self, settings: Settings) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # ---- Last.fm
        lfm_label = QLabel("Last.fm")
        lfm_label.setObjectName("sectionHeader")
        layout.addWidget(lfm_label)

        self.lastfm_enabled = QCheckBox("Enable Last.fm scrobbling")
        self.lastfm_enabled.setChecked(settings.lastfm_scrobbling_enabled)
        layout.addWidget(self.lastfm_enabled)

        lfm_status_row = QHBoxLayout()
        self._lastfm_status_label = QLabel(self._lastfm_status_text(settings))
        lfm_status_row.addWidget(self._lastfm_status_label)
        lfm_status_row.addStretch(1)
        self._lastfm_connect_btn = QPushButton("Connect Last.fm…")
        self._lastfm_connect_btn.clicked.connect(self._connect_lastfm)
        lfm_status_row.addWidget(self._lastfm_connect_btn)
        self._lastfm_disconnect_btn = QPushButton("Disconnect")
        self._lastfm_disconnect_btn.setEnabled(bool(settings.lastfm_session_key))
        self._lastfm_disconnect_btn.clicked.connect(self._disconnect_lastfm)
        lfm_status_row.addWidget(self._lastfm_disconnect_btn)
        layout.addLayout(lfm_status_row)

        if self._scrobbler is None:
            self._lastfm_connect_btn.setEnabled(False)
            warn = QLabel("Last.fm sign-in is unavailable: no scrobbler service is attached.")
            warn.setObjectName("warningLabel")
            warn.setWordWrap(True)
            layout.addWidget(warn)
        else:
            self._scrobbler.lastfm_token_ready.connect(self._on_lastfm_token_ready)
            self._scrobbler.lastfm_auth_complete.connect(self._on_lastfm_auth_complete)
            self._scrobbler.lastfm_auth_failed.connect(self._on_lastfm_auth_failed)

        layout.addSpacing(8)

        # ---- ListenBrainz
        lbz_label = QLabel("ListenBrainz")
        lbz_label.setObjectName("sectionHeader")
        layout.addWidget(lbz_label)

        self.lbz_enabled = QCheckBox("Enable ListenBrainz scrobbling")
        self.lbz_enabled.setChecked(settings.listenbrainz_scrobbling_enabled)
        layout.addWidget(self.lbz_enabled)

        lbz_token_row = QHBoxLayout()
        self.lbz_token = QLineEdit(settings.listenbrainz_token)
        self.lbz_token.setPlaceholderText("Paste your ListenBrainz user token here…")
        self.lbz_token.setEchoMode(QLineEdit.Password)
        lbz_token_row.addWidget(self.lbz_token, 1)
        lbz_link = QPushButton("Get token ↗")
        lbz_link.setToolTip("Open listenbrainz.org/profile/ in your browser")
        lbz_link.clicked.connect(self._open_lbz_profile)
        lbz_token_row.addWidget(lbz_link)
        layout.addLayout(lbz_token_row)

        layout.addStretch(1)
        return w

    def _build_dlna_tab(self, settings: Settings) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        form.setContentsMargins(12, 12, 12, 12)
        form.setVerticalSpacing(8)

        self.dlna_enabled = QCheckBox("Share library over DLNA / UPnP")
        self.dlna_enabled.setChecked(settings.dlna_enabled)
        form.addRow("", self.dlna_enabled)

        self.dlna_name = QLineEdit(settings.dlna_friendly_name)
        self.dlna_name.setPlaceholderText("Sea Lyon Media Manager")
        form.addRow("Server name:", self.dlna_name)

        self.dlna_port = QSpinBox()
        self.dlna_port.setRange(0, 65535)
        self.dlna_port.setSpecialValueText("Auto")
        self.dlna_port.setValue(settings.dlna_port)
        self.dlna_port.setToolTip("Use 0 to let the operating system choose an available port.")
        form.addRow("Port:", self.dlna_port)

        self.dlna_bind_address = QLineEdit(settings.dlna_bind_address)
        self.dlna_bind_address.setPlaceholderText("0.0.0.0")
        self.dlna_bind_address.setToolTip(
            "Use 127.0.0.1 for this computer only, or 0.0.0.0 for local network devices."
        )
        form.addRow("Bind address:", self.dlna_bind_address)

        note = QLabel(
            "DLNA shares indexed audio and video files with devices on your local network while "
            "Sea Lyon is running. Anyone on that network may be able to browse and stream them."
        )
        note.setWordWrap(True)
        note.setObjectName("mutedText")
        form.addRow("", note)

        return w

    def _build_updates_tab(self, settings: Settings) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        form.setContentsMargins(12, 12, 12, 12)
        form.setVerticalSpacing(8)

        self.update_check_enabled = QCheckBox(
            "Check for updates automatically (once a day)"
        )
        self.update_check_enabled.setChecked(settings.update_check_enabled)
        form.addRow("", self.update_check_enabled)

        self.update_appcast_url = QLineEdit(settings.update_appcast_url)
        self.update_appcast_url.setPlaceholderText(
            "https://drshoctopus.github.io/Sea-Lyon-Media-Manager/appcast.xml"
        )
        form.addRow("Update feed URL:", self.update_appcast_url)

        # Last-checked display + manual "Check now" button.
        check_row = QHBoxLayout()
        if settings.last_update_check_ts > 0:
            from datetime import datetime
            ts = datetime.fromtimestamp(settings.last_update_check_ts).strftime(
                "%Y-%m-%d %H:%M"
            )
            last_text = f"Last checked: {ts}"
        else:
            last_text = "Last checked: never"
        self._update_last_checked_label = QLabel(last_text)
        check_row.addWidget(self._update_last_checked_label, 1)

        check_now_btn = QPushButton("Check now")
        check_now_btn.clicked.connect(self._on_check_for_updates_clicked)
        check_row.addWidget(check_now_btn)
        form.addRow("", check_row)

        if settings.skipped_update_version:
            skipped_row = QHBoxLayout()
            skipped_label = QLabel(
                f"Currently skipping version {settings.skipped_update_version}."
            )
            skipped_label.setObjectName("mutedText")
            skipped_row.addWidget(skipped_label, 1)
            clear_btn = QPushButton("Stop skipping")
            clear_btn.clicked.connect(self._on_clear_skipped_clicked)
            skipped_row.addWidget(clear_btn)
            form.addRow("", skipped_row)

        note = QLabel(
            "Sea Lyon checks a GitHub-hosted feed for new releases. The check "
            "happens off the UI thread and does not transmit any of your data; "
            "see PRIVACY.md."
        )
        note.setWordWrap(True)
        note.setObjectName("mutedText")
        form.addRow("", note)

        return w

    def _on_check_for_updates_clicked(self) -> None:
        """Forward the manual "Check now" to MainWindow if accessible."""
        # Persist the URL toggle from the form first, then ask the parent
        # window to run a manual check. The parent owns the worker lifecycle.
        self.result_settings.update_check_enabled = self.update_check_enabled.isChecked()
        self.result_settings.update_appcast_url = self.update_appcast_url.text().strip()
        parent = self.parent()
        check = getattr(parent, "check_for_updates_now", None)
        if callable(check):
            # Push the latest URL into the parent's settings so the worker
            # uses what the user just typed (even if they haven't clicked OK).
            try:
                parent.settings.update_appcast_url = self.result_settings.update_appcast_url
            except Exception:  # noqa: BLE001
                pass
            check()
        else:
            QMessageBox.information(
                self,
                "Check for updates",
                "Updates can only be checked from the main window. Close this dialog and try Help → Check for Updates…",
            )

    def _on_clear_skipped_clicked(self) -> None:
        self.result_settings.skipped_update_version = ""
        parent = self.parent()
        try:
            parent.settings.skipped_update_version = ""  # type: ignore[union-attr]
            parent.settings.save()                       # type: ignore[union-attr]
        except Exception:  # noqa: BLE001
            pass
        QMessageBox.information(
            self, "Updates", "Cleared the skipped-version setting."
        )

    @staticmethod
    def _lastfm_status_text(settings: Settings) -> str:
        if not settings.lastfm_session_key:
            return "Not connected"
        if settings.lastfm_username:
            return f"Connected as {settings.lastfm_username}"
        return "Connected"

    def _connect_lastfm(self) -> None:
        if self._scrobbler is None:
            QMessageBox.warning(self, "Last.fm", "Scrobbler service is unavailable.")
            return
        self._lastfm_connect_btn.setEnabled(False)
        self._lastfm_status_label.setText("Getting token…")
        self._scrobbler.start_lastfm_auth()

    def _on_lastfm_token_ready(self, token: str) -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        from ..core.scrobbler import lastfm_auth_url
        QDesktopServices.openUrl(QUrl(lastfm_auth_url(token)))
        self._lastfm_status_label.setText("Waiting for browser authorisation…")
        if self._lastfm_poll_timer is None:
            self._lastfm_poll_timer = QTimer(self)
            self._lastfm_poll_timer.setInterval(5000)
            assert self._scrobbler is not None
            self._lastfm_poll_timer.timeout.connect(self._scrobbler.poll_lastfm_session)
        self._lastfm_poll_timer.start()

    def _on_lastfm_auth_complete(self, sk: str, name: str) -> None:
        if self._lastfm_poll_timer:
            self._lastfm_poll_timer.stop()
        self.result_settings.lastfm_session_key = sk
        self.result_settings.lastfm_username = name
        self._lastfm_status_label.setText(
            f"Connected as {name}" if name else "Connected"
        )
        self._lastfm_disconnect_btn.setEnabled(True)
        self._lastfm_connect_btn.setEnabled(True)

    def _on_lastfm_auth_failed(self, msg: str) -> None:
        if self._lastfm_poll_timer:
            self._lastfm_poll_timer.stop()
        self._lastfm_status_label.setText(f"Auth failed: {msg}")
        self._lastfm_connect_btn.setEnabled(True)

    def _disconnect_lastfm(self) -> None:
        if self._lastfm_poll_timer:
            self._lastfm_poll_timer.stop()
        self.result_settings.lastfm_session_key = ""
        self.result_settings.lastfm_username = ""
        self._lastfm_status_label.setText("Not connected")
        self._lastfm_disconnect_btn.setEnabled(False)
        self._lastfm_connect_btn.setEnabled(True)

    def _open_lbz_profile(self) -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl("https://listenbrainz.org/profile/"))

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

        copyright_label = QLabel(COPYRIGHT_NOTICE)
        copyright_label.setObjectName("mutedText")
        layout.addWidget(copyright_label)

        license_label = QLabel("Released under the MIT License.")
        license_label.setObjectName("mutedText")
        layout.addWidget(license_label)

        layout.addSpacing(12)

        credits_label = QLabel("Third-Party Acknowledgements")
        credits_label.setObjectName("sectionHeader")
        layout.addWidget(credits_label)

        third_party = QLabel(THIRD_PARTY_NOTICE)
        third_party.setObjectName("mutedText")
        third_party.setWordWrap(True)
        layout.addWidget(third_party)

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

        self.result_settings.audio_output = self.audio_output_combo.currentData() or ""
        self.result_settings.audio_output_device = self.audio_device_combo.currentData() or ""
        self.result_settings.replaygain_mode = self.rg_mode.currentData() or "off"
        self.result_settings.replaygain_preamp_db = self.rg_preamp.value()
        self.result_settings.replaygain_prevent_clipping = self.rg_prevent_clipping.isChecked()
        self.result_settings.crossfade_seconds = self.crossfade_seconds.value()
        self.result_settings.gapless_playback = self.gapless_playback.isChecked()
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
        self.result_settings.theaudiodb_api_key = self.audiodb_key.text().strip()
        self.result_settings.yt_audio_format = self.yt_audio_fmt.currentText()
        self.result_settings.yt_video_format = self.yt_video_fmt.currentText()
        self.result_settings.yt_video_quality = self.yt_video_quality.currentData() or "best"
        self.result_settings.yt_output_dir = self.yt_save_dir.text().strip()
        self.result_settings.yt_auto_add = self.yt_auto_add.isChecked()
        self.result_settings.lastfm_scrobbling_enabled = self.lastfm_enabled.isChecked()
        self.result_settings.listenbrainz_scrobbling_enabled = self.lbz_enabled.isChecked()
        self.result_settings.listenbrainz_token = self.lbz_token.text().strip()
        self.result_settings.dlna_enabled = self.dlna_enabled.isChecked()
        self.result_settings.dlna_port = self.dlna_port.value()
        self.result_settings.dlna_friendly_name = (
            self.dlna_name.text().strip() or "Sea Lyon Media Manager"
        )
        self.result_settings.dlna_bind_address = (
            self.dlna_bind_address.text().strip() or "0.0.0.0"
        )
        self.result_settings.update_check_enabled = self.update_check_enabled.isChecked()
        url = self.update_appcast_url.text().strip()
        if url:
            self.result_settings.update_appcast_url = url
        # lastfm_session_key and lastfm_username are updated live by the auth flow;
        # preserve whatever's there.
        self.accept()

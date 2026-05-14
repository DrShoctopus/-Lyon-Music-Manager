"""YouTube download dialog powered by yt-dlp."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit,
    QPushButton, QRadioButton, QVBoxLayout, QWidget,
)

from ..core.library import Library
from ..core.settings import Settings
from ..core.yt_downloader import YtDownloadWorker

_AUDIO_FORMATS = ["flac", "mp3"]
_VIDEO_FORMATS = ["mp4", "mkv", "webm"]


class YtDownloadDialog(QDialog):
    """Modal dialog that downloads a YouTube URL via yt-dlp and adds the
    result to the Lyon library."""

    library_updated = Signal()  # emitted whenever a file is added to library

    def __init__(
        self,
        url: str,
        settings: Settings,
        library: Library,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.settings = settings
        self.library = library
        self._worker: YtDownloadWorker | None = None

        self.setWindowTitle("Download from YouTube")
        self.setMinimumWidth(560)
        self.resize(580, 480)

        layout = QVBoxLayout(self)
        form = QFormLayout()

        # URL
        self.url_edit = QLineEdit(url)
        self.url_edit.setPlaceholderText("https://www.youtube.com/watch?v=...")
        form.addRow("URL:", self.url_edit)

        # Type: Audio / Video
        type_row = QHBoxLayout()
        self.radio_audio = QRadioButton("Audio")
        self.radio_video = QRadioButton("Video")
        self.radio_audio.setChecked(True)
        type_group = QButtonGroup(self)
        type_group.addButton(self.radio_audio)
        type_group.addButton(self.radio_video)
        type_row.addWidget(self.radio_audio)
        type_row.addWidget(self.radio_video)
        type_row.addStretch(1)
        type_w = QWidget()
        type_w.setLayout(type_row)
        form.addRow("Type:", type_w)

        # Format (updates when type changes)
        self.fmt_combo = QComboBox()
        self.fmt_combo.addItems(_AUDIO_FORMATS)
        self._set_format_default()
        form.addRow("Format:", self.fmt_combo)

        # Output directory
        dir_row = QHBoxLayout()
        self.dir_edit = QLineEdit(self._default_audio_dir())
        browse_btn = QPushButton("Browse…")
        browse_btn.clicked.connect(self._browse_output)
        dir_row.addWidget(self.dir_edit, 1)
        dir_row.addWidget(browse_btn)
        dir_w = QWidget()
        dir_w.setLayout(dir_row)
        form.addRow("Save to:", dir_w)

        # Playlist
        self.playlist_check = QCheckBox("Download full playlist")
        is_playlist = "list=" in url and "watch?v=" not in url
        self.playlist_check.setChecked(is_playlist)
        form.addRow("", self.playlist_check)

        layout.addLayout(form)

        # Log
        log_label = QLabel("Download log:")
        log_label.setStyleSheet("color:#72f4ff;font-weight:600;")
        layout.addWidget(log_label)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMinimumHeight(160)
        self.log.setStyleSheet("font-family:monospace;font-size:11px;")
        layout.addWidget(self.log, 1)

        # Buttons
        self._start_btn = QPushButton("Download")
        self._start_btn.setObjectName("accent")
        self._start_btn.clicked.connect(self._start)
        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.setEnabled(False)
        self._cancel_btn.clicked.connect(self._cancel)
        self._close_btn = QPushButton("Close")
        self._close_btn.clicked.connect(self.reject)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        btn_row.addWidget(self._start_btn)
        btn_row.addWidget(self._cancel_btn)
        btn_row.addWidget(self._close_btn)
        layout.addLayout(btn_row)

        # Wire type toggle
        self.radio_audio.toggled.connect(self._on_type_changed)
        self.radio_video.toggled.connect(self._on_type_changed)

    # ------------------------------------------------------------------ helpers

    def _default_audio_dir(self) -> str:
        if self.settings.yt_output_dir:
            return self.settings.yt_output_dir
        return str(Path(self.settings.music_root) / "YouTube")

    def _default_video_dir(self) -> str:
        if self.settings.yt_video_output_dir:
            return self.settings.yt_video_output_dir
        return str(Path(self.settings.music_root) / "Videos")

    def _set_format_default(self) -> None:
        if self.radio_audio.isChecked():
            fmt = self.settings.yt_audio_format
            items = _AUDIO_FORMATS
        else:
            fmt = self.settings.yt_video_format
            items = _VIDEO_FORMATS
        self.fmt_combo.clear()
        self.fmt_combo.addItems(items)
        idx = items.index(fmt) if fmt in items else 0
        self.fmt_combo.setCurrentIndex(idx)

    def _on_type_changed(self) -> None:
        self._set_format_default()
        if self.radio_audio.isChecked():
            self.dir_edit.setText(self._default_audio_dir())
        else:
            self.dir_edit.setText(self._default_video_dir())

    def _browse_output(self) -> None:
        d = QFileDialog.getExistingDirectory(
            self, "Choose output folder", self.dir_edit.text()
        )
        if d:
            self.dir_edit.setText(d)

    # ------------------------------------------------------------------ download

    def _start(self) -> None:
        url = self.url_edit.text().strip()
        if not url:
            self._log("Please enter a URL.")
            return

        output_dir = self.dir_edit.text().strip()
        if not output_dir:
            self._log("Please choose an output folder.")
            return

        Path(output_dir).mkdir(parents=True, exist_ok=True)

        mode = "audio" if self.radio_audio.isChecked() else "video"
        fmt = self.fmt_combo.currentText()
        playlist = self.playlist_check.isChecked()

        self.log.clear()
        self._log(f"Starting {'playlist' if playlist else 'single'} download → {output_dir}")
        self._log(f"Mode: {mode.upper()}  Format: {fmt.upper()}")
        self._log("")

        self._start_btn.setEnabled(False)
        self._cancel_btn.setEnabled(True)

        self._worker = YtDownloadWorker(url, mode, fmt, output_dir, playlist, self)
        self._worker.progress.connect(self._log)
        self._worker.track_ready.connect(self._on_track_ready)
        self._worker.error.connect(self._on_error)
        self._worker.finished.connect(self._on_finished)
        self._worker.start()

    def _cancel(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            self._log("\n[Cancelling…]")
            self._cancel_btn.setEnabled(False)

    def _log(self, msg: str) -> None:
        self.log.appendPlainText(msg)
        sb = self.log.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _on_track_ready(self, path: str) -> None:
        self._log(f"✓  {path}")
        if self.settings.yt_auto_add:
            if self.library.add_file(path):
                self.library.conn.commit()
                self.library_updated.emit()

    def _on_error(self, msg: str) -> None:
        self._log(f"\nERROR: {msg}")

    def _on_finished(self, succeeded: int, failed: int) -> None:
        self._log(
            f"\nDone — {succeeded} downloaded, {failed} failed."
        )
        self._start_btn.setEnabled(True)
        self._cancel_btn.setEnabled(False)
        self._worker = None

    def closeEvent(self, ev) -> None:
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait(3000)
        super().closeEvent(ev)

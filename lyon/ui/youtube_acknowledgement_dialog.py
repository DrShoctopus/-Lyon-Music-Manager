"""Blocking YouTube usage acknowledgement gate.

Shown on the first activation of the YouTube tab and on the first open of
the YouTube download dialog. Persists ``settings.youtube_acknowledged``
so subsequent uses are silent.

Per the v1.0 release plan, this is a lazy gate (not part of the first-run
wizard) so users who never touch the YouTube features never see it.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QVBoxLayout,
    QWidget,
)


class YouTubeAcknowledgementDialog(QDialog):
    """Modal dialog the user must accept before using YouTube features."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("YouTube Features — Please Read")
        self.setModal(True)
        self.setMinimumWidth(520)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        heading = QLabel("<h3>About the YouTube features</h3>", self)
        heading.setTextFormat(Qt.RichText)
        layout.addWidget(heading)

        body = QLabel(
            "Sea Lyon's YouTube tab uses the open-source <i>yt-dlp</i> tool to "
            "search YouTube and to download audio or video files at your "
            "request. yt-dlp is not affiliated with YouTube, and using it is "
            "subject to YouTube's Terms of Service as well as the copyright "
            "law in your jurisdiction.<br><br>"
            "Downloading content from YouTube may be restricted or prohibited "
            "by YouTube's terms, by the copyright in the underlying content, "
            "or by law where you live. Sea Lyon does not grant you any right "
            "to content you do not independently have permission to obtain.<br><br>"
            "If you enable browser-session downloads for restricted videos, "
            "yt-dlp may read applicable YouTube cookies from the browser you "
            "select and send them to YouTube for that download. Sea Lyon "
            "stores only the selected browser name, not your cookies.<br><br>"
            "You are solely responsible for ensuring that any search or "
            "download you initiate is permitted by YouTube's terms and by "
            "applicable law.",
            self,
        )
        body.setWordWrap(True)
        body.setTextFormat(Qt.RichText)
        layout.addWidget(body)

        self._confirm_checkbox = QCheckBox(
            "I understand and accept responsibility for my use of these features.",
            self,
        )
        layout.addWidget(self._confirm_checkbox)

        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        ok_button = button_box.button(QDialogButtonBox.StandardButton.Ok)
        if ok_button is not None:
            ok_button.setText("I Understand and Accept")
            ok_button.setEnabled(False)
        cancel_button = button_box.button(QDialogButtonBox.StandardButton.Cancel)
        if cancel_button is not None:
            cancel_button.setText("Cancel")
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

        self._confirm_checkbox.toggled.connect(
            lambda checked: ok_button.setEnabled(bool(checked)) if ok_button else None
        )

    @property
    def acknowledged(self) -> bool:
        return self._confirm_checkbox.isChecked()

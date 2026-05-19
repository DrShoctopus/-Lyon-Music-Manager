"""Artist discovery panel for Now Playing."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget

from ..core.metadata import ArtistInfo
from .widgets import cover_pixmap


class ArtistPanel(QWidget):
    """Display artist biography, image, and related discovery metadata."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self._photo = QLabel()
        self._photo.setObjectName("artistPhoto")
        self._photo.setFixedSize(128, 128)
        self._photo.setAlignment(Qt.AlignCenter)
        self._photo.setPixmap(cover_pixmap(None, 128, "♪"))

        self._name = QLabel("No artist selected")
        self._name.setObjectName("sectionTitle")
        self._name.setWordWrap(True)

        self._facts = QLabel("")
        self._facts.setObjectName("mutedTextSmall")
        self._facts.setWordWrap(True)

        header_info = QVBoxLayout()
        header_info.setSpacing(4)
        header_info.addWidget(self._name)
        header_info.addWidget(self._facts)
        header_info.addStretch(1)

        header = QHBoxLayout()
        header.setSpacing(12)
        header.addWidget(self._photo, 0, Qt.AlignTop)
        header.addLayout(header_info, 1)

        self._bio = QLabel("")
        self._bio.setObjectName("mutedText")
        self._bio.setWordWrap(True)
        self._bio.setAlignment(Qt.AlignTop | Qt.AlignLeft)

        self._similar = QLabel("")
        self._similar.setObjectName("mutedTextSmall")
        self._similar.setWordWrap(True)

        content = QWidget()
        content.setObjectName("artistPanelContent")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(8, 8, 8, 8)
        content_layout.setSpacing(10)
        content_layout.addLayout(header)
        content_layout.addWidget(self._bio)
        content_layout.addWidget(self._similar)
        content_layout.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(content)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(scroll)

    def set_loading(self, artist: str) -> None:
        artist = artist.strip() or "Unknown Artist"
        self._photo.setPixmap(cover_pixmap(None, 128, "♪"))
        self._name.setText(artist)
        self._facts.setText("")
        self._bio.setText("Looking up artist information...")
        self._similar.setText("")

    def set_empty(self, message: str = "No artist information available.") -> None:
        self._photo.setPixmap(cover_pixmap(None, 128, "♪"))
        self._name.setText("Artist")
        self._facts.setText("")
        self._bio.setText(message)
        self._similar.setText("")

    def set_artist(self, info: ArtistInfo | None, image_bytes: bytes | None = None) -> None:
        if info is None:
            self.set_empty()
            return

        self._name.setText(info.name or "Artist")
        self._facts.setText(self._facts_text(info))
        self._bio.setText(info.biography or "No biography available.")
        if info.similar_artists:
            self._similar.setText("Similar artists: " + ", ".join(info.similar_artists))
        else:
            self._similar.setText("")

        pixmap = QPixmap()
        if image_bytes:
            pixmap.loadFromData(image_bytes)
        if pixmap.isNull():
            self._photo.setPixmap(cover_pixmap(None, 128, "♪"))
        else:
            self._photo.setPixmap(
                pixmap.scaled(128, 128, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            )

    @staticmethod
    def _facts_text(info: ArtistInfo) -> str:
        facts: list[str] = []
        if info.genre:
            facts.append(info.genre)
        if info.country:
            facts.append(info.country)
        if info.formed_year:
            facts.append(f"Formed {info.formed_year}")
        if info.website:
            facts.append(info.website)
        return "  ·  ".join(facts)

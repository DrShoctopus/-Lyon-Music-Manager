"""Spotify-style 'Home' landing page with album cards."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QSizePolicy, QVBoxLayout, QWidget,
)

from ..core.library import Library
from .widgets import ElidedLabel, cover_pixmap


CARD_SIZE = 180
COVER_SIZE = 148


class AlbumCard(QFrame):
    clicked = Signal(str, str)   # (artist, album)

    def __init__(self, artist: str, album: str, art_path: str | None,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("card")
        self.setCursor(Qt.PointingHandCursor)
        self._artist = artist
        self._album = album
        self.setFixedWidth(CARD_SIZE)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)

        cover = QLabel()
        cover.setFixedSize(COVER_SIZE, COVER_SIZE)
        cover.setPixmap(cover_pixmap(art_path, COVER_SIZE, "♪"))
        cover.setStyleSheet("border-radius:4px;")

        title = ElidedLabel(album or "Unknown Album")
        title.setObjectName("cardTitle")
        sub = ElidedLabel(artist or "Unknown Artist")
        sub.setObjectName("cardSubtitle")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(6)
        layout.addWidget(cover, 0, Qt.AlignHCenter)
        layout.addSpacing(4)
        layout.addWidget(title)
        layout.addWidget(sub)

    def mousePressEvent(self, ev) -> None:
        if ev.button() == Qt.LeftButton:
            self.clicked.emit(self._artist, self._album)
        super().mousePressEvent(ev)


class HomeView(QWidget):
    open_album = Signal(str, str)         # (artist, album)
    open_library = Signal()
    open_rip = Signal()

    def __init__(self, library: Library, parent: QWidget | None = None):
        super().__init__(parent)
        self.library = library

        # Greeting + quick actions
        title = QLabel("Good evening")
        title.setObjectName("sectionTitle")

        actions = QHBoxLayout()
        actions.setContentsMargins(20, 0, 20, 12)
        actions.setSpacing(10)
        rip_btn = QPushButton("Rip a CD")
        rip_btn.setObjectName("accent")
        rip_btn.clicked.connect(self.open_rip)
        lib_btn = QPushButton("Open Library")
        lib_btn.setObjectName("ghost")
        lib_btn.clicked.connect(self.open_library)
        actions.addWidget(rip_btn)
        actions.addWidget(lib_btn)
        actions.addStretch(1)

        # Recently added albums grid
        recent_title = QLabel("Albums in your library")
        recent_title.setObjectName("sectionTitle")
        recent_title.setStyleSheet("font-size:16pt; padding-top:18px;")

        self.grid_host = QWidget()
        self.grid = QGridLayout(self.grid_host)
        self.grid.setContentsMargins(20, 6, 20, 20)
        self.grid.setSpacing(16)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)

        inner = QWidget()
        inner.setObjectName("contentArea")
        v = QVBoxLayout(inner)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        v.addWidget(title)
        v.addLayout(actions)
        v.addWidget(recent_title)
        v.addWidget(self.grid_host)
        v.addStretch(1)
        scroll.setWidget(inner)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

        self.refresh()

    def refresh(self) -> None:
        # Clear grid
        while self.grid.count():
            it = self.grid.takeAt(0)
            w = it.widget()
            if w is not None:
                w.deleteLater()

        albums = self.library.all_albums()
        if not albums:
            empty = QLabel("Your library is empty.\n"
                           "Click 'Rip a CD' to get started, or use\n"
                           "Your Library → Add Folder to import existing music.")
            empty.setStyleSheet("color:#b3b3b3; padding:30px;")
            empty.setAlignment(Qt.AlignCenter)
            self.grid.addWidget(empty, 0, 0)
            return

        cols = 5
        for i, (artist, album, art) in enumerate(albums[:30]):  # cap to avoid huge layouts
            card = AlbumCard(artist, album, art)
            card.clicked.connect(self.open_album)
            self.grid.addWidget(card, i // cols, i % cols)

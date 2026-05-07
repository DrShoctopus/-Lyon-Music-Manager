"""Spotify-style left sidebar navigation."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup, QFrame, QLabel, QPushButton, QVBoxLayout, QWidget,
)


class Sidebar(QFrame):
    nav_changed = Signal(str)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("sidebar")
        self.setFrameShape(QFrame.NoFrame)

        title = QLabel("Lyon")
        title.setObjectName("sidebarTitle")

        self._buttons: dict[str, QPushButton] = {}
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(title)

        for key, label in (
            ("home", "  Home"),
            ("library", "  Your Library"),
            ("youtube", "  YouTube"),
            ("rip", "  Rip CD"),
        ):
            btn = QPushButton(label)
            btn.setObjectName("navItem")
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.toggled.connect(lambda checked, k=key: checked and self.nav_changed.emit(k))
            layout.addWidget(btn)
            self._group.addButton(btn)
            self._buttons[key] = btn

        divider = QFrame()
        divider.setObjectName("sidebarDivider")
        divider.setFrameShape(QFrame.HLine)
        layout.addSpacing(8)
        layout.addWidget(divider)
        layout.addSpacing(8)

        # Footer label (placeholder for future playlists)
        hint = QLabel("Your music, ripped & ready.")
        hint.setStyleSheet("color:#6a6a6a; padding:8px 20px; font-size:8pt;")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addStretch(1)

    def set_active(self, key: str) -> None:
        if key in self._buttons:
            self._buttons[key].setChecked(True)

    def button(self, key: str) -> QPushButton | None:
        return self._buttons.get(key)

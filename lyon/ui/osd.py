"""On-screen display overlay for transient action feedback.

The OSD is a small frameless top-level window that briefly displays a
status string (e.g. "+5s", "Volume 65", "Muted") near the bottom-center
of a host window. It is intentionally a separate top-level window so it
can float over native libVLC video surfaces, which Qt cannot composite
over from inside the same QWidget tree.
"""
from __future__ import annotations

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget


class OSDOverlay(QWidget):
    """Transient bottom-center status overlay."""

    def __init__(self) -> None:
        flags = (
            Qt.FramelessWindowHint
            | Qt.Tool
            | Qt.WindowStaysOnTopHint
            | Qt.WindowDoesNotAcceptFocus
        )
        super().__init__(None, flags)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFocusPolicy(Qt.NoFocus)

        self._frame = QFrame(self)
        self._frame.setObjectName("osdFrame")
        self._label = QLabel("", self._frame)
        self._label.setObjectName("osdLabel")
        self._label.setAlignment(Qt.AlignCenter)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self._frame)
        inner = QVBoxLayout(self._frame)
        inner.setContentsMargins(22, 12, 22, 12)
        inner.addWidget(self._label)

        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self.hide)

    # ------------------------------------------------------------------ public
    def show_message(
        self,
        text: str,
        host: QWidget | None,
        duration_ms: int = 1200,
        bottom_margin: int = 80,
    ) -> None:
        """Display `text` for `duration_ms`, anchored above `host`'s bottom."""
        self._label.setText(text)
        self.adjustSize()
        if host is not None:
            origin = host.mapToGlobal(host.rect().topLeft())
            x = origin.x() + (host.width() - self.width()) // 2
            y = origin.y() + host.height() - self.height() - bottom_margin
            self.move(x, y)
        self.show()
        self.raise_()
        self._hide_timer.start(duration_ms)

    def message(self) -> str:
        """Currently rendered text (for tests)."""
        return self._label.text()

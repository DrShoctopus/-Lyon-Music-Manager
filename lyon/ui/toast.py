"""Floating toast notification widget.

A toast is a transient, non-modal banner pinned to the bottom-center of
its host widget. It auto-dismisses after a configurable timeout and
supports an optional action button (e.g. "Undo").
"""
from __future__ import annotations

from PySide6.QtCore import (
    QEasingCurve,
    QPropertyAnimation,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QToolButton,
    QWidget,
)

_VALID_LEVELS = ("info", "success", "warning", "error")


class Toast(QFrame):
    """Self-dismissing banner with optional action button."""

    closed = Signal()

    def __init__(
        self,
        message: str,
        level: str = "info",
        duration_ms: int = 2500,
        action_label: str | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        if level not in _VALID_LEVELS:
            level = "info"
        self.setObjectName("toast")
        self.setProperty("level", level)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self.setFocusPolicy(Qt.NoFocus)

        self._duration_ms = duration_ms

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 8, 8, 8)
        layout.setSpacing(10)

        self._label = QLabel(message)
        self._label.setObjectName("toastLabel")
        self._label.setWordWrap(True)
        layout.addWidget(self._label, 1)

        self._action_btn: QToolButton | None = None
        if action_label:
            self._action_btn = QToolButton()
            self._action_btn.setText(action_label)
            self._action_btn.setObjectName("toastAction")
            self._action_btn.setCursor(Qt.PointingHandCursor)
            layout.addWidget(self._action_btn)

        close = QToolButton()
        close.setText("×")
        close.setObjectName("toastClose")
        close.setCursor(Qt.PointingHandCursor)
        close.setToolTip("Dismiss")
        close.setAccessibleName("Dismiss notification")
        close.clicked.connect(self.dismiss)
        layout.addWidget(close)

        # Auto-dismiss timer (0 = persistent until user dismisses)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.dismiss)

        # Fade animation
        self._effect = QGraphicsOpacityEffect(self)
        self._effect.setOpacity(0.0)
        self.setGraphicsEffect(self._effect)
        self._fade = QPropertyAnimation(self._effect, b"opacity", self)
        self._fade.setDuration(160)
        self._fade.setEasingCurve(QEasingCurve.OutQuad)
        self._fade.finished.connect(self._on_fade_finished)
        self._closing = False

    # ------------------------------------------------------------------ public
    @property
    def action_button(self) -> QToolButton | None:
        return self._action_btn

    @property
    def level(self) -> str:
        value = self.property("level")
        return value if isinstance(value, str) else "info"

    def message(self) -> str:
        return self._label.text()

    def show_at(self, host: QWidget, bottom_margin: int = 16) -> None:
        """Position the toast above `bottom_margin` and start the fade-in."""
        self.setParent(host)
        self.adjustSize()
        self._reposition(bottom_margin)
        self.show()
        self.raise_()
        self._closing = False
        self._fade.stop()
        self._fade.setStartValue(self._effect.opacity())
        self._fade.setEndValue(1.0)
        self._fade.start()
        if self._duration_ms > 0:
            self._timer.start(self._duration_ms)

    def reposition(self, bottom_margin: int = 16) -> None:
        """Re-anchor the toast (e.g. after the host widget resized)."""
        self._reposition(bottom_margin)

    def dismiss(self) -> None:
        if self._closing:
            return
        self._closing = True
        self._timer.stop()
        self._fade.stop()
        self._fade.setStartValue(self._effect.opacity())
        self._fade.setEndValue(0.0)
        self._fade.start()

    # ------------------------------------------------------------------ internal
    def _reposition(self, bottom_margin: int = 16) -> None:
        host = self.parentWidget()
        if host is None:
            return
        max_width = max(160, min(560, host.width() - 32))
        if self.maximumWidth() != max_width:
            self.setMaximumWidth(max_width)
        self.adjustSize()
        x = max(16, (host.width() - self.width()) // 2)
        x = min(x, max(0, host.width() - self.width() - 16))
        y = max(0, host.height() - self.height() - bottom_margin)
        self.move(x, y)

    def _on_fade_finished(self) -> None:
        # Animation fires after both fade-in and fade-out; only act on fade-out.
        if self._closing:
            self.closed.emit()
            self.deleteLater()

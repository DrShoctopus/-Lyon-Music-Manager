"""Reusable widgets used across views."""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import QLabel


def placeholder_cover(size: int = 96, text: str = "?") -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(QColor("#1a2230"))
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QColor("#3a4658"))
    p.drawRect(0, 0, size - 1, size - 1)
    p.setPen(QColor("#aab3c0"))
    f = p.font()
    f.setPointSize(int(size / 3))
    f.setBold(True)
    p.setFont(f)
    p.drawText(pm.rect(), Qt.AlignCenter, text)
    p.end()
    return pm


def cover_pixmap(path: str | None, size: int = 96, fallback_text: str = "?") -> QPixmap:
    if path:
        pm = QPixmap(path)
        if not pm.isNull():
            return pm.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    return placeholder_cover(size, fallback_text)


class ElidedLabel(QLabel):
    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self._full = text

    def setText(self, text: str) -> None:  # type: ignore[override]
        self._full = text
        super().setText(text)
        self._apply()

    def resizeEvent(self, ev) -> None:
        super().resizeEvent(ev)
        self._apply()

    def _apply(self) -> None:
        fm = self.fontMetrics()
        elided = fm.elidedText(self._full, Qt.ElideRight, max(20, self.width() - 4))
        super().setText(elided)
        self.setToolTip(self._full)

    def sizeHint(self) -> QSize:
        return QSize(self.fontMetrics().horizontalAdvance(self._full) + 4,
                     self.fontMetrics().height())


def format_duration(seconds: float | int) -> str:
    s = int(seconds)
    m, s = divmod(s, 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def format_ms(ms: int) -> str:
    return format_duration(ms / 1000)

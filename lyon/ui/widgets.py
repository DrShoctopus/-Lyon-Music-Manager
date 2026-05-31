"""Reusable widgets used across views."""
from __future__ import annotations

import os
from collections import OrderedDict
from typing import Any

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QKeySequence,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPixmap,
)
from PySide6.QtWidgets import QLabel, QProgressBar, QWidget


def display_shortcut(seq: str) -> str:
    """Return a platform-native shortcut string; on macOS 'Ctrl+1' → '⌘1'."""
    return QKeySequence(seq).toString(QKeySequence.SequenceFormat.NativeText)


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


_COVER_CACHE_MAX = 64
_cover_cache: "OrderedDict[tuple[Any, ...], QPixmap]" = OrderedDict()


def _cover_source_state(path: str) -> tuple[int, int]:
    try:
        st = os.stat(path)
    except OSError:
        return (-1, -1)
    return (st.st_mtime_ns, st.st_size)


def cover_pixmap(path: str | None, size: int = 96, fallback_text: str = "?") -> QPixmap:
    if not path:
        return placeholder_cover(size, fallback_text)

    key = (path, size, fallback_text, _cover_source_state(path))
    cached = _cover_cache.get(key)
    if cached is not None:
        _cover_cache.move_to_end(key)
        return cached

    pm = QPixmap(path)
    if not pm.isNull():
        result = pm.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    else:
        result = placeholder_cover(size, fallback_text)
    _cover_cache[key] = result
    _cover_cache.move_to_end(key)
    if len(_cover_cache) > _COVER_CACHE_MAX:
        _cover_cache.popitem(last=False)
    return result


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


def draw_app_progress_bar(
    painter: QPainter,
    rect,
    pct: int,
    label: str,
    *,
    failed: bool = False,
) -> None:
    """Draw the app's split-label progress bar used by rip and download views."""
    r = QRectF(rect)
    chunk_w = r.width() * max(0, min(100, pct)) / 100.0

    painter.save()

    bg_path = QPainterPath()
    bg_path.addRoundedRect(r, 5.0, 5.0)
    painter.setPen(QColor("#27313b"))
    painter.fillPath(bg_path, QColor("#070a0f"))
    painter.drawPath(bg_path)

    if chunk_w > 0.5:
        grad = QLinearGradient(r.left(), 0.0, r.right(), 0.0)
        if failed:
            grad.setColorAt(0.00, QColor("#7a1018"))
            grad.setColorAt(0.55, QColor("#d92e35"))
            grad.setColorAt(1.00, QColor("#ff7a7d"))
        else:
            grad.setColorAt(0.00, QColor("#0f3c9c"))
            grad.setColorAt(0.55, QColor("#1b8dff"))
            grad.setColorAt(1.00, QColor("#68f3ff"))
        chunk_path = QPainterPath()
        chunk_path.addRoundedRect(QRectF(r.left(), r.top(), chunk_w, r.height()), 4.0, 4.0)
        chunk_path = chunk_path.intersected(bg_path)
        painter.fillPath(chunk_path, grad)

    normal_font = painter.font()
    bold_font = QFont(normal_font)
    bold_font.setBold(True)

    painter.setClipping(True)
    if chunk_w > 0.5:
        painter.setClipRect(QRectF(r.left(), r.top(), chunk_w, r.height()))
        painter.setFont(bold_font)
        painter.setPen(QColor("#0d0d0d"))
        painter.drawText(rect, Qt.AlignCenter, label)
        painter.setFont(normal_font)
    rest_w = r.width() - chunk_w
    if rest_w > 0.5:
        painter.setClipRect(QRectF(r.left() + chunk_w, r.top(), rest_w, r.height()))
        painter.setPen(QColor("#f0fbff"))
        painter.drawText(rect, Qt.AlignCenter, label)
    painter.setClipping(False)

    painter.restore()


class AppProgressBar(QProgressBar):
    """QProgressBar painted with the app's custom gradient and split-colour text."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._label = "0%"
        self._failed = False
        self.setRange(0, 100)
        self.setValue(0)
        self.setMinimumHeight(font_scaled(18))

    def label(self) -> str:
        return self._label

    def set_label(self, label: str) -> None:
        if label != self._label:
            self._label = label
            self.update()

    def set_failed(self, failed: bool) -> None:
        if failed != self._failed:
            self._failed = failed
            self.update()

    def is_failed(self) -> bool:
        return self._failed

    def reset_status(self, label: str = "Ready") -> None:
        self.setRange(0, 100)
        self.setValue(0)
        self.set_label(label)
        self.set_failed(False)

    def paintEvent(self, event) -> None:
        mn, mx, val = self.minimum(), self.maximum(), self.value()
        pct = int(100 * (val - mn) / (mx - mn)) if mx > mn else 0
        p = QPainter(self)
        draw_app_progress_bar(p, self.rect(), pct, self._label or f"{pct}%", failed=self._failed)
        p.end()


class StarRatingWidget(QWidget):
    """Interactive 5-star rating widget. Click a filled star to clear rating."""

    rating_changed = Signal(int)

    _FILLED = "★"
    _EMPTY = "☆"
    _GAP = 2

    def __init__(self, rating: int = 0, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._rating = max(0, min(5, rating))
        self._hover = -1
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)

    def sizeHint(self) -> QSize:
        fm = self.fontMetrics()
        w = fm.horizontalAdvance(self._FILLED) * 5 + self._GAP * 4 + 4
        return QSize(w, fm.height() + 4)

    def rating(self) -> int:
        return self._rating

    def set_rating(self, rating: int) -> None:
        r = max(0, min(5, rating))
        if r != self._rating:
            self._rating = r
            self.update()

    def _star_x_positions(self) -> list[int]:
        fm = self.fontMetrics()
        sw = fm.horizontalAdvance(self._FILLED)
        xs: list[int] = []
        x = 2
        for _ in range(5):
            xs.append(x)
            x += sw + self._GAP
        return xs

    def paintEvent(self, _ev) -> None:
        display = self._hover + 1 if self._hover >= 0 else self._rating
        p = QPainter(self)
        p.setRenderHint(QPainter.TextAntialiasing)
        fm = p.fontMetrics()
        y = (self.height() - fm.height()) // 2 + fm.ascent()
        for i, x in enumerate(self._star_x_positions()):
            p.setPen(QColor("#f5a623") if i < display else QColor("#555e70"))
            p.drawText(x, y, self._FILLED if i < display else self._EMPTY)
        p.end()

    def _index_at(self, pos) -> int:
        fm = self.fontMetrics()
        sw = fm.horizontalAdvance(self._FILLED)
        for i, x in enumerate(self._star_x_positions()):
            if x <= pos.x() < x + sw:
                return i
        return -1

    def mouseMoveEvent(self, ev) -> None:
        h = self._index_at(ev.pos())
        if h != self._hover:
            self._hover = h
            self.update()

    def leaveEvent(self, _ev) -> None:
        if self._hover != -1:
            self._hover = -1
            self.update()

    def mousePressEvent(self, ev) -> None:
        if ev.button() == Qt.LeftButton:
            i = self._index_at(ev.pos())
            if i >= 0:
                new = i + 1 if i + 1 != self._rating else 0
                self._rating = new
                self.rating_changed.emit(self._rating)
                self.update()


def font_scaled(value: int) -> int:
    """Scale a pixel value relative to the user's default font height.

    Use for fixed widget heights (icon sizes, button rows) so they follow
    accessibility font scaling instead of being locked to one font size.
    Returns the value unchanged before QApplication exists.
    """
    from PySide6.QtGui import QFontMetrics
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    if app is None:
        return value
    fm = QFontMetrics(app.font())
    return max(1, int(round(value * fm.height() / 15)))

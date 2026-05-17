"""Shared transport-button vocabulary.

One module so the audio transport bar and the video player draw the same
glyphs at the same sizes. All buttons custom-paint their icons with
QPainter; nothing depends on external assets.
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QToolButton

from .theme import ACCENT_CYAN, TEXT_PRIMARY


SIDE_BTN_SIZE = (42, 40)
PRIMARY_BTN_SIZE = 62

_GLYPH_COLOR     = QColor(TEXT_PRIMARY)
_GLYPH_DISABLED  = QColor("#65707c")
_GLYPH_ACTIVE    = QColor(ACCENT_CYAN)


def _draw_glyph(painter: QPainter, name: str, rect, color: QColor) -> None:
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setPen(Qt.NoPen)
    painter.setBrush(color)

    size = min(rect.width(), rect.height())
    cx = rect.center().x()
    cy = rect.center().y()

    if name == "play":
        iw = size * 0.46
        ih = size * 0.50
        path = QPainterPath()
        path.moveTo(cx - iw * 0.32, cy - ih / 2)
        path.lineTo(cx + iw * 0.50, cy)
        path.lineTo(cx - iw * 0.32, cy + ih / 2)
        path.closeSubpath()
        painter.drawPath(path)

    elif name == "pause":
        bar_w = max(3.0, size * 0.14)
        bar_h = size * 0.46
        gap = max(3.0, size * 0.07)
        r = max(1.0, bar_w * 0.10)
        top = cy - bar_h / 2
        painter.drawRoundedRect(QRectF(cx - gap / 2 - bar_w, top, bar_w, bar_h), r, r)
        painter.drawRoundedRect(QRectF(cx + gap / 2, top, bar_w, bar_h), r, r)

    elif name == "stop":
        s = size * 0.40
        painter.drawRoundedRect(QRectF(cx - s / 2, cy - s / 2, s, s), 1.5, 1.5)

    elif name == "prev":
        iw = size * 0.30
        ih = size * 0.44
        bar_w = max(2.0, size * 0.07)
        gap = max(1.0, size * 0.02)
        painter.drawRoundedRect(QRectF(cx - iw / 2 - gap - bar_w, cy - ih / 2, bar_w, ih), 1, 1)
        path = QPainterPath()
        path.moveTo(cx + iw / 2, cy - ih / 2)
        path.lineTo(cx - iw / 2 + size * 0.02, cy)
        path.lineTo(cx + iw / 2, cy + ih / 2)
        path.closeSubpath()
        painter.drawPath(path)

    elif name == "next":
        iw = size * 0.30
        ih = size * 0.44
        bar_w = max(2.0, size * 0.07)
        gap = max(1.0, size * 0.02)
        painter.drawRoundedRect(QRectF(cx + iw / 2 + gap, cy - ih / 2, bar_w, ih), 1, 1)
        path = QPainterPath()
        path.moveTo(cx - iw / 2, cy - ih / 2)
        path.lineTo(cx + iw / 2 - size * 0.02, cy)
        path.lineTo(cx - iw / 2, cy + ih / 2)
        path.closeSubpath()
        painter.drawPath(path)

    elif name == "shuffle":
        painter.setBrush(Qt.NoBrush)
        pen_w = max(1.6, size * 0.07)
        painter.setPen(QPen(color, pen_w, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        w = size * 0.46
        h = size * 0.20
        for sign in (-1, 1):
            path = QPainterPath()
            path.moveTo(cx - w / 2, cy - sign * h)
            path.cubicTo(cx - w * 0.10, cy - sign * h,
                         cx + w * 0.10, cy + sign * h,
                         cx + w / 2 - size * 0.06, cy + sign * h)
            painter.drawPath(path)
        painter.setBrush(color)
        painter.setPen(Qt.NoPen)
        head = size * 0.10
        for sign in (-1, 1):
            path = QPainterPath()
            tip_x = cx + w / 2
            tip_y = cy + sign * h
            path.moveTo(tip_x - head, tip_y - head)
            path.lineTo(tip_x, tip_y)
            path.lineTo(tip_x - head, tip_y + head)
            path.closeSubpath()
            painter.drawPath(path)

    elif name in ("repeat-off", "repeat-all", "repeat-one"):
        painter.setBrush(Qt.NoBrush)
        pen_w = max(1.6, size * 0.07)
        painter.setPen(QPen(color, pen_w, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        r = size * 0.26
        arc_rect = QRectF(cx - r, cy - r, r * 2, r * 2)
        painter.drawArc(arc_rect, 30 * 16, 300 * 16)
        painter.setBrush(color)
        painter.setPen(Qt.NoPen)
        head = size * 0.10
        from math import cos, sin, radians
        ang = radians(30)
        tip_x = cx + r * cos(-ang)
        tip_y = cy - r * sin(-ang)
        path = QPainterPath()
        path.moveTo(tip_x - head * 0.2, tip_y - head)
        path.lineTo(tip_x + head, tip_y - head * 0.2)
        path.lineTo(tip_x - head * 0.2, tip_y + head * 0.6)
        path.closeSubpath()
        painter.drawPath(path)
        if name == "repeat-one":
            painter.setPen(QPen(color, max(1.2, size * 0.05)))
            f = painter.font()
            f.setBold(True)
            f.setPixelSize(int(size * 0.32))
            painter.setFont(f)
            painter.drawText(QRectF(cx - r, cy - r, r * 2, r * 2), Qt.AlignCenter, "1")

    elif name in ("heart-empty", "heart-filled"):
        path = QPainterPath()
        # Four-segment heart: bottom tip → left lobe → center V → right lobe → tip.
        # Tip control points sit above the tip (cy + 0.20s) so the curves arrive
        # diagonally, producing a 90° pointed cusp instead of a rounded bottom.
        path.moveTo(cx, cy + size * 0.38)
        path.cubicTo(cx - size * 0.15, cy + size * 0.20,
                     cx - size * 0.52, cy - size * 0.05,
                     cx - size * 0.26, cy - size * 0.26)
        path.cubicTo(cx - size * 0.50, cy - size * 0.48,
                     cx - size * 0.08, cy - size * 0.48,
                     cx, cy - size * 0.14)
        path.cubicTo(cx + size * 0.08, cy - size * 0.48,
                     cx + size * 0.50, cy - size * 0.48,
                     cx + size * 0.26, cy - size * 0.26)
        path.cubicTo(cx + size * 0.52, cy - size * 0.05,
                     cx + size * 0.15, cy + size * 0.20,
                     cx, cy + size * 0.38)
        path.closeSubpath()
        if name == "heart-filled":
            painter.drawPath(path)
        else:
            painter.setBrush(Qt.NoBrush)
            pen_w = max(1.6, size * 0.07)
            painter.setPen(QPen(color, pen_w, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            painter.drawPath(path)

    elif name == "volume-muted":
        _draw_speaker(painter, cx, cy, size, color, arcs=0)
        pen_w = max(1.6, size * 0.08)
        painter.setPen(QPen(color, pen_w, Qt.SolidLine, Qt.RoundCap))
        painter.setBrush(Qt.NoBrush)
        ox = cx + size * 0.18
        oy = cy
        d = size * 0.12
        painter.drawLine(int(ox - d), int(oy - d), int(ox + d), int(oy + d))
        painter.drawLine(int(ox - d), int(oy + d), int(ox + d), int(oy - d))

    elif name == "volume-low":
        _draw_speaker(painter, cx, cy, size, color, arcs=1)

    elif name == "volume-mid":
        _draw_speaker(painter, cx, cy, size, color, arcs=2)

    elif name == "volume-high":
        _draw_speaker(painter, cx, cy, size, color, arcs=3)


def _draw_speaker(painter: QPainter, cx: float, cy: float, size: float,
                  color: QColor, arcs: int) -> None:
    painter.setPen(Qt.NoPen)
    painter.setBrush(color)
    body_w = size * 0.10
    body_h = size * 0.20
    cone_w = size * 0.22
    cone_h = size * 0.36
    left = cx - size * 0.22
    path = QPainterPath()
    path.moveTo(left, cy - body_h / 2)
    path.lineTo(left + body_w, cy - body_h / 2)
    path.lineTo(left + body_w + cone_w, cy - cone_h / 2)
    path.lineTo(left + body_w + cone_w, cy + cone_h / 2)
    path.lineTo(left + body_w, cy + body_h / 2)
    path.lineTo(left, cy + body_h / 2)
    path.closeSubpath()
    painter.drawPath(path)

    if arcs <= 0:
        return
    painter.setBrush(Qt.NoBrush)
    pen_w = max(1.4, size * 0.05)
    painter.setPen(QPen(color, pen_w, Qt.SolidLine, Qt.RoundCap))
    arc_x = left + body_w + cone_w + size * 0.02
    for i in range(arcs):
        r = size * (0.10 + i * 0.08)
        painter.drawArc(QRectF(arc_x - r, cy - r, r * 2, r * 2), -45 * 16, 90 * 16)


class TransportButton(QToolButton):
    """Base custom-painted transport button.

    Subclasses override `_glyph_name` to choose the glyph based on state.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("transportBtn")
        self.setFixedSize(*SIDE_BTN_SIZE)
        self.setCursor(Qt.PointingHandCursor)

    def _glyph_name(self) -> str:
        return ""

    def _glyph_color(self) -> QColor:
        if not self.isEnabled():
            return _GLYPH_DISABLED
        if self.isCheckable() and self.isChecked():
            return _GLYPH_ACTIVE
        return _GLYPH_COLOR

    def paintEvent(self, ev) -> None:
        super().paintEvent(ev)
        name = self._glyph_name()
        if not name:
            return
        painter = QPainter(self)
        _draw_glyph(painter, name, self.rect(), self._glyph_color())
        painter.end()


class PlayPauseButton(TransportButton):
    """Larger primary play/pause button used in the audio transport center."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("transportPlay")
        self.setFixedSize(PRIMARY_BTN_SIZE, PRIMARY_BTN_SIZE)
        self._playing = False
        self.setAccessibleName("Play")
        self.setAccessibleDescription("Play or pause the current track")
        self.setToolTip("Play / Pause  [Space]")

    def set_playing(self, playing: bool) -> None:
        if self._playing == playing:
            return
        self._playing = playing
        self.setAccessibleName("Pause" if playing else "Play")
        self.update()

    def _glyph_name(self) -> str:
        return "pause" if self._playing else "play"


class PlayPauseSideButton(TransportButton):
    """Smaller play/pause button used by the video player toolbar."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._playing = False
        self.setAccessibleName("Play")
        self.setToolTip("Play / Pause  [Space]")

    def set_playing(self, playing: bool) -> None:
        if self._playing == playing:
            return
        self._playing = playing
        self.setAccessibleName("Pause" if playing else "Play")
        self.update()

    def _glyph_name(self) -> str:
        return "pause" if self._playing else "play"


class StopButton(TransportButton):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAccessibleName("Stop")
        self.setAccessibleDescription("Stop playback")
        self.setToolTip("Stop")

    def _glyph_name(self) -> str:
        return "stop"


class PrevButton(TransportButton):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAccessibleName("Previous")
        self.setAccessibleDescription("Play previous track")
        self.setToolTip("Previous  [Ctrl+Left]")

    def _glyph_name(self) -> str:
        return "prev"


class NextButton(TransportButton):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAccessibleName("Next")
        self.setAccessibleDescription("Play next track")
        self.setToolTip("Next  [Ctrl+Right]")

    def _glyph_name(self) -> str:
        return "next"


class ShuffleButton(TransportButton):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setAccessibleName("Shuffle")
        self.setAccessibleDescription("Toggle shuffle mode")
        self.setToolTip("Shuffle")
        self.toggled.connect(lambda _: self.update())

    def _glyph_name(self) -> str:
        return "shuffle"


class RepeatButton(TransportButton):
    """Cycles through off / all / one.

    Use `set_state(0|1|2)` to sync from outside, or connect to `state_changed`
    to observe user-driven cycling.
    """

    state_changed = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self._state = 0
        self.clicked.connect(self._on_clicked)
        self.setToolTip("Repeat")
        self._apply_accessible()

    def state(self) -> int:
        return self._state

    def set_state(self, state: int) -> None:
        state = max(0, min(2, int(state)))
        if self._state == state:
            return
        self._state = state
        self.setChecked(state != 0)
        self._apply_accessible()
        self.update()

    def _on_clicked(self) -> None:
        self._state = (self._state + 1) % 3
        self.setChecked(self._state != 0)
        self._apply_accessible()
        self.update()
        self.state_changed.emit(self._state)

    def _apply_accessible(self) -> None:
        labels = ("Repeat off", "Repeat all", "Repeat one")
        self.setAccessibleName(labels[self._state])

    def _glyph_name(self) -> str:
        return ("repeat-off", "repeat-all", "repeat-one")[self._state]


class VolumeButton(TransportButton):
    """Speaker button whose glyph reflects volume level + mute state.

    Click toggles mute. Use `set_state(volume, muted)` to sync.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self._volume = 80
        self._muted = False
        self.setAccessibleName("Volume")
        self.setAccessibleDescription("Toggle mute")
        self.setToolTip("Mute / Unmute")

    def set_state(self, volume: int, muted: bool) -> None:
        changed = self._volume != volume or self._muted != muted
        self._volume = volume
        self._muted = muted
        if changed:
            self.blockSignals(True)
            self.setChecked(muted)
            self.blockSignals(False)
            self.setAccessibleName("Mute" if muted else "Volume")
            self.update()

    def _glyph_color(self) -> QColor:
        if not self.isEnabled():
            return _GLYPH_DISABLED
        return _GLYPH_COLOR

    def _glyph_name(self) -> str:
        if self._muted or self._volume == 0:
            return "volume-muted"
        if self._volume < 33:
            return "volume-low"
        if self._volume < 66:
            return "volume-mid"
        return "volume-high"


class HeartButton(TransportButton):
    """Toggle button that shows an empty/filled heart to mark a track as liked."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setAccessibleName("Like")
        self.setAccessibleDescription("Toggle liked status for current track")
        self.setToolTip("Like / Unlike")
        self.toggled.connect(lambda _: self.update())

    def _glyph_color(self) -> QColor:
        if not self.isEnabled():
            return _GLYPH_DISABLED
        if self.isChecked():
            return QColor("#e05c73")  # pink/red for liked state
        return _GLYPH_COLOR

    def _glyph_name(self) -> str:
        return "heart-filled" if self.isChecked() else "heart-empty"

"""Lyon Music Manager startup branding helpers."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import (
    QColor,
    QFont,
    QIcon,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import QApplication, QMainWindow, QSplashScreen


INK = QColor("#08223a")
RED = QColor("#df4932")
TEAL = QColor("#9fc5b3")
MINT = QColor("#dce9d2")
CREAM = QColor("#fff6e6")
SHADOW = QColor(8, 34, 58, 52)
BLUE = QColor("#70a8bd")
DEEP_TEAL = QColor("#5f8d85")


def app_icon() -> QIcon:
    icon = QIcon()
    for size in (32, 64, 128, 256):
        icon.addPixmap(robot_icon_pixmap(size))
    return icon


def robot_icon_pixmap(size: int = 256) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)

    painter = QPainter(pm)
    painter.setRenderHint(QPainter.Antialiasing)
    scale = size / 256
    painter.scale(scale, scale)
    _draw_robot_icon(painter)
    painter.end()
    return pm


def startup_splash_pixmap() -> QPixmap:
    pm = QPixmap(960, 500)
    pm.fill(CREAM)

    painter = QPainter(pm)
    painter.setRenderHint(QPainter.Antialiasing)

    bg = QLinearGradient(0, 0, 960, 500)
    bg.setColorAt(0, QColor("#fff9ec"))
    bg.setColorAt(1, QColor("#f3dfbf"))
    painter.fillRect(pm.rect(), bg)

    _draw_sunburst(painter, QPointF(244, 252), 206)
    _draw_full_robot(painter, 86, 32, 1.06)
    _draw_splash_wordmark(painter)

    painter.end()
    return pm


def create_startup_splash(app: QApplication) -> QSplashScreen:
    splash = QSplashScreen(startup_splash_pixmap(), Qt.WindowStaysOnTopHint)
    splash.show()
    app.processEvents()
    app._lyon_startup_splash = splash
    return splash


def finish_startup_splash(app: QApplication, window: QMainWindow, duration_ms: int = 1400) -> None:
    splash = getattr(app, "_lyon_startup_splash", None)
    if splash is None:
        return

    def finish() -> None:
        current = getattr(app, "_lyon_startup_splash", None)
        if current is None:
            return
        current.finish(window)
        app._lyon_startup_splash = None

    QTimer.singleShot(duration_ms, finish)


def _draw_robot_icon(painter: QPainter) -> None:
    painter.setPen(QPen(INK, 7, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    painter.setBrush(CREAM)
    painter.drawRoundedRect(QRectF(8, 8, 240, 240), 34, 34)
    painter.setPen(Qt.NoPen)
    painter.setBrush(TEAL)
    painter.drawRoundedRect(QRectF(20, 20, 216, 216), 30, 30)
    _draw_paper_texture(painter, QRectF(24, 24, 208, 208), QColor(255, 246, 230, 34))

    painter.setPen(Qt.NoPen)
    painter.setBrush(SHADOW)
    painter.drawEllipse(QRectF(60, 214, 138, 18))

    _draw_robot_head(painter, 27, 47, 1.02)


def _draw_sunburst(painter: QPainter, center: QPointF, radius: float) -> None:
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(223, 73, 50, 218))
    painter.drawEllipse(QRectF(center.x() - radius, center.y() - radius, radius * 2, radius * 2))

    painter.setBrush(QColor(255, 246, 230, 232))
    for idx in range(18):
        angle = math.radians(idx * 20)
        spread = math.radians(5.5)
        inner = center + QPointF(math.cos(angle) * 62, math.sin(angle) * 62)
        outer_a = center + QPointF(math.cos(angle - spread) * radius, math.sin(angle - spread) * radius)
        outer_b = center + QPointF(math.cos(angle + spread) * radius, math.sin(angle + spread) * radius)
        ray = QPainterPath(inner)
        ray.lineTo(outer_a)
        ray.lineTo(outer_b)
        ray.closeSubpath()
        painter.fillPath(ray, painter.brush())

    _draw_paper_texture(
        painter,
        QRectF(center.x() - radius, center.y() - radius, radius * 2, radius * 2),
        QColor(255, 246, 230, 28),
    )


def _draw_full_robot(painter: QPainter, x: float, y: float, scale: float) -> None:
    painter.save()
    painter.translate(x, y)
    painter.scale(scale, scale)

    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(8, 34, 58, 76))
    painter.drawEllipse(QRectF(73, 402, 210, 24))

    _draw_robot_head(painter, 41, 16, 1.0)

    painter.setPen(QPen(INK, 9, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    painter.setBrush(DEEP_TEAL)
    left_body = QPainterPath()
    left_body.moveTo(62, 210)
    left_body.lineTo(91, 194)
    left_body.lineTo(91, 342)
    left_body.lineTo(62, 357)
    left_body.closeSubpath()
    painter.drawPath(left_body)

    painter.setBrush(QColor("#e5ecd9"))
    painter.drawRoundedRect(QRectF(88, 190, 150, 152), 9, 9)

    painter.setBrush(CREAM)
    painter.drawRoundedRect(QRectF(112, 219, 100, 80), 4, 4)
    painter.setPen(Qt.NoPen)
    for idx, height in enumerate((16, 36, 28, 52, 22)):
        color = RED if idx in (3, 4) else QColor("#3f8ba0")
        painter.setBrush(color)
        painter.drawRect(QRectF(123 + idx * 14, 270 - height, 10, height))

    painter.setPen(QPen(RED, 6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    note = QPainterPath()
    note.moveTo(178, 244)
    note.lineTo(178, 213)
    note.lineTo(200, 208)
    note.lineTo(200, 238)
    painter.drawPath(note)
    painter.setBrush(RED)
    painter.setPen(Qt.NoPen)
    painter.drawEllipse(QRectF(161, 237, 23, 18))

    painter.setPen(QPen(INK, 9, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    painter.setBrush(TEAL)
    painter.drawEllipse(QRectF(42, 226, 50, 50))
    painter.drawEllipse(QRectF(231, 226, 50, 50))

    painter.setPen(QPen(INK, 13, Qt.SolidLine, Qt.RoundCap))
    painter.drawLine(63, 271, 48, 333)
    painter.drawLine(260, 271, 274, 333)
    painter.setPen(QPen(BLUE, 8, Qt.SolidLine, Qt.RoundCap))
    painter.drawLine(63, 271, 48, 333)
    painter.drawLine(260, 271, 274, 333)

    painter.setPen(QPen(INK, 8, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    painter.setBrush(MINT)
    painter.drawEllipse(QRectF(25, 326, 44, 44))
    painter.drawEllipse(QRectF(255, 326, 44, 44))
    painter.setBrush(CREAM)
    painter.drawEllipse(QRectF(40, 340, 16, 18))
    painter.drawEllipse(QRectF(269, 340, 16, 18))

    painter.setBrush(MINT)
    painter.drawRect(QRectF(104, 342, 42, 54))
    painter.drawRect(QRectF(180, 342, 42, 54))
    painter.setBrush(RED)
    painter.drawRect(QRectF(104, 371, 42, 19))
    painter.drawRect(QRectF(180, 371, 42, 19))
    painter.setBrush(QColor("#c9dfd8"))
    painter.drawRoundedRect(QRectF(88, 392, 68, 28), 6, 6)
    painter.drawRoundedRect(QRectF(170, 392, 68, 28), 6, 6)

    painter.restore()


def _draw_splash_wordmark(painter: QPainter) -> None:
    left = 462
    painter.setPen(QPen(INK, 8, Qt.SolidLine, Qt.SquareCap))
    painter.drawLine(left, 102, 856, 102)

    lyon_font = QFont("Arial Black", 94, QFont.Black)
    painter.setFont(lyon_font)
    painter.setPen(RED)
    painter.drawText(QRectF(left, 115, 310, 104), Qt.AlignLeft | Qt.AlignVCenter, "Lyon")
    _draw_star(painter, QPointF(833, 170), 38, 16, RED)

    painter.setPen(QPen(INK, 8, Qt.SolidLine, Qt.SquareCap))
    painter.drawLine(744, 232, 890, 232)

    word_font = QFont("Arial Black", 91, QFont.Black)
    painter.setFont(word_font)
    painter.setPen(INK)
    painter.drawText(QRectF(left, 214, 395, 105), Qt.AlignLeft | Qt.AlignVCenter, "music")

    manager_font = QFont("Arial Black", 78, QFont.Black)
    painter.setFont(manager_font)
    painter.drawText(QRectF(left, 315, 430, 96), Qt.AlignLeft | Qt.AlignVCenter, "manager")

    painter.setPen(QPen(INK, 8, Qt.SolidLine, Qt.SquareCap))
    painter.drawLine(left, 431, 826, 431)

    painter.setPen(Qt.NoPen)
    for idx, color in enumerate((TEAL, MINT, RED)):
        painter.setBrush(color)
        painter.drawRect(QRectF(836 + idx * 29, 420, 22, 18))


def _draw_robot_head(painter: QPainter, x: float, y: float, scale: float) -> None:
    painter.save()
    painter.translate(x, y)
    painter.scale(scale, scale)

    painter.setPen(QPen(INK, 8, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    painter.setBrush(DEEP_TEAL)
    side = QPainterPath()
    side.moveTo(18, 82)
    side.lineTo(50, 56)
    side.lineTo(50, 150)
    side.lineTo(18, 168)
    side.closeSubpath()
    painter.drawPath(side)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(255, 246, 230, 94))
    side_glint = QPainterPath()
    side_glint.moveTo(28, 89)
    side_glint.lineTo(45, 75)
    side_glint.lineTo(45, 142)
    side_glint.lineTo(28, 153)
    side_glint.closeSubpath()
    painter.drawPath(side_glint)

    painter.setPen(QPen(INK, 8, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    painter.setBrush(RED)
    painter.drawEllipse(QRectF(-2, 86, 36, 54))
    painter.drawEllipse(QRectF(173, 86, 36, 54))
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor("#ff7657"))
    painter.drawEllipse(QRectF(7, 94, 16, 38))
    painter.drawEllipse(QRectF(183, 94, 16, 38))
    painter.setBrush(QColor(255, 246, 230, 96))
    painter.drawRect(QRectF(15, 92, 8, 42))
    painter.drawRect(QRectF(191, 92, 8, 42))

    painter.setPen(QPen(INK, 8, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    painter.setBrush(QColor("#e8f0dd"))
    painter.drawRoundedRect(QRectF(47, 50, 130, 108), 8, 8)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(255, 246, 230, 128))
    painter.drawRoundedRect(QRectF(59, 63, 104, 68), 4, 4)

    painter.setPen(QPen(INK, 8, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    painter.setBrush(BLUE)
    painter.drawRoundedRect(QRectF(85, 31, 53, 18), 8, 8)
    painter.drawLine(112, 31, 112, 12)
    painter.setBrush(RED)
    painter.drawEllipse(QRectF(95, -18, 34, 34))
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor("#ffe1ca"))
    painter.drawEllipse(QRectF(103, -12, 13, 13))
    painter.setBrush(QColor(255, 255, 255, 160))
    painter.drawEllipse(QRectF(99, -15, 21, 18))

    painter.setPen(QPen(CREAM, 7))
    painter.setBrush(CREAM)
    painter.drawEllipse(QRectF(68, 82, 40, 42))
    painter.drawEllipse(QRectF(126, 82, 40, 42))
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor("#06213b"))
    painter.drawEllipse(QRectF(77, 88, 26, 31))
    painter.drawEllipse(QRectF(135, 88, 26, 31))
    painter.setBrush(QColor("#fffaf0"))
    painter.drawEllipse(QRectF(91, 88, 9, 9))
    painter.drawEllipse(QRectF(149, 88, 9, 9))

    painter.setPen(QPen(INK, 4, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    painter.setBrush(QColor("#8fc3cf"))
    nose = QPainterPath()
    nose.moveTo(114, 107)
    nose.lineTo(102, 137)
    nose.lineTo(128, 137)
    nose.closeSubpath()
    painter.drawPath(nose)

    painter.setPen(QPen(INK, 7, Qt.SolidLine, Qt.RoundCap))
    for bar_x in (78, 94, 110, 126, 142):
        painter.drawLine(bar_x, 138, bar_x, 154)

    painter.setPen(QPen(INK, 7, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    painter.setBrush(BLUE)
    painter.drawRoundedRect(QRectF(79, 164, 68, 15), 4, 4)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(255, 255, 255, 92))
    painter.drawRoundedRect(QRectF(89, 167, 48, 5), 2, 2)

    painter.restore()


def _draw_star(painter: QPainter, center: QPointF, outer: float, inner: float, color: QColor) -> None:
    star = QPainterPath()
    for idx in range(10):
        angle = math.radians(-90 + idx * 36)
        radius = outer if idx % 2 == 0 else inner
        point = center + QPointF(math.cos(angle) * radius, math.sin(angle) * radius)
        if idx == 0:
            star.moveTo(point)
        else:
            star.lineTo(point)
    star.closeSubpath()
    painter.setPen(Qt.NoPen)
    painter.setBrush(color)
    painter.drawPath(star)


def _draw_paper_texture(painter: QPainter, bounds: QRectF, color: QColor) -> None:
    painter.save()
    painter.setPen(QPen(color, 1))
    left = int(bounds.left())
    top = int(bounds.top())
    right = int(bounds.right())
    bottom = int(bounds.bottom())
    for row in range(top + 4, bottom, 11):
        for col in range(left + (row % 17), right, 19):
            painter.drawPoint(col, row)
    painter.restore()

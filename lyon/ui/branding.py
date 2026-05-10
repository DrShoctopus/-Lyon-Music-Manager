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
    pm = QPixmap(760, 420)
    pm.fill(CREAM)

    painter = QPainter(pm)
    painter.setRenderHint(QPainter.Antialiasing)

    bg = QLinearGradient(0, 0, 760, 420)
    bg.setColorAt(0, QColor("#fff9ec"))
    bg.setColorAt(1, QColor("#f5e4c6"))
    painter.fillRect(pm.rect(), bg)

    center = QPointF(208, 212)
    painter.setPen(Qt.NoPen)
    for idx in range(24):
        if idx % 2:
            continue
        a1 = math.radians(idx * 15 - 8)
        a2 = math.radians(idx * 15 + 8)
        ray = QPainterPath(center)
        ray.lineTo(center + QPointF(math.cos(a1) * 198, math.sin(a1) * 198))
        ray.lineTo(center + QPointF(math.cos(a2) * 198, math.sin(a2) * 198))
        ray.closeSubpath()
        painter.fillPath(ray, QColor(223, 73, 50, 44))

    painter.drawPixmap(82, 86, robot_icon_pixmap(248))

    painter.setPen(INK)
    title_font = QFont("Arial Narrow", 54, QFont.Black)
    title_font.setCapitalization(QFont.AllUppercase)
    painter.setFont(title_font)
    painter.setPen(RED)
    painter.drawText(QRectF(360, 86, 330, 70), Qt.AlignLeft | Qt.AlignVCenter, "Lyon")
    painter.setPen(INK)
    painter.drawText(QRectF(360, 155, 330, 70), Qt.AlignLeft | Qt.AlignVCenter, "Music")
    painter.drawText(QRectF(360, 224, 360, 70), Qt.AlignLeft | Qt.AlignVCenter, "Manager")

    painter.setPen(QPen(INK, 7))
    painter.drawLine(360, 82, 604, 82)
    painter.drawLine(360, 307, 604, 307)

    painter.setPen(Qt.NoPen)
    bars = [(360, 332, 18, 22, TEAL), (388, 320, 18, 34, RED), (416, 328, 18, 26, MINT)]
    for x, y, w, h, color in bars:
        painter.fillRect(QRectF(x, y, w, h), color)

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
    painter.setPen(Qt.NoPen)
    painter.setBrush(CREAM)
    painter.drawRoundedRect(QRectF(8, 8, 240, 240), 34, 34)
    painter.setBrush(TEAL)
    painter.drawRoundedRect(QRectF(18, 18, 220, 220), 28, 28)

    painter.setBrush(SHADOW)
    painter.drawEllipse(QRectF(65, 213, 126, 20))

    painter.setPen(QPen(INK, 9, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    painter.setBrush(QColor("#6d938b"))
    side = QPainterPath()
    side.moveTo(60, 108)
    side.lineTo(86, 83)
    side.lineTo(86, 177)
    side.lineTo(60, 191)
    side.closeSubpath()
    painter.drawPath(side)

    painter.setBrush(MINT)
    painter.drawRoundedRect(QRectF(82, 72, 124, 106), 8, 8)

    painter.setPen(QPen(INK, 8, Qt.SolidLine, Qt.RoundCap))
    painter.drawLine(144, 62, 144, 42)
    painter.setPen(QPen(INK, 7))
    painter.setBrush(RED)
    painter.drawEllipse(QRectF(130, 19, 28, 28))
    painter.setBrush(QColor("#ffe1ca"))
    painter.setPen(Qt.NoPen)
    painter.drawEllipse(QRectF(137, 24, 9, 9))

    painter.setPen(QPen(INK, 7))
    painter.setBrush(RED)
    painter.drawEllipse(QRectF(45, 106, 30, 48))
    painter.drawEllipse(QRectF(201, 106, 30, 48))

    painter.setBrush(CREAM)
    painter.setPen(QPen(INK, 6))
    painter.drawEllipse(QRectF(101, 101, 32, 32))
    painter.drawEllipse(QRectF(160, 101, 32, 32))
    painter.setBrush(INK)
    painter.setPen(Qt.NoPen)
    painter.drawEllipse(QRectF(112, 101, 17, 22))
    painter.drawEllipse(QRectF(171, 101, 17, 22))
    painter.setBrush(CREAM)
    painter.drawEllipse(QRectF(119, 104, 7, 7))
    painter.drawEllipse(QRectF(178, 104, 7, 7))

    painter.setPen(QPen(INK, 5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    nose = QPainterPath()
    nose.moveTo(147, 130)
    nose.lineTo(136, 153)
    nose.lineTo(158, 153)
    nose.closeSubpath()
    painter.setBrush(QColor("#78aebe"))
    painter.drawPath(nose)

    painter.setPen(QPen(INK, 7, Qt.SolidLine, Qt.RoundCap))
    for x in (111, 126, 141, 156, 171):
        painter.drawLine(x, 171, x, 188)

    painter.setPen(QPen(INK, 7))
    painter.setBrush(QColor("#70a8bd"))
    painter.drawRoundedRect(QRectF(111, 199, 76, 14), 4, 4)

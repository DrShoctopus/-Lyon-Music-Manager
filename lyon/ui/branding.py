"""Lyon Music Manager startup branding helpers."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import (
    QBrush,
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
SHADOW = QColor(8, 34, 58, 64)
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
    pm = QPixmap(1200, 620)
    pm.fill(CREAM)

    painter = QPainter(pm)
    painter.setRenderHint(QPainter.Antialiasing)

    bg = QLinearGradient(0, 0, 1200, 620)
    bg.setColorAt(0, QColor("#fffaf0"))
    bg.setColorAt(1, QColor("#f5e4c6"))
    painter.fillRect(pm.rect(), bg)

    _draw_sunburst(painter, QPointF(302, 318), 262)
    _draw_full_robot(painter, 37, 28, 1.31)
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

    teal_bg = _gradient(20, 20, 216, 216, "#acd0bf", "#7fae9f")
    painter.setPen(Qt.NoPen)
    painter.setBrush(teal_bg)
    painter.drawRoundedRect(QRectF(20, 20, 216, 216), 30, 30)
    _draw_paper_texture(painter, QRectF(24, 24, 208, 208), QColor(255, 246, 230, 36))

    painter.setPen(Qt.NoPen)
    painter.setBrush(SHADOW)
    painter.drawEllipse(QRectF(57, 214, 142, 18))

    _draw_robot_head(painter, 22, 45, 1.07)


def _draw_sunburst(painter: QPainter, center: QPointF, radius: float) -> None:
    painter.setPen(Qt.NoPen)
    sun = _gradient(center.x() - radius, center.y() - radius, radius * 2, radius * 2, "#ef634b", "#d9412c")
    painter.setBrush(sun)
    painter.drawEllipse(QRectF(center.x() - radius, center.y() - radius, radius * 2, radius * 2))

    painter.setBrush(QColor(255, 246, 230, 236))
    for idx in range(18):
        angle = math.radians(idx * 20)
        spread = math.radians(5.2)
        inner = center + QPointF(math.cos(angle) * 76, math.sin(angle) * 76)
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
        QColor(255, 246, 230, 34),
    )


def _draw_full_robot(painter: QPainter, x: float, y: float, scale: float) -> None:
    painter.save()
    painter.translate(x, y)
    painter.scale(scale, scale)

    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(8, 34, 58, 78))
    painter.drawEllipse(QRectF(74, 415, 220, 26))

    _draw_robot_sticker_silhouette(painter)
    _draw_robot_head(painter, 48, 5, 1.05)

    painter.setPen(QPen(INK, 9, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    painter.setBrush(_gradient(60, 190, 52, 170, "#86b0a2", "#3f746d"))
    left_body = QPainterPath()
    left_body.moveTo(61, 216)
    left_body.lineTo(94, 196)
    left_body.lineTo(94, 355)
    left_body.lineTo(61, 374)
    left_body.closeSubpath()
    painter.drawPath(left_body)

    painter.setBrush(_gradient(88, 190, 168, 164, "#eff4e7", "#cdddc8"))
    painter.drawRoundedRect(QRectF(88, 190, 168, 164), 10, 10)

    painter.setBrush(_gradient(111, 222, 115, 86, "#fff8e9", "#f1e7ce"))
    painter.drawRoundedRect(QRectF(111, 222, 115, 86), 4, 4)
    painter.setPen(Qt.NoPen)
    for idx, height in enumerate((18, 38, 30, 58, 28)):
        color = RED if idx in (3, 4) else QColor("#3f8ba0")
        painter.setBrush(color)
        painter.drawRect(QRectF(124 + idx * 16, 282 - height, 11, height))

    painter.setPen(QPen(RED, 7, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    note = QPainterPath()
    note.moveTo(186, 251)
    note.lineTo(186, 216)
    note.lineTo(212, 210)
    note.lineTo(212, 244)
    painter.drawPath(note)
    painter.setBrush(RED)
    painter.setPen(Qt.NoPen)
    painter.drawEllipse(QRectF(168, 244, 25, 19))

    painter.setPen(QPen(INK, 9, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    painter.setBrush(_gradient(39, 225, 58, 58, "#cfe4d5", "#82b5a5"))
    painter.drawEllipse(QRectF(39, 225, 58, 58))
    painter.setBrush(_gradient(246, 225, 58, 58, "#cfe4d5", "#82b5a5"))
    painter.drawEllipse(QRectF(246, 225, 58, 58))

    _draw_segmented_arm(painter, 73, 276, 44, 349, -1)
    _draw_segmented_arm(painter, 270, 276, 294, 349, 1)

    painter.setPen(QPen(INK, 8, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    painter.setBrush(_gradient(18, 336, 53, 53, "#f1f3db", "#b7d3bf"))
    painter.drawEllipse(QRectF(18, 336, 53, 53))
    painter.setBrush(_gradient(278, 336, 53, 53, "#f1f3db", "#b7d3bf"))
    painter.drawEllipse(QRectF(278, 336, 53, 53))
    painter.setBrush(CREAM)
    painter.drawEllipse(QRectF(34, 351, 20, 20))
    painter.drawEllipse(QRectF(294, 351, 20, 20))

    painter.setBrush(_gradient(105, 354, 50, 65, "#dbe9d1", "#a7c5b6"))
    painter.drawRect(QRectF(105, 354, 50, 65))
    painter.setBrush(_gradient(190, 354, 50, 65, "#dbe9d1", "#a7c5b6"))
    painter.drawRect(QRectF(190, 354, 50, 65))
    painter.setBrush(_gradient(105, 388, 50, 25, "#f15d43", "#d83825"))
    painter.drawRect(QRectF(105, 388, 50, 25))
    painter.setBrush(_gradient(190, 388, 50, 25, "#f15d43", "#d83825"))
    painter.drawRect(QRectF(190, 388, 50, 25))
    painter.setBrush(_gradient(82, 415, 88, 34, "#d8e9e2", "#79aebf"))
    painter.drawRoundedRect(QRectF(82, 415, 88, 34), 6, 6)
    painter.setBrush(_gradient(178, 415, 88, 34, "#d8e9e2", "#79aebf"))
    painter.drawRoundedRect(QRectF(178, 415, 88, 34), 6, 6)

    painter.restore()


def _draw_robot_sticker_silhouette(painter: QPainter) -> None:
    painter.setPen(QPen(CREAM, 22, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    painter.setBrush(CREAM)
    painter.drawRoundedRect(QRectF(70, 8, 236, 212), 26, 26)
    painter.drawRoundedRect(QRectF(76, 181, 198, 188), 18, 18)
    painter.drawEllipse(QRectF(24, 214, 292, 84))
    painter.drawEllipse(QRectF(10, 324, 71, 78))
    painter.drawEllipse(QRectF(270, 324, 71, 78))
    painter.drawRoundedRect(QRectF(70, 404, 210, 54), 14, 14)
    painter.setPen(QPen(CREAM, 26, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    painter.drawLine(73, 276, 44, 349)
    painter.drawLine(270, 276, 294, 349)


def _draw_segmented_arm(
    painter: QPainter,
    shoulder_x: float,
    shoulder_y: float,
    hand_x: float,
    hand_y: float,
    direction: int,
) -> None:
    painter.setPen(QPen(INK, 14, Qt.SolidLine, Qt.RoundCap))
    painter.drawLine(shoulder_x, shoulder_y, hand_x, hand_y)
    painter.setPen(QPen(BLUE, 9, Qt.SolidLine, Qt.RoundCap))
    painter.drawLine(shoulder_x, shoulder_y, hand_x, hand_y)

    painter.setPen(QPen(CREAM, 5, Qt.SolidLine, Qt.RoundCap))
    for step in range(1, 5):
        t = step / 5
        x = shoulder_x + (hand_x - shoulder_x) * t
        y = shoulder_y + (hand_y - shoulder_y) * t
        painter.drawLine(x - direction * 9, y - 3, x + direction * 9, y + 3)


def _draw_splash_wordmark(painter: QPainter) -> None:
    left = 575
    painter.setPen(QPen(INK, 9, Qt.SolidLine, Qt.SquareCap))
    painter.drawLine(left, 134, 985, 134)

    lyon_font = QFont("Arial Black", 150, QFont.Black)
    painter.setFont(lyon_font)
    painter.setPen(RED)
    painter.drawText(QRectF(left, 148, 360, 150), Qt.AlignLeft | Qt.AlignVCenter, "Lyon")
    _draw_star(painter, QPointF(1046, 235), 54, 22, RED)

    painter.setPen(QPen(INK, 9, Qt.SolidLine, Qt.SquareCap))
    painter.drawLine(918, 294, 1050, 294)

    music_font = QFont("Arial Black", 160, QFont.Black)
    painter.setFont(music_font)
    painter.setPen(INK)
    painter.drawText(QRectF(left, 278, 465, 165), Qt.AlignLeft | Qt.AlignVCenter, "music")

    manager_font = QFont("Arial Black", 126, QFont.Black)
    painter.setFont(manager_font)
    painter.drawText(QRectF(left, 424, 545, 132), Qt.AlignLeft | Qt.AlignVCenter, "manager")

    painter.setPen(QPen(INK, 9, Qt.SolidLine, Qt.SquareCap))
    painter.drawLine(left, 585, 985, 585)

    painter.setPen(Qt.NoPen)
    for idx, color in enumerate((TEAL, MINT, RED)):
        painter.setBrush(color)
        painter.drawRect(QRectF(1000 + idx * 32, 570, 24, 21))


def _draw_robot_head(painter: QPainter, x: float, y: float, scale: float) -> None:
    painter.save()
    painter.translate(x, y)
    painter.scale(scale, scale)

    painter.setPen(QPen(INK, 8, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    painter.setBrush(_gradient(18, 82, 34, 100, "#7fb0a0", "#416f6b"))
    side = QPainterPath()
    side.moveTo(18, 87)
    side.lineTo(55, 58)
    side.lineTo(55, 158)
    side.lineTo(18, 180)
    side.closeSubpath()
    painter.drawPath(side)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(255, 246, 230, 104))
    side_glint = QPainterPath()
    side_glint.moveTo(30, 96)
    side_glint.lineTo(49, 80)
    side_glint.lineTo(49, 148)
    side_glint.lineTo(30, 160)
    side_glint.closeSubpath()
    painter.drawPath(side_glint)

    painter.setPen(QPen(INK, 8, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    painter.setBrush(_gradient(-4, 89, 40, 56, "#ff704f", "#d43a28"))
    painter.drawEllipse(QRectF(-4, 89, 40, 56))
    painter.setBrush(_gradient(180, 89, 40, 56, "#ff704f", "#d43a28"))
    painter.drawEllipse(QRectF(180, 89, 40, 56))
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor("#ff8b68"))
    painter.drawEllipse(QRectF(7, 99, 16, 36))
    painter.drawEllipse(QRectF(191, 99, 16, 36))
    painter.setBrush(QColor(255, 246, 230, 96))
    painter.drawRect(QRectF(18, 96, 8, 42))
    painter.drawRect(QRectF(202, 96, 8, 42))

    painter.setPen(QPen(INK, 8, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    painter.setBrush(_gradient(51, 54, 136, 114, "#eff5e4", "#cbdcc6"))
    painter.drawRoundedRect(QRectF(51, 54, 136, 114), 8, 8)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(255, 246, 230, 132))
    painter.drawRoundedRect(QRectF(65, 68, 108, 72), 4, 4)

    painter.setPen(QPen(INK, 8, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    painter.setBrush(_gradient(88, 34, 58, 20, "#8fc3cf", "#447f91"))
    painter.drawRoundedRect(QRectF(88, 34, 58, 20), 8, 8)
    painter.drawLine(117, 34, 117, 12)
    painter.setBrush(_gradient(99, -20, 36, 36, "#ff6b4c", "#c93725"))
    painter.drawEllipse(QRectF(99, -20, 36, 36))
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor("#ffe1ca"))
    painter.drawEllipse(QRectF(108, -14, 13, 13))
    painter.setBrush(QColor(255, 255, 255, 160))
    painter.drawEllipse(QRectF(103, -17, 21, 18))

    painter.setPen(QPen(CREAM, 7))
    painter.setBrush(CREAM)
    painter.drawEllipse(QRectF(72, 88, 42, 44))
    painter.drawEllipse(QRectF(135, 88, 42, 44))
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor("#06213b"))
    painter.drawEllipse(QRectF(80, 94, 27, 32))
    painter.drawEllipse(QRectF(143, 94, 27, 32))
    painter.setBrush(QColor("#fffaf0"))
    painter.drawEllipse(QRectF(94, 94, 9, 9))
    painter.drawEllipse(QRectF(157, 94, 9, 9))

    painter.setPen(QPen(INK, 4, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    painter.setBrush(_gradient(111, 113, 28, 32, "#a9d4d9", "#5792ac"))
    nose = QPainterPath()
    nose.moveTo(121, 113)
    nose.lineTo(108, 145)
    nose.lineTo(136, 145)
    nose.closeSubpath()
    painter.drawPath(nose)

    painter.setPen(QPen(INK, 7, Qt.SolidLine, Qt.RoundCap))
    for bar_x in (84, 101, 118, 135, 152):
        painter.drawLine(bar_x, 146, bar_x, 164)

    painter.setPen(QPen(INK, 7, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    painter.setBrush(_gradient(83, 176, 76, 16, "#8fc3cf", "#447f91"))
    painter.drawRoundedRect(QRectF(83, 176, 76, 16), 4, 4)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(255, 255, 255, 92))
    painter.drawRoundedRect(QRectF(95, 180, 52, 5), 2, 2)

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


def _gradient(x: float, y: float, width: float, height: float, start: str, end: str) -> QBrush:
    gradient = QLinearGradient(x, y, x + width, y + height)
    gradient.setColorAt(0, QColor(start))
    gradient.setColorAt(1, QColor(end))
    return QBrush(gradient)

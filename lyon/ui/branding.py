"""Lyon Media Manager startup branding helpers."""
from __future__ import annotations


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
    QRadialGradient,
)
from PySide6.QtWidgets import QApplication, QMainWindow, QSplashScreen


DEEP_NAVY = QColor("#021225")
CYAN = QColor("#10d5f0")
SOFT_CYAN = QColor(16, 213, 240, 95)
WHITE_GLOW = QColor(255, 255, 255, 190)


def app_icon() -> QIcon:
    icon = QIcon()
    for size in (32, 64, 128, 256):
        icon.addPixmap(seal_icon_pixmap(size))
    return icon


def seal_icon_pixmap(size: int = 256) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)

    painter = QPainter(pm)
    painter.setRenderHint(QPainter.Antialiasing)
    scale = size / 256
    painter.scale(scale, scale)
    _draw_icon_background(painter)
    _draw_seal_mark(painter, QRectF(30, 31, 196, 194), icon_mode=True)
    painter.end()
    return pm


def startup_splash_pixmap() -> QPixmap:
    pm = QPixmap(840, 450)
    pm.fill(DEEP_NAVY)

    painter = QPainter(pm)
    painter.setRenderHint(QPainter.Antialiasing)
    _draw_splash_background(painter, pm.width(), pm.height())
    _draw_media_tiles(painter)
    _draw_wave_lines(painter)
    _draw_seal_mark(painter, QRectF(118, 82, 272, 268), icon_mode=False)
    _draw_splash_text(painter)
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


def _draw_icon_background(painter: QPainter) -> None:
    painter.setPen(Qt.NoPen)
    bg = QLinearGradient(0, 0, 256, 256)
    bg.setColorAt(0, QColor("#173b64"))
    bg.setColorAt(0.55, QColor("#061a32"))
    bg.setColorAt(1, QColor("#020811"))
    painter.setBrush(bg)
    painter.drawRoundedRect(QRectF(6, 6, 244, 244), 43, 43)

    painter.setBrush(Qt.NoBrush)
    painter.setPen(QPen(QColor(117, 183, 255, 130), 3))
    painter.drawRoundedRect(QRectF(11, 10, 234, 234), 38, 38)
    painter.setPen(QPen(CYAN, 2))
    painter.drawArc(QRectF(10, 10, 236, 236), 205 * 16, 100 * 16)
    painter.setPen(QPen(QColor(255, 255, 255, 75), 2))
    painter.drawArc(QRectF(16, 14, 224, 222), 46 * 16, 112 * 16)


def _draw_splash_background(painter: QPainter, width: int, height: int) -> None:
    bg = QLinearGradient(0, 0, width, height)
    bg.setColorAt(0, QColor("#102f52"))
    bg.setColorAt(0.5, QColor("#061931"))
    bg.setColorAt(1, QColor("#010812"))
    painter.fillRect(0, 0, width, height, bg)

    glow = QRadialGradient(QPointF(250, 220), 315)
    glow.setColorAt(0, QColor(29, 165, 222, 90))
    glow.setColorAt(0.52, QColor(9, 53, 93, 45))
    glow.setColorAt(1, QColor(0, 0, 0, 0))
    painter.fillRect(0, 0, width, height, glow)


def _draw_media_tiles(painter: QPainter) -> None:
    painter.save()
    painter.setOpacity(0.3)
    painter.setPen(QPen(QColor(38, 147, 205, 110), 1))
    painter.setBrush(QColor(8, 35, 62, 100))
    tiles = [
        QRectF(646, 72, 100, 70),
        QRectF(758, 64, 98, 70),
        QRectF(648, 164, 82, 62),
        QRectF(742, 158, 82, 64),
        QRectF(686, 252, 150, 76),
    ]
    for rect in tiles:
        painter.drawRoundedRect(rect, 5, 5)
    painter.setBrush(QColor(37, 168, 220, 125))
    play = QPainterPath()
    play.moveTo(668, 96)
    play.lineTo(668, 123)
    play.lineTo(694, 109)
    play.closeSubpath()
    painter.fillPath(play, painter.brush())
    painter.drawEllipse(QRectF(765, 187, 15, 15))
    painter.drawRect(QRectF(778, 177, 6, 28))
    painter.drawRoundedRect(QRectF(785, 172, 17, 6), 2, 2)
    painter.drawRoundedRect(QRectF(783, 86, 38, 26), 4, 4)
    for idx, x in enumerate(range(705, 820, 9)):
        h = 12 + (idx % 5) * 6
        painter.drawLine(x, 294 - h / 2, x, 294 + h / 2)
    painter.restore()


def _draw_wave_lines(painter: QPainter) -> None:
    painter.save()
    for row in range(5):
        path = QPainterPath(QPointF(-20, 314 + row * 12))
        path.cubicTo(160, 250 + row * 9, 310, 362 + row * 4, 485, 306 + row * 7)
        path.cubicTo(630, 260 + row * 3, 735, 316 + row * 5, 870, 272 + row * 8)
        painter.setPen(QPen(QColor(13, 202, 235, 42 - row * 5), 1.2))
        painter.drawPath(path)
    painter.restore()


def _draw_splash_text(painter: QPainter) -> None:
    painter.setPen(WHITE_GLOW)
    lyon_font = QFont("Segoe UI", 56, QFont.Light)
    painter.setFont(lyon_font)
    painter.drawText(QRectF(388, 148, 260, 80), Qt.AlignLeft | Qt.AlignVCenter, "Lyon")

    media_font = QFont("Segoe UI", 30, QFont.Light)
    media_font.setLetterSpacing(QFont.AbsoluteSpacing, 9)
    painter.setFont(media_font)
    painter.setPen(QColor("#42d6f5"))
    painter.drawText(QRectF(392, 225, 380, 52), Qt.AlignLeft | Qt.AlignVCenter, "Media Manager")

    painter.setPen(QPen(SOFT_CYAN, 1))
    painter.drawLine(392, 301, 650, 301)
    painter.setBrush(CYAN)
    painter.setPen(Qt.NoPen)
    painter.drawEllipse(QRectF(510, 297, 8, 8))

    tag_font = QFont("Segoe UI", 14, QFont.Light)
    tag_font.setLetterSpacing(QFont.AbsoluteSpacing, 5)
    painter.setFont(tag_font)
    painter.setPen(QColor(166, 196, 225, 160))
    painter.drawText(QRectF(414, 316, 320, 32), Qt.AlignCenter, "Organize. Play. Create.")

    painter.setPen(QColor(190, 226, 248, 190))
    painter.setFont(QFont("Segoe UI", 13, QFont.Normal))
    painter.drawText(QRectF(348, 392, 210, 24), Qt.AlignRight | Qt.AlignVCenter, "Loading library...")
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(34, 102, 153, 90))
    painter.drawRoundedRect(QRectF(570, 401, 210, 5), 3, 3)
    progress = QLinearGradient(570, 401, 650, 401)
    progress.setColorAt(0, QColor("#18e2ff"))
    progress.setColorAt(1, QColor("#6ff6ff"))
    painter.setBrush(progress)
    painter.drawRoundedRect(QRectF(570, 401, 84, 5), 3, 3)


def _draw_seal_mark(painter: QPainter, rect: QRectF, *, icon_mode: bool) -> None:
    painter.save()
    painter.translate(rect.x(), rect.y())
    sx = rect.width() / 300
    sy = rect.height() / 300
    painter.scale(sx, sy)

    painter.setPen(Qt.NoPen)
    shadow = QRadialGradient(QPointF(140, 255), 130)
    shadow.setColorAt(0, QColor(0, 217, 245, 85 if icon_mode else 65))
    shadow.setColorAt(1, QColor(0, 0, 0, 0))
    painter.setBrush(shadow)
    painter.drawEllipse(QRectF(20, 210, 252, 70))

    tail_grad = QLinearGradient(84, 214, 265, 255)
    tail_grad.setColorAt(0, QColor("#067fa5"))
    tail_grad.setColorAt(0.5, QColor("#15c8dc"))
    tail_grad.setColorAt(1, QColor("#034c77"))
    painter.setBrush(tail_grad)
    painter.setPen(QPen(QColor("#37ecff"), 2.2))
    tail = QPainterPath()
    tail.moveTo(92, 214)
    tail.cubicTo(134, 252, 220, 260, 268, 218)
    tail.cubicTo(248, 271, 172, 296, 92, 244)
    tail.cubicTo(64, 226, 47, 196, 40, 164)
    tail.cubicTo(54, 184, 68, 201, 92, 214)
    tail.closeSubpath()
    painter.drawPath(tail)

    fluke = QPainterPath()
    fluke.moveTo(194, 225)
    fluke.cubicTo(236, 202, 252, 180, 268, 162)
    fluke.cubicTo(270, 196, 240, 229, 198, 246)
    fluke.closeSubpath()
    painter.drawPath(fluke)

    body_grad = QLinearGradient(75, 54, 178, 230)
    body_grad.setColorAt(0, QColor("#f3fbff"))
    body_grad.setColorAt(0.35, QColor("#b9d4ea"))
    body_grad.setColorAt(0.76, QColor("#5f8bb2"))
    body_grad.setColorAt(1, QColor("#edf8ff"))
    painter.setBrush(body_grad)
    painter.setPen(QPen(QColor("#bdeeff"), 2.4))
    body = QPainterPath()
    body.moveTo(64, 226)
    body.cubicTo(17, 143, 73, 56, 142, 42)
    body.cubicTo(170, 36, 185, 52, 210, 50)
    body.cubicTo(230, 51, 242, 62, 243, 76)
    body.cubicTo(227, 72, 203, 80, 182, 103)
    body.cubicTo(130, 158, 142, 207, 196, 226)
    body.cubicTo(151, 238, 103, 238, 64, 226)
    body.closeSubpath()
    painter.drawPath(body)

    inner = QPainterPath()
    inner.moveTo(106, 224)
    inner.cubicTo(76, 159, 102, 91, 154, 61)
    inner.cubicTo(131, 99, 121, 148, 145, 193)
    inner.cubicTo(154, 210, 171, 220, 193, 227)
    inner.cubicTo(157, 233, 128, 232, 106, 224)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(255, 255, 255, 36))
    painter.drawPath(inner)

    painter.setBrush(QColor("#021225"))
    painter.setPen(QPen(QColor("#aeeaff"), 1.6))
    painter.drawEllipse(QRectF(202, 63, 13, 8))
    painter.setPen(QPen(QColor(230, 248, 255, 195), 1.2))
    for y in (76, 80, 84):
        painter.drawLine(QPointF(226, y), QPointF(258, y - 15 + (y - 76) * 5))

    highlight = QPainterPath()
    highlight.moveTo(75, 159)
    highlight.cubicTo(73, 94, 118, 56, 159, 50)
    painter.setPen(QPen(QColor(255, 255, 255, 110), 5, Qt.SolidLine, Qt.RoundCap))
    painter.drawPath(highlight)
    painter.restore()

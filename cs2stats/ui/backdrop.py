"""Fondo de la ventana (azul noche con auroras turquesa, estelas de luz y partículas) y halos de color
alrededor de las tarjetas que lo piden con la propiedad "glow"."""

from __future__ import annotations

import math
import random

from PySide6.QtCore import QEvent, QObject, QPointF, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QRadialGradient
from PySide6.QtWidgets import QFrame, QWidget


class Backdrop(QWidget):
    """Fondo pintado una sola vez por tamaño de ventana (queda en caché): no cuesta nada al animar."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cache = QPixmap()

    def resizeEvent(self, event):  # noqa: N802
        self._cache = QPixmap()
        super().resizeEvent(event)

    def paintEvent(self, event):  # noqa: N802
        if self._cache.size() != self.size() * 2:
            self._cache = self._render()
        painter = QPainter(self)
        target = QRectF(event.rect())
        painter.drawPixmap(target, self._cache, QRectF(target.x() * 2, target.y() * 2, target.width() * 2, target.height() * 2))

    def _render(self) -> QPixmap:
        w, h = max(1, self.width()), max(1, self.height())
        pixmap = QPixmap(w * 2, h * 2)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.scale(2, 2)
        base = QLinearGradient(0, 0, w * 0.3, h)
        base.setColorAt(0, QColor("#08202a"))
        base.setColorAt(0.45, QColor("#061720"))
        base.setColorAt(1, QColor("#040d13"))
        painter.fillRect(QRectF(0, 0, w, h), base)
        painter.setPen(Qt.PenStyle.NoPen)
        # Auroras: turquesa arriba a la izquierda, azul arriba a la derecha y un horizonte que brilla abajo.
        for cx, cy, rx, ry, color in ((0.28, -0.05, 0.55, 0.45, QColor(34, 211, 166, 78)),
                                      (0.85, 0.05, 0.45, 0.4, QColor(40, 130, 210, 58)),
                                      (0.55, 1.02, 0.6, 0.28, QColor(34, 211, 166, 66)),
                                      (0.05, 0.75, 0.3, 0.35, QColor(20, 110, 140, 44))):
            center = QPointF(cx * w, cy * h)
            radius = max(rx * w, 1.0)
            glow = QRadialGradient(center, radius)
            glow.setColorAt(0, color)
            fade = QColor(color)
            fade.setAlpha(0)
            glow.setColorAt(1, fade)
            painter.save()
            painter.translate(center)
            painter.scale(1, ry * h / radius)
            painter.translate(-center)
            painter.setBrush(glow)
            painter.drawEllipse(center, radius, radius)
            painter.restore()
        rng = random.Random(7)   # siempre el mismo dibujo
        # Estelas de luz: curvas largas y suaves, con un trazo ancho y tenue debajo para que parezcan brillar.
        for index in range(7):
            top = index < 4
            y0 = h * (0.08 + 0.06 * index) if top else h * (0.82 + 0.05 * (index - 4))
            path = QPainterPath(QPointF(-40, y0))
            path.cubicTo(QPointF(w * 0.3, y0 - h * rng.uniform(0.05, 0.14)), QPointF(w * 0.62, y0 + h * rng.uniform(0.04, 0.12)),
                         QPointF(w + 40, y0 - h * rng.uniform(-0.04, 0.08)))
            for width, alpha in ((8, 9), (3, 20), (1, 44 if index % 2 else 30)):
                painter.setPen(QPen(QColor(64, 230, 200, alpha), width))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawPath(path)
        # Partículas: polvo de luz, más denso cerca de las auroras.
        painter.setPen(Qt.PenStyle.NoPen)
        for _ in range(int(w * h / 5200)):
            x, y = rng.random() * w, rng.random() * h
            near = max(0.0, 1 - math.hypot(x / w - 0.3, y / h) * 1.2) + max(0.0, 1 - math.hypot(x / w - 0.55, y / h - 1) * 2)
            size = rng.uniform(0.5, 1.6)
            alpha = int(min(160, rng.uniform(15, 70) + 90 * near))
            tint = QColor(150, 255, 230, alpha) if rng.random() < 0.7 else QColor(255, 255, 255, alpha)
            painter.setBrush(tint)
            painter.drawEllipse(QPointF(x, y), size, size)
        painter.end()
        pixmap.setDevicePixelRatio(1)
        return pixmap


def set_glow(frame: QWidget, color: str | None, strength: float = 1.0) -> None:
    """Pide (o saca, con None) un halo del color dado alrededor de la tarjeta. Lo pinta GlowLayer en el fondo de la página."""
    frame.setProperty("glow", color or "")
    frame.setProperty("glowStrength", strength)
    parent = frame.parentWidget()
    if parent is not None:
        parent.update()


def paint_glow(painter: QPainter, rect: QRectF, color: QColor, strength: float, radius: float = 14, spread: int = 14) -> None:
    """Halo suave hacia afuera de un rectángulo redondeado, hecho con trazos que se van apagando."""
    painter.setBrush(Qt.BrushStyle.NoBrush)
    for step in range(1, spread + 1):
        fade = (1 - step / (spread + 1)) ** 2.2
        shade = QColor(color)
        shade.setAlpha(int(min(255, 70 * strength * fade)))
        painter.setPen(QPen(shade, 1.6))
        painter.drawRoundedRect(rect.adjusted(-step, -step, step, step), radius + step, radius + step)


class GlowLayer(QObject):
    """Se instala en el lienzo de una página y, antes de que se dibujen las tarjetas, pinta el halo
    de las que tienen la propiedad "glow". Mientras una tarjeta entra (Reveal), su halo aparece con ella."""

    def __init__(self, canvas: QWidget):
        super().__init__(canvas)
        self.canvas = canvas
        canvas.installEventFilter(self)

    def eventFilter(self, obj, event):  # noqa: N802
        if obj is self.canvas and event.type() == QEvent.Type.Paint:
            frames = [f for f in self.canvas.findChildren(QFrame) if f.property("glow") and f.isVisible()]
            if frames:
                painter = QPainter(self.canvas)
                painter.setRenderHint(QPainter.RenderHint.Antialiasing)
                exposed = event.rect()
                for frame in frames:
                    top_left = frame.mapTo(self.canvas, frame.rect().topLeft())
                    rect = QRect(top_left, frame.size())
                    if not rect.adjusted(-20, -20, 20, 20).intersects(exposed):
                        continue
                    strength = float(frame.property("glowStrength") or 1.0)
                    effect = frame.graphicsEffect()
                    progress = getattr(effect, "progress", None)
                    if progress is not None:
                        strength *= progress
                    if strength > 0.02:
                        paint_glow(painter, QRectF(rect).adjusted(0.5, 0.5, -0.5, -0.5), QColor(frame.property("glow")), strength,
                                   float(frame.property("glowRadius") or 14))
                painter.end()
        return False

"""Piezas visuales del detalle de partida: tarjeta del jugador con destellos dorados, placa del rating,
mini tendencias y el VS de cara a cara."""

from __future__ import annotations

import random

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QRadialGradient
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QWidget

from .theme import CT_COLOR, T_COLOR, fmt_num, icon, label, rating_color

GOLD = "#ffcf5a"


def _star(painter: QPainter, center: QPointF, size: float, color: QColor) -> None:
    """Destello de cuatro puntas con un halo chico."""
    halo = QRadialGradient(center, size * 2.6)
    soft = QColor(color)
    soft.setAlpha(int(color.alpha() * 0.45))
    halo.setColorAt(0, soft)
    soft.setAlpha(0)
    halo.setColorAt(1, soft)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(halo)
    painter.drawEllipse(center, size * 2.6, size * 2.6)
    path = QPainterPath(QPointF(center.x(), center.y() - size))
    thin = size * 0.22
    for x, y in ((thin, -thin), (size, 0), (thin, thin), (0, size), (-thin, thin), (-size, 0), (-thin, -thin)):
        path.lineTo(center.x() + x, center.y() + y)
    path.closeSubpath()
    painter.setBrush(color)
    painter.drawPath(path)


class PlayerCard(QFrame):
    """Tarjeta del jugador en la cabecera. Si subiste de Premier (o de ELO), el borde derecho se dora y aparecen
    destellos alrededor del puntaje, como al subir de rango en el juego."""

    def __init__(self, seed: int = 0, celebrate: bool = False, parent=None):
        super().__init__(parent)
        self.setObjectName("playerCard")
        self.celebrate = celebrate
        self.seed = seed

    def paintEvent(self, event):  # noqa: N802
        super().paintEvent(event)
        if not self.celebrate:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        # Resplandor cálido detrás del puntaje.
        warm = QRadialGradient(QPointF(w - 150, h * 0.55), 230)
        warm.setColorAt(0, QColor(255, 196, 80, 38))
        warm.setColorAt(1, QColor(255, 196, 80, 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(warm)
        painter.drawRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), 18, 18)
        # Borde dorado que nace a la derecha y se apaga hacia la izquierda.
        edge = QLinearGradient(w * 0.55, 0, w, 0)
        edge.setColorAt(0, QColor(255, 207, 90, 0))
        edge.setColorAt(0.7, QColor(255, 207, 90, 170))
        edge.setColorAt(1, QColor(255, 226, 140, 255))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(edge, 1.6))
        painter.drawRoundedRect(QRectF(1, 1, w - 2, h - 2), 18, 18)
        rng = random.Random(self.seed)
        for _ in range(18):
            # Más destellos cerca de la esquina derecha, algunos sobre el borde.
            x = w - 12 - (rng.random() ** 1.6) * 330
            y = rng.choice((rng.random() * 10, h - rng.random() * 10, rng.random() * h))
            size = 1.6 + rng.random() * (4.2 if x > w - 120 else 2.6)
            color = QColor(GOLD)
            color.setAlpha(int(120 + rng.random() * 135))
            _star(painter, QPointF(x, y), size, color)


def rating_pill(value: float | None) -> QFrame:
    """El rating dentro de una placa con borde de su color y un escudito, como en la imagen de referencia."""
    color = rating_color(value)
    box = QFrame()
    box.setObjectName("ratingPill")
    tint = QColor(color)
    box.setStyleSheet(f"QFrame#ratingPill {{ background: rgba({tint.red()},{tint.green()},{tint.blue()},34);"
                      f" border: 1px solid rgba({tint.red()},{tint.green()},{tint.blue()},150); border-radius: 9px; }}")
    row = QHBoxLayout(box)
    row.setContentsMargins(10, 3, 14, 3)
    row.setSpacing(8)
    shield = QLabel()
    shield.setPixmap(icon("shield", color, 20).pixmap(QSize(20, 20)))
    row.addWidget(shield)
    text = label(fmt_num(value, 2), "bigValue")
    text.setStyleSheet(f"color: {color};")
    row.addWidget(text)
    box.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
    return box


class Sparkline(QWidget):
    """Tendencia de tus últimas partidas en una línea fina; el último punto (esta partida) va marcado."""

    def __init__(self, values: list[float | None], color: str, parent=None):
        super().__init__(parent)
        self.values = [v for v in values if v is not None]
        # El punto marca esta partida; si esta no tiene el dato, la línea queda sin punto.
        self.marked = bool(values) and values[-1] is not None
        self.color = color
        self.setFixedSize(140, 28)

    def paintEvent(self, _event):  # noqa: N802
        if len(self.values) < 2:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        low, high = min(self.values), max(self.values)
        span = (high - low) or 1.0
        pad = 4
        w, h = self.width() - pad * 2, self.height() - pad * 2
        step = w / (len(self.values) - 1)
        points = [QPointF(pad + i * step, pad + h - (v - low) / span * h) for i, v in enumerate(self.values)]
        path = QPainterPath(points[0])
        for a, b in zip(points, points[1:]):
            middle = (a.x() + b.x()) / 2
            path.cubicTo(QPointF(middle, a.y()), QPointF(middle, b.y()), b)
        area = QPainterPath(path)
        area.lineTo(points[-1].x(), self.height())
        area.lineTo(points[0].x(), self.height())
        area.closeSubpath()
        fill = QLinearGradient(0, 0, 0, self.height())
        shade = QColor(self.color)
        shade.setAlpha(60)
        fill.setColorAt(0, shade)
        shade.setAlpha(0)
        fill.setColorAt(1, shade)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(fill)
        painter.drawPath(area)
        line = QColor(self.color)
        line.setAlpha(200)
        painter.setPen(QPen(line, 1.6))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)
        if not self.marked:
            return
        end = points[-1]
        painter.setPen(Qt.PenStyle.NoPen)
        glow = QColor(self.color)
        glow.setAlpha(70)
        painter.setBrush(glow)
        painter.drawEllipse(end, 5.5, 5.5)
        painter.setBrush(QColor(self.color))
        painter.drawEllipse(end, 2.8, 2.8)


class VersusBadge(QWidget):
    """«VS» inclinado entre tus kills y las del rival: la V turquesa (vos) y la S naranja (ellos)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(76, 76)

    def paintEvent(self, _event):  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = QPointF(self.width() / 2, self.height() / 2)
        halo = QRadialGradient(c, 36)
        halo.setColorAt(0, QColor(255, 255, 255, 26))
        halo.setColorAt(1, QColor(255, 255, 255, 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(halo)
        painter.drawEllipse(c, 36, 36)
        # Rayo diagonal detrás de las letras.
        painter.setPen(QPen(QColor(255, 255, 255, 60), 2))
        painter.drawLine(QPointF(c.x() + 10, 8), QPointF(c.x() - 10, self.height() - 8))
        font = QFont("Segoe UI Variable Display", 28, QFont.Weight.Black)
        font.setItalic(True)
        painter.setFont(font)
        for text, color, dx in (("V", QColor(CT_COLOR).lighter(105), -13), ("S", QColor(T_COLOR), 13)):
            rect = QRectF(c.x() + dx - 20, c.y() - 24, 40, 48)
            shadow = QColor(color)
            shadow.setAlpha(90)
            painter.setPen(shadow)
            painter.drawText(rect.translated(0, 2), Qt.AlignmentFlag.AlignCenter, text)
            painter.setPen(color)
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)


def heat_color(value: float, span: float = 15.0) -> QColor:
    """Rojo para lo que restó, ámbar cerca de cero y verde para lo que sumó (impacto por ronda)."""
    share = max(-1.0, min(1.0, value / span))
    stops = [(-1.0, (255, 92, 92)), (-0.35, (240, 132, 70)), (0.0, (242, 193, 78)), (0.4, (160, 206, 96)),
             (1.0, (52, 214, 150))]
    for (a, ca), (b, cb) in zip(stops, stops[1:]):
        if share <= b:
            k = (share - a) / (b - a)
            return QColor(*(int(x + (y - x) * k) for x, y in zip(ca, cb)))
    return QColor(*stops[-1][1])


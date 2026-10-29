"""Mapa de calor: dónde matás y dónde morís en cada mapa, sobre el mapa armado con las posiciones de tus demos."""

from __future__ import annotations

from collections import Counter

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QRadialGradient
from PySide6.QtWidgets import QSizePolicy, QWidget

from ..i18n import t
from ..nades import GRID, MapGrid, place_label
from .motion import Growing
from .theme import BAD, MUTED

KILL_COLOR = "#22d3a6"
DEATH_COLOR = BAD


def hot_zones(grid: MapGrid | None, points: list[list], count: int = 4) -> list[tuple[str, int]]:
    """Las zonas del mapa (nombres del juego) con más puntos."""
    if not grid or not points:
        return []
    names = Counter(place_label(grid.place_at(x, y)) for x, y in points)
    return names.most_common(count)


class HeatMap(Growing, QWidget):
    """Manchas de calor sobre el mapa: turquesa donde matás, rojo donde morís. El calor aparece de a poco."""

    grow_ms = 1200

    def __init__(self, parent=None):
        super().__init__(parent)
        self.grid: MapGrid | None = None
        self.kills: list[list] = []
        self.deaths: list[list] = []
        self.mode = "deaths"
        self._base: QImage | None = None
        self._heat: QImage | None = None
        self.setMinimumHeight(380)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_data(self, grid: MapGrid | None, kills: list[list], deaths: list[list], mode: str) -> None:
        self.grid, self.kills, self.deaths, self.mode = grid, kills, deaths, mode
        self._base = self._heat = None
        if self.isVisible():
            self.start_grow()
        self.update()

    def resizeEvent(self, event):  # noqa: N802
        self._base = self._heat = None
        super().resizeEvent(event)

    def _frame(self) -> tuple[float, float, float, float]:
        """Límites del mapa en unidades del juego (el mapa armado o, si no hay, los puntos)."""
        if self.grid and self.grid.cells:
            return self.grid.bounds()
        points = self.kills + self.deaths
        xs, ys = [p[0] for p in points] or [0], [p[1] for p in points] or [0]
        return min(xs) - 300, min(ys) - 300, max(xs) + 300, max(ys) + 300

    def _mapper(self):
        x0, y0, x1, y1 = self._frame()
        pad = 16
        scale = min((self.width() - 2 * pad) / max(1, x1 - x0), (self.height() - 2 * pad) / max(1, y1 - y0))
        ox = (self.width() - (x1 - x0) * scale) / 2
        oy = (self.height() - (y1 - y0) * scale) / 2
        return scale, lambda x, y: QPointF(ox + (x - x0) * scale, oy + (y1 - y) * scale)   # en el juego la Y crece hacia arriba

    def _paint_base(self) -> QImage:
        image = QImage(self.size(), QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(QColor("#0d1115"))
        if self.grid and self.grid.cells:
            painter = QPainter(image)
            scale, to_screen = self._mapper()
            zs = [c[0] for c in self.grid.cells.values()]
            z_low, z_high = min(zs), max(max(zs), min(zs) + 1)
            size = max(2.0, GRID * scale)
            painter.setPen(Qt.PenStyle.NoPen)
            for (gx, gy), (z, _place, _n) in self.grid.cells.items():
                shade = int(30 + 34 * (z - z_low) / (z_high - z_low))
                painter.setBrush(QColor(shade, shade + 7, shade + 11))
                p = to_screen(gx * GRID, (gy + 1) * GRID)
                painter.drawRect(QRectF(p.x(), p.y(), size + 0.6, size + 0.6))
            painter.end()
        return image

    def _paint_heat(self) -> QImage:
        """Cada punto suma una mancha difusa; donde se juntan muchas, el color se vuelve intenso."""
        image = QImage(self.size(), QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
        painter.setPen(Qt.PenStyle.NoPen)
        scale, to_screen = self._mapper()
        radius = max(12.0, 360 * scale)
        layers = []
        if self.mode in ("kills", "both"):
            layers.append((self.kills, KILL_COLOR))
        if self.mode in ("deaths", "both"):
            layers.append((self.deaths, DEATH_COLOR))
        for points, color in layers:
            strength = max(40, min(150, int(1500 / max(1, len(points)) + 35)))
            for x, y in points:
                center = to_screen(x, y)
                blob = QRadialGradient(center, radius)
                hot = QColor(color)
                hot.setAlpha(strength)
                blob.setColorAt(0, hot)
                hot.setAlpha(strength // 2)
                blob.setColorAt(0.4, hot)
                hot.setAlpha(0)
                blob.setColorAt(1, hot)
                painter.setBrush(blob)
                painter.drawEllipse(center, radius, radius)
        painter.end()
        return image

    def paintEvent(self, _event):  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not (self.kills or self.deaths):
            painter.fillRect(self.rect(), QColor("#0d1115"))
            painter.setPen(QColor(MUTED))
            painter.drawText(self.rect().adjusted(20, 0, -20, 0), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                             t("Todavía no hay posiciones de este mapa. Se guardan en las partidas nuevas y en las que la app "
                               "vuelve a leer mientras la demo siga disponible."))
            return
        if self._base is None or self._base.size() != self.size():
            self._base = self._paint_base()
            self._heat = self._paint_heat()
        painter.drawImage(0, 0, self._base)
        painter.setOpacity(self.grow)
        painter.drawImage(0, 0, self._heat)
        painter.setOpacity(1.0)
        # Un punto chiquito por cada kill o muerte, para ver los casos sueltos.
        _scale, to_screen = self._mapper()
        painter.setPen(Qt.PenStyle.NoPen)
        dots = []
        if self.mode in ("kills", "both"):
            dots.append((self.kills, KILL_COLOR))
        if self.mode in ("deaths", "both"):
            dots.append((self.deaths, DEATH_COLOR))
        for points, color in dots:
            shade = QColor(color)
            shade.setAlpha(int(230 * self.grow))
            painter.setBrush(shade)
            for x, y in points:
                painter.drawEllipse(to_screen(x, y), 2.2, 2.2)

"""Radar oficial de cada mapa (el mismo del juego, sacado de tu CS2) como fondo de la repetición 2D, el mapa de
calor y las latas.

Si el juego no trae radar de ese mapa (los mapas nuevos a veces no lo tienen), cada pantalla sigue dibujando el
mapa armado con las posiciones de tus demos."""

from __future__ import annotations

from PySide6.QtCore import QRectF
from PySide6.QtGui import QImage, QPainter

from ..assets import map_radar

MARGIN = 150.0          # unidades del juego alrededor de la parte dibujada del radar
LOWER_OPACITY = 0.45    # el piso de abajo (Nuke, Vertigo, Train) se ve tenue debajo del de arriba


class Radar:
    """La imagen del radar y cómo ubicarla: el píxel (0, 0) es la esquina (x, y) del juego y cada píxel mide `scale`."""

    def __init__(self, info: dict):
        self.x, self.y, self.scale = float(info["x"]), float(info["y"]), float(info["scale"])
        self.width, self.height = info.get("size") or (1024, 1024)
        self.box = info.get("box") or [0, 0, self.width, self.height]
        self.image = QImage(str(info["image"]))
        self.lower = QImage(str(info["lower"])) if info.get("lower") else None
        if self.lower is not None and self.lower.isNull():
            self.lower = None

    @property
    def ok(self) -> bool:
        return not self.image.isNull()

    def bounds(self, margin: float = MARGIN) -> tuple[float, float, float, float]:
        """Parte dibujada del radar en coordenadas del juego: (x0, y0, x1, y1), con la Y hacia arriba como en el juego."""
        left, top, right, bottom = self.box
        return (self.x + left * self.scale - margin, self.y - bottom * self.scale - margin,
                self.x + right * self.scale + margin, self.y - top * self.scale + margin)

    def paint(self, painter: QPainter, to_screen, opacity: float = 1.0) -> None:
        """Dibuja el radar en su lugar según to_screen (de coordenadas del juego a la pantalla)."""
        target = QRectF(to_screen(self.x, self.y),
                        to_screen(self.x + self.width * self.scale, self.y - self.height * self.scale))
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        if self.lower is not None:
            painter.setOpacity(opacity * LOWER_OPACITY)
            painter.drawImage(target, self.lower)
        painter.setOpacity(opacity)
        painter.drawImage(target, self.image)
        painter.restore()


_cache: dict[str, Radar] = {}


def radar_for(map_name: str) -> Radar | None:
    """El radar del mapa, o None si todavía no se sacó del juego (solo se guardan los encontrados: al terminar de
    sacarlos aparecen sin reiniciar la app)."""
    if not map_name:
        return None
    if map_name not in _cache:
        info = map_radar(map_name)
        radar = Radar(info) if info else None
        if radar is None or not radar.ok:
            return None
        _cache[map_name] = radar
    return _cache[map_name]

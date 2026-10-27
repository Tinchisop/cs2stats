"""Piezas visuales con imágenes: foto de perfil, tarjetas de mapa con la foto oficial e íconos de armas."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QLabel, QSizePolicy, QWidget

from ..i18n import t
from ..assets import avatar_path, map_image, weapon_icon
from .theme import ACCENT, GOOD, MUTED, TEXT, fmt_num, fmt_pct, rating_color, score_color

_svg_cache: dict[tuple, QPixmap] = {}


def svg_pixmap(path: Path | None, color: str, size: QSize) -> QPixmap:
    """Dibuja un SVG del juego en un color plano (como las siluetas de armas del HUD)."""
    key = (str(path), color, size.width(), size.height())
    if key in _svg_cache:
        return _svg_cache[key]
    pixmap = QPixmap(size * 2)
    pixmap.setDevicePixelRatio(2)
    pixmap.fill(Qt.GlobalColor.transparent)
    if path:
        renderer = QSvgRenderer(str(path))
        if renderer.isValid():
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            view = renderer.defaultSize()
            scale = min(size.width() / max(1, view.width()), size.height() / max(1, view.height()))
            w, h = view.width() * scale, view.height() * scale
            renderer.render(painter, QRectF((size.width() - w) / 2, (size.height() - h) / 2, w, h))
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
            painter.fillRect(QRectF(0, 0, size.width(), size.height()), QColor(color))
            painter.end()
    _svg_cache[key] = pixmap
    return pixmap


class Avatar(QLabel):
    """Tu foto de Steam con esquinas redondeadas; si no hay foto, la inicial sobre el color de acento."""

    def __init__(self, name: str, size: int = 64, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        source = QPixmap(str(avatar_path())) if avatar_path().exists() else QPixmap()
        canvas = QPixmap(size * 2, size * 2)
        canvas.setDevicePixelRatio(2)
        canvas.fill(Qt.GlobalColor.transparent)
        painter = QPainter(canvas)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, size, size), size * 0.2, size * 0.2)
        painter.setClipPath(path)
        if not source.isNull():
            painter.drawPixmap(QRectF(0, 0, size, size), source, QRectF(source.rect()))
        else:
            painter.fillRect(QRectF(0, 0, size, size), QColor(ACCENT))
            painter.setPen(QColor("white"))
            painter.setFont(QFont("Segoe UI Variable Display", int(size * 0.42), QFont.Weight.Black))
            painter.drawText(QRectF(0, 0, size, size), Qt.AlignmentFlag.AlignCenter, (name or "?")[:1].upper())
        painter.setClipping(False)
        painter.setPen(QPen(QColor(255, 255, 255, 40), 1.5))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)
        painter.end()
        self.setPixmap(canvas)


class MapCard(QWidget):
    """Tarjeta de mapa con la foto oficial de CS2 de fondo, como en la referencia."""

    clicked = Signal(str)

    def __init__(self, map_name: str, title: str, parent=None):
        super().__init__(parent)
        self.map_name, self.title = map_name, title
        self.win_rate: float | None = None
        self.games = 0
        self.rating: float | None = None
        self.extra = ""
        self.selected = False
        path = map_image(map_name)
        self.image = QPixmap(str(path)) if path else QPixmap()
        self.setMinimumHeight(180)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_stats(self, games: int, win_rate: float | None, rating: float | None, extra: str = "") -> None:
        self.games, self.win_rate, self.rating, self.extra = games, win_rate, rating, extra
        self.update()

    def mousePressEvent(self, _event):  # noqa: N802
        self.clicked.emit(self.map_name)

    def paintEvent(self, _event):  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        clip = QPainterPath()
        clip.addRoundedRect(rect, 14, 14)
        painter.setClipPath(clip)
        painter.fillRect(rect, QColor("#151920"))
        if not self.image.isNull():
            scaled = self.image.scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                       Qt.TransformationMode.SmoothTransformation)
            painter.drawPixmap(int((self.width() - scaled.width()) / 2), int((self.height() - scaled.height()) / 2), scaled)
        shade = QLinearGradient(rect.topLeft(), rect.bottomRight())
        shade.setColorAt(0, QColor(10, 14, 22, 150))
        shade.setColorAt(0.6, QColor(10, 14, 22, 205))
        shade.setColorAt(1, QColor(10, 14, 22, 235))
        painter.fillRect(rect, shade)
        painter.setClipping(False)
        border = QColor(ACCENT) if self.selected else QColor(255, 255, 255, 34)
        painter.setPen(QPen(border, 2 if self.selected else 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(rect, 14, 14)

        pad = 18
        painter.setPen(QColor(TEXT))
        painter.setFont(QFont("Segoe UI Variable Display", 20, QFont.Weight.Bold))
        painter.drawText(QRectF(pad, 12, rect.width() - 120, 40), Qt.AlignmentFlag.AlignVCenter, self.title)
        if self.win_rate is not None:
            chip = QRectF(rect.right() - 76, 16, 62, 26)
            color = QColor(score_color(self.win_rate * 100))
            back = QColor(color); back.setAlpha(45)
            painter.setPen(QPen(color, 1))
            painter.setBrush(back)
            painter.drawRoundedRect(chip, 13, 13)
            painter.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
            painter.drawText(chip, Qt.AlignmentFlag.AlignCenter, fmt_pct(self.win_rate))
        painter.setPen(QColor("#c9ced6"))
        painter.setFont(QFont("Segoe UI", 9))
        games = t("{0} {1}").format(self.games, t("partida") if self.games == 1 else t("partidas")) if self.games else t("Sin partidas todavía")
        painter.drawText(QRectF(pad, 52, rect.width() - 2 * pad, 18), Qt.AlignmentFlag.AlignVCenter, games)
        track = QRectF(pad, 78, rect.width() - 2 * pad, 6)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255, 40))
        painter.drawRoundedRect(track, 3, 3)
        if self.win_rate is not None:
            fill = QLinearGradient(track.topLeft(), track.topRight())
            fill.setColorAt(0, QColor("#b6d96a")); fill.setColorAt(1, QColor(GOOD))
            painter.setBrush(fill)
            painter.drawRoundedRect(QRectF(track.left(), track.top(), track.width() * self.win_rate, 6), 3, 3)
            painter.setBrush(QColor(TEXT))
            painter.drawRect(QRectF(track.left() + track.width() * 0.5 - 1, track.top() - 3, 2, 12))
        painter.setPen(QColor(MUTED))
        painter.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        painter.drawText(QRectF(pad, 100, 120, 16), Qt.AlignmentFlag.AlignVCenter, t("RATING"))
        painter.setPen(QColor(rating_color(self.rating)))
        painter.setFont(QFont("Segoe UI Variable Display", 24, QFont.Weight.Bold))
        painter.drawText(QRectF(pad, 116, 160, 40), Qt.AlignmentFlag.AlignVCenter, fmt_num(self.rating, 2) if self.rating else "—")
        if self.extra:
            painter.setPen(QColor("#c9ced6"))
            painter.setFont(QFont("Segoe UI", 9))
            painter.drawText(QRectF(pad + 150, 116, rect.width() - pad * 2 - 150, 40),
                             Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, self.extra)


class WeaponRow(QWidget):
    """Silueta del arma + nombre + barra de kills, como el HUD del juego."""

    def __init__(self, weapon: str, label_text: str, kills: int, top: int, note: str, parent=None):
        super().__init__(parent)
        self.icon = svg_pixmap(weapon_icon(weapon), ACCENT, QSize(92, 30))
        self.label_text, self.kills, self.top, self.note = label_text, kills, max(1, top), note
        self.setFixedHeight(44)

    def paintEvent(self, _event):  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.drawPixmap(0, 7, self.icon)
        painter.setPen(QColor(TEXT))
        painter.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        painter.drawText(QRectF(104, 0, 130, 44), Qt.AlignmentFlag.AlignVCenter, self.label_text)
        note_w = 230
        track = QRectF(240, 18, max(60, self.width() - 240 - note_w - 60), 8)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#262a31"))
        painter.drawRoundedRect(track, 4, 4)
        fill = QLinearGradient(track.topLeft(), track.topRight())
        fill.setColorAt(0, QColor("#ff6b8f")); fill.setColorAt(1, QColor(ACCENT))
        painter.setBrush(fill)
        painter.drawRoundedRect(QRectF(track.left(), track.top(), max(6, track.width() * self.kills / self.top), 8), 4, 4)
        painter.setPen(QColor(TEXT))
        painter.setFont(QFont("Segoe UI Variable Display", 12, QFont.Weight.Bold))
        painter.drawText(QRectF(track.right() + 10, 0, 50, 44), Qt.AlignmentFlag.AlignVCenter, str(self.kills))
        painter.setPen(QColor(MUTED))
        painter.setFont(QFont("Segoe UI", 9))
        painter.drawText(QRectF(self.width() - note_w, 0, note_w, 44), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, self.note)

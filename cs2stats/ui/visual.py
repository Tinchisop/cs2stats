"""Piezas visuales con imágenes: foto de perfil, tarjetas de mapa con la foto oficial e íconos de armas."""

from __future__ import annotations

from pathlib import Path

import math

from PySide6.QtCore import QEasingCurve, QPointF, QRectF, QSize, Qt, QTimer, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QLabel, QSizePolicy, QWidget

from ..i18n import t
from ..assets import avatar_path, map_image, weapon_icon
from .motion import Growing
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
    """Foto de Steam con esquinas redondeadas (la tuya, o la de otro jugador si se pasa su archivo);
    si no hay foto, la inicial sobre un color. ring: aro del color del equipo."""

    def __init__(self, name: str, size: int = 64, parent=None, *, photo: bool | Path | None = True, color: str = ACCENT,
                 circle: bool = False, ring: str = ""):
        super().__init__(parent)
        self.setFixedSize(size, size)
        file = avatar_path() if photo is True else photo or None
        source = QPixmap(str(file)) if file and Path(file).exists() else QPixmap()
        canvas = QPixmap(size * 2, size * 2)
        canvas.setDevicePixelRatio(2)
        canvas.fill(Qt.GlobalColor.transparent)
        painter = QPainter(canvas)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        radius = size / 2 if circle else size * 0.2
        path.addRoundedRect(QRectF(0, 0, size, size), radius, radius)
        painter.setClipPath(path)
        if not source.isNull():
            painter.drawPixmap(QRectF(0, 0, size, size), source, QRectF(source.rect()))
        else:
            painter.fillRect(QRectF(0, 0, size, size), QColor(color))
            painter.setPen(QColor("white"))
            painter.setFont(QFont("Segoe UI Variable Display", int(size * 0.42), QFont.Weight.Black))
            painter.drawText(QRectF(0, 0, size, size), Qt.AlignmentFlag.AlignCenter, (name or "?")[:1].upper())
        painter.setClipping(False)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        if ring:
            painter.setPen(QPen(QColor(ring), 2))
            inner = QPainterPath()
            inner.addRoundedRect(QRectF(1, 1, size - 2, size - 2), radius - 1, radius - 1)
            painter.drawPath(inner)
        else:
            painter.setPen(QPen(QColor(255, 255, 255, 40), 1.5))
            painter.drawPath(path)
        painter.end()
        self.setPixmap(canvas)


class MapThumb(QWidget):
    """Foto oficial del mapa recortada con esquinas redondeadas (cabecera del detalle de partida)."""

    def __init__(self, map_name: str, parent=None):
        super().__init__(parent)
        path = map_image(map_name)
        self.image = QPixmap(str(path)) if path else QPixmap()
        self.setFixedSize(184, 104)
        self.setVisible(not self.image.isNull())

    def paintEvent(self, _event):  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        clip = QPainterPath()
        clip.addRoundedRect(rect, 12, 12)
        painter.setClipPath(clip)
        scaled = self.image.scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                   Qt.TransformationMode.SmoothTransformation)
        painter.drawPixmap(int((self.width() - scaled.width()) / 2), int((self.height() - scaled.height()) / 2), scaled)
        painter.setClipping(False)
        painter.setPen(QPen(QColor(255, 196, 140, 120), 1.5))
        painter.drawRoundedRect(rect, 12, 12)


class MapTitle(QWidget):
    """Nombre del mapa en letras grandes con brillo metálico y sombra, como un título del juego."""

    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        self.text = text
        self.font_ = QFont("Segoe UI Variable Display", 40, QFont.Weight.Black)
        self.font_.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 96)
        width = QFontMetrics(self.font_).horizontalAdvance(text)
        self.setFixedSize(width + 12, 64)

    def paintEvent(self, _event):  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addText(QPointF(2, 52), self.font_, self.text)
        painter.translate(2, 3)
        painter.fillPath(path, QColor(0, 0, 0, 170))  # sombra
        painter.translate(-2, -3)
        metal = QLinearGradient(0, 8, 0, 56)
        metal.setColorAt(0, QColor("#ffffff"))
        metal.setColorAt(0.45, QColor("#d9dce1"))
        metal.setColorAt(0.52, QColor("#8f959e"))
        metal.setColorAt(1, QColor("#c9ccd2"))
        painter.fillPath(path, metal)
        painter.setPen(QPen(QColor(255, 255, 255, 60), 0.8))
        painter.drawPath(path)


class PremierBadge(QWidget):
    """Rating de Premier como lo muestra CS2: placa inclinada del color del rango, dos rayas a la izquierda
    y el número en cursiva, con los miles grandes y el resto más chico (8,851)."""

    def __init__(self, rating: int | None, height: int = 26, parent=None):
        super().__init__(parent)
        from ..benchmarks import tier_of
        self.rating = int(rating) if rating else None
        tier = tier_of(self.rating)
        self.color = QColor(tier[3] if tier else "#5f6570")
        self.big = QFont("Segoe UI Variable Display", max(8, int(height * 0.52)), QFont.Weight.Black)
        self.big.setItalic(True)
        self.small = QFont(self.big)
        self.small.setPointSize(max(7, int(height * 0.38)))
        if self.rating:
            head, tail = (f"{self.rating // 1000}", f",{self.rating % 1000:03d}") if self.rating >= 1000 else (str(self.rating), "")
        else:
            head, tail = "---", ""
        self.parts = (head, tail)
        text_w = QFontMetrics(self.big).horizontalAdvance(head) + QFontMetrics(self.small).horizontalAdvance(tail)
        self.slant = height * 0.27
        self.setFixedSize(int(text_w + height * 1.25 + self.slant * 2), height)
        self.setToolTip(f"{tier[2]} · Premier" if tier else "")

    def paintEvent(self, _event):  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h, s = self.width(), self.height(), self.slant

        def parallelogram(x0: float, x1: float) -> QPainterPath:
            path = QPainterPath(QPointF(x0 + s, 0.5))
            path.lineTo(x1, 0.5)
            path.lineTo(x1 - s, h - 0.5)
            path.lineTo(x0, h - 0.5)
            path.closeSubpath()
            return path
        body = parallelogram(0, w)
        fill = QLinearGradient(0, 0, w, 0)
        dark = QColor(self.color)
        dark.setAlpha(70)
        fill.setColorAt(0, dark)
        dark.setAlpha(18)
        fill.setColorAt(1, dark)
        painter.fillPath(body, QColor("#121419"))
        painter.fillPath(body, fill)
        edge = QColor(self.color)
        edge.setAlpha(150)
        painter.setPen(QPen(edge, 1))
        painter.drawPath(body)
        # Las dos rayas de la izquierda.
        stripe = h * 0.16
        for index in range(2):
            x = h * 0.18 + index * stripe * 1.9
            painter.fillPath(parallelogram(x, x + stripe + s), self.color if index == 0 else self.color.darker(130))
        painter.setPen(self.color)
        x = h * 0.18 + stripe * 3.8 + s * 0.6
        head, tail = self.parts
        baseline = (h + QFontMetrics(self.big).capHeight()) / 2  # las dos partes sobre la misma línea
        painter.setFont(self.big)
        painter.drawText(QPointF(x, baseline), head)
        x += QFontMetrics(self.big).horizontalAdvance(head)
        painter.setFont(self.small)
        painter.drawText(QPointF(x, baseline), tail)


class MapCard(Growing, QWidget):
    """Tarjeta de mapa con la foto oficial de CS2 de fondo. Al pasar el mouse la foto se acerca y el borde brilla;
    al tocarla suena la música del mapa (con un ecualizador en la esquina mientras suena)."""

    clicked = Signal(str)
    grow_ms = 1000

    def __init__(self, map_name: str, title: str, parent=None):
        super().__init__(parent)
        self.hover = 0.0
        self.playing = False
        self.phase = 0.0
        self.zoom = QVariantAnimation(self)
        self.zoom.setDuration(260)
        self.zoom.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.zoom.valueChanged.connect(self._zoom_step)
        self.beat = QTimer(self)
        self.beat.setInterval(33)
        self.beat.timeout.connect(self._beat)
        self.setToolTip(t("Clic para escuchar la música del mapa"))
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

    def set_playing(self, playing: bool) -> None:
        self.playing = playing
        if playing:
            self.beat.start()
        else:
            self.beat.stop()
        self.update()

    def _beat(self) -> None:
        self.phase += 0.17
        self.update()

    def _zoom_step(self, value: float) -> None:
        self.hover = value
        self.update()

    def _animate_hover(self, target: float) -> None:
        self.zoom.stop()
        self.zoom.setStartValue(self.hover)
        self.zoom.setEndValue(target)
        self.zoom.start()

    def enterEvent(self, event):  # noqa: N802
        self._animate_hover(1.0)
        super().enterEvent(event)

    def leaveEvent(self, event):  # noqa: N802
        self._animate_hover(0.0)
        super().leaveEvent(event)

    def mousePressEvent(self, _event):  # noqa: N802
        self.clicked.emit(self.map_name)

    def resizeEvent(self, event):  # noqa: N802
        self._cover = None
        super().resizeEvent(event)

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
            if getattr(self, "_cover", None) is None or self._cover.size() != self.size() * 1.1:
                self._cover = self.image.scaled(self.size() * 1.1, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                                Qt.TransformationMode.SmoothTransformation)
            scale = (1.0 + 0.08 * self.hover) / 1.1
            w, h = self._cover.width() * scale, self._cover.height() * scale
            painter.drawPixmap(QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h), self._cover,
                               QRectF(self._cover.rect()))
        shade = QLinearGradient(rect.topLeft(), rect.bottomRight())
        shade.setColorAt(0, QColor(10, 14, 22, int(150 - 50 * self.hover)))
        shade.setColorAt(0.6, QColor(10, 14, 22, int(205 - 40 * self.hover)))
        shade.setColorAt(1, QColor(10, 14, 22, 235))
        painter.fillRect(rect, shade)
        painter.setClipping(False)
        lit = self.selected or self.playing
        border = QColor(ACCENT) if lit else QColor(255, 255, 255, 34 + int(150 * self.hover))
        if not lit and self.hover:
            border = QColor(34, 211, 166, int(40 + 180 * self.hover))
        painter.setPen(QPen(border, 2 if lit else 1 + self.hover))
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
            painter.drawRoundedRect(QRectF(track.left(), track.top(), track.width() * self.win_rate * self.grow, 6), 3, 3)
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
        # Música: ecualizador cuando suena, nota cuando el mouse está encima.
        if self.playing or self.hover > 0.05:
            box = QRectF(rect.right() - 112, 18, 26, 22)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(34, 211, 166, 60 if self.playing else int(40 * self.hover)))
            painter.drawRoundedRect(box.adjusted(-4, -2, 4, 2), 7, 7)
            painter.setBrush(QColor(ACCENT) if self.playing else QColor(255, 255, 255, int(200 * self.hover)))
            for index in range(4):
                level = 0.3 + 0.7 * abs(math.sin(self.phase * (1 + index * 0.37) + index)) if self.playing else 0.25 + 0.15 * index
                h = 16 * level
                painter.drawRoundedRect(QRectF(box.left() + 3 + index * 5.5, box.bottom() - 3 - h, 3.2, h), 1.2, 1.2)


class WeaponRow(Growing, QWidget):
    """Silueta del arma + nombre + barra de kills, como el HUD del juego. La barra crece al aparecer
    y la fila se ilumina al pasar el mouse."""

    grow_ms = 1000

    def __init__(self, weapon: str, label_text: str, kills: int, top: int, note: str, parent=None, order: int = 0):
        super().__init__(parent)
        self.icon = svg_pixmap(weapon_icon(weapon), ACCENT, QSize(92, 30))
        self.icon_hot = svg_pixmap(weapon_icon(weapon), "#ffffff", QSize(92, 30))
        self.label_text, self.kills, self.top, self.note = label_text, kills, max(1, top), note
        self.grow_delay = order * 60
        self.hot = False
        self.setFixedHeight(44)

    def enterEvent(self, event):  # noqa: N802
        self.hot = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):  # noqa: N802
        self.hot = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, _event):  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self.hot:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(34, 211, 166, 22))
            painter.drawRoundedRect(QRectF(self.rect()).adjusted(-6, 1, 6, -1), 8, 8)
        painter.drawPixmap(0, 7, self.icon_hot if self.hot else self.icon)
        painter.setPen(QColor(TEXT))
        painter.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        painter.drawText(QRectF(104, 0, 130, 44), Qt.AlignmentFlag.AlignVCenter, self.label_text)
        note_w = 230
        track = QRectF(240, 18, max(60, self.width() - 240 - note_w - 60), 8)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#262a31"))
        painter.drawRoundedRect(track, 4, 4)
        fill = QLinearGradient(track.topLeft(), track.topRight())
        fill.setColorAt(0, QColor("#6ff0cc")); fill.setColorAt(1, QColor(ACCENT))
        painter.setBrush(fill)
        painter.drawRoundedRect(QRectF(track.left(), track.top(), max(6, track.width() * self.kills / self.top * self.grow), 8), 4, 4)
        painter.setPen(QColor(TEXT))
        painter.setFont(QFont("Segoe UI Variable Display", 12, QFont.Weight.Bold))
        painter.drawText(QRectF(track.right() + 10, 0, 50, 44), Qt.AlignmentFlag.AlignVCenter, str(self.kills))
        painter.setPen(QColor(MUTED))
        painter.setFont(QFont("Segoe UI", 9))
        painter.drawText(QRectF(self.width() - note_w, 0, note_w, 44), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, self.note)

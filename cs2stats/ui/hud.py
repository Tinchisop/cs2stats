"""Piezas animadas del perfil y del menú: mini tendencias, radar de rendimiento, carrusel de partidas,
barra hacia el próximo rango de Premier, ecualizador de la música y el robot entrenador."""

from __future__ import annotations

import math

from PySide6.QtCore import QEasingCurve, QPointF, QRectF, QSize, Qt, QTimer, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QRadialGradient
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QSizePolicy, QToolTip, QWidget

from ..assets import map_icon, map_image
from ..i18n import t
from .charts import smooth_path
from .motion import Growing, Hovering, ease, stagger
from .theme import ACCENT, BAD, CT_COLOR, GOOD, MID, MUTED, SUBTLE, TEXT, fmt_num, rating_color, score_color

_pixmaps: dict[tuple, QPixmap] = {}


def map_picture(map_name: str, width: int, height: int) -> QPixmap:
    """Foto del mapa recortada al tamaño pedido (con caché)."""
    key = ("map", map_name, width, height)
    if key not in _pixmaps:
        path = map_image(map_name)
        source = QPixmap(str(path)) if path else QPixmap()
        if source.isNull():
            _pixmaps[key] = QPixmap()
        else:
            scaled = source.scaled(width * 2, height * 2, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                   Qt.TransformationMode.SmoothTransformation)
            crop = scaled.copy(int((scaled.width() - width * 2) / 2), int((scaled.height() - height * 2) / 2), width * 2, height * 2)
            crop.setDevicePixelRatio(2)
            _pixmaps[key] = crop
    return _pixmaps[key]


def map_emblem(map_name: str, size: int) -> QPixmap:
    """Ícono del mapa del juego (el escudito de colores)."""
    key = ("icon", map_name, size)
    if key not in _pixmaps:
        pixmap = QPixmap(size * 2, size * 2)
        pixmap.setDevicePixelRatio(2)
        pixmap.fill(Qt.GlobalColor.transparent)
        path = map_icon(map_name)
        if path:
            renderer = QSvgRenderer(str(path))
            if renderer.isValid():
                painter = QPainter(pixmap)
                painter.setRenderHint(QPainter.RenderHint.Antialiasing)
                renderer.render(painter, QRectF(0, 0, size, size))
                painter.end()
        _pixmaps[key] = pixmap
    return _pixmaps[key]


class Sparkline(Growing, QWidget):
    """Mini gráfico de tendencia (sin ejes): línea suave con relleno que se dibuja sola y un punto brillante al final."""

    grow_ms = 1200

    def __init__(self, values: list, color: str = ACCENT, width: int = 96, height: int = 34, parent=None):
        super().__init__(parent)
        self.values = [v for v in values if v is not None]
        self.color = color
        # Se achica (hasta un mínimo) si la ventana es angosta, para no empujar el resto.
        self.setFixedHeight(height)
        self.setMinimumWidth(min(width, 34))
        self.setMaximumWidth(width)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def paintEvent(self, _event):  # noqa: N802
        if len(self.values) < 2:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        low, high = min(self.values), max(self.values)
        span = (high - low) or 1
        n = len(self.values)
        points = [QPointF(3 + i * (w - 10) / (n - 1), h - 5 - (v - low) / span * (h - 12)) for i, v in enumerate(self.values)]
        path = smooth_path(points)
        painter.setClipRect(QRectF(0, 0, 3 + (w - 3) * self.grow, h))
        shade = QPainterPath(path)
        shade.lineTo(points[-1].x(), h)
        shade.lineTo(points[0].x(), h)
        shade.closeSubpath()
        color = QColor(self.color)
        gradient = QLinearGradient(0, 0, 0, h)
        top = QColor(color)
        top.setAlpha(85)
        gradient.setColorAt(0, top)
        top.setAlpha(0)
        gradient.setColorAt(1, top)
        painter.fillPath(shade, gradient)
        painter.setPen(QPen(color, 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        painter.drawPath(path)
        if self.grow >= 0.97:
            end = points[-1]
            halo = QRadialGradient(end, 7)
            shine = QColor(color)
            shine.setAlpha(170)
            halo.setColorAt(0, shine)
            shine.setAlpha(0)
            halo.setColorAt(1, shine)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(halo)
            painter.drawEllipse(end, 7, 7)
            painter.setBrush(QColor("#ffffff"))
            painter.drawEllipse(end, 2, 2)


class RadarChart(Growing, Hovering, QWidget):
    """Radar de rendimiento: tu percentil en cada área (0 a 100) contra el promedio de tu rango (50)."""

    grow_ms = 1400

    def __init__(self, parent=None):
        super().__init__(parent)
        self.axes: list[dict] = []   # {"label", "score", "tip"}
        self.setMinimumSize(150, 260)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)
        self.init_hover()
        self._labels: list[QRectF] = []

    def set_axes(self, axes: list[dict]) -> None:
        self.axes = axes
        self.update()

    def _geometry(self) -> tuple[QPointF, float]:
        radius = max(40.0, min(self.width() / 2 - 56, self.height() / 2 - 42))
        return QPointF(self.width() / 2, self.height() / 2 + 2), radius

    def _point(self, center: QPointF, radius: float, index: int, value: float) -> QPointF:
        angle = math.radians(-90 + index * 360 / len(self.axes))
        return QPointF(center.x() + radius * value * math.cos(angle), center.y() + radius * value * math.sin(angle))

    def _polygon(self, center: QPointF, radius: float, values: list[float]) -> QPainterPath:
        path = QPainterPath()
        n = len(values)
        for index in range(n + 1):
            point = self._point(center, radius, index % n, values[index % n])
            path.moveTo(point) if index == 0 else path.lineTo(point)
        return path

    def paintEvent(self, _event):  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if len(self.axes) < 3:
            painter.setPen(QColor(MUTED))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, t("Faltan datos para el radar"))
            return
        center, radius = self._geometry()
        n = len(self.axes)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for ring in (0.25, 0.5, 0.75, 1.0):
            painter.setPen(QPen(QColor(255, 255, 255, 36 if ring == 1.0 else 16), 1))
            painter.drawPath(self._polygon(center, radius, [ring] * n))
        for index in range(n):
            painter.drawLine(center, self._point(center, radius, index, 1.0))
        # Promedio de tu rango: percentil 50 en todas las áreas.
        blue = QColor(CT_COLOR)
        blue.setAlpha(34)
        painter.setPen(QPen(QColor(CT_COLOR), 1.5))
        painter.setBrush(blue)
        painter.drawPath(self._polygon(center, radius, [0.5 * ease(self.grow * 1.8)] * n))
        mine = [max(0.05, (a["score"] or 0) / 100) * stagger(self.grow, i, n, 0.35) for i, a in enumerate(self.axes)]
        shape = self._polygon(center, radius, mine)
        fill = QRadialGradient(center, radius)
        inner = QColor(ACCENT)
        inner.setAlpha(150)
        fill.setColorAt(0, inner)
        inner.setAlpha(55)
        fill.setColorAt(1, inner)
        halo = QColor(ACCENT)
        halo.setAlpha(55)
        painter.setPen(QPen(halo, 8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(shape)
        painter.setPen(QPen(QColor(ACCENT), 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        painter.setBrush(fill)
        painter.drawPath(shape)
        self._labels = []
        name_font = QFont("Segoe UI", 9, QFont.Weight.DemiBold)
        value_font = QFont("Segoe UI Variable Display", 9, QFont.Weight.Bold)
        metrics = QFontMetrics(name_font)
        for index, axis in enumerate(self.axes):
            hover = self.hover.get(index, 0.0)
            point = self._point(center, radius, index, mine[index])
            painter.setPen(QPen(QColor("#0c0f13"), 1.5))
            painter.setBrush(QColor(score_color(axis["score"])))
            size = 3.5 + 3 * hover
            painter.drawEllipse(point, size, size)
            outside = self._point(center, radius + 20, index, 1.0)
            width = metrics.horizontalAdvance(axis["label"]) + 10
            box = QRectF(outside.x() - width / 2, outside.y() - 15, width, 32)
            if outside.x() > center.x() + 8:
                box.moveLeft(outside.x() - 4)
            elif outside.x() < center.x() - 8:
                box.moveRight(outside.x() + 4)
            if outside.y() < center.y() - radius * 0.8:
                box.moveBottom(outside.y() + 10)
            box.moveLeft(max(2.0, min(box.left(), self.width() - box.width() - 2)))
            painter.setFont(name_font)
            painter.setPen(QColor(TEXT if hover else "#b9c3ca"))
            painter.drawText(QRectF(box.left(), box.top(), box.width(), 16), Qt.AlignmentFlag.AlignCenter, axis["label"])
            painter.setFont(value_font)
            painter.setPen(QColor(score_color(axis["score"])))
            painter.drawText(QRectF(box.left(), box.top() + 15, box.width(), 16), Qt.AlignmentFlag.AlignCenter,
                             t("Top {0:.0f} %").format(max(1, 100 - axis["score"])) if axis["score"] is not None else "—")
            self._labels.append(box)

    def mouseMoveEvent(self, event):  # noqa: N802
        if len(self.axes) < 3:
            return
        center, radius = self._geometry()
        pos = event.position()
        angle = math.degrees(math.atan2(pos.y() - center.y(), pos.x() - center.x())) + 90
        index = round((angle % 360) / (360 / len(self.axes))) % len(self.axes)
        near = math.hypot(pos.x() - center.x(), pos.y() - center.y()) < radius + 40
        self.set_hover(index if near else None)
        if near and self.axes[index].get("tip"):
            QToolTip.showText(event.globalPosition().toPoint(), self.axes[index]["tip"], self)
        else:
            QToolTip.hideText()

    def leaveEvent(self, event):  # noqa: N802
        self.set_hover(None)
        super().leaveEvent(event)


class MatchCarousel(Growing, Hovering, QWidget):
    """Tus últimas partidas como tarjetas con la foto del mapa: rating, K/D, resultado y MVP.
    Se desliza con las flechas o la rueda del mouse; la tarjeta bajo el mouse se levanta y brilla."""

    clicked = Signal(int)
    CARD_W, CARD_H, GAP = 178.0, 100.0, 12.0

    def __init__(self, parent=None):
        super().__init__(parent)
        self.items: list[dict] = []   # {"id", "map", "map_label", "rating", "kd", "us", "them", "result", "mvp", "tip"}
        self.offset = 0.0
        self.setFixedHeight(int(self.CARD_H + 16))
        self.setMouseTracking(True)
        self.init_hover()
        self.slide = QVariantAnimation(self)
        self.slide.setDuration(420)
        self.slide.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.slide.valueChanged.connect(self._slide_step)
        self._cells: list[tuple[QRectF, dict]] = []
        self.arrow_hover = ""

    def set_items(self, items: list[dict]) -> None:
        self.items = items
        self.offset = 0.0
        self.update()

    def _track(self) -> QRectF:
        return QRectF(30, 4, self.width() - 60, self.CARD_H + 8)

    def _max_offset(self) -> float:
        total = len(self.items) * (self.CARD_W + self.GAP) - self.GAP
        return max(0.0, total - self._track().width())

    def _slide_step(self, value: float) -> None:
        self.offset = value
        self.update()

    def scroll_by(self, cards: int) -> None:
        target = max(0.0, min(self._max_offset(), (self.slide.endValue() if self.slide.state() else self.offset)
                              + cards * (self.CARD_W + self.GAP)))
        self.slide.stop()
        self.slide.setStartValue(self.offset)
        self.slide.setEndValue(target)
        self.slide.start()

    def paintEvent(self, _event):  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self._cells = []
        track = self._track()
        if not self.items:
            painter.setPen(QColor(MUTED))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, t("Todavía no hay partidas con demo"))
            return
        painter.save()
        painter.setClipRect(track.adjusted(-2, -4, 2, 4))
        n = len(self.items)
        for index, item in enumerate(self.items):
            x = track.left() + index * (self.CARD_W + self.GAP) - self.offset
            if x > track.right() or x + self.CARD_W < track.left():
                continue
            appear = stagger(self.grow, index, min(n, 8), 0.5)
            hover = self.hover.get(index, 0.0)
            painter.save()
            painter.setOpacity(appear)
            painter.translate(0, (1 - appear) * 16 - hover * 4)
            rect = QRectF(x, track.top() + 4, self.CARD_W, self.CARD_H)
            self._paint_card(painter, rect, item, hover)
            painter.restore()
            self._cells.append((rect, item))
        painter.restore()
        # Fundido en los bordes cuando hay más tarjetas.
        for side in ("left", "right"):
            if (side == "left" and self.offset > 1) or (side == "right" and self.offset < self._max_offset() - 1):
                self._paint_arrow(painter, side)

    def _paint_card(self, painter: QPainter, rect: QRectF, item: dict, hover: float) -> None:
        clip = QPainterPath()
        clip.addRoundedRect(rect, 12, 12)
        painter.save()
        painter.setClipPath(clip)
        painter.fillRect(rect, QColor("#141b21"))
        picture = map_picture(item["map"], int(rect.width() * 0.55), int(rect.height()))
        if not picture.isNull():
            image_rect = QRectF(rect.right() - rect.width() * 0.55, rect.top(), rect.width() * 0.55, rect.height())
            painter.setOpacity(painter.opacity() * (0.75 + 0.25 * hover))
            painter.drawPixmap(image_rect, picture, QRectF(picture.rect()))
            painter.setOpacity(painter.opacity() / (0.75 + 0.25 * hover))
            fade = QLinearGradient(image_rect.topLeft(), image_rect.topRight())
            fade.setColorAt(0, QColor("#141b21"))
            fade.setColorAt(0.55, QColor(20, 27, 33, 120))
            fade.setColorAt(1, QColor(20, 27, 33, 40))
            painter.fillRect(image_rect, fade)
        result = item.get("result")
        tone = QColor(GOOD if result == "W" else BAD if result == "L" else MID)
        wash = QLinearGradient(rect.bottomLeft(), rect.topLeft())
        tone.setAlpha(40 + int(30 * hover))
        wash.setColorAt(0, tone)
        tone.setAlpha(0)
        wash.setColorAt(0.6, tone)
        painter.fillRect(rect, wash)
        painter.restore()
        border = QColor(ACCENT) if hover > 0.05 else QColor(255, 255, 255, 30)
        if hover > 0.05:
            border.setAlpha(int(90 + 140 * hover))
        painter.setPen(QPen(border, 1.2 + hover))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), 12, 12)
        pad = 12
        painter.setFont(QFont("Segoe UI Variable Display", 13, QFont.Weight.Bold))
        painter.setPen(QColor(rating_color(item.get("rating"))))
        painter.drawText(QRectF(rect.left() + pad, rect.top() + 8, 80, 22), Qt.AlignmentFlag.AlignVCenter,
                         fmt_num(item.get("rating"), 2))
        painter.setFont(QFont("Segoe UI Variable Display", 11, QFont.Weight.DemiBold))
        painter.setPen(QColor("#c9d0d6"))
        painter.drawText(QRectF(rect.left() + pad, rect.top() + 32, 60, 22), Qt.AlignmentFlag.AlignVCenter,
                         fmt_num(item.get("kd"), 2))
        score = f"{item['us']} : {item['them']}"
        chip = QRectF(rect.left() + pad + 50, rect.top() + 33, 56, 20)
        color = QColor(GOOD if result == "W" else BAD if result == "L" else MID)
        back = QColor(color)
        back.setAlpha(46)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(back)
        painter.drawRoundedRect(chip, 5, 5)
        painter.setPen(color)
        painter.setFont(QFont("Segoe UI Variable Display", 10, QFont.Weight.Bold))
        painter.drawText(chip, Qt.AlignmentFlag.AlignCenter, score)
        emblem = map_emblem(item["map"], 16)
        painter.drawPixmap(QPointF(rect.left() + pad, rect.bottom() - 26), emblem)
        painter.setPen(QColor("#dfe5ea"))
        painter.setFont(QFont("Segoe UI", 9, QFont.Weight.DemiBold))
        painter.drawText(QRectF(rect.left() + pad + 22, rect.bottom() - 28, 120, 20), Qt.AlignmentFlag.AlignVCenter,
                         item["map_label"])
        if item.get("mvp"):
            badge = QRectF(rect.right() - 58, rect.top() + 8, 48, 18)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#f2c14e"))
            painter.drawRoundedRect(badge, 5, 5)
            crown = QPainterPath(QPointF(badge.left() + 6, badge.top() + 13))
            for px, py in ((5, 5), (9, 9), (12, 3.5), (15, 9), (19, 5), (18, 13)):
                crown.lineTo(badge.left() + px + 1, badge.top() + py)
            crown.closeSubpath()
            painter.setBrush(QColor("#2a2008"))
            painter.drawPath(crown)
            painter.setPen(QColor("#2a2008"))
            painter.setFont(QFont("Segoe UI", 7, QFont.Weight.Black))
            painter.drawText(QRectF(badge.left() + 20, badge.top(), 28, badge.height()), Qt.AlignmentFlag.AlignVCenter, "MVP")

    def _paint_arrow(self, painter: QPainter, side: str) -> None:
        cx = 14 if side == "left" else self.width() - 14
        cy = self.height() / 2
        hot = self.arrow_hover == side
        painter.setPen(QPen(QColor(255, 255, 255, 60 if hot else 30), 1))
        painter.setBrush(QColor(34, 211, 166, 70) if hot else QColor(255, 255, 255, 14))
        painter.drawEllipse(QPointF(cx, cy), 13, 13)
        painter.setPen(QPen(QColor(TEXT), 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        d = -3 if side == "left" else 3
        painter.drawPolyline([QPointF(cx - d, cy - 6), QPointF(cx + d, cy), QPointF(cx - d, cy + 6)])

    def _arrow_at(self, pos: QPointF) -> str:
        if pos.x() < 28 and self.offset > 1:
            return "left"
        if pos.x() > self.width() - 28 and self.offset < self._max_offset() - 1:
            return "right"
        return ""

    def mouseMoveEvent(self, event):  # noqa: N802
        pos = event.position()
        self.arrow_hover = self._arrow_at(pos)
        if self.arrow_hover:
            self.set_hover(None)
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            self.update()
            return
        for rect, item in self._cells:
            if rect.contains(pos):
                self.set_hover(self.items.index(item))
                self.setCursor(Qt.CursorShape.PointingHandCursor)
                QToolTip.showText(event.globalPosition().toPoint(), item.get("tip", ""), self)
                return
        self.set_hover(None)
        self.unsetCursor()
        QToolTip.hideText()

    def leaveEvent(self, event):  # noqa: N802
        self.set_hover(None)
        self.arrow_hover = ""
        self.update()
        super().leaveEvent(event)

    def wheelEvent(self, event):  # noqa: N802
        steps = -1 if event.angleDelta().y() > 0 or event.angleDelta().x() > 0 else 1
        self.scroll_by(steps)

    def mousePressEvent(self, event):  # noqa: N802
        pos = event.position()
        arrow = self._arrow_at(pos)
        if arrow:
            visible = max(1, int(self._track().width() // (self.CARD_W + self.GAP)))
            self.scroll_by(-visible if arrow == "left" else visible)
            return
        for rect, item in self._cells:
            if rect.contains(pos) and item.get("id"):
                self.clicked.emit(item["id"])
                return


class TierProgress(Growing, QWidget):
    """Barra hacia el próximo color de Premier, con el color del rango actual y un brillo que la recorre."""

    grow_ms = 1300

    def __init__(self, progress: float, color: str, parent=None):
        super().__init__(parent)
        self.progress = max(0.0, min(1.0, progress))
        self.color = QColor(color)
        self.shine = 0.0
        self.setFixedHeight(10)
        self.setMinimumWidth(160)
        self.sweep = QVariantAnimation(self)
        self.sweep.setStartValue(0.0)
        self.sweep.setEndValue(1.0)
        self.sweep.setDuration(2600)
        self.sweep.setLoopCount(-1)
        self.sweep.valueChanged.connect(self._sweep)

    def _sweep(self, value: float) -> None:
        self.shine = value
        self.update()

    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        self.sweep.start()

    def hideEvent(self, event):  # noqa: N802
        self.sweep.stop()
        super().hideEvent(event)

    def paintEvent(self, _event):  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        track = QRectF(0, 2, self.width(), 6)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255, 22))
        painter.drawRoundedRect(track, 3, 3)
        fill = QRectF(0, 2, max(6.0, self.width() * self.progress * self.grow), 6)
        gradient = QLinearGradient(fill.topLeft(), fill.topRight())
        start = QColor(ACCENT)
        gradient.setColorAt(0, start)
        gradient.setColorAt(1, self.color)
        painter.setBrush(gradient)
        painter.drawRoundedRect(fill, 3, 3)
        if self.grow >= 1:
            x = fill.left() + (fill.width() + 60) * self.shine - 30
            shine = QLinearGradient(x - 30, 0, x + 30, 0)
            shine.setColorAt(0, QColor(255, 255, 255, 0))
            shine.setColorAt(0.5, QColor(255, 255, 255, 120))
            shine.setColorAt(1, QColor(255, 255, 255, 0))
            painter.setClipRect(fill)
            painter.setBrush(shine)
            painter.drawRoundedRect(fill, 3, 3)


class Equalizer(QWidget):
    """Cuatro barritas que bailan mientras suena la música del mapa."""

    def __init__(self, color: str = ACCENT, parent=None):
        super().__init__(parent)
        self.color = QColor(color)
        self.phase = 0.0
        self.active = False
        self.setFixedSize(QSize(18, 14))
        self.timer = QTimer(self)
        self.timer.setInterval(33)
        self.timer.timeout.connect(self._tick)

    def set_active(self, active: bool) -> None:
        self.active = active
        if active:
            self.timer.start()
        else:
            self.timer.stop()
        self.update()

    def _tick(self) -> None:
        self.phase += 0.16
        self.update()

    def paintEvent(self, _event):  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self.color if self.active else QColor(SUBTLE))
        for index in range(4):
            level = 0.3 + 0.7 * abs(math.sin(self.phase * (1 + index * 0.37) + index)) if self.active else 0.3
            h = self.height() * level
            painter.drawRoundedRect(QRectF(index * 4.6, self.height() - h, 3, h), 1.2, 1.2)


class CoachBot(QWidget):
    """Robot entrenador del menú: flota, parpadea y mira hacia donde está el mouse dentro de la ventana."""

    def __init__(self, size: int = 46, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.bob = 0.0
        self.blink = 0.0
        self.float_animation = QVariantAnimation(self)
        self.float_animation.setStartValue(0.0)
        self.float_animation.setEndValue(2 * math.pi)
        self.float_animation.setDuration(2800)
        self.float_animation.setLoopCount(-1)
        self.float_animation.valueChanged.connect(self._float)
        self.blink_timer = QTimer(self)
        self.blink_timer.timeout.connect(self._blink)
        self.blink_timer.start(3600)

    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        self.float_animation.start()

    def hideEvent(self, event):  # noqa: N802
        self.float_animation.stop()
        super().hideEvent(event)

    def _float(self, value: float) -> None:
        self.bob = math.sin(value)
        self.update()

    def _blink(self) -> None:
        self.blink = 1.0
        QTimer.singleShot(140, self._open_eyes)
        self.update()

    def _open_eyes(self) -> None:
        self.blink = 0.0
        self.update()

    def paintEvent(self, _event):  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        s = self.width() / 46
        painter.scale(s, s)
        painter.translate(0, self.bob * 2.2)
        aura = QRadialGradient(QPointF(23, 25), 24)
        aura.setColorAt(0, QColor(34, 211, 166, 70))
        aura.setColorAt(1, QColor(34, 211, 166, 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(aura)
        painter.drawEllipse(QPointF(23, 25), 24, 22)
        # Antena con luz.
        painter.setPen(QPen(QColor("#9fb4bf"), 1.6))
        painter.drawLine(QPointF(23, 9), QPointF(23, 4))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(ACCENT))
        painter.drawEllipse(QPointF(23, 3.5), 2.4, 2.4)
        head = QLinearGradient(0, 9, 0, 36)
        head.setColorAt(0, QColor("#f2f6f8"))
        head.setColorAt(1, QColor("#aebdc6"))
        painter.setBrush(head)
        painter.drawRoundedRect(QRectF(7, 9, 32, 26), 11, 11)
        painter.setBrush(QColor("#c7d3da"))
        painter.drawRoundedRect(QRectF(3.5, 17, 4.5, 10), 2, 2)
        painter.drawRoundedRect(QRectF(38, 17, 4.5, 10), 2, 2)
        painter.setBrush(QColor("#0f1a22"))
        painter.drawRoundedRect(QRectF(10.5, 13.5, 25, 17), 8, 8)
        eye_h = max(0.8, 5.5 * (1 - self.blink))
        painter.setBrush(QColor(ACCENT))
        for x in (17, 29):
            painter.drawRoundedRect(QRectF(x - 2.6, 22 - eye_h / 2, 5.2, eye_h), 2.4, 2.4)
        painter.setPen(QPen(QColor(ACCENT), 1.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawArc(QRectF(19.5, 24, 7, 4), 200 * 16, 140 * 16)
        # Cuerpito.
        painter.setPen(Qt.PenStyle.NoPen)
        body = QLinearGradient(0, 36, 0, 46)
        body.setColorAt(0, QColor("#dfe7ec"))
        body.setColorAt(1, QColor("#93a5b0"))
        painter.setBrush(body)
        painter.drawRoundedRect(QRectF(14, 36, 18, 8), 4, 4)
        painter.setBrush(QColor(ACCENT))
        painter.drawEllipse(QPointF(23, 40), 1.8, 1.8)


def tier_progress(rating: int | None) -> tuple[float, int, str, str] | None:
    """Cuánto te falta para el próximo color de Premier: (avance 0 a 1, puntos que faltan, color actual, color siguiente)."""
    from ..benchmarks import TIERS, tier_of
    tier = tier_of(rating)
    if not tier:
        return None
    index = TIERS.index(tier)
    if index == len(TIERS) - 1:
        return 1.0, 0, tier[3], ""
    following = TIERS[index + 1]
    span = following[0] - tier[0]
    return (rating - tier[0]) / span, following[0] - rating, tier[3], following[2]

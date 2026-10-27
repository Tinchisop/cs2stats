"""Gráficos y piezas visuales dibujadas con QPainter."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QSizePolicy, QToolTip, QWidget

from ..i18n import t
from .theme import ACCENT, BAD, CT_COLOR, GOOD, MUTED, SUBTLE, T_COLOR, TEXT, fmt_num, rating_color, score_color


def smooth_path(points: list[QPointF]) -> QPainterPath:
    """Curva suave que pasa por todos los puntos (Catmull-Rom convertido a Bézier)."""
    path = QPainterPath(points[0])
    for index in range(len(points) - 1):
        p0 = points[max(0, index - 1)]; p1 = points[index]; p2 = points[index + 1]; p3 = points[min(len(points) - 1, index + 2)]
        c1 = QPointF(p1.x() + (p2.x() - p0.x()) / 6, p1.y() + (p2.y() - p0.y()) / 6)
        c2 = QPointF(p2.x() - (p3.x() - p1.x()) / 6, p2.y() - (p3.y() - p1.y()) / 6)
        path.cubicTo(c1, c2, p2)
    return path


class PercentileBar(QWidget):
    """Barra 0 a 100: dónde quedás entre los jugadores de referencia. La marca del medio es el promedio."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.score: float | None = None
        self.setFixedHeight(10)
        self.setMinimumWidth(120)

    def set_score(self, score: float | None) -> None:
        self.score = score
        self.update()

    def paintEvent(self, _event):  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(0, 2, self.width(), 6)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#25282f"))
        painter.drawRoundedRect(rect, 3, 3)
        if self.score is not None:
            fill = QRectF(rect.left(), rect.top(), max(4.0, rect.width() * self.score / 100), rect.height())
            painter.setBrush(QColor(score_color(self.score)))
            painter.drawRoundedRect(fill, 3, 3)
        painter.setBrush(QColor("#8b919d"))
        painter.drawRect(QRectF(rect.center().x() - 0.75, 0, 1.5, 10))


class MatchPills(QWidget):
    """Últimas partidas como fichas de color con el rating (verde = buena, roja = mala) y raya de resultado."""

    clicked = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.items: list[dict] = []   # {"id", "rating", "result", "tip"}
        self._cells: list[tuple[QRectF, dict]] = []
        self.setMouseTracking(True)
        self.setFixedHeight(52)

    def set_items(self, items: list[dict]) -> None:
        self.items = items
        self.update()

    def paintEvent(self, _event):  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._cells = []
        if not self.items:
            painter.setPen(QColor(MUTED))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignVCenter, t("Todavía no hay partidas con demo"))
            return
        gap, width = 6.0, 46.0
        count = min(len(self.items), int((self.width() + gap) // (width + gap)))
        for index, item in enumerate(self.items[-count:]):
            rect = QRectF(index * (width + gap), 4, width, 40)
            color = QColor(rating_color(item.get("rating")))
            back = QColor(color); back.setAlpha(40)
            painter.setPen(Qt.PenStyle.NoPen); painter.setBrush(back)
            painter.drawRoundedRect(rect, 6, 6)
            result = item.get("result")
            painter.setBrush(QColor(GOOD if result == "W" else BAD if result == "L" else MUTED))
            painter.drawRoundedRect(QRectF(rect.left() + 6, rect.bottom() - 5, rect.width() - 12, 3), 1.5, 1.5)
            painter.setPen(color)
            painter.setFont(QFont("Segoe UI Variable Display", 10, QFont.Weight.Bold))
            painter.drawText(QRectF(rect.left(), rect.top(), rect.width(), rect.height() - 6), Qt.AlignmentFlag.AlignCenter,
                             fmt_num(item.get("rating"), 2))
            self._cells.append((rect, item))

    def mouseMoveEvent(self, event):  # noqa: N802
        for rect, item in self._cells:
            if rect.contains(event.position()):
                QToolTip.showText(event.globalPosition().toPoint(), item.get("tip", ""), self)
                self.setCursor(Qt.CursorShape.PointingHandCursor)
                return
        self.unsetCursor()
        QToolTip.hideText()

    def mousePressEvent(self, event):  # noqa: N802
        for rect, item in self._cells:
            if rect.contains(event.position()) and item.get("id"):
                self.clicked.emit(item["id"])
                return


class TrendChart(QWidget):
    """Evolución partida por partida: línea, puntos verdes (victoria) o rojos (derrota) y promedio punteado."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.points: list[dict] = []   # {"value", "label", "won", "tip"}
        self.average: float | None = None
        self.reference: float | None = None
        self.reference_label = ""
        self.decimals = 2
        self.suffix = ""
        self.color = ACCENT
        self._hits: list[tuple[QPointF, str]] = []
        self.setMinimumHeight(220)
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_data(self, points: list[dict], average=None, reference=None, reference_label: str = "",
                 decimals: int = 2, suffix: str = "", color: str = ACCENT) -> None:
        self.points, self.average, self.reference, self.reference_label = points, average, reference, reference_label
        self.decimals, self.suffix, self.color = decimals, suffix, color
        self.update()

    def _fmt(self, value: float) -> str:
        return fmt_num(value, self.decimals) + self.suffix

    def paintEvent(self, _event):  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setFont(QFont("Segoe UI", 8))
        area = QRectF(52, 14, max(10, self.width() - 66), max(10, self.height() - 42))
        values = [p["value"] for p in self.points if p["value"] is not None]
        self._hits = []
        if not values:
            painter.setPen(QColor(MUTED))
            painter.drawText(area, Qt.AlignmentFlag.AlignCenter, t("Sin datos todavía"))
            return
        refs = values + [v for v in (self.average, self.reference) if v is not None]
        low, high = min(refs), max(refs)
        pad = max((high - low) * 0.15, abs(high) * 0.05, 0.05)
        low, high = low - pad, high + pad
        if min(refs) >= 0 and low < 0:
            low = 0

        def y_of(v: float) -> float:
            return area.bottom() - (v - low) / (high - low) * area.height()

        for step in range(4):
            value = low + (high - low) * step / 3
            y = y_of(value)
            painter.setPen(QPen(QColor("#202329"), 1))
            painter.drawLine(QPointF(area.left(), y), QPointF(area.right(), y))
            painter.setPen(QColor(SUBTLE))
            painter.drawText(QRectF(0, y - 8, 46, 16), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, self._fmt(value))
        n = len(self.points)

        def x_of(i: int) -> float:
            return area.center().x() if n == 1 else area.left() + i * area.width() / (n - 1)

        for value, color, text in ((self.average, MUTED, t('Tu promedio {0}').format(self._fmt(self.average) if self.average is not None else '')),
                                   (self.reference, CT_COLOR, f"{self.reference_label} {self._fmt(self.reference) if self.reference is not None else ''}")):
            if value is None:
                continue
            y = y_of(value)
            painter.setPen(QPen(QColor(color), 1.2, Qt.PenStyle.DashLine))
            painter.drawLine(QPointF(area.left(), y), QPointF(area.right(), y))
            painter.setPen(QColor(color))
            painter.drawText(QRectF(area.right() - 260, y - 17, 260, 15), Qt.AlignmentFlag.AlignRight, text)

        mapped = [(i, QPointF(x_of(i), y_of(p["value"])), p) for i, p in enumerate(self.points) if p["value"] is not None]
        line = [q for _, q, _ in mapped]
        if len(line) > 1:
            path = smooth_path(line)
            shade = QPainterPath(path)
            shade.lineTo(line[-1].x(), area.bottom()); shade.lineTo(line[0].x(), area.bottom()); shade.closeSubpath()
            gradient = QLinearGradient(0, area.top(), 0, area.bottom())
            top = QColor(self.color); top.setAlpha(45); bottom = QColor(self.color); bottom.setAlpha(0)
            gradient.setColorAt(0, top); gradient.setColorAt(1, bottom)
            painter.fillPath(shade, gradient)
            painter.setPen(QPen(QColor(self.color), 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            painter.drawPath(path)
        label_every = max(1, n // 8)
        for i, point, data in mapped:
            color = QColor(GOOD if data.get("won") else BAD if data.get("won") is False else MUTED)
            painter.setPen(QPen(QColor("#0f1014"), 2))
            painter.setBrush(color)
            painter.drawEllipse(point, 4.5, 4.5)
            self._hits.append((point, data.get("tip", "")))
            if i % label_every == 0 or i == n - 1:
                painter.setPen(QColor(SUBTLE))
                painter.drawText(QRectF(point.x() - 40, area.bottom() + 8, 80, 16), Qt.AlignmentFlag.AlignHCenter, data.get("label", ""))

    def mouseMoveEvent(self, event):  # noqa: N802
        pos = event.position()
        best = min(self._hits, key=lambda h: (h[0].x() - pos.x()) ** 2 + (h[0].y() - pos.y()) ** 2, default=None)
        if best and abs(best[0].x() - pos.x()) < 18 and best[1]:
            QToolTip.showText(event.globalPosition().toPoint(), best[1], self)
        else:
            QToolTip.hideText()


class ColumnChart(QWidget):
    """Columnas por mes: alto = partidas, color = porcentaje de victorias."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.items: list[dict] = []    # {"label", "value", "rate", "tip"}
        self._cells: list[tuple[QRectF, str]] = []
        self.setMinimumHeight(190)
        self.setMouseTracking(True)

    def set_items(self, items: list[dict]) -> None:
        self.items = items
        self.update()

    def paintEvent(self, _event):  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._cells = []
        area = QRectF(8, 10, self.width() - 16, self.height() - 34)
        if not self.items:
            painter.setPen(QColor(MUTED))
            painter.drawText(area, Qt.AlignmentFlag.AlignCenter, t("Sin datos todavía"))
            return
        top = max(i["value"] for i in self.items) or 1
        n = len(self.items)
        slot = area.width() / n
        width = min(34.0, slot * 0.7)
        painter.setFont(QFont("Segoe UI", 8))
        for index, item in enumerate(self.items):
            h = max(3.0, area.height() * item["value"] / top)
            rect = QRectF(area.left() + index * slot + (slot - width) / 2, area.bottom() - h, width, h)
            rate = item.get("rate")
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(score_color(rate * 100 if rate is not None else None)))
            painter.drawRoundedRect(rect, 4, 4)
            if n <= 16 or index % max(1, n // 12) == 0:
                painter.setPen(QColor(SUBTLE))
                painter.drawText(QRectF(rect.center().x() - 30, area.bottom() + 6, 60, 14), Qt.AlignmentFlag.AlignHCenter, item["label"])
            self._cells.append((rect.adjusted(-3, -area.height(), 3, 0), item.get("tip", "")))

    def mouseMoveEvent(self, event):  # noqa: N802
        for rect, tip in self._cells:
            if rect.contains(event.position()):
                QToolTip.showText(event.globalPosition().toPoint(), tip, self)
                return
        QToolTip.hideText()


class BarList(QWidget):
    """Barras horizontales con nombre, valor y una nota a la derecha."""

    ROW = 34

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows: list[dict] = []   # {"label", "value", "text", "note", "color"}
        self.empty = t("Sin datos todavía")
        self.scale: float | None = None

    def set_rows(self, rows: list[dict], scale: float | None = None) -> None:
        """scale fija el valor de la barra llena (por ejemplo 100 para porcentajes)."""
        self.rows = rows
        self.scale = scale
        self.setMinimumHeight(max(50, len(rows) * self.ROW + 6))
        self.updateGeometry()
        self.update()

    def paintEvent(self, _event):  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self.rows:
            painter.setPen(QColor(MUTED))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.empty)
            return
        top = self.scale or max((r["value"] for r in self.rows), default=1) or 1
        name_w, note_w = 130, 230
        bar_left = name_w + 10
        bar_w = max(40, self.width() - bar_left - note_w - 70)
        for index, row in enumerate(self.rows):
            y = 3 + index * self.ROW
            painter.setFont(QFont("Segoe UI", 10, QFont.Weight.DemiBold))
            painter.setPen(QColor(TEXT))
            painter.drawText(QRectF(0, y, name_w, 26), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, row["label"])
            track = QRectF(bar_left, y + 9, bar_w, 8)
            painter.setPen(Qt.PenStyle.NoPen); painter.setBrush(QColor("#25282f"))
            painter.drawRoundedRect(track, 4, 4)
            fill = QRectF(track.left(), track.top(), max(5, track.width() * min(1.0, row["value"] / top)), track.height())
            painter.setBrush(QColor(row.get("color", ACCENT)))
            painter.drawRoundedRect(fill, 4, 4)
            painter.setFont(QFont("Segoe UI Variable Display", 11, QFont.Weight.Bold))
            painter.setPen(QColor(TEXT))
            painter.drawText(QRectF(track.right() + 10, y, 64, 26), Qt.AlignmentFlag.AlignVCenter, row["text"])
            painter.setFont(QFont("Segoe UI", 9))
            painter.setPen(QColor(MUTED))
            painter.drawText(QRectF(self.width() - note_w, y, note_w, 26), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                             row.get("note", ""))


class SideCompare(QWidget):
    """CT contra T, métrica por métrica, con dos barras enfrentadas."""

    ROW = 40

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows: list[dict] = []   # {"label", "ct", "t", "ct_text", "t_text", "scale"}

    def set_rows(self, rows: list[dict]) -> None:
        self.rows = rows
        self.setMinimumHeight(34 + len(rows) * self.ROW)
        self.updateGeometry()
        self.update()

    def paintEvent(self, _event):  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()
        mid = w / 2
        painter.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        painter.setPen(QColor(CT_COLOR))
        painter.drawText(QRectF(0, 0, mid - 80, 22), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, t("CT"))
        painter.setPen(QColor(T_COLOR))
        painter.drawText(QRectF(mid + 80, 0, mid - 80, 22), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "T")
        half = mid - 90
        for index, row in enumerate(self.rows):
            y = 30 + index * self.ROW
            painter.setFont(QFont("Segoe UI", 9, QFont.Weight.DemiBold))
            painter.setPen(QColor(MUTED))
            painter.drawText(QRectF(mid - 80, y, 160, 24), Qt.AlignmentFlag.AlignCenter, row["label"])
            top = row.get("scale") or max(row["ct"] or 0, row["t"] or 0) or 1
            for side, value, text, color in (("ct", row["ct"], row["ct_text"], CT_COLOR), ("t", row["t"], row["t_text"], T_COLOR)):
                length = max(4, half * 0.78 * min(1.0, (value or 0) / top)) if value is not None else 0
                rect = QRectF(mid - 84 - length, y + 8, length, 8) if side == "ct" else QRectF(mid + 84, y + 8, length, 8)
                painter.setPen(Qt.PenStyle.NoPen); painter.setBrush(QColor(color))
                painter.drawRoundedRect(rect, 4, 4)
                painter.setFont(QFont("Segoe UI Variable Display", 11, QFont.Weight.Bold))
                painter.setPen(QColor(TEXT))
                if side == "ct":
                    painter.drawText(QRectF(rect.left() - 80, y, 74, 24), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, text)
                else:
                    painter.drawText(QRectF(rect.right() + 6, y, 80, 24), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, text)


class RoundStrip(QWidget):
    """Una ficha por ronda: verde si la ganó tu equipo, roja si no; puntos = tus kills; raya = lado."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rounds: list[dict] = []
        self._cells: list[tuple[QRectF, str]] = []
        self.setMouseTracking(True)
        self.setMinimumHeight(84)

    def set_rounds(self, rounds: list[dict]) -> None:
        self.rounds = rounds
        self.update()

    def paintEvent(self, _event):  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._cells = []
        n = len(self.rounds)
        if not n:
            return
        gaps = sum(1 for r in self.rounds if r["n"] in (13, 25, 31))
        cell = min(28.0, (self.width() - 5 * n - 14 * gaps) / n)
        x = 0.0
        painter.setFont(QFont("Segoe UI", 8))
        for r in self.rounds:
            if r["n"] in (13, 25, 31):
                x += 14
            rect = QRectF(x, 16, cell, 44)
            base = QColor(GOOD if r["won"] else BAD); base.setAlpha(45)
            painter.setPen(Qt.PenStyle.NoPen); painter.setBrush(base)
            painter.drawRoundedRect(rect, 5, 5)
            painter.setBrush(QColor(CT_COLOR if r["side"] == "CT" else T_COLOR))
            painter.drawRoundedRect(QRectF(rect.left() + 4, rect.top() + 4, rect.width() - 8, 3), 1.5, 1.5)
            painter.setBrush(QColor(TEXT))
            for k in range(min(r["kills"], 5)):
                painter.drawEllipse(QPointF(rect.center().x(), rect.top() + 13 + k * 6), 2.2, 2.2)
            if r["died"]:
                painter.setPen(QPen(QColor(BAD), 1.4))
                cx, cy = rect.center().x(), rect.bottom() - 7
                painter.drawLine(QPointF(cx - 3, cy - 3), QPointF(cx + 3, cy + 3))
                painter.drawLine(QPointF(cx - 3, cy + 3), QPointF(cx + 3, cy - 3))
            painter.setPen(QColor(SUBTLE))
            painter.drawText(QRectF(rect.left() - 4, rect.bottom() + 4, rect.width() + 8, 14), Qt.AlignmentFlag.AlignHCenter, str(r["n"]))
            buy = {"pistola": "pistola", "ahorro": "ahorro", "forzada": "forzada", "completa": t("compra completa")}.get(r["buy"], r["buy"])
            tip = (t('Ronda {0} · {1} · {2}\n{3} kills · {4:.0f} de daño · {5}\nEquipo: ${6:.0f} ({7})').format(r['n'], r['side'], t('ganada') if r['won'] else t('perdida'), r['kills'], r['damage'], t('moriste') if r['died'] else t('sobreviviste'), r['equip'], buy))
            if r.get("opening") == "kill":
                tip += t("\nGanaste el primer duelo")
            elif r.get("opening") == "death":
                tip += t("\nPerdiste el primer duelo")
            if r.get("clutch_vs"):
                tip += t("\nClutch 1 contra {0}: {1}").format(r['clutch_vs'], t("ganado") if r['clutch_won'] else t("perdido"))
            self._cells.append((rect, tip))
            x += cell + 5
        painter.setPen(QColor(SUBTLE))
        painter.drawText(QRectF(0, 0, 400, 14), Qt.AlignmentFlag.AlignLeft, t("Raya azul: CT · Raya naranja: T · Puntos: tus kills · Cruz: moriste"))

    def mouseMoveEvent(self, event):  # noqa: N802
        pos = event.position()
        for rect, tip in self._cells:
            if rect.adjusted(-3, -3, 3, 3).contains(pos):
                QToolTip.showText(event.globalPosition().toPoint(), tip, self)
                return
        QToolTip.hideText()

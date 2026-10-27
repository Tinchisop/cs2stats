"""Gráficos del detalle de partida: medidores de impacto, impacto ganado y perdido, impacto por ronda y repartos."""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QToolTip, QWidget

from ..i18n import t
from .theme import BAD, CT_COLOR, GOOD, MUTED, SUBTLE, T_COLOR, TEXT, fmt_num


def signed(value: float | None, decimals: int = 2) -> str:
    if value is None:
        return "—"
    return ("+" if value >= 0 else "") + fmt_num(value, decimals)


class Gauge(QWidget):
    """Medidor en arco: el valor de esta partida y una marca con tu promedio de las últimas partidas."""

    SPAN = 10.0  # el arco va de -10 a +10

    def __init__(self, title: str, value: float | None, average: float | None, color: str, parent=None):
        super().__init__(parent)
        self.title, self.value, self.average, self.color = title, value, average, color
        self.setFixedSize(200, 190)

    def _angle(self, value: float) -> float:
        share = (max(-self.SPAN, min(self.SPAN, value)) + self.SPAN) / (2 * self.SPAN)
        return 220 - share * 260  # de 220° (izquierda abajo) a -40° (derecha abajo)

    def paintEvent(self, _event):  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(20, 36, 160, 160)
        painter.setPen(QPen(QColor("#262a31"), 9, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawArc(rect, int(220 * 16), int(-260 * 16))
        if self.value is not None:
            painter.setPen(QPen(QColor(self.color), 9, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawArc(rect, int(220 * 16), int((self._angle(self.value) - 220) * 16))
        if self.average is not None:
            angle = math.radians(self._angle(self.average))
            center = rect.center()
            inner, outer = 66, 92
            painter.setPen(QPen(QColor(TEXT), 2))
            painter.drawLine(QPointF(center.x() + inner * math.cos(angle), center.y() - inner * math.sin(angle)),
                             QPointF(center.x() + outer * math.cos(angle), center.y() - outer * math.sin(angle)))
            painter.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
            painter.drawText(QRectF(0, 0, self.width(), 18), Qt.AlignmentFlag.AlignHCenter,
                             t("tu promedio {0}").format(signed(self.average)))
        painter.setPen(QColor(TEXT))
        painter.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        painter.drawText(QRectF(0, 88, self.width(), 16), Qt.AlignmentFlag.AlignHCenter, self.title.upper())
        painter.setPen(QColor(self.color if self.value is not None else SUBTLE))
        painter.setFont(QFont("Segoe UI Variable Display", 24, QFont.Weight.Bold))
        painter.drawText(QRectF(0, 104, self.width(), 40), Qt.AlignmentFlag.AlignHCenter, signed(self.value))


class DivergingBars(QWidget):
    """Barras horizontales que salen del cero: a la derecha lo que sumó, a la izquierda lo que restó."""

    ROW = 30

    def __init__(self, rows: list[tuple[str, float, str]], parent=None):
        super().__init__(parent)
        self.rows = rows  # (nombre, valor, explicación)
        self._hits: list[tuple[QRectF, str]] = []
        self.setMouseTracking(True)
        self.setMinimumHeight(self.ROW * len(rows) + 24)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def paintEvent(self, _event):  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._hits = []
        name_w, value_w = 170, 60
        left = name_w
        width = self.width() - name_w - value_w
        mid = left + width / 2
        top = max([abs(v) for _n, v, _h in self.rows] + [1.0])
        painter.setPen(QPen(QColor("#3a3e46"), 1))
        painter.drawLine(QPointF(mid, 4), QPointF(mid, self.ROW * len(self.rows) + 4))
        for index, (name, value, help_text) in enumerate(self.rows):
            y = 6 + index * self.ROW
            painter.setPen(QColor("#cfd3da"))
            painter.setFont(QFont("Segoe UI", 10))
            painter.drawText(QRectF(0, y, name_w - 12, self.ROW - 8), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, name)
            length = width / 2 * abs(value) / top
            bar = QRectF(mid, y + 3, length, self.ROW - 14) if value >= 0 else QRectF(mid - length, y + 3, length, self.ROW - 14)
            color = QColor(GOOD if value >= 0 else BAD)
            color.setAlpha(190)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            painter.drawRoundedRect(bar, 3, 3)
            painter.setPen(QColor(GOOD if value > 0 else BAD if value < 0 else MUTED))
            painter.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
            painter.drawText(QRectF(left + width + 8, y, value_w, self.ROW - 8), Qt.AlignmentFlag.AlignVCenter, signed(value, 1))
            self._hits.append((QRectF(0, y, self.width(), self.ROW), help_text))

    def mouseMoveEvent(self, event):  # noqa: N802
        for rect, tip in self._hits:
            if rect.contains(event.position()) and tip:
                QToolTip.showText(event.globalPosition().toPoint(), tip, self)
                return
        QToolTip.hideText()


class RoundImpact(QWidget):
    """Impacto de cada ronda: barra verde hacia arriba si sumaste, roja hacia abajo si restaste; raya = lado."""

    def __init__(self, rounds: list[dict], parent=None):
        super().__init__(parent)
        self.rounds = rounds  # {"n", "value", "side", "won"}
        self._cells: list[tuple[QRectF, str]] = []
        self.setMouseTracking(True)
        self.setMinimumHeight(260)

    def paintEvent(self, _event):  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._cells = []
        if not self.rounds:
            return
        axis_w, bottom = 44, 34
        height = self.height() - bottom - 10
        top = max([abs(r["value"]) for r in self.rounds] + [10.0])
        top = (int(top / 10) + 1) * 10
        zero = 10 + height / 2
        painter.setFont(QFont("Segoe UI", 8))
        for step in (-top, -top / 2, 0, top / 2, top):
            y = zero - step / top * height / 2
            painter.setPen(QPen(QColor("#22252b") if step else QColor("#3a3e46"), 1))
            painter.drawLine(QPointF(axis_w, y), QPointF(self.width(), y))
            painter.setPen(QColor(SUBTLE))
            painter.drawText(QRectF(0, y - 8, axis_w - 6, 16), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, signed(step, 0))
        slot = (self.width() - axis_w) / len(self.rounds)
        bar_w = max(6.0, min(34.0, slot * 0.62))
        for index, r in enumerate(self.rounds):
            x = axis_w + index * slot + (slot - bar_w) / 2
            length = abs(r["value"]) / top * height / 2
            rect = QRectF(x, zero - length, bar_w, length) if r["value"] >= 0 else QRectF(x, zero, bar_w, length)
            color = QColor(GOOD if r["value"] >= 0 else BAD)
            color.setAlpha(200)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            painter.drawRoundedRect(rect, 3, 3)
            painter.setBrush(QColor(CT_COLOR if r["side"] == "CT" else T_COLOR))
            painter.drawRoundedRect(QRectF(x, self.height() - bottom + 6, bar_w, 3), 1.5, 1.5)
            painter.setPen(QColor(SUBTLE))
            painter.drawText(QRectF(x - 6, self.height() - bottom + 12, bar_w + 12, 14), Qt.AlignmentFlag.AlignHCenter, str(r["n"]))
            tip = t("Ronda {0} · {1} · {2}\nImpacto {3}").format(r["n"], r["side"], t("ganada") if r["won"] else t("perdida"),
                                                                signed(r["value"], 1))
            self._cells.append((QRectF(axis_w + index * slot, 0, slot, self.height()), tip))

    def mouseMoveEvent(self, event):  # noqa: N802
        for rect, tip in self._cells:
            if rect.contains(event.position()):
                QToolTip.showText(event.globalPosition().toPoint(), tip, self)
                return
        QToolTip.hideText()


class ShareBar(QWidget):
    """Barra repartida en tramos (cuántas granadas de cada tipo tiró el equipo)."""

    def __init__(self, parts: list[tuple[str, int, str]], parent=None, text: bool = True):
        super().__init__(parent)
        self.parts = [p for p in parts if p[1] > 0]
        self.text = text
        self.setFixedHeight(40)

    def paintEvent(self, _event):  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        total = sum(p[1] for p in self.parts)
        if not total:
            return
        x, gap = 0.0, 4.0
        width = self.width() - gap * (len(self.parts) - 1)
        painter.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        for name, count, color in self.parts:
            w = width * count / total
            rect = QRectF(x, 0, w, self.height())
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(color))
            painter.drawRoundedRect(rect, 6, 6)
            painter.setPen(QColor("#0f1014"))
            if self.text and w > 70:
                painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, f"{name} · {round(count / total * 100)} %")
            elif self.text and w > 30:
                painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, f"{round(count / total * 100)}%")
            x += w + gap


class MarkerBar(QWidget):
    """Barra con tu valor y una marca con el promedio de tu equipo."""

    def __init__(self, share: float | None, marker: float | None, color: str, parent=None):
        super().__init__(parent)
        self.share, self.marker, self.color = share, marker, color
        self.setFixedHeight(14)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def paintEvent(self, _event):  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        track = QRectF(0, 4, self.width(), 6)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#262a31"))
        painter.drawRoundedRect(track, 3, 3)
        if self.share is not None:
            fill = QLinearGradient(track.topLeft(), track.topRight())
            dark = QColor(self.color)
            dark.setAlpha(90)
            fill.setColorAt(0, dark)
            fill.setColorAt(1, QColor(self.color))
            painter.setBrush(fill)
            painter.drawRoundedRect(QRectF(0, 4, max(6.0, track.width() * self.share), 6), 3, 3)
        if self.marker is not None:
            painter.setBrush(QColor(TEXT))
            painter.drawRect(QRectF(track.width() * self.marker - 1, 0, 2, 14))

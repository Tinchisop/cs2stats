"""Piezas compartidas por las pestañas del detalle de partida: filas de jugadores, celdas y avisos."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QFontMetrics
from PySide6.QtWidgets import QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel, QVBoxLayout

from ..assets import player_avatar
from ..i18n import t
from .theme import ACCENT, BAD, CT_COLOR, GOOD, MID, SUBTLE, T_COLOR, TEXT, icon, label, panel
from .visual import Avatar

NAME_WIDTH = 140


def tone_color(value, good: float, bad: float) -> str:
    """Verde, amarillo o rojo según dos cortes; si good < bad, menos es mejor."""
    if value is None:
        return SUBTLE
    if good > bad:
        return GOOD if value >= good else BAD if value < bad else MID
    return GOOD if value <= good else BAD if value > bad else MID


def cell(text: str, width: int, color: str = "#d5d8de", bold: bool = False, tip: str = "") -> QLabel:
    widget = QLabel(text)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    widget.setFixedWidth(width)
    widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
    widget.setStyleSheet(f"color: {color}; font-size: 14px; font-weight: {700 if bold else 500};")
    if tip:
        widget.setToolTip(tip)
    return widget


def divider() -> QFrame:
    line = QFrame()
    line.setFixedWidth(1)
    line.setStyleSheet("background: rgba(255,255,255,22);")
    return line


def player_face(p: dict, size: int) -> Avatar:
    """Foto de Steam del jugador con un aro del color de su equipo (rosa si sos vos); sin foto, su inicial."""
    color = CT_COLOR if p["ally"] else T_COLOR
    photo = True if p.get("me") else player_avatar(p["steamid"])
    return Avatar(p["name"], size, photo=photo, color=color, circle=True, ring=ACCENT if p.get("me") else color)


def glow(widget, color: str = ACCENT, blur: int = 28, strength: int = 110):
    """Brillo de color alrededor de una pieza (tarjetas destacadas, resultado, foto del mapa)."""
    effect = QGraphicsDropShadowEffect(widget)
    shade = QColor(color)
    shade.setAlpha(strength)
    effect.setColor(shade)
    effect.setBlurRadius(blur)
    effect.setOffset(0, 0)
    widget.setGraphicsEffect(effect)
    return widget


def header_row(titles: list[tuple[str, int, str]], first: str = "") -> QFrame:
    """Encabezado en dos bloques: azul para el jugador y naranja degradado para los números."""
    frame = QFrame()
    row = QHBoxLayout(frame)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(0)
    left = panel("tableHeadLeft")
    left_row = QHBoxLayout(left)
    left_row.setContentsMargins(15, 8, 8, 8)
    left_row.addWidget(label(first or t("Jugador"), "tableHeadText"))
    left_row.addStretch(1)
    row.addWidget(left, 1)
    right = panel("tableHeadRight")
    right_row = QHBoxLayout(right)
    right_row.setContentsMargins(0, 8, 10, 8)
    right_row.setSpacing(0)
    for text, width, tip in titles:
        widget = label(text, "tableHeadText")
        widget.setFixedWidth(width)
        widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if tip:
            widget.setToolTip(tip)
        right_row.addWidget(widget)
    right_row.addSpacing(22)
    row.addWidget(right)
    return frame


def player_row(p: dict, cells: list[QLabel], best: bool = False, crown: str = "") -> QFrame:
    """Fila de un jugador: borde azul tu equipo, naranja los rivales, rosa vos; corona con su explicación."""
    kind = "rowMe" if p.get("me") else "rowBest" if best else "rowAlly" if p["ally"] else "rowRival"
    frame = panel(kind)
    row = QHBoxLayout(frame)
    row.setContentsMargins(12, 6, 10, 6)
    row.setSpacing(0)
    row.addWidget(player_face(p, 34))
    row.addSpacing(10)
    name = QLabel(QFontMetrics(frame.font()).elidedText(p["name"], Qt.TextElideMode.ElideRight, NAME_WIDTH - 10))
    name.setTextFormat(Qt.TextFormat.PlainText)
    name.setToolTip(p["name"])
    name.setStyleSheet(f"color: {'#ff6b8f' if p.get('me') else TEXT}; font-size: 14px; font-weight: {700 if p.get('me') else 500};")
    row.addWidget(name)
    if p.get("me"):
        row.addSpacing(8)
        row.addWidget(label(t("TÚ"), "meChip"))
    row.addStretch(1)
    for widget in cells:
        row.addWidget(widget)
    if crown:
        crown_icon = QLabel()
        crown_icon.setPixmap(icon("crown", MID, 18).pixmap(QSize(18, 18)))
        crown_icon.setToolTip(crown)
        crown_icon.setFixedWidth(22)
        row.addWidget(crown_icon)
    else:
        row.addSpacing(22)
    return frame


def team_rows(layout: QVBoxLayout, players: list[dict], build) -> None:
    """Agrega tu equipo, el separador de rivales y el equipo rival, en ese orden."""
    for ally in (True, False):
        if not ally:
            layout.addWidget(label(t("RIVALES"), "tableSection"))
        for p in [p for p in players if p["ally"] == ally]:
            layout.addWidget(build(p))


def color_legend(layout: QVBoxLayout) -> None:
    legend = QHBoxLayout()
    legend.setSpacing(16)
    for text, color in ((t("Muy bien"), GOOD), (t("Normal"), MID), (t("Para mejorar"), BAD)):
        item = label(f"●  {text}", "smallMuted")
        item.setStyleSheet(f"color: {color};")
        legend.addWidget(item)
    legend.addStretch(1)
    layout.addSpacing(6)
    layout.addLayout(legend)


def missing_note(value) -> str:
    """Aviso para las partidas importadas antes de que la app midiera esto (None) o sin demo disponible ({})."""
    if value is None:
        return t("Esta partida se importó antes de que la app midiera esto. Tocá Buscar partidas y se completa sola "
                 "(si Valve todavía tiene la demo).")
    return t("La demo de esta partida ya no está disponible, así que no se pudo medir.")

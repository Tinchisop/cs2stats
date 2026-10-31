"""Repetición 2D de una partida: los 10 jugadores sobre el mapa, con barra de tiempo, granadas, bomba y kills.

ReplayScene sabe dibujar un instante de una ronda (en la pantalla o en un video); ReplayPlayer es el reproductor."""

from __future__ import annotations

import math
from pathlib import Path

from PySide6.QtCore import QElapsedTimer, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QButtonGroup, QFileDialog, QGridLayout, QHBoxLayout, QMessageBox, QProgressDialog, QPushButton,
                               QSizePolicy, QVBoxLayout, QWidget)

from ..assets import map_markers
from ..i18n import t
from ..metrics import map_label, weapon_label
from ..nades import GRID, TYPE_COLORS
from ..replay import CELL, FAILS
from .theme import ACCENT, BAD, BG, CT_COLOR, MUTED, T_COLOR, TEXT, button, icon, label

TEAM_COLORS = {"T": T_COLOR, "CT": CT_COLOR}
SMOKE_TIME, MOLOTOV_TIME, POP_TIME = 18.0, 7.0, 0.45
ROUND_TIME, BOMB_TIME = 115.0, 40.0
SPEEDS = (0.5, 1.0, 2.0, 4.0)


def clock(seconds: float) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 60}:{seconds % 60:02d}"


def moment_title(moment: dict) -> str:
    """Nombre de la jugada para mostrar: "As con AK-47", "Clutch 1v2", "Moriste sin disparar"."""
    kind = moment["kind"]
    if kind in ("ace", "4k", "3k"):
        name = {"ace": t("As"), "4k": "4K", "3k": "3K"}[kind]
        return t("{0} con {1}").format(name, weapon_label(moment.get("weapon") or ""))
    if kind == "clutch":
        return t("Clutch 1v{0} ganado").format(moment.get("vs") or 1)
    if kind == "no_shots":
        return t("Moriste sin disparar")
    if kind == "team_flash":
        return t("Tu flash cegó a {0} compañeros").format(moment.get("count") or 2)
    return kind


class ReplayScene:
    """Dibuja un instante de una ronda: mapa, granadas, bomba, disparos, jugadores, kills y reloj."""

    def __init__(self, data: dict, grid=None):
        self.data = data
        self.me = data.get("me", "")
        self.step = data.get("step", 8)
        self.rounds = data.get("rounds", [])
        self.players = data.get("players", {})
        self.cells = data.get("cells") or []
        self.grid = grid
        self.markers = map_markers(data.get("map", ""))
        self._base: QImage | None = None
        self._base_key = None
        xs = [c[0] * CELL for c in self.cells] + [c[0] * CELL + CELL for c in self.cells]
        ys = [c[1] * CELL for c in self.cells] + [c[1] * CELL + CELL for c in self.cells]
        if not xs:
            for rnd in self.rounds[:3]:
                for track in rnd["tracks"].values():
                    xs.extend(track[0::4])
                    ys.extend(track[1::4])
        xs, ys = xs or [0], ys or [0]
        pad = 160
        self.frame = (min(xs) - pad, min(ys) - pad, max(xs) + pad, max(ys) + pad)

    # Geometría
    def mapper(self, rect: QRectF):
        x0, y0, x1, y1 = self.frame
        scale = min(rect.width() / max(1, x1 - x0), rect.height() / max(1, y1 - y0))
        ox = rect.left() + (rect.width() - (x1 - x0) * scale) / 2
        oy = rect.top() + (rect.height() - (y1 - y0) * scale) / 2
        return scale, lambda x, y: QPointF(ox + (x - x0) * scale, oy + (y1 - y) * scale)   # la Y del juego crece hacia arriba

    def length(self, index: int) -> float:
        return self.rounds[index]["length"] if 0 <= index < len(self.rounds) else 0.0

    def position(self, track: list[int], at: float) -> tuple[float, float, float, int]:
        """Lugar, mira y vida en un instante, interpolando entre las dos muestras más cercanas."""
        count = len(track) // 4
        exact = max(0.0, min(count - 1, at * 64 / self.step))
        i = int(exact)
        j = min(i + 1, count - 1)
        share = exact - i
        x = track[i * 4] + (track[j * 4] - track[i * 4]) * share
        y = track[i * 4 + 1] + (track[j * 4 + 1] - track[i * 4 + 1]) * share
        turn = (track[j * 4 + 2] - track[i * 4 + 2] + 180) % 360 - 180
        health = track[j * 4 + 3] if share > 0.5 else track[i * 4 + 3]
        return x, y, track[i * 4 + 2] + turn * share, health

    # Dibujo
    def _paint_base(self, rect: QRectF) -> QImage:
        # El piso se pinta a media resolución y se agranda suave: así los bordes de las celdas no se ven escalonados.
        half = QImage(max(1, int(rect.width() / 2)), max(1, int(rect.height() / 2)), QImage.Format.Format_ARGB32_Premultiplied)
        half.fill(QColor("#0d1115"))
        painter = QPainter(half)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        scale, to_screen = self.mapper(QRectF(0, 0, half.width(), half.height()))
        painter.setPen(Qt.PenStyle.NoPen)
        layers = []
        if self.grid and self.grid.cells:
            layers.append(([(gx, gy, z) for (gx, gy), (z, _p, _n) in self.grid.cells.items()], GRID))
        if self.cells:
            layers.append((self.cells, CELL))
        zs = [c[2] for cells, _s in layers for c in cells] or [0]
        low, high = min(zs), max(max(zs), min(zs) + 1)
        for cells, size in layers:
            side = max(1.5, size * scale) + 0.7
            for gx, gy, z in cells:
                shade = int(34 + 40 * (z - low) / (high - low))
                painter.setBrush(QColor(shade, shade + 8, shade + 13))
                p = to_screen(gx * size, (gy + 1) * size)
                painter.drawRect(QRectF(p.x(), p.y(), side, side))
        painter.end()
        image = half.scaled(int(rect.width()), int(rect.height()), Qt.AspectRatioMode.IgnoreAspectRatio,
                            Qt.TransformationMode.SmoothTransformation)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        scale, to_screen = self.mapper(QRectF(0, 0, rect.width(), rect.height()))
        painter.setFont(QFont("Segoe UI Variable Display", max(14, int(30 * min(1.0, rect.width() / 700))), QFont.Weight.Black))
        for name, (x, y) in self.markers.items():
            p = to_screen(x, y)
            painter.setPen(QColor(255, 255, 255, 46 if name in ("A", "B") else 26))
            painter.drawText(QRectF(p.x() - 40, p.y() - 24, 80, 48), Qt.AlignmentFlag.AlignCenter, name)
        painter.end()
        return image

    def paint(self, painter: QPainter, rect: QRectF, index: int, at: float, names: bool = True) -> None:
        if not (0 <= index < len(self.rounds)):
            return
        rnd = self.rounds[index]
        key = (int(rect.width()), int(rect.height()))
        if self._base is None or self._base_key != key:
            self._base, self._base_key = self._paint_base(rect), key
        painter.drawImage(rect.topLeft(), self._base)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        scale, to_screen = self.mapper(rect)
        tracks, teams = rnd["tracks"], rnd["teams"]
        spots = {player: self.position(track, at) for player, track in tracks.items()}

        # Granadas: en el aire una estela; al caer, la nube, el fuego o el destello.
        for thrown, who, kind, x, y, lx, ly, flight in rnd["nades"]:
            if lx is None or at < thrown:
                continue
            color = QColor(TYPE_COLORS.get(kind, "#cccccc"))
            landed = thrown + (flight or 0)
            if at < landed:
                share = (at - thrown) / max(0.01, landed - thrown)
                start, end = to_screen(x, y), to_screen(x + (lx - x) * share, y + (ly - y) * share)
                pen = QPen(color, 1.4, Qt.PenStyle.DashLine)
                painter.setPen(pen)
                painter.drawLine(start, end)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(color)
                painter.drawEllipse(end, 3, 3)
                continue
            since = at - landed
            center = to_screen(lx, ly)
            if kind == "smoke" and since < SMOKE_TIME:
                fade = min(1.0, since / 0.8, (SMOKE_TIME - since) / 1.5)
                painter.setPen(QPen(QColor(220, 225, 232, int(150 * fade)), 1.2))
                painter.setBrush(QColor(190, 196, 205, int(120 * fade)))
                painter.drawEllipse(center, 144 * scale, 144 * scale)
            elif kind == "molotov" and since < MOLOTOV_TIME:
                fade = min(1.0, (MOLOTOV_TIME - since) / 1.0)
                fire = QColor(TYPE_COLORS["molotov"])
                fire.setAlpha(int(110 * fade))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(fire)
                painter.drawEllipse(center, 115 * scale, 115 * scale)
            elif kind in ("flash", "he") and since < POP_TIME:
                fade = 1 - since / POP_TIME
                pop = QColor("#ffffff" if kind == "flash" else TYPE_COLORS["he"])
                pop.setAlpha(int(200 * fade))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(pop)
                radius = (180 if kind == "flash" else 150) * scale * (0.5 + since / POP_TIME)
                painter.drawEllipse(center, radius, radius)

        # Bomba: plantada parpadea; al explotar o desactivarse se marca.
        planted = None
        for when, kind, x, y in rnd["bomb"]:
            if when > at:
                break
            planted = (when, kind, x, y)
        if planted:
            when, kind, x, y = planted
            center = to_screen(x, y)
            if kind == "plant":
                blink = 0.5 + 0.5 * math.sin(at * (6 + 8 * min(1.0, (at - when) / BOMB_TIME)))
                painter.setPen(QPen(QColor(255, 92, 92, int(120 + 120 * blink)), 2))
                painter.setBrush(QColor(255, 92, 92, int(60 + 80 * blink)))
                painter.drawRoundedRect(QRectF(center.x() - 6, center.y() - 5, 12, 10), 2, 2)
            elif kind == "explode" and at - when < 1.2:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(255, 120, 60, int(200 * (1 - (at - when) / 1.2))))
                radius = 500 * scale * (0.3 + (at - when))
                painter.drawEllipse(center, radius, radius)
            elif kind == "defuse":
                painter.setPen(QPen(QColor(CT_COLOR), 2))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawEllipse(center, 8, 8)

        # Disparos: un trazo corto en la dirección de la mira.
        for player, times in rnd["shots"].items():
            spot = spots.get(player)
            if not spot or not any(at - 0.09 <= when <= at for when in times):
                continue
            x, y, yaw, health = spot
            if health <= 0:
                continue
            start = to_screen(x, y)
            reach = 380 * scale
            end = QPointF(start.x() + reach * math.cos(math.radians(yaw)), start.y() - reach * math.sin(math.radians(yaw)))
            painter.setPen(QPen(QColor(255, 236, 170, 190), 1.3))
            painter.drawLine(start, end)

        blinded = {victim for when, _a, victim, length in rnd["blinds"] if when <= at <= when + length}
        killed_by: dict[str, tuple] = {}
        for when, killer, victim, weapon, head in rnd["kills"]:
            if when <= at:
                killed_by[victim] = (when, killer)

        # Jugadores: los muertos quedan como una cruz; vos con un aro turquesa.
        painter.setFont(QFont("Segoe UI", 8, QFont.Weight.DemiBold))
        order = sorted(spots, key=lambda p: (p == self.me, spots[p][3] > 0))
        for player in order:
            x, y, yaw, health = spots[player]
            team = teams.get(player, "")
            color = QColor(TEAM_COLORS.get(team, MUTED))
            center = to_screen(x, y)
            mine = player == self.me
            if health <= 0 or player in killed_by:
                dim = QColor(color)
                dim.setAlpha(120)
                painter.setPen(QPen(dim, 2.2))
                painter.drawLine(QPointF(center.x() - 4.5, center.y() - 4.5), QPointF(center.x() + 4.5, center.y() + 4.5))
                painter.drawLine(QPointF(center.x() - 4.5, center.y() + 4.5), QPointF(center.x() + 4.5, center.y() - 4.5))
                continue
            radius = 8.5 if mine else 7.0
            if player in blinded:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(255, 255, 255, 110))
                painter.drawEllipse(center, radius + 6, radius + 6)
            # Hacia dónde mira: una cuña delante del círculo.
            angle = math.radians(yaw)
            tip = QPointF(center.x() + (radius + 7) * math.cos(angle), center.y() - (radius + 7) * math.sin(angle))
            side_a = QPointF(center.x() + radius * math.cos(angle + 0.55), center.y() - radius * math.sin(angle + 0.55))
            side_b = QPointF(center.x() + radius * math.cos(angle - 0.55), center.y() - radius * math.sin(angle - 0.55))
            wedge = QPainterPath(tip)
            wedge.lineTo(side_a)
            wedge.lineTo(side_b)
            wedge.closeSubpath()
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color.lighter(130))
            painter.drawPath(wedge)
            painter.setPen(QPen(QColor(ACCENT) if mine else QColor(10, 12, 15), 2.4 if mine else 1.2))
            painter.setBrush(color)
            painter.drawEllipse(center, radius, radius)
            # Vida: arco alrededor del círculo.
            if health < 100:
                painter.setPen(QPen(QColor(255, 255, 255, 170), 1.6))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawArc(QRectF(center.x() - radius - 3, center.y() - radius - 3, 2 * radius + 6, 2 * radius + 6),
                                90 * 16, int(360 * 16 * max(0, health) / 100))
            if names:
                name = self.players.get(player, "")[:14]
                painter.setPen(QColor(TEXT if mine else "#c6ccd3"))
                painter.drawText(QRectF(center.x() - 60, center.y() - radius - 17, 120, 14), Qt.AlignmentFlag.AlignCenter, name)

        self._paint_hud(painter, rect, rnd, at, spots, killed_by)

    def _paint_hud(self, painter: QPainter, rect: QRectF, rnd: dict, at: float, spots: dict, killed_by: dict) -> None:
        teams = rnd["teams"]
        alive = {"T": 0, "CT": 0}
        for player, (_x, _y, _yaw, health) in spots.items():
            if health > 0 and player not in killed_by and teams.get(player) in alive:
                alive[teams[player]] += 1
        plant = next((when for when, kind, _x, _y in rnd["bomb"] if kind == "plant" and when <= at), None)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(8, 10, 13, 190))
        painter.drawRoundedRect(QRectF(rect.left() + 10, rect.top() + 10, 196, 50), 8, 8)
        painter.setFont(QFont("Segoe UI", 9, QFont.Weight.DemiBold))
        painter.setPen(QColor(MUTED))
        painter.drawText(QRectF(rect.left() + 20, rect.top() + 14, 120, 18), Qt.AlignmentFlag.AlignLeft,
                         t("Ronda {0}").format(rnd["n"]))
        painter.setFont(QFont("Segoe UI Variable Display", 15, QFont.Weight.Bold))
        if plant is not None and at <= rnd["end"]:
            painter.setPen(QColor(BAD))
            text = clock(BOMB_TIME - (at - plant))
        else:
            painter.setPen(QColor(TEXT))
            text = clock(ROUND_TIME - min(at, rnd["end"]))
        painter.drawText(QRectF(rect.left() + 20, rect.top() + 30, 80, 26), Qt.AlignmentFlag.AlignLeft, text)
        painter.setFont(QFont("Segoe UI Variable Display", 13, QFont.Weight.Bold))
        for offset, side in ((100, "T"), (150, "CT")):
            painter.setPen(QColor(TEAM_COLORS[side]))
            painter.drawText(QRectF(rect.left() + offset, rect.top() + 28, 46, 26), Qt.AlignmentFlag.AlignCenter,
                             f"{alive[side]}")
            painter.setFont(QFont("Segoe UI", 7, QFont.Weight.DemiBold))
            painter.drawText(QRectF(rect.left() + offset, rect.top() + 14, 46, 14), Qt.AlignmentFlag.AlignCenter, side)
            painter.setFont(QFont("Segoe UI Variable Display", 13, QFont.Weight.Bold))
        if at > rnd["end"]:
            painter.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
            winner = rnd.get("winner", "")
            painter.setPen(QColor(TEAM_COLORS.get(winner, TEXT)))
            painter.drawText(QRectF(rect.left() + 10, rect.top() + 64, 196, 18), Qt.AlignmentFlag.AlignCenter,
                             t("Ganan los {0}").format(winner))

        # Kills de los últimos segundos, arriba a la derecha.
        feed = [k for k in rnd["kills"] if at - 6 <= k[0] <= at][-5:]
        painter.setFont(QFont("Segoe UI", 8, QFont.Weight.DemiBold))
        width = 270
        for row, (_when, killer, victim, weapon, head) in enumerate(feed):
            box = QRectF(rect.right() - width - 10, rect.top() + 10 + row * 24, width, 21)
            mine = self.me in (killer, victim)
            painter.setPen(QPen(QColor(BAD if victim == self.me else ACCENT), 1.2) if mine else Qt.PenStyle.NoPen)
            painter.setBrush(QColor(8, 10, 13, 200))
            painter.drawRoundedRect(box, 5, 5)
            middle = weapon_label(weapon) + (" ◎" if head else "")
            painter.setPen(QColor(TEAM_COLORS.get(teams.get(killer), MUTED)))
            painter.drawText(box.adjusted(8, 0, -width * 0.62, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                             self.players.get(killer, t("Mundo"))[:12])
            painter.setPen(QColor("#d5d8de"))
            painter.drawText(box.adjusted(width * 0.38, 0, -width * 0.38, 0), Qt.AlignmentFlag.AlignCenter, middle)
            painter.setPen(QColor(TEAM_COLORS.get(teams.get(victim), MUTED)))
            painter.drawText(box.adjusted(width * 0.62, 0, -8, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                             self.players.get(victim, "")[:12])


class ReplayCanvas(QWidget):
    def __init__(self, scene: ReplayScene, parent=None):
        super().__init__(parent)
        self.scene = scene
        self.index = 0
        self.at = 0.0
        self.setMinimumHeight(520)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def show_moment(self, index: int, at: float) -> None:
        self.index, self.at = index, at
        self.update()

    def paintEvent(self, _event):  # noqa: N802
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#0d1115"))
        self.scene.paint(painter, QRectF(self.rect()), self.index, self.at)


class Timeline(QWidget):
    """Barra de tiempo de la ronda: se toca o se arrastra para saltar. Marca las kills (turquesa las tuyas, rojo tu muerte)."""

    seeked = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.length = 1.0
        self.at = 0.0
        self.marks: list[tuple[float, str]] = []
        self.span: tuple[float, float] | None = None
        self.setFixedHeight(30)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_round(self, length: float, marks: list[tuple[float, str]], span=None) -> None:
        self.length, self.marks, self.span = max(0.1, length), marks, span
        self.update()

    def set_time(self, at: float) -> None:
        self.at = at
        self.update()

    def _seek(self, x: float) -> None:
        share = max(0.0, min(1.0, (x - 6) / max(1, self.width() - 12)))
        self.seeked.emit(share * self.length)

    def mousePressEvent(self, event):  # noqa: N802
        self._seek(event.position().x())

    def mouseMoveEvent(self, event):  # noqa: N802
        if event.buttons() & Qt.MouseButton.LeftButton:
            self._seek(event.position().x())

    def paintEvent(self, _event):  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        left, width = 6, self.width() - 12
        y = self.height() / 2

        def x_of(when: float) -> float:
            return left + width * max(0.0, min(1.0, when / self.length))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255, 22))
        painter.drawRoundedRect(QRectF(left, y - 3, width, 6), 3, 3)
        if self.span:
            painter.setBrush(QColor(34, 211, 166, 40))
            painter.drawRoundedRect(QRectF(x_of(self.span[0]), y - 7, x_of(self.span[1]) - x_of(self.span[0]), 14), 4, 4)
        painter.setBrush(QColor(ACCENT))
        painter.drawRoundedRect(QRectF(left, y - 3, x_of(self.at) - left, 6), 3, 3)
        for when, color in self.marks:
            painter.setBrush(QColor(color))
            painter.drawEllipse(QPointF(x_of(when), y - 10), 2.6, 2.6)
        painter.setBrush(QColor(TEXT))
        painter.setPen(QPen(QColor(ACCENT), 2))
        painter.drawEllipse(QPointF(x_of(self.at), y), 6.5, 6.5)


class ReplayPlayer(QWidget):
    """Reproductor: rondas, mapa, play/pausa, velocidad y barra de tiempo.

    Con `clip` (una jugada: ronda, desde, hasta) muestra solo ese tramo, en bucle."""

    open_in_game = Signal(int, float)   # ronda y segundo

    def __init__(self, data: dict, grid=None, clip: dict | None = None, title: str = "", parent=None):
        super().__init__(parent)
        self.scene = ReplayScene(data, grid)
        self.data = data
        self.clip = clip
        self.title = title
        self.speed = 1.0
        self.index = 0
        self.at = 0.0
        self.playing = False
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.round_buttons: list[QPushButton] = []
        if not clip:
            # Rondas en filas de hasta 24 (los alargues no estiran la página) y tus jugadas de a 4 por fila.
            strip = QGridLayout()
            strip.setHorizontalSpacing(3)
            strip.setVerticalSpacing(4)
            group = QButtonGroup(self)
            for index, rnd in enumerate(self.scene.rounds):
                seg = QPushButton(str(rnd["n"]))
                seg.setObjectName("segment")
                seg.setCheckable(True)
                seg.setFixedSize(30, 26)
                seg.setCursor(Qt.CursorShape.PointingHandCursor)
                won = rnd.get("winner") == rnd["teams"].get(self.scene.me)
                seg.setToolTip(t("Ronda {0}: ganaron los {1}").format(rnd["n"], rnd.get("winner", "")))
                seg.setStyleSheet(f"QPushButton {{ color: {TEAM_COLORS.get(rnd.get('winner'), MUTED)}; padding: 0;"
                                  f" border-bottom: 2px solid {'#3fcf8e' if won else '#ff5c5c'}; }}")
                seg.clicked.connect(lambda _=False, i=index: self.go_round(i))
                group.addButton(seg)
                strip.addWidget(seg, index // 24, index % 24)
                self.round_buttons.append(seg)
            strip.setColumnStretch(24, 1)
            layout.addLayout(strip)
            moments = data.get("moments") or []
            if moments:
                layout.addWidget(label(t("Tus jugadas en esta partida:"), "smallMuted"))
                row = QGridLayout()
                row.setSpacing(6)
                for position, moment in enumerate(moments[:12]):
                    chip_button = QPushButton(t("R{0} · {1}").format(moment["round"], moment_title(moment)))
                    chip_button.setObjectName("ghostButton")
                    chip_button.setCursor(Qt.CursorShape.PointingHandCursor)
                    if moment["kind"] in FAILS:
                        chip_button.setStyleSheet("QPushButton { color: #ff8a8a; }")
                    chip_button.clicked.connect(lambda _=False, m=moment: self.jump(m))
                    row.addWidget(chip_button, position // 4, position % 4)
                for col in range(4):
                    row.setColumnStretch(col, 1)
                layout.addLayout(row)
        self.canvas = ReplayCanvas(self.scene)
        layout.addWidget(self.canvas, 1)
        controls = QHBoxLayout()
        controls.setSpacing(8)
        self.play_button = QPushButton()
        self.play_button.setObjectName("roundButton")
        self.play_button.setFixedSize(36, 36)
        self.play_button.setStyleSheet("border-radius: 18px;")
        self.play_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.play_button.clicked.connect(self.toggle)
        controls.addWidget(self.play_button)
        self.timeline = Timeline()
        self.timeline.seeked.connect(self.seek)
        controls.addWidget(self.timeline, 1)
        self.time_label = label("0:00", "smallMuted")
        self.time_label.setMinimumWidth(80)
        controls.addWidget(self.time_label)
        speeds = QButtonGroup(self)
        for value in SPEEDS:
            seg = QPushButton(f"{value:g}×")
            seg.setObjectName("segment")
            seg.setCheckable(True)
            seg.setChecked(value == 1.0)
            seg.setCursor(Qt.CursorShape.PointingHandCursor)
            seg.clicked.connect(lambda _=False, v=value: setattr(self, "speed", v))
            speeds.addButton(seg)
            controls.addWidget(seg)
        save = button(t("Guardar clip") if clip else t("Guardar ronda"), "film")
        save.setToolTip(t("Guarda este tramo como video MP4 o GIF, sin abrir el juego"))
        save.clicked.connect(self.save)
        controls.addWidget(save)
        in_game = button(t("Abrir en CS2"), "external")
        in_game.setToolTip(t("Abre la demo real en CS2, en este momento de la ronda y con la cámara en tu jugador"))
        in_game.clicked.connect(self._open_in_game)
        controls.addWidget(in_game)
        layout.addLayout(controls)
        layout.addWidget(label(t("Espacio: play o pausa · ← →: 5 segundos · turquesa: tus kills · rojo: tu muerte"),
                               "smallMuted", wrap=True))
        self.timer = QTimer(self)
        self.timer.setInterval(33)
        self.timer.timeout.connect(self._tick)
        self.clock = QElapsedTimer()
        if clip:
            self.go_round(clip["round"] - 1, clip["from"])
            self.play()
        else:
            self.go_round(0)

    # Control
    def bounds(self) -> tuple[float, float]:
        if self.clip:
            return self.clip["from"], self.clip["to"]
        return 0.0, self.scene.length(self.index)

    def go_round(self, index: int, at: float | None = None) -> None:
        if not (0 <= index < len(self.scene.rounds)):
            return
        self.index = index
        if self.round_buttons:
            self.round_buttons[index].setChecked(True)
        rnd = self.scene.rounds[index]
        me = self.scene.me
        marks = []
        for when, killer, victim, _weapon, _head in rnd["kills"]:
            marks.append((when, BAD if victim == me else ACCENT if killer == me else "#6b7480"))
        low, high = self.bounds()
        self.timeline.set_round(self.scene.length(index), marks, (low, high) if self.clip else None)
        self.seek(low if at is None else at)

    def jump(self, moment: dict) -> None:
        self.go_round(moment["round"] - 1, moment["from"])
        self.play()

    def seek(self, at: float) -> None:
        low, high = self.bounds()
        self.at = max(0.0, min(self.scene.length(self.index), at))
        if self.clip:
            self.at = max(low, min(high, self.at))
        self.canvas.show_moment(self.index, self.at)
        self.timeline.set_time(self.at)
        self.time_label.setText(f"{clock(self.at)} / {clock(self.scene.length(self.index))}")

    def play(self) -> None:
        low, high = self.bounds()
        if self.at >= high - 0.05:
            self.seek(low)
        self.playing = True
        self.clock.start()
        self.timer.start()
        self.play_button.setIcon(icon("pause", TEXT, 16))

    def pause(self) -> None:
        self.playing = False
        self.timer.stop()
        self.play_button.setIcon(icon("play", TEXT, 16))

    def toggle(self) -> None:
        self.pause() if self.playing else self.play()

    def _tick(self) -> None:
        step = self.clock.restart() / 1000 * self.speed
        low, high = self.bounds()
        at = self.at + min(step, 0.5)
        if at >= high:
            if self.clip:
                at = low   # los clips se repiten en bucle
            elif self.index + 1 < len(self.scene.rounds):
                self.go_round(self.index + 1)
                return
            else:
                self.seek(high)
                self.pause()
                return
        self.seek(at)

    def keyPressEvent(self, event):  # noqa: N802
        if event.key() == Qt.Key.Key_Space:
            self.toggle()
        elif event.key() == Qt.Key.Key_Right:
            self.seek(self.at + 5)
        elif event.key() == Qt.Key.Key_Left:
            self.seek(self.at - 5)
        else:
            super().keyPressEvent(event)

    def hideEvent(self, event):  # noqa: N802
        self.pause()
        super().hideEvent(event)

    def save(self) -> None:
        self.pause()
        low, high = self.bounds()
        save_clip(self, self.scene, self.index, low, high, self.title)

    def _open_in_game(self) -> None:
        self.pause()
        self.open_in_game.emit(self.scene.rounds[self.index]["n"], self.bounds()[0] if self.clip else self.at)


def save_clip(parent: QWidget, scene: ReplayScene, index: int, start: float, end: float, title: str = "") -> None:
    """Pregunta dónde guardar y graba el tramo como MP4 o GIF, con una barra de progreso."""
    rnd = scene.rounds[index]
    name = map_label(scene.data.get("map", ""))
    base = f"{name}_R{rnd['n']}_{int(start)}s".replace(" ", "_")
    path, _kind = QFileDialog.getSaveFileName(parent, t("Guardar clip"), base + ".mp4",
                                              t("Video MP4 (*.mp4);;GIF animado (*.gif)"))
    if not path:
        return
    progress = QProgressDialog(t("Armando el clip"), t("Cancelar"), 0, 100, parent)
    progress.setWindowModality(Qt.WindowModality.WindowModal)
    progress.setMinimumDuration(200)
    try:
        done = export_clip(scene, index, start, end, path, title or name,
                           lambda share: (progress.setValue(int(share * 100)), not progress.wasCanceled())[1])
    except (OSError, RuntimeError, ValueError) as error:
        progress.close()
        QMessageBox.warning(parent, t("CS2 Stats"), t("No se pudo guardar el clip: {0}").format(error))
        return
    progress.close()
    if done:
        QMessageBox.information(parent, t("CS2 Stats"), t("Clip guardado en {0}").format(path))


def export_clip(scene: ReplayScene, index: int, start: float, end: float, path: str, title: str = "",
                progress=None) -> bool:
    """Graba un tramo de la repetición como MP4 (30 cuadros por segundo) o GIF (10). Devuelve False si se canceló."""
    import cv2
    import numpy as np
    gif = path.lower().endswith(".gif")
    width = height = 420 if gif else 960
    fps = 10 if gif else 30
    count = max(1, int((end - start) * fps) + 1)
    writer = None
    frames = []
    cancelled = False
    if not gif:
        writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height))
        if not writer.isOpened():
            raise OSError(t("no se pudo crear el video"))
    image = QImage(width, height, QImage.Format.Format_RGB888)
    try:
        for frame in range(count):
            at = start + frame / fps
            image.fill(QColor(BG))
            painter = QPainter(image)
            scene.paint(painter, QRectF(0, 0, width, height), index, at, names=True)
            if title:
                painter.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
                painter.setPen(QColor(ACCENT))
                painter.drawText(QRectF(0, height - 28, width - 12, 22), Qt.AlignmentFlag.AlignRight, f"CS2 Stats · {title}")
            painter.end()
            line = image.bytesPerLine()
            pixels = np.frombuffer(image.constBits(), np.uint8).reshape(height, line)[:, :width * 3].reshape(height, width, 3)
            bgr = np.ascontiguousarray(pixels[..., ::-1])
            if gif:
                frames.append(bgr)
            else:
                writer.write(bgr)
            if progress and not progress((frame + 1) / count):
                cancelled = True
                return False
    finally:
        if writer is not None:
            writer.release()
        if cancelled:
            Path(path).unlink(missing_ok=True)
    if gif:
        animation = cv2.Animation()
        animation.frames = frames
        animation.durations = [round(1000 / fps)] * len(frames)
        animation.loop_count = 0
        if not cv2.imwriteanimation(path, animation):
            raise OSError(t("no se pudo crear el GIF"))
    return True


class ReplayTab(QWidget):
    """Pestaña del detalle de partida. La repetición se abre recién cuando se mira la pestaña (son datos pesados)."""

    build_requested = Signal()
    open_in_game = Signal(int, float)   # ronda y segundo

    def __init__(self, match: dict, loader, grid=None, parent=None):
        super().__init__(parent)
        self.match, self.loader, self.grid = match, loader, grid
        self.loaded = False
        self.player: ReplayPlayer | None = None
        self.layout_ = QVBoxLayout(self)
        self.layout_.setContentsMargins(0, 0, 0, 0)
        self.layout_.setSpacing(10)

    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        if not self.loaded:
            self.reload()

    def set_busy(self, text: str) -> None:
        if hasattr(self, "status"):
            self.status.setText(text)

    def reload(self) -> None:
        from .pages import card, clear
        clear(self.layout_)
        self.loaded = True
        data, status = self.loader(self.match["match_key"])
        if data:
            box, layout = card(t("Repetición 2D"), t("Los 10 jugadores ronda por ronda"))
            self.player = ReplayPlayer(data, self.grid, title=map_label(self.match["map"]))
            self.player.open_in_game.connect(self.open_in_game)
            layout.addWidget(self.player)
            self.layout_.addWidget(box)
            # Se arma recién al mostrarse: la página que la contiene tiene que volver a medir su alto.
            self.setMinimumHeight(box.sizeHint().height())
            self.updateGeometry()
            return
        box, layout = card(t("Repetición 2D"))
        if status == "sin_demo":
            text = t("La demo de esta partida ya no está en la PC ni en los servidores de Valve, así que no se puede armar "
                     "la repetición.")
        else:
            text = t("Esta partida se importó antes de que la app guardara las posiciones. Si la demo sigue disponible, "
                     "la app la vuelve a leer y arma la repetición (puede bajar unos 100 MB).")
        layout.addWidget(label(text, "muted", wrap=True))
        self.status = label("", "smallMuted", wrap=True)
        if status != "sin_demo":
            action = button(t("Armar la repetición"), "film", primary=True)
            action.clicked.connect(self.build_requested.emit)
            action.clicked.connect(lambda: self.set_busy(t("Buscando la demo")))
            layout.addWidget(action, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self.status)
        self.layout_.addWidget(box)

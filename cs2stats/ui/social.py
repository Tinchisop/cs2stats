"""Páginas de amigos (cara a cara con los que más jugás) y de logros y metas (medallas, metas propias y pronóstico)."""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QComboBox, QDoubleSpinBox, QFrame, QGridLayout, QHBoxLayout, QPushButton,
                               QSizePolicy, QVBoxLayout, QWidget)

from ..assets import player_avatar
from ..friends import FACE_OFF, friends, score
from ..i18n import t
from ..metrics import map_label
from ..progress import GOAL_KINDS, achievements, goal_progress, goal_value, premier_forecast
from .charts import TrendChart
from .hud import TierProgress
from .motion import CountUp, Growing, Hovering, hover_glow, stagger
from .pages import Page, card, chip, empty_state, short_date
from .theme import (ACCENT, BAD, CT_COLOR, GOOD, MID, MUTED, SUBTLE, TEXT, button, fmt_metric, fmt_num, fmt_pct, icon,
                    label, panel, score_color)
from .visual import Avatar

TIER_COLORS = {"bronce": "#d08a4e", "plata": "#c9d3da", "oro": "#f2c14e"}


class FaceOff(Growing, Hovering, QWidget):
    """Cara a cara métrica por métrica: vos a la izquierda, tu amigo a la derecha; el que gana se ilumina."""

    ROW = 38
    grow_ms = 1100

    def __init__(self, friend: dict, parent=None):
        super().__init__(parent)
        self.friend = friend
        self.rows = [(title, kind, higher, friend["mine"].get(key), friend["theirs"].get(key))
                     for key, title, kind, higher in FACE_OFF]
        self.setMinimumHeight(10 + len(self.rows) * self.ROW)
        self.setMouseTracking(True)
        self.init_hover()

    def mouseMoveEvent(self, event):  # noqa: N802
        index = int((event.position().y() - 5) // self.ROW)
        self.set_hover(index if 0 <= index < len(self.rows) else None)

    def leaveEvent(self, event):  # noqa: N802
        self.set_hover(None)
        super().leaveEvent(event)

    def paintEvent(self, _event):  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()
        mid = w / 2
        half = mid - 110
        for index, (title, kind, higher, mine, theirs) in enumerate(self.rows):
            y = 5 + index * self.ROW
            hover = self.hover.get(index, 0.0)
            if hover:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(255, 255, 255, int(12 * hover)))
                painter.drawRoundedRect(QRectF(0, y - 3, w, self.ROW - 2), 8, 8)
            painter.setFont(QFont("Segoe UI", 9, QFont.Weight.DemiBold))
            painter.setPen(QColor("#b9c3ca"))
            painter.drawText(QRectF(mid - 100, y, 200, 26), Qt.AlignmentFlag.AlignCenter, title)
            top = max(abs(mine or 0), abs(theirs or 0)) or 1
            win_mine = mine is not None and theirs is not None and mine != theirs and (mine > theirs) == higher
            win_theirs = mine is not None and theirs is not None and mine != theirs and not win_mine
            grow = stagger(self.grow, index, len(self.rows))
            for side, value, winner, color in (("me", mine, win_mine, ACCENT), ("them", theirs, win_theirs, CT_COLOR)):
                length = max(4.0, half * 0.8 * min(1.0, abs(value or 0) / top)) * grow if value is not None else 0
                rect = (QRectF(mid - 104 - length, y + 9, length, 8) if side == "me" else QRectF(mid + 104, y + 9, length, 8))
                shade = QColor(color if winner else "#3a434b")
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(shade)
                painter.drawRoundedRect(rect, 4, 4)
                painter.setFont(QFont("Segoe UI Variable Display", 11, QFont.Weight.Bold if winner else QFont.Weight.Normal))
                painter.setPen(QColor(TEXT if winner else MUTED))
                text = fmt_metric(value, kind)
                if side == "me":
                    painter.drawText(QRectF(rect.left() - 76, y, 70, 26), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, text)
                else:
                    painter.drawText(QRectF(rect.right() + 6, y, 70, 26), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, text)


class FriendsPage(Page):
    """Los compañeros con los que más jugaste y el cara a cara con cada uno en las mismas partidas."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.view = None
        self.selected = None

    def update_view(self, view: dict) -> None:
        self.view = view
        self.rebuild()
        body = self.body
        found = friends(view["all_matches"])
        if not found:
            body.addWidget(empty_state(t("Cuando juegues al menos 2 partidas con demo con el mismo compañero, lo vas a ver acá "
                                         "con el cara a cara."), t("Conectar Steam"), "conectar", self.go_to.emit))
            body.addStretch(1)
            return
        if self.selected not in {str(f["steamid"]) for f in found}:
            self.selected = str(found[0]["steamid"])
        body.addWidget(label(t("Compañeros con los que jugaste 2 o más partidas con demo. Elegí uno para compararte."),
                             "pageLead", wrap=True))
        chips = QGridLayout()
        chips.setSpacing(10)
        for index, friend in enumerate(found[:8]):
            chips.addWidget(self._chip(friend), index // 4, index % 4)
        for col in range(4):
            chips.setColumnStretch(col, 1)
        body.addLayout(chips)
        friend = next(f for f in found if str(f["steamid"]) == self.selected)
        body.addWidget(self._duel(friend, view))
        box, layout = card(t("Partidas juntos"), t("Clic para ver el detalle"))
        for m in reversed(friend["matches"][-10:]):
            layout.addWidget(self._match_row(m, friend))
        body.addWidget(box)
        body.addStretch(1)

    def _chip(self, friend: dict) -> QWidget:
        on = str(friend["steamid"]) == self.selected
        frame = QPushButton()
        frame.setObjectName("friendChipOn" if on else "friendChip")
        frame.setCursor(Qt.CursorShape.PointingHandCursor)
        frame.setFixedHeight(54)
        frame.setStyleSheet(f"QPushButton {{ background: {'rgba(34,211,166,30)' if on else 'rgba(255,255,255,6)'};"
                            f"border: 1px solid {ACCENT if on else 'rgba(255,255,255,18)'}; border-radius: 12px; }}"
                            "QPushButton:hover { border-color: #22d3a6; }")
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(8, 6, 14, 6)
        layout.setSpacing(8)
        layout.addWidget(Avatar(friend["name"], 38, photo=player_avatar(friend["steamid"]), color=CT_COLOR, circle=True,
                                ring=ACCENT if on else ""))
        text = QVBoxLayout()
        text.setSpacing(0)
        name = label(friend["name"], "body")
        name.setStyleSheet("font-weight: 700;")
        name.setMinimumWidth(40)
        name.setToolTip(friend["name"])
        text.addWidget(name)
        text.addWidget(label(t("{0} partidas juntos").format(friend["games"]), "smallMuted"))
        layout.addLayout(text, 1)
        frame.setMinimumWidth(150)
        frame.clicked.connect(lambda: self._pick(str(friend["steamid"])))
        return hover_glow(frame, ACCENT, 26, 90)

    def _pick(self, steamid: str) -> None:
        self.selected = steamid
        if self.view:
            self.update_view(self.view)

    def _duel(self, friend: dict, view: dict) -> QFrame:
        box, layout = card(t("Cara a cara"), t("Solo las partidas que jugaron juntos"))
        top = QHBoxLayout()
        name = view["name"] or t("Vos")
        me_col = QVBoxLayout()
        me_col.setSpacing(4)
        me_col.addWidget(Avatar(name, 64, circle=True, ring=ACCENT), 0, Qt.AlignmentFlag.AlignHCenter)
        me_col.addWidget(label(name, "insightTitle"), 0, Qt.AlignmentFlag.AlignHCenter)
        top.addLayout(me_col, 1)
        mine, theirs = score(friend)
        center = QVBoxLayout()
        center.setSpacing(2)
        tally = QHBoxLayout()
        tally.setSpacing(14)
        left = CountUp(mine, lambda v: fmt_num(v, 0), "heroValue")
        left.setStyleSheet(f"color: {ACCENT if mine >= theirs else MUTED}; font-size: 40px;")
        right = CountUp(theirs, lambda v: fmt_num(v, 0), "heroValue")
        right.setStyleSheet(f"color: {CT_COLOR if theirs >= mine else MUTED}; font-size: 40px;")
        tally.addStretch(1)
        tally.addWidget(left)
        tally.addWidget(label("—", "bigValue"))
        tally.addWidget(right)
        tally.addStretch(1)
        center.addLayout(tally)
        verdict = (t("Le ganás en más números") if mine > theirs else t("Te gana en más números") if theirs > mine
                   else t("Empatados"))
        note = label(verdict, "smallMuted")
        note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        center.addWidget(note)
        together = label(t("Juntos: {0} de victorias ({1} de {2})").format(fmt_pct(friend["win_rate"]), friend["wins"],
                                                                            friend["games"]), "body")
        together.setAlignment(Qt.AlignmentFlag.AlignCenter)
        together.setStyleSheet(f"color: {score_color(friend['win_rate'] * 100)}; font-weight: 700;")
        center.addWidget(together)
        top.addLayout(center, 2)
        them_col = QVBoxLayout()
        them_col.setSpacing(4)
        them_col.addWidget(Avatar(friend["name"], 64, photo=player_avatar(friend["steamid"]), color=CT_COLOR, circle=True,
                                  ring=CT_COLOR), 0, Qt.AlignmentFlag.AlignHCenter)
        them_col.addWidget(label(friend["name"], "insightTitle"), 0, Qt.AlignmentFlag.AlignHCenter)
        top.addLayout(them_col, 1)
        layout.addLayout(top)
        layout.addWidget(FaceOff(friend))
        return box

    def _match_row(self, m: dict, friend: dict) -> QWidget:
        row = QPushButton()
        row.setObjectName("ghostButton")
        row.setCursor(Qt.CursorShape.PointingHandCursor)
        row.setFixedHeight(40)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(12, 0, 12, 0)
        color = GOOD if m["result"] == "W" else BAD if m["result"] == "L" else MID
        layout.addWidget(label(short_date(m["played_at"]), "smallMuted"))
        layout.addSpacing(12)
        name = label(map_label(m["map"]), "body")
        name.setStyleSheet("font-weight: 700;")
        layout.addWidget(name)
        layout.addStretch(1)
        mine = next((p for p in m["scoreboard"] if p.get("me")), {})
        theirs = next((p for p in m["scoreboard"] if str(p["steamid"]) == str(friend["steamid"])), {})
        layout.addWidget(label(t("Vos {0} · {1} {2}").format(fmt_num(mine.get("rating"), 2), friend["name"],
                                                              fmt_num(theirs.get("rating"), 2)), "smallMuted"))
        layout.addSpacing(16)
        score_label = label(f"{m['score_us']} : {m['score_them']}", "body")
        score_label.setStyleSheet(f"color: {color}; font-weight: 800;")
        layout.addWidget(score_label)
        row.clicked.connect(lambda: self.open_match.emit(m["id"]))
        return row


class Medal(Growing, QWidget):
    """Medalla pintada: aro de progreso que se llena; si está ganada, metal con un brillo que la cruza."""

    grow_ms = 1200

    def __init__(self, kind: str, tier: str, share: float, unlocked: bool, parent=None):
        super().__init__(parent)
        self.kind, self.color, self.share, self.unlocked = kind, QColor(TIER_COLORS[tier]), share, unlocked
        self.shine = 0.0
        self.setFixedSize(76, 76)
        if unlocked:
            self.sweep = QVariantAnimation(self)
            self.sweep.setStartValue(0.0)
            self.sweep.setEndValue(1.0)
            self.sweep.setDuration(3200)
            self.sweep.setLoopCount(-1)
            self.sweep.valueChanged.connect(self._sweep)

    def _sweep(self, value: float) -> None:
        self.shine = value
        self.update()

    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        if self.unlocked:
            self.sweep.start()

    def hideEvent(self, event):  # noqa: N802
        if self.unlocked:
            self.sweep.stop()
        super().hideEvent(event)

    def paintEvent(self, _event):  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = QPointF(38, 38)
        ring = QRectF(5, 5, 66, 66)
        painter.setPen(QPen(QColor(255, 255, 255, 20), 5))
        painter.drawEllipse(ring)
        if self.share > 0:
            painter.setPen(QPen(self.color if self.unlocked else QColor(ACCENT), 5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawArc(ring, 90 * 16, -int(360 * 16 * self.share * self.grow))
        # Cara de la medalla: hexágono de metal (o gris si falta).
        face = QPainterPath()
        for index in range(7):
            angle = math.radians(-90 + index * 60)
            point = QPointF(c.x() + 24 * math.cos(angle), c.y() + 24 * math.sin(angle))
            face.moveTo(point) if index == 0 else face.lineTo(point)
        metal = QLinearGradient(0, 14, 0, 62)
        if self.unlocked:
            metal.setColorAt(0, self.color.lighter(135))
            metal.setColorAt(0.5, self.color)
            metal.setColorAt(1, self.color.darker(170))
        else:
            metal.setColorAt(0, QColor("#3a434b"))
            metal.setColorAt(1, QColor("#20262c"))
        painter.setPen(QPen(QColor(255, 255, 255, 70 if self.unlocked else 25), 1.2))
        painter.setBrush(metal)
        painter.drawPath(face)
        if self.unlocked:
            painter.save()
            painter.setClipPath(face)
            x = -30 + 140 * self.shine
            shine = QLinearGradient(x - 14, 0, x + 14, 30)
            shine.setColorAt(0, QColor(255, 255, 255, 0))
            shine.setColorAt(0.5, QColor(255, 255, 255, 120))
            shine.setColorAt(1, QColor(255, 255, 255, 0))
            painter.fillRect(self.rect(), shine)
            painter.restore()
        glyph = icon(self.kind, "#1b1406" if self.unlocked else SUBTLE, 24).pixmap(QSize(24, 24))
        painter.drawPixmap(QPointF(c.x() - 12, c.y() - 12), glyph)


class AchievementsPage(Page):
    """Metas propias, pronóstico de Premier y medallas."""

    goals_changed = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.goals: list[dict] = []
        self.view = None

    def set_goals(self, goals: list[dict]) -> None:
        self.goals = list(goals)

    def update_view(self, view: dict) -> None:
        self.view = view
        self.rebuild()
        body = self.body
        body.addWidget(self._goals(view))
        forecast_box = self._forecast(view)
        if forecast_box:
            body.addWidget(forecast_box)
        medals = achievements(view["all_matches"], view["all_history"])
        won = sum(1 for a in medals if a.unlocked)
        box, layout = card(t("Medallas"), t("{0} de {1} ganadas").format(won, len(medals)))
        grid = QGridLayout()
        grid.setSpacing(12)
        ordered = sorted(medals, key=lambda a: (not a.unlocked, -a.share))
        for index, item in enumerate(ordered):
            grid.addWidget(self._medal(item), index // 4, index % 4)
        for col in range(4):
            grid.setColumnStretch(col, 1)
        layout.addLayout(grid)
        body.addWidget(box)
        body.addStretch(1)

    def _medal(self, item) -> QFrame:
        frame = panel("medalOn" if item.unlocked else "medal")
        hover_glow(frame, TIER_COLORS[item.tier] if item.unlocked else ACCENT, 30, 120)
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(10, 10, 12, 10)
        layout.setSpacing(10)
        layout.addWidget(Medal(item.icon, item.tier, item.share, item.unlocked))
        text = QVBoxLayout()
        text.setSpacing(2)
        title = label(item.title, "insightTitle", wrap=True)
        if item.unlocked:
            title.setStyleSheet(f"color: {TIER_COLORS[item.tier]};")
        text.addWidget(title)
        text.addWidget(label(item.detail, "smallMuted", wrap=True))
        decimals = 2 if isinstance(item.goal, float) else 0
        status = (t("¡Ganada!") if item.unlocked
                  else f"{fmt_num(min(item.value, item.goal), decimals)} / {fmt_num(item.goal, decimals)}")
        text.addWidget(label(status, "smallMuted"))
        text.addStretch(1)
        layout.addLayout(text, 1)
        return frame

    def _goals(self, view: dict) -> QFrame:
        box, layout = card(t("Tus metas"), t("Las de números usan tus últimas 10 partidas con demo"))
        recent = view["recent_total"]
        if not self.goals:
            layout.addWidget(label(t("Todavía no tenés metas. Ponete una abajo, por ejemplo llegar a 10.000 de Premier."),
                                   "muted", wrap=True))
        for index, goal in enumerate(self.goals):
            current = goal_value(goal["kind"], view["all_matches"], recent)
            share = goal_progress(goal, current)
            row = panel("challengeDone" if share >= 1 else "challenge")
            col = QVBoxLayout(row)
            col.setContentsMargins(14, 10, 12, 12)
            col.setSpacing(6)
            top = QHBoxLayout()
            kind = self._kind(goal["kind"])
            top.addWidget(label(t("{0}: llegar a {1}").format(GOAL_KINDS[goal["kind"]], fmt_metric(goal["target"], kind)), "body"))
            top.addStretch(1)
            now = label(t("Ahora: {0}").format(fmt_metric(current, kind)), "smallMuted")
            top.addWidget(now)
            top.addWidget(chip(t("¡Cumplida!") if share >= 1 else fmt_pct(share), "chipGood" if share >= 1 else "chip"))
            remove = QPushButton()
            remove.setObjectName("roundButton")
            remove.setFixedSize(26, 26)
            remove.setStyleSheet("border-radius: 13px;")
            remove.setIcon(icon("stop", MUTED, 10))
            remove.setToolTip(t("Borrar meta"))
            remove.setCursor(Qt.CursorShape.PointingHandCursor)
            remove.clicked.connect(lambda _=False, i=index: self._remove(i))
            top.addWidget(remove)
            col.addLayout(top)
            col.addWidget(TierProgress(share, GOOD if share >= 1 else CT_COLOR))
            layout.addWidget(row)
        form = QHBoxLayout()
        form.setSpacing(8)
        form.addWidget(label(t("Nueva meta"), "smallMuted"))
        self.kind_box = QComboBox()
        for key, title in GOAL_KINDS.items():
            self.kind_box.addItem(title, key)
        self.kind_box.currentIndexChanged.connect(self._suggest)
        form.addWidget(self.kind_box)
        self.target_box = QDoubleSpinBox()
        self.target_box.setMinimumWidth(110)
        form.addWidget(self.target_box)
        add = button(t("Agregar meta"), "flag", primary=True)
        add.clicked.connect(self._add)
        form.addWidget(add)
        form.addStretch(1)
        layout.addLayout(form)
        self._suggest()
        return box

    @staticmethod
    def _kind(goal_kind: str) -> str:
        return {"premier": "num0", "rating": "num2", "kd": "num2", "adr": "num1"}.get(goal_kind, "pct")

    def _suggest(self) -> None:
        """Propone un objetivo un poco arriba de donde estás."""
        if not self.view:
            return
        kind = self.kind_box.currentData()
        current = goal_value(kind, self.view["all_matches"], self.view["recent_total"])
        pct = self._kind(kind) == "pct"
        box = self.target_box
        box.setSuffix(" %" if pct else "")
        if kind == "premier":
            box.setDecimals(0)
            box.setRange(1000, 40000)
            box.setSingleStep(500)
            box.setValue(round(((current or 5000) + 1000) / 500) * 500)
        elif pct:
            box.setDecimals(0)
            box.setRange(1, 100)
            box.setSingleStep(1)
            box.setValue(min(100, round((current or 0.4) * 100 + 5)))
        else:
            decimals = 1 if kind == "adr" else 2
            box.setDecimals(decimals)
            box.setRange(0.1, 300)
            box.setSingleStep(0.05 if decimals == 2 else 1)
            box.setValue(round((current or 1) * 1.1, decimals))

    def _add(self) -> None:
        kind = self.kind_box.currentData()
        target = self.target_box.value() / (100 if self._kind(kind) == "pct" else 1)
        current = goal_value(kind, self.view["all_matches"], self.view["recent_total"]) if self.view else None
        self.goals.append({"kind": kind, "target": target, "start": current})
        self.goals_changed.emit(self.goals)

    def _remove(self, index: int) -> None:
        if 0 <= index < len(self.goals):
            self.goals.pop(index)
            self.goals_changed.emit(self.goals)

    def _forecast(self, view: dict) -> QFrame | None:
        forecast = premier_forecast(view["all_matches"])
        if not forecast:
            return None
        box, layout = card(t("Pronóstico de Premier"), t("Si seguís como en tus últimas {0} partidas").format(forecast.games))
        row = QHBoxLayout()
        row.setSpacing(24)
        for title, value, color in ((t("AHORA"), forecast.current, TEXT),
                                    (t("EN 10 PARTIDAS"), forecast.expected, GOOD if forecast.per_match >= 0 else BAD),
                                    (t("RANGO PROBABLE"), None, MUTED)):
            col = QVBoxLayout()
            col.setSpacing(0)
            col.addWidget(label(title, "cardTitle"))
            if value is None:
                text = label(f"{fmt_num(forecast.low, 0)} – {fmt_num(forecast.high, 0)}", "bigValue")
            else:
                text = CountUp(value, lambda v: fmt_num(v, 0), "heroValue")
            text.setStyleSheet(f"color: {color};")
            col.addWidget(text)
            row.addLayout(col)
        per = label(t("{0} pts por partida en promedio").format(f"{forecast.per_match:+.0f}"), "body")
        per.setStyleSheet(f"color: {GOOD if forecast.per_match >= 0 else BAD}; font-weight: 700;")
        row.addStretch(1)
        row.addWidget(per, 0, Qt.AlignmentFlag.AlignBottom)
        layout.addLayout(row)
        premier = [m for m in view["all_matches"] if m.get("rank_type") == 11 and m.get("rank_new")][-20:]
        chart = TrendChart()
        chart.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        chart.setFixedHeight(230)
        chart.set_data([{"value": m["rank_new"], "label": short_date(m["played_at"])[:5], "won": m["result"] == "W",
                         "tip": f"{map_label(m['map'])} · {fmt_num(m['rank_new'], 0)} ({(m['rank_change'] or 0):+.0f})"}
                        for m in premier], decimals=0, color=CT_COLOR, forecast=forecast.points,
                       band=(forecast.low, forecast.high))
        layout.addWidget(chart)
        layout.addWidget(label(t("Es una estimación con tu promedio reciente: cambia con cada partida."), "smallMuted"))
        return box


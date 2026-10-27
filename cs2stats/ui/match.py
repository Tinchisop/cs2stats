"""Detalle de una partida: cabecera y pestañas (tu partida, resumen, tabla, puntería, utilidad, cara a cara, impacto)."""

from __future__ import annotations

import random

from PySide6.QtCore import QPointF, QSize, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen, QPixmap, QRadialGradient
from PySide6.QtWidgets import QButtonGroup, QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ..assets import map_image
from ..i18n import t
from ..metrics import SOURCE_NAMES, aim_summary, map_label
from .charts import RoundStrip
from .match_parts import cell, color_legend, divider, glow, header_row, missing_note, player_row, team_rows, tone_color
from .match_tabs import DuelsTab, ImpactTab, overview_tab, page, utility_tab, your_match_tab
from .pages import card, result_text, scroll_page, short_date
from .theme import (ACCENT, BAD, BG, CT_COLOR, GOOD, MID, MUTED, T_COLOR, fmt_num, fmt_pct, icon, label, panel,
                    rating_color)
from .visual import Avatar, MapThumb, MapTitle, PremierBadge

BOARD = [("Premier", 86), ("K", 32), ("D", 32), ("A", 32), ("+/-", 40), ("ADR", 42), ("KAST", 50), ("HS %", 48),
         ("1er duelo", 60), ("Rating", 54)]


def _pct(value) -> str:
    return fmt_pct(value)


def _ms(value) -> str:
    return f"{fmt_num(value, 0)} ms" if value is not None else "—"


def _deg(value) -> str:
    return f"{fmt_num(value, 2)}°" if value is not None else "—"


# Clave, título de la columna, explicación, formato, bueno desde, malo desde (el orden dice si más es mejor).
AIM = [
    ("seen_accuracy", t("Precisión\na la vista"), t("Balas que pegaron, contando solo las que tiraste con un rival a la vista."), _pct, 0.32, 0.22),
    ("time_to_damage", t("Tiempo\nal daño"), t("Cuánto tardaste en pegarle a un rival desde que apareció. Menos es mejor."), _ms, 450, 650),
    ("crosshair", t("Ubicación\nde la mira"), t("Cuántos grados tenías que mover la mira hasta la cabeza del rival cuando apareció. "
                                              "Menos es mejor."), _deg, 5.0, 8.0),
    ("head_accuracy", t("Precisión\ncabeza"), t("De las balas que pegaron, cuántas fueron a la cabeza."), _pct, 0.25, 0.14),
    ("hs_kills", t("Kills\ncon HS"), t("Kills con tiro a la cabeza."), _pct, 0.50, 0.30),
    ("first_bullet", t("Primera\nbala"), t("Primeras balas de cada ráfaga que pegaron, con un rival a la vista."), _pct, 0.30, 0.18),
    ("spray_accuracy", t("Precisión\nráfaga"), t("Balas de ráfaga (después de la primera) que pegaron, con un rival a la vista."), _pct, 0.30, 0.18),
    ("counter_strafe", t("Counter-\nstrafe"), t("Primeros disparos que hiciste quieto o frenando bien, cuando el arma ya es precisa."),
     _pct, 0.85, 0.65),
    ("accuracy", t("Precisión\ntotal"), t("Todas las balas que pegaron sobre todas las que disparaste."), _pct, 0.24, 0.16),
]
AIM_WIDTH = 84
TABS = [("you", t("Tu partida")), ("overview", t("Resumen")), ("board", t("Tabla")), ("aim", t("Puntería")),
        ("utility", t("Utilidad")), ("duels", t("Cara a cara")), ("impact", t("Impacto"))]


def stat_tile(title: str, value: str, kind: str, tone: str) -> QFrame:
    color = {"good": CT_COLOR, "bad": BAD, "util": T_COLOR}.get(tone, MUTED)
    frame = panel({"good": "tileGood", "bad": "tileBad", "util": "tileUtil"}.get(tone, "tile"))
    row = QHBoxLayout(frame)
    row.setContentsMargins(12, 10, 10, 10)
    text = QVBoxLayout()
    text.setSpacing(2)
    text.addWidget(label(title.upper(), "cardTitle"))
    text.addWidget(label(value, "midValue", wrap=True))
    row.addLayout(text, 1)
    picture = QLabel()
    picture.setPixmap(icon(kind, color, 30).pixmap(QSize(30, 30)))
    row.addWidget(picture, 0, Qt.AlignmentFlag.AlignVCenter)
    return frame


class MatchDialog(QDialog):
    def __init__(self, m: dict, parent=None, history: list[dict] | None = None):
        super().__init__(parent)
        self.setObjectName("matchDialog")
        self.setWindowTitle(f"{map_label(m['map'])} · {short_date(m['played_at'])}")
        self.resize(1340, 940)
        path = map_image(m["map"])
        self.backdrop_image = QPixmap(str(path)) if path else QPixmap()
        self.backdrop: QPixmap | None = None
        self.seed = int(m.get("id") or 0)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        area, body = scroll_page()
        body.setContentsMargins(24, 20, 24, 24)
        area.viewport().setAutoFillBackground(False)
        outer.addWidget(area)
        self.area = area
        s = m["s"]
        players = m["scoreboard"]
        ratings = [p.get("rating") or 0 for p in players]
        self.best = players[ratings.index(max(ratings))]["steamid"] if players else None

        body.addLayout(self._header(m, s))
        bar = QHBoxLayout()
        bar.setSpacing(4)
        group = QButtonGroup(self)
        self.pages: dict[str, QWidget] = {}
        self.buttons: dict[str, QPushButton] = {}
        holder = QVBoxLayout()
        builders = {"you": lambda: your_match_tab(m, history or []), "overview": lambda: overview_tab(m),
                    "board": lambda: self._board_tab(m, s, players), "aim": lambda: self._aim_tab(m, players),
                    "utility": lambda: utility_tab(m), "duels": lambda: DuelsTab(m), "impact": lambda: ImpactTab(m, history or [])}
        for key, title in TABS:
            button = QPushButton(title)
            button.setObjectName("tabButton")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _=False, k=key: self.show_tab(k))
            group.addButton(button)
            bar.addWidget(button)
            self.buttons[key] = button
            self.pages[key] = builders[key]()
            holder.addWidget(self.pages[key])
        bar.addStretch(1)
        body.addLayout(bar)
        body.addLayout(holder)
        body.addStretch(1)
        # Las tarjetas principales de cada pestaña llevan un brillo suave.
        for widget in self.pages.values():
            for frame in widget.findChildren(QFrame, options=Qt.FindChildOption.FindDirectChildrenOnly):
                if frame.objectName() in ("card", "identityCard", "rowMe"):
                    glow(frame, ACCENT, 30, 60)
        self.show_tab("you")

    def show_tab(self, key: str) -> None:
        for name, widget in self.pages.items():
            widget.setVisible(name == key)
            self.buttons[name].setChecked(name == key)
            if name == key:
                glow(self.buttons[name], ACCENT, 22, 150)
            else:
                self.buttons[name].setGraphicsEffect(None)
        self.area.verticalScrollBar().setValue(0)

    def resizeEvent(self, event):  # noqa: N802
        self.backdrop = None
        super().resizeEvent(event)

    def paintEvent(self, _event):  # noqa: N802
        if self.backdrop is None or self.backdrop.size() != self.size():
            self.backdrop = self._paint_backdrop()
        painter = QPainter(self)
        painter.drawPixmap(0, 0, self.backdrop)

    def _paint_backdrop(self) -> QPixmap:
        """Fondo: la foto del mapa muy difuminada y oscura, con brasas naranjas como en el menú del juego."""
        w, h = max(1, self.width()), max(1, self.height())
        canvas = QPixmap(w, h)
        canvas.fill(QColor(BG))
        painter = QPainter(canvas)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        if not self.backdrop_image.isNull():
            # El mapa de la partida ocupa toda la ventana, apenas desenfocado (achicar y agrandar con suavizado)
            # para que se reconozca sin competir con los números.
            soft = self.backdrop_image.scaledToWidth(360, Qt.TransformationMode.SmoothTransformation)
            cover = soft.scaled(w, h, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
            painter.setOpacity(0.85)
            painter.drawPixmap(int((w - cover.width()) / 2), int((h - cover.height()) / 3), cover)
            painter.setOpacity(1)
        fade = QLinearGradient(0, 0, 0, h)
        fade.setColorAt(0, QColor(12, 14, 18, 105))
        fade.setColorAt(0.4, QColor(12, 14, 18, 150))
        fade.setColorAt(0.85, QColor(14, 13, 15, 205))
        fade.setColorAt(1, QColor(22, 12, 9, 235))
        painter.fillRect(0, 0, w, h, fade)
        sides = QLinearGradient(0, 0, w, 0)
        sides.setColorAt(0, QColor(10, 11, 14, 150))
        sides.setColorAt(0.18, QColor(10, 11, 14, 0))
        sides.setColorAt(0.82, QColor(10, 11, 14, 0))
        sides.setColorAt(1, QColor(10, 11, 14, 150))
        painter.fillRect(0, 0, w, h, sides)
        glow_bottom = QRadialGradient(QPointF(w * 0.5, h * 1.05), w * 0.6)
        glow_bottom.setColorAt(0, QColor(255, 110, 40, 46))
        glow_bottom.setColorAt(1, QColor(255, 110, 40, 0))
        painter.fillRect(0, 0, w, h, glow_bottom)
        rng = random.Random(self.seed)
        painter.setPen(Qt.PenStyle.NoPen)
        for _ in range(48):
            # Cada brasa: un halo difuso y un punto brillante con una estela corta hacia arriba.
            x = rng.random() * w
            y = h * (0.4 + 0.6 * rng.random() ** 0.7)
            size = 1.2 + rng.random() * 2.4
            heat = QColor(255, int(110 + rng.random() * 100), 40)
            halo = QRadialGradient(QPointF(x, y), size * 5)
            heat.setAlpha(int(40 + rng.random() * 60))
            halo.setColorAt(0, heat)
            heat.setAlpha(0)
            halo.setColorAt(1, heat)
            painter.setBrush(halo)
            painter.drawEllipse(QPointF(x, y), size * 5, size * 5)
            heat.setAlpha(int(130 + rng.random() * 120))
            painter.setPen(QPen(heat, size * 0.7, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            tail = 2 + rng.random() * 6
            painter.drawLine(QPointF(x, y), QPointF(x - tail * 0.35, y + tail))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(heat)
            painter.drawEllipse(QPointF(x, y), size * 0.6, size * 0.6)
        painter.end()
        return canvas

    def showEvent(self, event):  # noqa: N802
        # La página no tiene barra horizontal: la ventana no se deja achicar más que su contenido (ya con el estilo puesto).
        super().showEvent(event)
        widest = max(widget.minimumSizeHint().width() for widget in self.pages.values())
        self.setMinimumWidth(max(widest + 48, self.area.widget().minimumSizeHint().width()) + 16)

    def _header(self, m: dict, s: dict) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(20)
        left = QVBoxLayout()
        left.setSpacing(2)
        left.addWidget(MapTitle(map_label(m["map"]).upper()))
        info = QHBoxLayout()
        info.setSpacing(8)
        if m.get("rank_type") == 11 and m.get("rank_new"):
            # En Premier se muestra el rating con la placa del juego en vez del texto.
            info.addWidget(PremierBadge(m["rank_new"], 26))
            info.addWidget(label(short_date(m["played_at"]), "muted"))
        else:
            info.addWidget(label(f"{SOURCE_NAMES.get(m['source'], m['source'])} · {short_date(m['played_at'])}", "muted"))
        info.addStretch(1)
        left.addLayout(info)
        text, color = result_text(m["result"], m["score_us"], m["score_them"])
        result = QHBoxLayout()
        result.setSpacing(14)
        word = {"W": t("VICTORIA"), "L": t("DERROTA")}.get(m["result"], t("EMPATE"))
        chip_label = label(word, {"W": "resultWin", "L": "resultLoss"}.get(m["result"], "resultTie"))
        result.addWidget(glow(chip_label, {"W": GOOD, "L": BAD}.get(m["result"], MID), 26, 200))
        score = label(text, "matchScore")
        score.setStyleSheet(f"color: {color};")
        result.addWidget(score)
        result.addStretch(1)
        left.addSpacing(8)
        left.addLayout(result)
        row.addLayout(left)
        row.addWidget(glow(MapThumb(m["map"]), T_COLOR, 30, 120), 0, Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(self._player_card(m, s), 1)
        return row

    def _player_card(self, m: dict, s: dict) -> QFrame:
        box = panel("playerCard")
        row = QHBoxLayout(box)
        row.setContentsMargins(18, 14, 20, 14)
        row.setSpacing(14)
        me = next((p for p in m["scoreboard"] if p.get("me")), {})
        name = m.get("my_name") or me.get("name") or ""
        row.addWidget(Avatar(name, 66, circle=True, ring=ACCENT))
        who = QVBoxLayout()
        who.setSpacing(0)
        who.addWidget(label(name, "cardPlayer"))
        who.addWidget(label(t("RATING"), "cardTitle"))
        rating = label(fmt_num(s["rating"], 2), "bigValue")
        rating.setStyleSheet(f"color: {rating_color(s['rating'])};")
        who.addWidget(rating)
        row.addLayout(who)
        row.addWidget(divider())

        def titled(title: str, color: str = CT_COLOR, extra: QWidget | None = None) -> QVBoxLayout:
            """Título chico con una rayita de color abajo, como en el HUD."""
            col = QVBoxLayout()
            col.setSpacing(3)
            head = QHBoxLayout()
            head.setSpacing(6)
            head.addWidget(label(title, "cardTitle"))
            if extra:
                head.addWidget(extra)
            head.addStretch(1)
            col.addLayout(head)
            line = QFrame()
            line.setFixedSize(34, 2)
            line.setStyleSheet(f"background: {color}; border-radius: 1px;")
            col.addWidget(line)
            return col
        for index, (title, value) in enumerate((("K / D / A", f"{s['kills']} / {s['deaths']} / {s['assists']}"),
                                               (t("ADR"), fmt_num(s["adr"], 0)), (t("KAST"), fmt_pct(s["kast"])),
                                               (t("HS %"), fmt_pct(s["hs"])))):
            col = titled(title)
            col.addWidget(label(value, "bigValue"))
            row.addLayout(col)
            if index == 0:
                row.addWidget(divider())
        row.addStretch(1)
        if m.get("rank_type") == 11 and m.get("rank_new"):
            row.addWidget(divider())
            change = m.get("rank_change") or 0
            arrow = QLabel()
            arrow.setPixmap(icon("up" if change >= 0 else "down", GOOD if change >= 0 else BAD, 18).pixmap(QSize(18, 18)))
            col = titled(t("PREMIER"), GOOD if change >= 0 else BAD, arrow)
            value = QHBoxLayout()
            value.setSpacing(8)
            value.addWidget(PremierBadge(m["rank_new"], 34))
            delta = QLabel(f"{change:+.0f}")
            delta.setStyleSheet(f"color: {GOOD if change >= 0 else BAD}; font-family: 'Segoe UI Variable Display';"
                                "font-size: 18px; font-weight: 800;")
            value.addWidget(delta)
            col.addLayout(value)
            row.addLayout(col)
        return box

    def _board_tab(self, m: dict, s: dict, players: list[dict]) -> QWidget:
        widget, outer = page()
        columns = QHBoxLayout()
        columns.setSpacing(16)
        left = QVBoxLayout()
        left.setSpacing(16)
        rounds_box, layout = card(t("Ronda por ronda"), t("Pasá el mouse por una ronda"))
        strip = RoundStrip()
        strip.set_rounds(m["rounds"])
        layout.addWidget(strip)
        left.addWidget(rounds_box)
        left.addWidget(self._stats(s))
        left.addStretch(1)
        columns.addLayout(left, 4)
        right = QVBoxLayout()
        right.addWidget(self._board(players))
        right.addStretch(1)
        columns.addLayout(right, 7)
        outer.addLayout(columns)
        return widget

    def _stats(self, s: dict) -> QFrame:
        box, layout = card(t("Estadísticas de partida"))
        grid = QGridLayout()
        grid.setSpacing(10)
        first_rate = s["first_team_deaths"] / s["rounds"] if s["rounds"] else 0
        tiles = [
            (t("Primeros duelos"), t("{0} ganados, {1} perdidos").format(s["opening_kills"], s["opening_deaths"]), "duel",
             "good" if s["opening_kills"] >= s["opening_deaths"] and s["opening_kills"] else "bad" if s["opening_deaths"] else ""),
            (t("Clutches"), t("{0} de {1}").format(s["clutches_won"], s["clutches"]), "shield", "good" if s["clutches_won"] else ""),
            (t("Muertes vengadas"), t("{0} de {1}").format(s["tradeable_deaths"] - s["untraded_deaths"], s["tradeable_deaths"]),
             "target", ""),
            (t("Moriste primero"), t("{0} de {1} rondas").format(s["first_team_deaths"], s["rounds"]), "skull",
             "bad" if first_rate > 0.2 else ""),
            (t("Utilidad"), t("{0} flashes, {1} humos, {2} molotovs, {3} HE").format(s["flashes"], s["smokes"], s["molotovs"], s["hes"]),
             "grenade", "util"),
            (t("Flashes efectivas"), t("{0} enemigos, {1} compañeros").format(s["enemies_flashed"], s["team_flashed"]), "flash", "util"),
            (t("Daño de granadas"), fmt_num(s["util_damage"], 0), "burst", "util"),
            (t("Kills de cambio"), str(s["trade_kills"]), "swap", "util"),
        ]
        for index, (title, value, kind, tone) in enumerate(tiles):
            grid.addWidget(stat_tile(title, value, kind, tone), index // 2, index % 2)
        layout.addLayout(grid)
        return box

    def _board(self, players: list[dict]) -> QFrame:
        box, layout = card(t("Tabla de la partida"), t("Rating, ADR y KAST calculados de la demo para los 10 jugadores"))
        layout.setSpacing(4)
        layout.addWidget(header_row([(t(title), width, "") for title, width in BOARD]))

        def build(p: dict) -> QFrame:
            st = p.get("stats") or {}
            diff = p["kills"] - p["deaths"]
            premier = QWidget()
            premier.setFixedWidth(BOARD[0][1])
            premier_row = QHBoxLayout(premier)
            premier_row.setContentsMargins(0, 0, 0, 0)
            premier_row.addStretch(1)
            premier_row.addWidget(PremierBadge(p["premier"], 22) if p.get("premier") else label("—", "smallMuted"))
            premier_row.addStretch(1)
            cells = [premier,
                     cell(str(p["kills"]), BOARD[1][1]), cell(str(p["deaths"]), BOARD[2][1]), cell(str(p["assists"]), BOARD[3][1]),
                     cell(f"{diff:+d}", BOARD[4][1], GOOD if diff > 0 else BAD if diff < 0 else MUTED, True),
                     cell(fmt_num(p["adr"], 0), BOARD[5][1]), cell(fmt_pct(st.get("kast")), BOARD[6][1]),
                     cell(fmt_pct(p["hs"] / p["kills"] if p["kills"] else None), BOARD[7][1]),
                     cell(f"{st.get('opening_kills', 0)}-{st.get('opening_deaths', 0)}", BOARD[8][1]),
                     cell(fmt_num(p.get("rating"), 2), BOARD[9][1], rating_color(p.get("rating")), True)]
            best = p["steamid"] == self.best
            return player_row(p, cells, best, t("Mejor rating de la partida") if best else "")
        team_rows(layout, players, build)
        return box

    def _aim_tab(self, m: dict, players: list[dict]) -> QWidget:
        widget, outer = page()
        aim = m.get("aim")
        box, layout = card(t("Puntería"), t("Medida con la demo para los 10 jugadores · pasá el mouse por cada columna") if aim else "")
        layout.setSpacing(4)
        outer.addWidget(box)
        if not aim:
            layout.addWidget(label(missing_note(aim), "muted", wrap=True))
            return widget
        layout.addWidget(header_row([(title, AIM_WIDTH, tip) for _k, title, tip, *_rest in AIM]))

        def build(p: dict) -> QFrame:
            values = aim_summary(aim.get(str(p["steamid"]))) or {}
            values["hs_kills"] = p["hs"] / p["kills"] if p["kills"] else None
            cells = []
            for key, _title, _tip, fmt, good, bad in AIM:
                value = values.get(key)
                cells.append(cell(fmt(value), AIM_WIDTH, tone_color(value, good, bad), p.get("me", False)))
            return player_row(p, cells)
        team_rows(layout, players, build)
        color_legend(layout)
        return widget

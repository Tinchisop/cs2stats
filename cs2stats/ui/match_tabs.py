"""Pestañas del detalle de partida al estilo Leetify: tu partida, resumen, utilidad, cara a cara e impacto."""

from __future__ import annotations

from collections import Counter

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import (QButtonGroup, QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton,
                               QVBoxLayout, QWidget)

from ..assets import weapon_icon
from ..i18n import t
from ..metrics import impact_rating, player_numbers, scale_value, utility_rating, weapon_label
from .detail_charts import DivergingBars, Gauge, MarkerBar, RoundImpact, ShareBar, signed
from .match_parts import (NAME_WIDTH, cell, color_legend, header_row, missing_note, player_face, player_row,
                          team_rows, tone_color)
from .pages import card, chip, clear
from .theme import (ACCENT, BAD, CT_COLOR, GOOD, MID, MUTED, SUBTLE, T_COLOR, TEXT, fmt_num, fmt_pct, icon, label,
                    panel, rating_color)
from .visual import Avatar, svg_pixmap

CATEGORY = {"aim": (t("PUNTERÍA"), BAD), "impact": (t("IMPACTO"), MID), "utility": (t("UTILIDAD"), CT_COLOR),
            "duels": (t("DUELOS"), ACCENT), "support": (t("EQUIPO"), GOOD)}
IDENTITY = {"aim": t("Estrella de la puntería"), "impact": t("El que define las rondas"),
            "utility": t("Cerebro de la utilidad"), "duels": t("El que abre las rondas"), "support": t("El compañero ideal")}


def _int(value) -> str:
    return str(int(value)) if value is not None else "—"


def _num0(value) -> str:
    return fmt_num(value, 0)


def _ms(value) -> str:
    return f"{fmt_num(value, 0)} ms" if value is not None else "—"


def _deg(value) -> str:
    return f"{fmt_num(value, 2)}°" if value is not None else "—"


def _sec(value) -> str:
    return f"{fmt_num(value, 1)} s" if value is not None else "—"


def _money(value) -> str:
    return f"${fmt_num(value, 0)}" if value is not None else "—"


# Números candidatos para "tus 5 mejores": clave, nombre, categoría, formato, peor y mejor valor razonable.
TOP_CANDIDATES = [
    ("time_to_damage", t("Tiempo al daño"), "aim", _ms, 800, 300),
    ("head_accuracy", t("Precisión a la cabeza"), "aim", fmt_pct, 0.05, 0.40),
    ("crosshair", t("Ubicación de la mira"), "aim", _deg, 10, 2),
    ("counter_strafe", t("Counter-strafe"), "aim", fmt_pct, 0.45, 0.95),
    ("seen_accuracy", t("Precisión con rival a la vista"), "aim", fmt_pct, 0.12, 0.42),
    ("aim_rating", t("Nota de puntería"), "aim", _num0, 0, 100),
    ("impact", t("Impacto"), "impact", signed, -10, 10),
    ("impact_t", t("Impacto como T"), "impact", signed, -10, 10),
    ("impact_ct", t("Impacto como CT"), "impact", signed, -10, 10),
    ("adr", t("ADR"), "impact", _num0, 40, 130),
    ("kills", t("Kills"), "impact", _int, 5, 30),
    ("utility_rating", t("Nota de utilidad"), "utility", _num0, 0, 100),
    ("enemies_flashed", t("Enemigos cegados"), "utility", _int, 0, 20),
    ("util_damage", t("Daño de granadas"), "utility", _num0, 0, 250),
    ("opening_kills", t("Primeros duelos ganados"), "duels", _int, 0, 8),
    ("clutches_won", t("Clutches ganados"), "duels", _int, 0, 3),
    ("trade_kills", t("Kills de cambio"), "support", _int, 0, 8),
]
# Esta partida contra tus últimas 30: clave, nombre, formato, diferencia que ya cuenta, si más es mejor.
VERSUS = [
    ("impact", t("Impacto"), signed, 1.0, True), ("aim_rating", t("Nota de puntería"), _num0, 5, True),
    ("utility_rating", t("Nota de utilidad"), _num0, 5, True), ("rating", t("Rating"), lambda v: fmt_num(v, 2), 0.05, True),
    ("kills", t("Kills"), lambda v: fmt_num(v, 1) if v is not None and v % 1 else _int(v), 1.5, True),
    ("adr", t("ADR"), _num0, 5, True), ("kast", t("KAST"), fmt_pct, 0.04, True),
    ("opening_attempts", t("Intentos de primer duelo"), fmt_pct, 0.04, True),
    ("clutches_won", t("Clutches ganados"), lambda v: fmt_num(v, 1) if v is not None and v % 1 else _int(v), 0.5, True),
    ("trade_kills", t("Kills de cambio"), lambda v: fmt_num(v, 1) if v is not None and v % 1 else _int(v), 0.8, True),
    ("time_to_damage", t("Tiempo al daño"), _ms, 40, False),
]
CATEGORIES = [
    ("clutch", t("Clutches"), t("Kills y muertes quedando último vivo de tu equipo.")),
    ("midround", t("Duelos en la ronda"), t("Kills y muertes después del primer duelo, sin la bomba plantada.")),
    ("opening", t("Primeros duelos"), t("La primera kill o muerte de la ronda.")),
    ("damage_assist", t("Asistencias de daño"), t("Daño que le hiciste a rivales que después mató un compañero.")),
    ("traded", t("Te vengaron"), t("Si un compañero mató enseguida a tu asesino, te devuelve la mitad de lo que perdiste.")),
    ("afterplant", t("Después de plantar"), t("Jugadas como T con la bomba plantada (incluye plantarla).")),
    ("retake", t("Retakes"), t("Jugadas como CT con la bomba plantada (incluye desactivarla).")),
]
IMPACT_HELP = t("Cada kill cambia la probabilidad de ganar la ronda (por ejemplo, de 5 contra 5 a 5 contra 4). Esa "
                "diferencia se reparte entre el que mató y los que le hicieron daño, y se le resta al que murió. El "
                "número es el promedio por ronda × 100: +5 es muy bueno y −5 es flojo.")
GUNS = {"snipers": {"awp", "ssg08", "g3sg1", "scar20"},
        "rifles": {"ak47", "m4a1", "m4a1_silencer", "famas", "galilar", "aug", "sg556"},
        "mid": {"mac10", "mp9", "mp7", "mp5sd", "ump45", "p90", "bizon", "nova", "xm1014", "mag7", "sawedoff", "negev", "m249"},
        "pistols": {"glock", "usp_silencer", "hkp2000", "p250", "tec9", "fiveseven", "cz75a", "elite", "deagle", "revolver"}}
GUN_NAMES = {"snipers": t("FRANCOTIRADORES"), "rifles": t("RIFLES"), "mid": t("INTERMEDIAS"), "pistols": t("PISTOLAS"),
             "other": t("OTRAS")}
NADE_COLORS = {"flashes": "#3fb6c8", "smokes": "#5a7dff", "hes": "#c8783f", "molotovs": "#d04848"}


def numbers(m: dict) -> dict[str, dict]:
    return {str(p["steamid"]): player_numbers(m, p["steamid"]) for p in m["scoreboard"]}


MIN_ROUNDS_FOR_AVERAGE = 10  # una partida abandonada a las pocas rondas no sirve de referencia


def previous_matches(history: list[dict], m: dict) -> list[dict]:
    """Tus últimas 30 partidas anteriores a esta, sin las que duraron muy pocas rondas."""
    return [h for h in history if h["played_at"] < m["played_at"] and len(h["rounds"]) >= MIN_ROUNDS_FOR_AVERAGE][-30:]


def history_average(history: list[dict], steamid, key: str) -> float | None:
    values = [v for h in history if (v := player_numbers(h, steamid).get(key)) is not None]
    return sum(values) / len(values) if values else None


def note_card(title: str, text: str) -> QFrame:
    box, layout = card(title)
    layout.addWidget(label(text, "muted", wrap=True))
    return box


def page() -> tuple[QWidget, QVBoxLayout]:
    widget = QWidget()
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(16)
    return widget, layout


# Tu partida ───────────────────────────────────────────────────────────────────────────────────────────────────────

def your_match_tab(m: dict, history: list[dict]) -> QWidget:
    widget, outer = page()
    me = str(m["steamid"])
    nums = numbers(m)
    mine = nums.get(me, {})
    allies = [nums[str(p["steamid"])] for p in m["scoreboard"] if p["ally"]]
    row = QHBoxLayout()
    row.setSpacing(16)

    picks = []
    for key, name, category, fmt, worst, best in TOP_CANDIDATES:
        value = mine.get(key)
        if value is None:
            continue
        lower = best < worst
        others = [a.get(key) for a in allies if a is not mine and a.get(key) is not None]
        team_best = all((value <= o) if lower else (value >= o) for o in others)
        team_avg = sum(others) / len(others) if others else None
        score = (scale_value(value, worst, best) or 0) - (scale_value(team_avg, worst, best) if team_avg is not None else 50)
        picks.append((team_best and bool(others), score, key, name, category, fmt, value, worst, best, team_avg))
    picks.sort(key=lambda p: (p[0], p[1]), reverse=True)
    top = picks[:5]

    identity = panel("identityCard")
    layout = QVBoxLayout(identity)
    layout.setContentsMargins(0, 0, 0, 14)
    layout.setSpacing(8)
    head = panel("identityHead")
    head_row = QHBoxLayout(head)
    head_row.setContentsMargins(20, 18, 20, 18)
    head_row.setSpacing(16)
    my_name = m.get("my_name") or ""
    head_row.addWidget(Avatar(my_name, 64, circle=True, ring=ACCENT))
    text = QVBoxLayout()
    text.setSpacing(4)
    text.addWidget(label(t("IDENTIDAD DE LA PARTIDA · TUS 5 MEJORES NÚMEROS"), "identityChip"), 0, Qt.AlignmentFlag.AlignLeft)
    if top:
        counts = Counter(p[4] for p in top)
        main = max(counts, key=lambda c: (counts[c], c == top[0][4]))
        text.addWidget(label(IDENTITY[main], "cardPlayer"))
    head_row.addLayout(text, 1)
    layout.addWidget(head)
    if not top:
        layout.addWidget(label(missing_note(m.get("detail")), "muted", wrap=True))
    for index, (is_best, _score, key, name, category, fmt, value, worst, best, team_avg) in enumerate(top, start=1):
        item = panel("cardFlat")
        line = QHBoxLayout(item)
        line.setContentsMargins(14, 10, 14, 10)
        line.setSpacing(14)
        number = label(f"#{index}", "bigValue")
        number.setStyleSheet(f"color: {MUTED};")
        number.setFixedWidth(40)
        line.addWidget(number)
        body = QVBoxLayout()
        body.setSpacing(6)
        top_line = QHBoxLayout()
        top_line.setSpacing(10)
        top_line.addWidget(label(name, "insightTitle"))
        if is_best:
            top_line.addWidget(chip(t("MEJOR DEL EQUIPO"), "chipGood"))
        top_line.addStretch(1)
        tag, color = CATEGORY[category]
        tag_label = label(tag, "cardTitle")
        tag_label.setStyleSheet(f"color: {color};")
        top_line.addWidget(tag_label)
        body.addLayout(top_line)
        bar_line = QHBoxLayout()
        bar = MarkerBar((scale_value(value, worst, best) or 0) / 100,
                        (scale_value(team_avg, worst, best) or 0) / 100 if team_avg is not None else None, color)
        bar.setToolTip(t("La marca blanca es el promedio del resto de tu equipo"))
        bar_line.addWidget(bar, 1)
        value_label = label(fmt(value), "midValue")
        value_label.setFixedWidth(80)
        value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        bar_line.addWidget(value_label)
        body.addLayout(bar_line)
        line.addLayout(body, 1)
        wrap = QHBoxLayout()
        wrap.setContentsMargins(14, 0, 14, 0)
        wrap.addWidget(item)
        layout.addLayout(wrap)
    row.addWidget(identity, 5, Qt.AlignmentFlag.AlignTop)

    previous = previous_matches(history, m)
    box, layout = card(t("Esta partida"), t("contra tus últimas {0} partidas").format(len(previous)))
    layout.setSpacing(6)
    head = QHBoxLayout()
    head.setContentsMargins(14, 0, 14, 0)
    head.addStretch(1)
    for head_text in (t("ESTA"), t("PROMEDIO")):
        heading = label(head_text, "cardTitle")
        heading.setFixedWidth(90)
        heading.setAlignment(Qt.AlignmentFlag.AlignRight)
        head.addWidget(heading)
    layout.addLayout(head)
    for key, name, fmt, margin, higher in VERSUS:
        value, average = mine.get(key), history_average(previous, me, key)
        color = TEXT
        if value is not None and average is not None and abs(value - average) >= margin:
            color = GOOD if (value > average) == higher else BAD
        line = panel("cardFlat")
        line_layout = QHBoxLayout(line)
        line_layout.setContentsMargins(14, 9, 14, 9)
        line_layout.addWidget(label(name, "body"), 1)
        this = label(fmt(value), "midValue")
        this.setStyleSheet(f"color: {color};")
        this.setFixedWidth(90)
        this.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        line_layout.addWidget(this)
        avg = label(fmt(average), "muted")
        avg.setFixedWidth(90)
        avg.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        line_layout.addWidget(avg)
        layout.addWidget(line)
    row.addWidget(box, 4, Qt.AlignmentFlag.AlignTop)
    outer.addLayout(row)
    outer.addStretch(1)
    return widget


# Resumen ──────────────────────────────────────────────────────────────────────────────────────────────────────────

OVERVIEW = [("impact", t("Impacto"), 74, signed, lambda v: tone_color(v, 2, -2)),
            ("rating", t("Rating"), 62, lambda v: fmt_num(v, 2), rating_color),
            ("kd", "K/D", 58, lambda v: fmt_num(v, 2), lambda v: tone_color(v, 1.1, 0.9)),
            ("adr", t("ADR"), 52, _num0, lambda v: tone_color(v, 85, 65)),
            ("aim_rating", t("Puntería"), 74, _num0, lambda v: tone_color(v, 65, 45)),
            ("utility_rating", t("Utilidad"), 74, _num0, lambda v: tone_color(v, 50, 25))]


def overview_tab(m: dict) -> QWidget:
    widget, outer = page()
    nums = numbers(m)
    players = m["scoreboard"]
    ranked = sorted([p for p in players if nums[str(p["steamid"])].get("impact") is not None],
                    key=lambda p: -nums[str(p["steamid"])]["impact"])
    if ranked:
        podium = QHBoxLayout()
        podium.setSpacing(14)
        for place, p in enumerate(ranked[:3], start=1):
            box = panel("rowMe" if p.get("me") else "card")
            line = QHBoxLayout(box)
            line.setContentsMargins(16, 12, 16, 12)
            line.setSpacing(12)
            line.addWidget(player_face(p, 50))
            text = QVBoxLayout()
            text.setSpacing(0)
            medal = ("#f2c14e", "#c9ced6", "#d08a4e")[place - 1]
            place_row = QHBoxLayout()
            place_row.setSpacing(6)
            crown = QLabel()
            crown.setPixmap(icon("crown", medal, 14).pixmap(QSize(14, 14)))
            place_row.addWidget(crown)
            place_label = label(t("{0}°").format(place), "cardTitle")
            place_label.setStyleSheet(f"color: {medal};")
            place_row.addWidget(place_label)
            place_row.addStretch(1)
            text.addLayout(place_row)
            name = QLabel(QFontMetrics(box.font()).elidedText(p["name"], Qt.TextElideMode.ElideRight, 180))
            name.setObjectName("insightTitle")
            text.addWidget(name)
            line.addLayout(text, 1)
            value = nums[str(p["steamid"])]["impact"]
            ring = QLabel(signed(value))
            ring.setFixedSize(64, 64)
            ring.setAlignment(Qt.AlignmentFlag.AlignCenter)
            ring.setStyleSheet(f"color: {GOOD if value >= 0 else BAD}; border: 2px solid {GOOD if value >= 0 else BAD};"
                               "border-radius: 32px; font-size: 14px; font-weight: 800;")
            ring.setToolTip(IMPACT_HELP)
            line.addWidget(ring)
            podium.addWidget(box, 1)
        outer.addLayout(podium)
    box, layout = card(t("Resumen de los 10"), t("Impacto: cuánto movió cada uno la probabilidad de ganar · ★ el mejor de la partida"))
    layout.setSpacing(4)
    if not m.get("detail"):
        layout.addWidget(label(missing_note(m.get("detail")), "muted", wrap=True))
    layout.addWidget(header_row([(title, width, IMPACT_HELP if key == "impact" else "") for key, title, width, *_r in OVERVIEW]))
    bests = {}
    for key, *_rest in OVERVIEW:
        values = [n.get(key) for n in nums.values() if n.get(key) is not None]
        bests[key] = max(values) if values else None

    def build(p: dict) -> QFrame:
        n = nums[str(p["steamid"])]
        cells = []
        for key, _title, width, fmt, colorize in OVERVIEW:
            value = n.get(key)
            star = " ★" if value is not None and value == bests[key] else ""
            cells.append(cell(fmt(value) + star, width, colorize(value) if value is not None else SUBTLE, bool(p.get("me"))))
        return player_row(p, cells)
    team_rows(layout, players, build)
    outer.addWidget(box)
    outer.addStretch(1)
    return widget


# Utilidad ─────────────────────────────────────────────────────────────────────────────────────────────────────────

UTILITY = [
    ("rating", t("Nota"), 56, _num0, (50, 25), t("Nota de utilidad: raíz de cantidad × calidad, de 0 a 100.")),
    ("quality", t("Calidad"), 62, _num0, (50, 20), t("Cuánto rindieron: ceguera de las flashes, daño de las HE y compañeros cegados.")),
    ("quantity", t("Cantidad"), 66, _num0, (55, 30), t("Cuántas granadas tiraste por ronda.")),
    ("flash_assists", t("Asist.\nflash"), 58, _int, (2, 0.5), t("Kills de compañeros sobre rivales que cegaste.")),
    ("enemies_per_flash", t("Enemigos\npor flash"), 70, lambda v: fmt_num(v, 2), (0.8, 0.3), t("Rivales cegados (más de 0,7 s) por cada flash.")),
    ("friends_per_flash", t("Compañeros\npor flash"), 76, lambda v: fmt_num(v, 2), (0.2, 0.6), t("Compañeros que cegaste por cada flash. Menos es mejor.")),
    ("blind_time", t("Ceguera\npromedio"), 66, _sec, (2.5, 1.5), t("Segundos que quedó ciego, en promedio, cada rival que cegaste.")),
    ("he_avg", t("Daño\npor HE"), 60, lambda v: fmt_num(v, 1), (20, 8), t("Daño promedio de cada granada HE.")),
    ("he_team_avg", t("HE a\ncompañeros"), 76, lambda v: fmt_num(v, 1), (0.5, 5), t("Daño promedio de cada HE a tu propio equipo. Menos es mejor.")),
    ("unused", t("Sin usar\nal morir"), 70, _money, (200, 400), t("Plata en granadas que tenías encima, en promedio, cada vez que moriste.")),
]


def utility_tab(m: dict) -> QWidget:
    widget, outer = page()
    unused = (m.get("detail") or {}).get("unused") or {}
    util = {str(p["steamid"]): utility_rating(p.get("stats") or {}, unused.get(str(p["steamid"]))) for p in m["scoreboard"]}
    for ally in (True, False):
        players = [p for p in m["scoreboard"] if p["ally"] == ally]
        box, layout = card(t("Tu equipo") if ally else t("Rivales"), t("Pasá el mouse por cada columna para ver qué mide"))
        layout.setSpacing(4)
        totals = {k: sum(util[str(p["steamid"])][k] for p in players) for k in NADE_COLORS}
        layout.addWidget(ShareBar([(t("Flashes"), totals["flashes"], NADE_COLORS["flashes"]),
                                   (t("Humos"), totals["smokes"], NADE_COLORS["smokes"]),
                                   (t("HE"), totals["hes"], NADE_COLORS["hes"]),
                                   (t("Molotovs"), totals["molotovs"], NADE_COLORS["molotovs"])]))
        legend = QHBoxLayout()
        legend.setSpacing(14)
        legend.addWidget(label(t("{0} en total").format(sum(totals.values())), "smallMuted"))
        for key, name in (("flashes", t("Flashes")), ("smokes", t("Humos")), ("hes", t("HE")), ("molotovs", t("Molotovs"))):
            item = label(f"●  {name}: {totals[key]}", "smallMuted")
            item.setStyleSheet(f"color: {NADE_COLORS[key]};")
            legend.addWidget(item)
        legend.addStretch(1)
        layout.addLayout(legend)
        layout.addSpacing(6)
        layout.addWidget(header_row([(title, width, tip) for _k, title, width, _f, _c, tip in UTILITY]))
        for p in sorted(players, key=lambda p: -util[str(p["steamid"])]["rating"]):
            u = util[str(p["steamid"])]
            cells = []
            for key, _title, width, fmt, (good, bad), _tip in UTILITY:
                value = u.get(key)
                if key in ("enemies_per_flash", "friends_per_flash", "blind_time") and not u["flashes"]:
                    value = None
                if key in ("he_avg", "he_team_avg") and not u["hes"]:
                    value = None
                cells.append(cell(fmt(value), width, tone_color(value, good, bad), bool(p.get("me"))))
            layout.addWidget(player_row(p, cells))
        if ally:
            color_legend(layout)
        outer.addWidget(box)
    outer.addStretch(1)
    return widget


# Cara a cara ──────────────────────────────────────────────────────────────────────────────────────────────────────

def gun_group(weapon: str) -> str:
    return next((group for group, guns in GUNS.items() if weapon in guns), "other")


class DuelsTab(QWidget):
    """Vos contra cada rival: kills, daño y con qué armas; abajo la matriz de tu equipo contra el de ellos."""

    def __init__(self, m: dict, parent=None):
        super().__init__(parent)
        self.m = m
        detail = m.get("detail") or {}
        self.kills = detail.get("kills") or []
        self.damage = detail.get("damage") or {}
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(16)
        if not detail:
            outer.addWidget(note_card(t("Cara a cara"), missing_note(m.get("detail"))))
            outer.addStretch(1)
            return
        players = m["scoreboard"]
        self.me = next((p for p in players if p.get("me")), None)
        self.rivals = [p for p in players if not p["ally"]]
        top = QHBoxLayout()
        top.addWidget(label(t("Elegí un rival:"), "muted"))
        group = QButtonGroup(self)
        counts = {str(r["steamid"]): self._count(self.me, r) + self._count(r, self.me) for r in self.rivals}
        first = max(self.rivals, key=lambda r: counts[str(r["steamid"])]) if self.rivals else None
        for rival in self.rivals:
            button = QPushButton(QFontMetrics(self.font()).elidedText(rival["name"], Qt.TextElideMode.ElideRight, 120))
            button.setObjectName("segment")
            button.setCheckable(True)
            button.setChecked(rival is first)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _=False, r=rival: self._show(r))
            group.addButton(button)
            top.addWidget(button)
        top.addStretch(1)
        outer.addLayout(top)
        self.versus = QVBoxLayout()
        self.versus.setSpacing(16)
        outer.addLayout(self.versus)
        outer.addWidget(self._matrix())
        outer.addStretch(1)
        if first and self.me:
            self._show(first)

    def _count(self, killer: dict | None, victim: dict | None) -> int:
        if not killer or not victim:
            return 0
        return sum(1 for k in self.kills if k[1] == str(killer["steamid"]) and k[2] == str(victim["steamid"]))

    def _dmg(self, attacker: dict, victim: dict) -> float:
        return self.damage.get(f"{attacker['steamid']}>{victim['steamid']}", 0.0)

    def _show(self, rival: dict) -> None:
        clear(self.versus)
        me = self.me
        box = panel("card")
        row = QHBoxLayout(box)
        row.setContentsMargins(22, 18, 22, 18)
        row.setSpacing(20)
        row.addWidget(player_face(me, 56))
        row.addWidget(label(t("Vos"), "cardPlayer"))
        row.addStretch(1)
        mine, theirs = self._dmg(me, rival), self._dmg(rival, me)
        for value, color in ((self._count(me, rival), ACCENT), (None, ""), (self._count(rival, me), TEXT)):
            if value is None:
                middle = QVBoxLayout()
                middle.addWidget(label(t("DAÑO"), "cardTitle"), 0, Qt.AlignmentFlag.AlignHCenter)
                bar_row = QHBoxLayout()
                bar_row.addWidget(label(fmt_num(mine, 0), "midValue"))
                bar = ShareBar([("", int(mine), ACCENT), ("", int(theirs), "#3a3e46")], text=False)
                bar.setFixedHeight(12)
                bar.setFixedWidth(320)
                bar_row.addWidget(bar)
                bar_row.addWidget(label(fmt_num(theirs, 0), "midValue"))
                middle.addLayout(bar_row)
                row.addLayout(middle)
                continue
            col = QVBoxLayout()
            col.addWidget(label(t("KILLS"), "cardTitle"), 0, Qt.AlignmentFlag.AlignHCenter)
            big = label(str(value), "kpiValue")
            big.setStyleSheet(f"color: {color};")
            col.addWidget(big, 0, Qt.AlignmentFlag.AlignHCenter)
            row.addLayout(col)
        row.addStretch(1)
        row.addWidget(label(rival["name"], "cardPlayer"))
        row.addWidget(player_face(rival, 56))
        self.versus.addWidget(box)

        weapons = QHBoxLayout()
        weapons.setSpacing(16)
        for killer, victim, title in ((me, rival, t("Tus kills contra {0}").format(rival["name"])),
                                      (rival, me, t("Kills de {0} contra vos").format(rival["name"]))):
            panel_box, layout = card(title)
            done = [k for k in self.kills if k[1] == str(killer["steamid"]) and k[2] == str(victim["steamid"])]
            if not done:
                layout.addWidget(label(t("Ninguna"), "muted"))
            groups: dict[str, list] = {}
            for k in done:
                groups.setdefault(gun_group(k[3]), []).append(k)
            line = QHBoxLayout()
            line.setSpacing(18)
            for group in ("snipers", "rifles", "mid", "pistols", "other"):
                items = groups.get(group)
                if not items:
                    continue
                col = QVBoxLayout()
                col.setSpacing(4)
                gun = Counter(k[3] for k in items).most_common(1)[0][0]
                picture = QLabel()
                picture.setPixmap(svg_pixmap(weapon_icon(gun if gun != "inferno" else "molotov"), TEXT, QSize(70, 24)))
                col.addWidget(picture, 0, Qt.AlignmentFlag.AlignHCenter)
                col.addWidget(label(GUN_NAMES[group], "cardTitle"), 0, Qt.AlignmentFlag.AlignHCenter)
                hs = sum(1 for k in items if k[4])
                count = label(t("{0} kills · {1} HS").format(len(items), hs), "midValue")
                count.setToolTip(", ".join(sorted({weapon_label(k[3]) for k in items})))
                col.addWidget(count, 0, Qt.AlignmentFlag.AlignHCenter)
                line.addLayout(col)
            line.addStretch(1)
            layout.addLayout(line)
            weapons.addWidget(panel_box, 1)
        self.versus.addLayout(weapons)

    def _matrix(self) -> QFrame:
        box, layout = card(t("Matriz de duelos"), t("Kills de cada compañero contra cada rival · pasá el mouse para ver el daño"))
        grid = QGridLayout()
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(6)
        allies = [p for p in self.m["scoreboard"] if p["ally"]]
        for col, rival in enumerate(self.rivals, start=1):
            head = QVBoxLayout()
            head.setSpacing(4)
            head.addWidget(player_face(rival, 28), 0, Qt.AlignmentFlag.AlignHCenter)
            name = QLabel(QFontMetrics(self.font()).elidedText(rival["name"], Qt.TextElideMode.ElideRight, 110))
            name.setStyleSheet(f"color: {T_COLOR}; font-weight: 700;")
            name.setAlignment(Qt.AlignmentFlag.AlignCenter)
            head.addWidget(name)
            grid.addLayout(head, 0, col)
        for row, ally in enumerate(allies, start=1):
            who = QHBoxLayout()
            who.setSpacing(8)
            who.addWidget(player_face(ally, 28))
            name = QLabel(QFontMetrics(self.font()).elidedText(ally["name"], Qt.TextElideMode.ElideRight, NAME_WIDTH))
            name.setStyleSheet(f"color: {'#6ff0cc' if ally.get('me') else CT_COLOR}; font-weight: 700;")
            who.addWidget(name)
            who.addStretch(1)
            grid.addLayout(who, row, 0)
            for col, rival in enumerate(self.rivals, start=1):
                won, lost = self._count(ally, rival), self._count(rival, ally)
                color = GOOD if won > lost else BAD if lost > won else MUTED
                square = QLabel(f"{won} – {lost}")
                square.setAlignment(Qt.AlignmentFlag.AlignCenter)
                square.setMinimumHeight(38)
                square.setStyleSheet(f"color: {color}; background: {'#16241d' if won > lost else '#2a181c' if lost > won else '#1c2027'};"
                                     "border-radius: 8px; font-size: 14px; font-weight: 700;")
                square.setToolTip(t("{0} mató {1} veces a {2} y murió {3} veces\nDaño: {4} hecho, {5} recibido").format(
                    ally["name"], won, rival["name"], lost, fmt_num(self._dmg(ally, rival), 0), fmt_num(self._dmg(rival, ally), 0)))
                grid.addWidget(square, row, col)
        grid.setColumnStretch(0, 0)
        for col in range(1, len(self.rivals) + 1):
            grid.setColumnStretch(col, 1)
        layout.addLayout(grid)
        return box


# Impacto ──────────────────────────────────────────────────────────────────────────────────────────────────────────

class ImpactTab(QWidget):
    """Impacto total, como T y como CT; qué jugadas lo sumaron o restaron; y ronda por ronda."""

    def __init__(self, m: dict, history: list[dict], parent=None):
        super().__init__(parent)
        self.m, self.history = m, previous_matches(history, m)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(16)
        if not m.get("detail"):
            outer.addWidget(note_card(t("Impacto"), missing_note(m.get("detail"))))
            outer.addStretch(1)
            return
        top = QHBoxLayout()
        top.addWidget(label(t("Jugador:"), "muted"))
        self.picker = QComboBox()
        self.players = sorted(m["scoreboard"], key=lambda p: (not p.get("me"), not p["ally"]))
        for p in self.players:
            self.picker.addItem(p["name"])
        self.picker.currentIndexChanged.connect(lambda i: self._show(self.players[i]))
        top.addWidget(self.picker)
        top.addStretch(1)
        how = label(t("¿Cómo se calcula?"), "smallMuted")
        how.setStyleSheet(f"color: {MID};")
        how.setToolTip(IMPACT_HELP)
        top.addWidget(how)
        outer.addLayout(top)
        self.content = QVBoxLayout()
        self.content.setSpacing(16)
        outer.addLayout(self.content)
        outer.addStretch(1)
        self._show(self.players[0])

    def _show(self, p: dict) -> None:
        clear(self.content)
        n = player_numbers(self.m, p["steamid"])
        impact = impact_rating((self.m["detail"].get("impact") or {}).get(str(p["steamid"])))
        row = QHBoxLayout()
        row.setSpacing(16)
        box, layout = card(t("Impacto de {0}").format(p["name"]) if not p.get("me") else t("Tu impacto"))
        gauges = QHBoxLayout()
        for key, title, color in (("impact", t("Impacto"), ACCENT), ("impact_t", t("Como T"), T_COLOR), ("impact_ct", t("Como CT"), CT_COLOR)):
            col = QVBoxLayout()
            col.setSpacing(0)
            average = history_average(self.history, p["steamid"], key) if p.get("me") else None
            col.addWidget(Gauge(title, n.get(key), average, color), 0, Qt.AlignmentFlag.AlignHCenter)
            if average is not None and n.get(key) is not None:
                diff = n[key] - average
                text, tone = ((t("▲ POR ENCIMA DE LO TUYO"), GOOD) if diff > 1 else (t("▼ POR DEBAJO DE LO TUYO"), BAD)
                              if diff < -1 else (t("— COMO SIEMPRE"), MUTED))
                state = label(text, "cardTitle")
                state.setStyleSheet(f"color: {tone};")
                col.addWidget(state, 0, Qt.AlignmentFlag.AlignHCenter)
            gauges.addLayout(col)
        layout.addLayout(gauges)
        row.addWidget(box, 5)
        box, layout = card(t("Impacto ganado y perdido"), t("Suma de la partida por tipo de jugada"))
        layout.addWidget(DivergingBars([(name, impact["cats"].get(key, 0.0), help_text) for key, name, help_text in CATEGORIES]))
        row.addWidget(box, 6)
        self.content.addLayout(row)
        winners = {r["n"]: r["side"] if r["won"] else ("CT" if r["side"] == "T" else "T") for r in self.m["rounds"]}
        rounds = [{"n": number, "value": value, "side": impact["sides"].get(number, ""),
                   "won": winners.get(number) == impact["sides"].get(number)} for number, value in sorted(impact["rounds"].items())]
        box, layout = card(t("Impacto por ronda"), t("Cuánto movió cada ronda la probabilidad de ganar de su equipo"))
        layout.addWidget(RoundImpact(rounds))
        self.content.addWidget(box)

"""Pantallas de estadísticas. Reciben una vista ya calculada y solo dibujan."""

from __future__ import annotations

from collections import Counter
from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QDialog, QFrame, QGridLayout, QHBoxLayout,
                               QHeaderView, QLabel, QMenu, QPushButton, QScrollArea, QSizePolicy, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from ..i18n import t
from ..benchmarks import BY_KEY, tier_label
from ..insights import Insight, analyze
from ..metrics import SOURCE_NAMES, by_key, map_label, summarize, weapon_label
from .charts import BarList, ColumnChart, MatchPills, PercentileBar, RoundStrip, SideCompare, TrendChart
from .visual import Avatar, MapCard, WeaponRow
from .theme import (ACCENT, BAD, CT_COLOR, GOOD, MUTED, SUBTLE, TEXT, button, fmt_metric, fmt_num,
                    fmt_pct, label, panel, rating_color, score_color)

MONTHS = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]


def short_date(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).strftime("%d/%m/%y %H:%M")
    except (TypeError, ValueError):
        return "—"


def clear(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        if item.widget():
            item.widget().deleteLater()
        elif item.layout():
            clear(item.layout())


def scroll_page() -> tuple[QScrollArea, QVBoxLayout]:
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QFrame.Shape.NoFrame)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    canvas = QWidget()
    canvas.setObjectName("canvas")
    layout = QVBoxLayout(canvas)
    layout.setContentsMargins(28, 6, 28, 28)
    layout.setSpacing(16)
    area.setWidget(canvas)
    return area, layout


def card(title: str = "", note: str = "", name: str = "card") -> tuple[QFrame, QVBoxLayout]:
    frame = panel(name)
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(18, 14, 18, 16)
    layout.setSpacing(10)
    if title or note:
        row = QHBoxLayout()
        if title:
            row.addWidget(label(title, "sectionTitle"))
        row.addStretch(1)
        if note:
            row.addWidget(label(note, "smallMuted"))
        layout.addLayout(row)
    return frame, layout


def chip(text: str, kind: str = "chip", tip: str = "") -> QLabel:
    widget = label(text, kind)
    widget.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
    if tip:
        widget.setToolTip(tip)
    return widget


def empty_state(text: str, action: str = "", target: str = "", go=None) -> QWidget:
    box, layout = card()
    layout.setContentsMargins(24, 28, 24, 28)
    title = label(t("Todavía no hay datos acá"), "sectionTitle")
    title.setAlignment(Qt.AlignmentFlag.AlignCenter)
    layout.addWidget(title)
    note = label(text, "muted", wrap=True)
    note.setAlignment(Qt.AlignmentFlag.AlignCenter)
    layout.addWidget(note)
    if action and go:
        btn = button(action, primary=True)
        btn.clicked.connect(lambda: go(target))
        layout.addWidget(btn, 0, Qt.AlignmentFlag.AlignCenter)
    return box


def table(headers: list[str]) -> QTableWidget:
    widget = QTableWidget(0, len(headers))
    widget.setHorizontalHeaderLabels(headers)
    widget.verticalHeader().setVisible(False)
    widget.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    widget.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    widget.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    widget.setAlternatingRowColors(True)
    widget.setShowGrid(False)
    widget.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    widget.verticalHeader().setDefaultSectionSize(36)
    header = widget.horizontalHeader()
    header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    widget.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    return widget


def cell(text: str, color: str | None = None, bold: bool = False, back: str | None = None, center: bool = False) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    if color:
        item.setForeground(QColor(color))
    if bold:
        item.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
    if back:
        shade = QColor(back); shade.setAlpha(38)
        item.setBackground(shade)
    if center:
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
    return item


def rating_cell(value) -> QTableWidgetItem:
    return cell(fmt_num(value, 2), rating_color(value), True, rating_color(value) if value is not None else None, True)


def fit_table(widget: QTableWidget, row_height: int = 36) -> None:
    header = max(widget.horizontalHeader().sizeHint().height(), 34)
    widget.setFixedHeight(header + widget.rowCount() * row_height + 6)


def result_text(result: str, us: int, them: int) -> tuple[str, str]:
    return f"{us} : {them}", GOOD if result == "W" else BAD if result == "L" else MUTED


def premier_badge(rating: int | None, tier: tuple | None, big: bool = False) -> QLabel:
    color = tier[3] if tier else MUTED
    text = fmt_num(rating, 0) if rating else t("Sin rating")
    widget = QLabel(text)
    size = 20 if big else 12
    widget.setStyleSheet(f"color: {color}; background: #1b1d23; border: 1px solid {color}; border-left: 5px solid {color};"
                         f"border-radius: 6px; padding: {t('4px 12px') if big else t('2px 10px')}; font-family: 'Segoe UI Variable Display';"
                         f"font-size: {size}px; font-weight: 800; font-style: italic;")
    widget.setMinimumHeight(34 if big else 24)
    widget.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
    return widget


def delta_chip(comp, compact: bool = False) -> QLabel:
    """'+12 %' verde o rojo según si es bueno, con el percentil en el tooltip."""
    if comp is None or comp.delta is None or comp.average is None:
        return chip(t("sin referencia"), "chip")
    better = comp.delta > 0 if comp.metric.higher_better else comp.delta < 0
    if comp.metric.kind == "pct":
        text = f"{comp.delta * 100:+.0f} pts"
    else:
        text = ("+" if comp.delta >= 0 else "") + fmt_metric(comp.delta, comp.metric.kind)
    near = abs(comp.delta) < (0.02 if comp.metric.kind in ("pct", "num2") else 1.5)
    kind = "chip" if near else "chipGood" if better else "chipBad"
    tip = t('Promedio de referencia: {0} ({1} registros)').format(fmt_metric(comp.average, comp.metric.kind), comp.samples)
    return chip(text, kind, tip)


def percentile_text(comp) -> str:
    if comp is None or comp.score is None:
        return t("Faltan datos para comparar")
    score = comp.score
    if score >= 50:
        return t('Mejor que el {0:.0f} % de tu rango').format(score)
    return t('Por debajo del {0:.0f} % de tu rango').format(100 - score)


class Page(QWidget):
    open_match = Signal(int)
    go_to = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.scroll, self.body = scroll_page()
        outer.addWidget(self.scroll)

    def update_view(self, view: dict) -> None:  # pragma: no cover
        raise NotImplementedError

    def rebuild(self) -> None:
        clear(self.body)


class StatTile(QFrame):
    """Tarjeta de métrica: valor grande, comparación con tu rango y barra de percentil."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.layout_ = QVBoxLayout(self)
        self.layout_.setContentsMargins(16, 12, 16, 14)
        self.layout_.setSpacing(5)

    def fill(self, title: str, value: str, color: str, comp, note: str) -> None:
        layout = self.layout_
        clear(layout)
        top = QHBoxLayout()
        top.addWidget(label(title.upper(), "cardTitle"))
        top.addStretch(1)
        top.addWidget(delta_chip(comp))
        layout.addLayout(top)
        big = label(value, "kpiValue")
        big.setStyleSheet(f"color: {color};")
        layout.addWidget(big)
        reference = fmt_metric(comp.average, comp.metric.kind) if comp and comp.average is not None else "—"
        layout.addWidget(label(t('Tu rango: {0}').format(reference), "smallMuted"))
        bar = PercentileBar()
        bar.set_score(comp.score if comp else None)
        layout.addWidget(bar)
        layout.addWidget(label(note or percentile_text(comp), "smallMuted"))


class ProfilePage(Page):
    sync_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.metric = "rating"
        self.view = None

    def update_view(self, view: dict) -> None:
        self.view = view
        self.rebuild()
        body = self.body
        body.addWidget(self._header(view))
        if not view["steam"]["codes"] or not view["steam"]["gc"]:
            notice = panel("notice")
            row = QHBoxLayout(notice)
            row.setContentsMargins(18, 12, 14, 12)
            row.addWidget(label(t("Conectá Steam para que tus partidas de Premier se bajen solas y para traer todo tu historial."),
                                "body", wrap=True), 1)
            go = button(t("Conectar Steam"), "link", primary=True)
            go.clicked.connect(lambda: self.go_to.emit("conectar"))
            row.addWidget(go)
            body.addWidget(notice)
        if not view["matches"]:
            body.addWidget(empty_state(t("Cuando importes partidas con demo vas a ver tus métricas comparadas con tu rango."),
                                       t("Conectar Steam"), "conectar", self.go_to.emit))
            body.addStretch(1)
            return

        pills, layout = card(t("Últimas partidas"), t("Color = rating · raya = resultado · clic para ver el detalle"))
        strip = MatchPills()
        strip.set_items([{"id": m["id"], "rating": m["s"]["rating"], "result": m["result"],
                          "tip": f"{map_label(m['map'])} · {short_date(m['played_at'])}\n{m['score_us']} : {m['score_them']} · "
                                 f"{m['s']['kills']}/{m['s']['deaths']}/{m['s']['assists']} · ADR {fmt_num(m['s']['adr'], 0)}"}
                         for m in view["matches"][-24:]])
        strip.clicked.connect(self.open_match.emit)
        layout.addWidget(strip)
        body.addWidget(pills)

        n_recent = len(view["recent"])
        body.addWidget(label(t('Tus últimas {0} partidas contra {1}').format(n_recent, view['reference']), "pageLead"))
        grid = QGridLayout()
        grid.setSpacing(12)
        comps = {c.metric.key: c for c in view["recent_comparisons"]}
        for index, key in enumerate(("rating", "adr", "kast", "kd", "hs")):
            comp = comps.get(key)
            metric = BY_KEY[key]
            value = comp.mine if comp else None
            color = rating_color(value) if key == "rating" else score_color(comp.score if comp else None)
            tile = StatTile()
            tile.fill(metric.label, fmt_metric(value, metric.kind), color if value is not None else TEXT, comp, "")
            grid.addWidget(tile, 0, index)
        body.addLayout(grid)

        strong, weak = view["highlights"]
        row = QHBoxLayout()
        row.setSpacing(12)
        for title, items, good in ((t("Dónde destacás"), strong, True), (t("Dónde estás por debajo de tu rango"), weak, False)):
            box, layout = card(title, t("Todas tus partidas con demo"))
            if not items:
                layout.addWidget(label(t("Con los datos de ahora no hay diferencias claras."), "muted"))
            for comp in items:
                layout.addWidget(self._highlight(comp, good))
            layout.addStretch(1)
            row.addWidget(box, 1)
        body.addLayout(row)

        trend, layout = card(t("Evolución"))
        top = QHBoxLayout()
        top.addWidget(label(t("Partida por partida, con tu promedio y el de tu rango"), "smallMuted"))
        top.addStretch(1)
        group = QButtonGroup(trend)
        for key in ("rating", "adr", "kast", "hs", "kd"):
            seg = QPushButton(BY_KEY[key].label)
            seg.setObjectName("segment")
            seg.setCheckable(True)
            seg.setChecked(key == self.metric)
            seg.setCursor(Qt.CursorShape.PointingHandCursor)
            seg.clicked.connect(lambda _=False, k=key: self._pick(k))
            group.addButton(seg)
            top.addWidget(seg)
        layout.addLayout(top)
        self.chart = TrendChart()
        layout.addWidget(self.chart)
        body.addWidget(trend)
        self._draw_chart()

        premier = [m for m in view["all_matches"] if m.get("rank_type") == 11 and m.get("rank_new")]
        if len(premier) >= 2:
            box, layout = card(t("Rating de Premier"), t("Después de cada partida con demo"))
            chart = TrendChart()
            chart.set_data([{"value": m["rank_new"], "label": short_date(m["played_at"])[:5], "won": m["result"] == "W",
                             "tip": f"{map_label(m['map'])} · {fmt_num(m['rank_new'], 0)} ({(m['rank_change'] or 0):+.0f})"}
                            for m in premier], decimals=0, color=CT_COLOR)
            layout.addWidget(chart)
            body.addWidget(box)
        body.addStretch(1)

    def _header(self, view: dict) -> QWidget:
        box = panel("heroCard")
        row = QHBoxLayout(box)
        row.setContentsMargins(22, 18, 22, 18)
        row.setSpacing(18)
        name = view["name"] or t("Tu cuenta")
        row.addWidget(Avatar(name, 72))
        text = QVBoxLayout()
        text.setSpacing(4)
        title = QHBoxLayout()
        title.setSpacing(12)
        title.addWidget(label(name, "playerName"))
        title.addWidget(premier_badge(view["premier"], view["premier_tier"]))
        title.addStretch(1)
        text.addLayout(title)
        history = view["all_history"]
        if history:
            first = history[0]["played_at"][:10]
            text.addWidget(label(t('{0} partidas de CS2 en tu historial de Steam desde {1} · {2} con demo analizada').format(len(history), first, len(view['all_matches'])), "muted"))
        else:
            text.addWidget(label(t('{0} partidas con demo analizada').format(len(view['all_matches'])), "muted"))
        row.addLayout(text, 1)
        source = history if history else view["all_matches"]
        stats = []
        if source:
            wins = sum(1 for m in source if m["result"] == "W")
            stats.append((t("Victorias"), fmt_pct(wins / len(source))))
            if history:
                kills, deaths = sum(h["kills"] for h in history), sum(h["deaths"] for h in history)
                stats.append(("K/D", fmt_num(kills / deaths if deaths else None, 2)))
                stats.append((t("HS %"), f"{sum(h['hsp'] for h in history) / len(history):.0f} %"))
            else:
                stats.append(("K/D", fmt_num(view["total"]["kd"], 2)))
                stats.append((t("HS %"), fmt_pct(view["total"]["hs"])))
            stats.append((t("Rating"), fmt_num(view["total"]["rating"], 2)))
        for title_text, value in stats:
            col = QVBoxLayout()
            col.setSpacing(0)
            col.addWidget(label(title_text.upper(), "cardTitle"))
            big = label(value, "bigValue")
            if title_text == t("Rating"):
                big.setStyleSheet(f"color: {rating_color(view['total']['rating'])};")
            col.addWidget(big)
            row.addLayout(col)
            row.addSpacing(10)
        sync = button(t("Buscar partidas"), "scan")
        sync.clicked.connect(self.sync_requested)
        row.addWidget(sync)
        return box

    def _highlight(self, comp, good: bool) -> QWidget:
        frame = panel("goodCard" if good else "badCard")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(4)
        top = QHBoxLayout()
        top.addWidget(label(comp.metric.label, "insightTitle"))
        top.addStretch(1)
        score = comp.score
        top.addWidget(chip(t('Top {0:.0f} %').format(100 - score) if good else t('Abajo del {0:.0f} %').format(100 - score),
                           "chipGood" if good else "chipBad"))
        layout.addLayout(top)
        layout.addWidget(label(t('Vos {0} · tu rango {1}').format(fmt_metric(comp.mine, comp.metric.kind), fmt_metric(comp.average, comp.metric.kind)), "body"))
        bar = PercentileBar()
        bar.set_score(score)
        layout.addWidget(bar)
        return frame

    def _pick(self, key: str) -> None:
        self.metric = key
        self._draw_chart()

    def _draw_chart(self) -> None:
        view = self.view
        metric = BY_KEY[self.metric]
        scale = 100 if metric.kind == "pct" else 1
        points = []
        for m in view["matches"][-40:]:
            value = m["s"].get(metric.key)
            points.append({"value": value * scale if value is not None else None, "label": short_date(m["played_at"])[:5],
                           "won": m["result"] == "W" if m["result"] != "T" else None,
                           "tip": f"{map_label(m['map'])} · {short_date(m['played_at'])}\n{m['score_us']} : {m['score_them']} · "
                                  f"{metric.label} {fmt_metric(value, metric.kind)}"})
        comp = next((c for c in view["comparisons"] if c.metric.key == metric.key), None)
        average = view["total"].get(metric.key)
        reference = comp.average if comp else None
        self.chart.set_data(points, average * scale if average is not None else None,
                            reference * scale if reference is not None else None, t("Tu rango"),
                            0 if metric.kind in ("pct", "num0") else 2 if metric.kind == "num2" else 1,
                            " %" if metric.kind == "pct" else "")


class MatchesPage(Page):
    delete_requested = Signal(int)
    HEADERS = [t("Fecha"), t("Modo"), t("Mapa"), t("Resultado"), "K", "A", "D", "+/-", t("ADR"), t("HS %"), t("Rating"), t("Premier"), t("Datos")]

    def __init__(self, parent=None):
        super().__init__(parent)
        box, layout = card(t("Todas tus partidas"), t("Clic en una partida con demo para ver ronda por ronda"))
        self.table = table(self.HEADERS)
        header = self.table.horizontalHeader()
        for col in range(4, 12):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        self.table.cellClicked.connect(self._open)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._menu)
        layout.addWidget(self.table)
        self.box = box
        self.body.addWidget(box)
        self.empty = empty_state(t("Conectá Steam o importá demos para ver tus partidas acá."), t("Conectar Steam"), "conectar",
                                 lambda t: self.go_to.emit(t))
        self.body.addWidget(self.empty)
        self.body.addStretch(1)
        self.ids: list[int | None] = []

    def update_view(self, view: dict) -> None:
        rows = list(reversed(view["rows"]))[:600]
        self.ids = [r.get("id") for r in rows]
        self.empty.setVisible(not rows)
        self.box.setVisible(bool(rows))
        self.table.setRowCount(len(rows))
        for index, r in enumerate(rows):
            text, color = result_text(r["result"], r["us"], r["them"])
            diff = r["k"] - r["d"]
            values = [cell(short_date(r["played_at"]), MUTED), cell(SOURCE_NAMES.get(r["mode"], r["mode"])),
                      cell(map_label(r["map"]), bold=True), cell(text, color, True, color),
                      cell(str(r["k"]), center=True), cell(str(r["a"]), center=True), cell(str(r["d"]), center=True),
                      cell(f"{diff:+d}", GOOD if diff > 0 else BAD if diff < 0 else MUTED, center=True),
                      cell(fmt_num(r.get("adr"), 0), center=True), cell(f"{r['hs']:.0f} %" if r.get("hs") is not None else "—", center=True),
                      rating_cell(r.get("rating")), cell(r.get("premier", ""), CT_COLOR),
                      cell(t("Demo") if r.get("id") else t("Steam"), TEXT if r.get("id") else SUBTLE)]
            for col, item in enumerate(values):
                self.table.setItem(index, col, item)
        fit_table(self.table)

    def _open(self, row: int, _col: int) -> None:
        if 0 <= row < len(self.ids) and self.ids[row]:
            self.open_match.emit(self.ids[row])

    def _menu(self, pos) -> None:
        row = self.table.rowAt(pos.y())
        if row < 0 or not self.ids[row]:
            return
        menu = QMenu(self)
        see = menu.addAction(t("Ver detalle"))
        remove = menu.addAction(t("Borrar del historial"))
        chosen = menu.exec(self.table.viewport().mapToGlobal(pos))
        if chosen == see:
            self.open_match.emit(self.ids[row])
        elif chosen == remove:
            self.delete_requested.emit(self.ids[row])


class RankPage(Page):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.scope = "all"
        self.view = None

    def update_view(self, view: dict) -> None:
        self.view = view
        self.rebuild()
        body = self.body
        if not view["matches"]:
            body.addWidget(empty_state(t("Necesitás partidas con demo para compararte con tu rango."), t("Conectar Steam"), "conectar",
                                       self.go_to.emit))
            body.addStretch(1)
            return
        top = QHBoxLayout()
        intro = QVBoxLayout()
        title = QHBoxLayout()
        title.addWidget(label(t("Tu rango"), "sectionTitle"))
        title.addWidget(premier_badge(view["premier"], view["premier_tier"]))
        if view["premier_tier"]:
            title.addWidget(label(f"{view['premier_tier'][2]} · {tier_label(view['premier_tier'])}", "muted"))
        title.addStretch(1)
        intro.addLayout(title)
        intro.addWidget(label(t('Referencia: {0} ({1} registros jugador-partida). La marca del medio de cada barra es el promedio; la barra muestra a cuántos superás.').format(view['reference'], view['reference_n']),
                              "smallMuted", wrap=True))
        top.addLayout(intro, 1)
        group = QButtonGroup(self)
        for key, text in (("all", t("Todas las partidas")), ("recent", t('Últimas {0}').format(len(view['recent'])))):
            seg = QPushButton(text)
            seg.setObjectName("segment")
            seg.setCheckable(True)
            seg.setChecked(key == self.scope)
            seg.setCursor(Qt.CursorShape.PointingHandCursor)
            seg.clicked.connect(lambda _=False, k=key: self._scope(k))
            group.addButton(seg)
            top.addWidget(seg, 0, Qt.AlignmentFlag.AlignTop)
        body.addLayout(top)
        comps = view["recent_comparisons"] if self.scope == "recent" else view["comparisons"]
        by_cat: dict[str, list] = {}
        for comp in comps:
            by_cat.setdefault(comp.metric.category, []).append(comp)
        for category, items in by_cat.items():
            box, layout = card(category)
            grid = QGridLayout()
            grid.setHorizontalSpacing(18)
            grid.setVerticalSpacing(10)
            for col, head in enumerate((t("Métrica"), t("Vos"), t("Tu rango"), t("Diferencia"), t("Dónde quedás"), "")):
                grid.addWidget(label(head.upper(), "cardTitle"), 0, col)
            for row, comp in enumerate(items, start=1):
                name = label(comp.metric.label, "body")
                name.setToolTip(comp.metric.help)
                grid.addWidget(name, row, 0)
                mine = label(fmt_metric(comp.mine, comp.metric.kind), "midValue")
                mine.setStyleSheet(f"color: {score_color(comp.score)};")
                grid.addWidget(mine, row, 1)
                grid.addWidget(label(fmt_metric(comp.average, comp.metric.kind), "muted"), row, 2)
                grid.addWidget(delta_chip(comp), row, 3)
                bar = PercentileBar()
                bar.set_score(comp.score)
                grid.addWidget(bar, row, 4)
                grid.addWidget(label(percentile_text(comp), "smallMuted"), row, 5)
            grid.setColumnStretch(4, 2)
            grid.setColumnStretch(0, 2)
            layout.addLayout(grid)
            body.addWidget(box)
        body.addStretch(1)

    def _scope(self, key: str) -> None:
        self.scope = key
        if self.view:
            self.update_view(self.view)


class MapsPage(Page):
    """Una tarjeta por mapa con la foto oficial: partidas, porcentaje de victorias y rating; abajo CT contra T."""

    def update_view(self, view: dict) -> None:
        self.rebuild()
        body = self.body
        history = view["history"]
        rounds = [r for m in view["matches"] for r in m["rounds"]]
        if not history and not rounds:
            body.addWidget(empty_state(t("Conectá Steam o importá demos para ver tus mapas."), t("Conectar Steam"), "conectar", self.go_to.emit))
            body.addStretch(1)
            return
        names: dict[str, str] = {}
        for m in view["matches"]:
            names[map_label(m["map"]).lower()] = m["map"]
        for h in history:
            key = h["map"].lower()
            names.setdefault(key, "de_" + key.replace(" ii", "2").replace(" ", ""))
        cards = []
        for key, raw in names.items():
            hist = [h for h in history if h["map"].lower() == key]
            demos = [m for m in view["matches"] if map_label(m["map"]).lower() == key]
            games = hist if hist else demos
            wins = sum(1 for g in games if g["result"] == "W")
            rs = demos_rounds(demos)
            s = summarize(rs) if rs else None
            kd = (sum(h["kills"] for h in hist) / max(1, sum(h["deaths"] for h in hist))) if hist else (s["kd"] if s else None)
            ct = summarize([r for r in rs if r["side"] == "CT"]) if rs else None
            tt = summarize([r for r in rs if r["side"] == "T"]) if rs else None
            extra = f"K/D {fmt_num(kd, 2)}"
            if ct and tt and ct["rounds"] and tt["rounds"]:
                extra += f"   ·   CT {fmt_num(ct['rating'], 2)}   T {fmt_num(tt['rating'], 2)}"
            cards.append((len(games), raw, key, wins, s, extra))
        cards.sort(key=lambda c: -c[0])
        grid = QGridLayout()
        grid.setSpacing(14)
        for index, (count, raw, key, wins, s, extra) in enumerate(cards):
            card_widget = MapCard(raw, map_label(raw))
            card_widget.set_stats(count, wins / count if count else None, s["rating"] if s else None, extra)
            grid.addWidget(card_widget, index // 3, index % 3)
        for col in range(3):
            grid.setColumnStretch(col, 1)
        body.addLayout(grid)
        if rounds:
            box, layout = card(t("Comparativa CT contra T"), t("Partidas con demo del filtro elegido"))
            compare = SideCompare()
            side = {k: summarize(v) for k, v in by_key(rounds, lambda r: r["side"]).items()}
            ct, tt = side.get(t("CT")) or summarize([]), side.get("T") or summarize([])

            def row(title, key, decimals=0, pct=False, scale=None):
                a, b = ct.get(key), tt.get(key)
                text = (lambda v: fmt_pct(v)) if pct else (lambda v: fmt_num(v, decimals))
                return {"label": title, "ct": a, "t": b, "ct_text": text(a), "t_text": text(b), "scale": 1.0 if pct else scale}
            compare.set_rows([row("Rating", "rating", 2, scale=2.0), row("ADR", "adr", scale=150), row("KAST", "kast", pct=True),
                              row(t("Rondas ganadas"), "win_rate", pct=True), row(t("Primeros duelos ganados"), "opening_win", pct=True),
                              row(t("Morís primero"), "first_team_death", pct=True), row(t("HS %"), "hs", pct=True)])
            layout.addWidget(compare)
            body.addWidget(box)
        body.addStretch(1)


def demos_rounds(demos: list[dict]) -> list[dict]:
    return [r for m in demos for r in m["rounds"]]


class WeaponsPage(Page):
    """Kills por arma con la silueta del arma del juego, y el detalle en una tabla."""

    def update_view(self, view: dict) -> None:
        self.rebuild()
        totals: dict[str, dict] = {}
        for m in view["matches"]:
            for gun, w in m["weapons"].items():
                key = "knife" if gun.startswith("knife") or gun.startswith("bayonet") else gun
                row = totals.setdefault(key, {"kills": 0, "hs": 0, "damage": 0.0, "shots": 0, "hits": 0})
                for field in row:
                    row[field] += w[field]
        rows = sorted(((g, w) for g, w in totals.items() if w["kills"] or w["shots"] >= 20),
                      key=lambda kv: (-kv[1]["kills"], -kv[1]["damage"]))
        if not rows:
            self.body.addWidget(empty_state(t("Importá partidas con demo para ver tus armas."), t("Conectar Steam"), "conectar", self.go_to.emit))
            self.body.addStretch(1)
            return
        box, layout = card(t("Kills por arma"))
        layout.setSpacing(4)
        top = max(w["kills"] for _g, w in rows) or 1
        for gun, w in [r for r in rows if r[1]["kills"]][:10]:
            accuracy = w["hits"] / w["shots"] if w["shots"] else None
            note = t('HS {0} · precisión {1} · {2} de daño').format(fmt_pct(w['hs'] / w['kills'] if w['kills'] else None), fmt_pct(accuracy), fmt_num(w['damage'], 0))
            layout.addWidget(WeaponRow(gun if gun != "inferno" else "molotov", weapon_label(gun), w["kills"], top, note))
        self.body.addWidget(box)
        box, layout = card(t("Detalle"), t("Precisión: balas que pegaron sobre balas disparadas"))
        widget = table([t("Arma"), t("Kills"), t("HS %"), t("Daño"), t("Daño por kill"), t("Disparos"), t("Precisión")])
        widget.setRowCount(len(rows))
        for index, (gun, w) in enumerate(rows):
            accuracy = w["hits"] / w["shots"] if w["shots"] else None
            values = [cell(weapon_label(gun), bold=True), cell(str(w["kills"])),
                      cell(fmt_pct(w["hs"] / w["kills"] if w["kills"] else None)),
                      cell(fmt_num(w["damage"], 0)), cell(fmt_num(w["damage"] / w["kills"], 0) if w["kills"] else "—"),
                      cell(str(w["shots"]) if w["shots"] else "—"),
                      cell(fmt_pct(accuracy), BAD if accuracy is not None and accuracy < 0.15 and w["shots"] >= 100 else None)]
            for col, item in enumerate(values):
                widget.setItem(index, col, item)
        fit_table(widget)
        layout.addWidget(widget)
        self.body.addWidget(box)
        self.body.addStretch(1)



class UtilityPage(Page):
    def update_view(self, view: dict) -> None:
        self.rebuild()
        rounds = [r for m in view["matches"] for r in m["rounds"]]
        if not rounds:
            self.body.addWidget(empty_state(t("Importá partidas con demo para ver tu utilidad y tu economía."), t("Conectar Steam"),
                                            "conectar", self.go_to.emit))
            self.body.addStretch(1)
            return
        comps = {c.metric.key: c for c in view["comparisons"]}
        grid = QGridLayout()
        grid.setSpacing(12)
        for index, key in enumerate(("flashes_per_round", "blinded_per_flash", "team_flash_rate", "util_adr")):
            comp = comps.get(key)
            tile = StatTile()
            tile.fill(BY_KEY[key].label, fmt_metric(comp.mine if comp else None, BY_KEY[key].kind),
                      score_color(comp.score if comp else None), comp, "")
            grid.addWidget(tile, 0, index)
        self.body.addLayout(grid)
        s = view["total"]
        n = max(1, s["rounds"])
        box, layout = card(t("Granadas"), t("Flash efectiva: el enemigo quedó ciego más de 0,7 segundos"))
        row = QHBoxLayout()
        for title, value in ((t("Flashes"), s["flashes"]), (t("Enemigos cegados"), s["enemies_flashed"]),
                             (t("Compañeros cegados"), s["team_flashed"]), (t("Humos"), s["smokes"]), (t("Molotovs"), s["molotovs"]),
                             (t("HE"), s["hes"]), (t("Asistencias por flash"), s["flash_assists"])):
            col = QVBoxLayout()
            col.addWidget(label(title.upper(), "cardTitle"))
            col.addWidget(label(str(value), "bigValue"))
            col.addWidget(label(t('{0} cada 10 rondas').format(fmt_num(value / n * 10)), "smallMuted"))
            row.addLayout(col)
        layout.addLayout(row)
        self.body.addWidget(box)
        box, layout = card(t("Rondas ganadas según la compra de tu equipo"), t("Ahorro: menos de $1.250 promedio · Forzada: hasta $3.500"))
        eco = BarList()
        by_buy = by_key(rounds, lambda r: r["team_buy"])
        rows = []
        for key, title in (("pistola", t("Pistola")), ("ahorro", t("Ahorro")), ("forzada", t("Forzada")), ("completa", t("Completa"))):
            b = summarize(by_buy.get(key, []))
            if b["rounds"]:
                rows.append({"label": title, "value": (b["win_rate"] or 0) * 100, "text": fmt_pct(b["win_rate"]),
                             "note": t('{0} de {1} rondas · tu ADR {2}').format(b['won'], b['rounds'], fmt_num(b['adr'], 0)),
                             "color": score_color((b["win_rate"] or 0) * 100)})
        eco.set_rows(rows, scale=100)
        layout.addWidget(eco)
        self.body.addWidget(box)
        box, layout = card(t("Clutches"), t("Rondas en las que quedaste último vivo de tu equipo"))
        clutch = BarList()
        clutch.empty = t("Todavía no quedaste último vivo en ninguna ronda")
        rows = []
        for vs, title in ((1, t("1 contra 1")), (2, t("1 contra 2")), (3, t("1 contra 3")), (4, t("1 contra 4 o 5"))):
            cs = [r for r in rounds if r["clutch_vs"] and (r["clutch_vs"] == vs if vs < 4 else r["clutch_vs"] >= 4)]
            if cs:
                won = sum(1 for r in cs if r["clutch_won"])
                rows.append({"label": title, "value": won / len(cs) * 100, "text": f"{won} de {len(cs)}",
                             "note": t('ganaste el {0}').format(fmt_pct(won / len(cs))), "color": GOOD if won else SUBTLE})
        clutch.set_rows(rows, scale=100)
        layout.addWidget(clutch)
        self.body.addWidget(box)
        self.body.addStretch(1)


class InsightCard(QFrame):
    def __init__(self, item: Insight, parent=None):
        super().__init__(parent)
        self.setObjectName("badCard" if item.kind == "flojo" else "goodCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 14)
        layout.setSpacing(6)
        chips = QHBoxLayout()
        chips.setSpacing(8)
        chips.addWidget(chip(item.area, "chipBad" if item.kind == "flojo" else "chipGood"))
        confidence = {"alta": t("Confianza alta"), "media": t("Confianza media"), "baja": t("Pocos datos todavía")}[item.confidence]
        chips.addWidget(chip(f"{confidence} · {item.sample} {t(item.unit)}", "chipWarn" if item.confidence == "baja" else "chip"))
        chips.addStretch(1)
        layout.addLayout(chips)
        layout.addWidget(label(item.title, "insightTitle", wrap=True))
        layout.addWidget(label(item.detail, "muted", wrap=True))
        for tip in item.advice:
            layout.addWidget(label(f"•  {tip}", "body", wrap=True))


class AdvicePage(Page):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.scope = "all"
        self.view = None

    def _scope(self, key: str) -> None:
        self.scope = key
        if self.view:
            self.update_view(self.view)

    def update_view(self, view: dict) -> None:
        self.view = view
        self.rebuild()
        body = self.body
        if not view["matches"]:
            body.addWidget(empty_state(t("Importá partidas con demo para recibir consejos."), t("Conectar Steam"), "conectar", self.go_to.emit))
            body.addStretch(1)
            return
        top = QHBoxLayout()
        top.addWidget(label(t("Cada consejo sale de tus números. Cuantas más partidas, más confiables."), "pageLead", wrap=True), 1)
        group = QButtonGroup(self)
        for key, title in (("all", t("Todas las partidas")), ("recent", t('Últimas {0}').format(len(view['recent'])))):
            seg = QPushButton(title)
            seg.setObjectName("segment")
            seg.setCheckable(True)
            seg.setChecked(key == self.scope)
            seg.setCursor(Qt.CursorShape.PointingHandCursor)
            seg.clicked.connect(lambda _=False, k=key: self._scope(k))
            group.addButton(seg)
            top.addWidget(seg)
        body.addLayout(top)
        matches = view["recent"] if self.scope == "recent" else view["matches"]
        items = view["insights"] if self.scope == "all" else analyze(matches)
        weak = [i for i in items if i.kind == "flojo"]
        strong = [i for i in items if i.kind == "fuerte"]
        body.addWidget(label(t('Para mejorar ({0})').format(len(weak)), "sectionTitle"))
        for item in weak:
            body.addWidget(InsightCard(item))
        if not weak:
            body.addWidget(label(t("No aparece ningún punto flojo claro con estos datos."), "muted"))
        body.addWidget(label(t('Tus fuertes ({0})').format(len(strong)), "sectionTitle"))
        for item in strong:
            body.addWidget(InsightCard(item))
        if not strong:
            body.addWidget(label(t("Todavía no hay fuertes claros con estos datos."), "muted"))
        body.addStretch(1)


class HistoryPage(Page):
    def update_view(self, view: dict) -> None:
        self.rebuild()
        body = self.body
        history = view["history"]
        if not history:
            body.addWidget(empty_state(t("Tu historial completo de CS2 sale de la página \"Datos personales del juego\" de Steam. "
                                       "Iniciá sesión una vez con QR desde Conectar Steam."), t("Conectar Steam"), "conectar", self.go_to.emit))
            body.addStretch(1)
            return
        games = len(history)
        wins = sum(1 for h in history if h["result"] == "W")
        ties = sum(1 for h in history if h["result"] == "T")
        kills, deaths = sum(h["kills"] for h in history), sum(h["deaths"] for h in history)
        grid = QGridLayout()
        grid.setSpacing(12)
        tiles = [(t("Partidas"), str(games), TEXT, t('desde {0}').format(history[0]['played_at'][:10])),
                 (t("Victorias"), fmt_pct(wins / games), score_color(wins / games * 100), f"{wins} ganadas · {games - wins - ties} perdidas · {ties} empates"),
                 ("K/D", fmt_num(kills / deaths if deaths else None, 2), TEXT, f"{kills} kills · {deaths} muertes"),
                 (t("HS %"), f"{sum(h['hsp'] for h in history) / games:.0f} %", TEXT, t("promedio por partida")),
                 (t("Kills por partida"), fmt_num(kills / games), TEXT, t('{0} MVP por partida').format(fmt_num(sum(h['mvps'] for h in history) / games)))]
        for index, (title, value, color, note) in enumerate(tiles):
            box = panel()
            layout = QVBoxLayout(box)
            layout.setContentsMargins(16, 12, 16, 12)
            layout.addWidget(label(title.upper(), "cardTitle"))
            big = label(value, "kpiValue")
            big.setStyleSheet(f"color: {color};")
            layout.addWidget(big)
            layout.addWidget(label(note, "smallMuted"))
            grid.addWidget(box, 0, index)
        body.addLayout(grid)

        months: dict[str, list] = {}
        for h in history:
            months.setdefault(h["played_at"][:7], []).append(h)
        box, layout = card(t("Partidas por mes"), t("Alto = cantidad · color = porcentaje de victorias"))
        chart = ColumnChart()
        items = []
        for key in sorted(months):
            ms = months[key]
            rate = sum(1 for h in ms if h["result"] == "W") / len(ms)
            year, month = key.split("-")
            items.append({"label": f"{MONTHS[int(month) - 1]} {year[2:]}", "value": len(ms), "rate": rate,
                          "tip": t('{0} {1}: {2} partidas · {3} ganadas · K/D {4}').format(MONTHS[int(month) - 1], year, len(ms), fmt_pct(rate), fmt_num(sum(h['kills'] for h in ms) / max(1, sum(h['deaths'] for h in ms)), 2))})
        chart.set_items(items[-24:])
        layout.addWidget(chart)
        body.addWidget(box)

        row = QHBoxLayout()
        row.setSpacing(12)
        box, layout = card(t("Por mapa"))
        maps = by_key(history, lambda h: h["map"])
        widget = table([t("Mapa"), t("Partidas"), t("Victorias"), "K/D", t("HS %")])
        ordered = sorted(maps.items(), key=lambda kv: -len(kv[1]))
        widget.setRowCount(len(ordered))
        for index, (name, ms) in enumerate(ordered):
            rate = sum(1 for h in ms if h["result"] == "W") / len(ms)
            kd = sum(h["kills"] for h in ms) / max(1, sum(h["deaths"] for h in ms))
            values = [cell(name, bold=True), cell(str(len(ms))), cell(fmt_pct(rate), score_color(rate * 100), True),
                      cell(fmt_num(kd, 2), GOOD if kd >= 1.1 else BAD if kd < 0.9 else None),
                      cell(f"{sum(h['hsp'] for h in ms) / len(ms):.0f} %")]
            for col, item in enumerate(values):
                widget.setItem(index, col, item)
        fit_table(widget)
        layout.addWidget(widget)
        row.addWidget(box, 3, Qt.AlignmentFlag.AlignTop)

        box, layout = card(t("Con quién jugás más"), t("Compañeros de equipo en tu historial"))
        mates = Counter()
        mate_wins = Counter()
        mate_names = {}
        for h in history:
            for p in h["team"]:
                key = p.get("steamid") or p.get("name")
                mates[key] += 1
                mate_wins[key] += 1 if h["result"] == "W" else 0
                mate_names[key] = p.get("name", "")
        widget = table([t("Jugador"), t("Partidas"), t("Victorias")])
        top = [(k, c) for k, c in mates.most_common(10) if c >= 2]
        widget.setRowCount(len(top))
        for index, (key, count) in enumerate(top):
            rate = mate_wins[key] / count
            for col, item in enumerate([cell(mate_names[key], bold=True), cell(str(count)), cell(fmt_pct(rate), score_color(rate * 100), True)]):
                widget.setItem(index, col, item)
        fit_table(widget)
        layout.addWidget(widget if top else label(t("Todavía no hay compañeros que se repitan."), "muted"))
        layout.addStretch(1)
        row.addWidget(box, 2, Qt.AlignmentFlag.AlignTop)
        body.addLayout(row)
        body.addStretch(1)


class HelpPage(Page):
    STEPS = [
        (t("1. Conectá Steam una vez"), t("En Conectar Steam pegás tu código de autenticación, tu último código de partida y tu clave de "
                                     "Web API, y conectás una cuenta secundaria con QR. Desde ahí tus partidas de Premier se bajan solas.")),
        (t("2. Traé tu historial"), t("También en Conectar Steam, iniciás sesión con QR con tu cuenta principal y la app lee todas tus "
                                 "partidas de CS2 de la página oficial \"Datos personales del juego\".")),
        (t("3. Jugá"), t("Al terminar cada partida, CS2 avisa a la app (si está abierta o en la bandeja) y unos minutos después la "
                    "demo se baja y se analiza sola.")),
        (t("4. FACEIT"), t("Bajá la demo desde la sala del partido: queda en Descargas y la app la importa desde Demos y aviso.")),
    ]
    GLOSSARY = [
        (t("Rating"), t("Impacto general (kills, supervivencia y rondas con varias kills). 1,00 es el promedio.")),
        (t("ADR"), t("Daño real promedio por ronda: si al rival le quedaban 20 de vida, suma 20.")),
        (t("KAST"), t("Rondas en las que mataste, asististe, sobreviviste o vengaron tu muerte.")),
        (t("Tu rango"), t("Jugadores de tu mismo color de Premier que jugaron con vos o contra vos, sacados de tus demos.")),
        (t("Percentil"), t("Dónde quedás entre esos jugadores: \"Top 20 %\" quiere decir que superás al 80 %.")),
        (t("Primer duelo"), t("La primera kill de la ronda. Ganarlo deja a tu equipo 5 contra 4.")),
        (t("Muerte vengada"), t("Un compañero mata a tu asesino en menos de 5 segundos.")),
        (t("Clutch"), t("Quedar último vivo de tu equipo contra uno o más rivales.")),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        box, layout = card(t("Cómo se usa"))
        for title, text in self.STEPS:
            layout.addWidget(label(title, "insightTitle"))
            layout.addWidget(label(text, "body", wrap=True))
        self.body.addWidget(box)
        box, layout = card(t("Es seguro para tu cuenta"), name="okNotice")
        for text in (t("Usa solo herramientas oficiales de Valve: el código de autenticación, la Match History API, los servidores "
                     "de repeticiones y el aviso Game State Integration."),
                     t("Nunca abre, lee ni modifica el juego ni su memoria. No hay riesgo de VAC."),
                     t("La cuenta secundaria solo pide datos al Game Coordinator; tu cuenta principal no queda conectada."),
                     t("Las claves se guardan cifradas en tu PC. Nada se manda a otros servicios.")):
            layout.addWidget(label(f"✓  {text}", "body", wrap=True))
        self.body.addWidget(box)
        box, layout = card(t("Qué significa cada número"))
        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(8)
        for index, (term, text) in enumerate(self.GLOSSARY):
            name = label(term, "body")
            name.setStyleSheet(f"color: {ACCENT}; font-weight: 700;")
            grid.addWidget(name, index, 0, Qt.AlignmentFlag.AlignTop)
            grid.addWidget(label(text, "body", wrap=True), index, 1)
        grid.setColumnStretch(1, 1)
        layout.addLayout(grid)
        self.data_note = label("", "smallMuted", wrap=True)
        layout.addWidget(self.data_note)
        self.body.addWidget(box)
        self.body.addStretch(1)

    def update_view(self, view: dict) -> None:
        self.data_note.setText(t('Tu historial se guarda en {0}').format(view['data_dir']))


class MatchDialog(QDialog):
    def __init__(self, m: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"{map_label(m['map'])} · {short_date(m['played_at'])}")
        self.resize(1120, 800)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        area, body = scroll_page()
        body.setContentsMargins(24, 20, 24, 24)
        outer.addWidget(area)
        s = m["s"]
        text, color = result_text(m["result"], m["score_us"], m["score_them"])
        head = panel()
        row = QHBoxLayout(head)
        row.setContentsMargins(20, 14, 20, 14)
        left = QVBoxLayout()
        left.addWidget(label(f"{SOURCE_NAMES.get(m['source'], m['source'])} · {short_date(m['played_at'])}", "muted"))
        title = QHBoxLayout()
        title.addWidget(label(map_label(m["map"]), "playerName"))
        score = label(text, "playerName")
        score.setStyleSheet(f"color: {color};")
        title.addWidget(score)
        title.addStretch(1)
        left.addLayout(title)
        row.addLayout(left, 1)
        for title_text, value, value_color in ((t("RATING"), fmt_num(s["rating"], 2), rating_color(s["rating"])),
                                               ("K / D / A", f"{s['kills']} / {s['deaths']} / {s['assists']}", TEXT),
                                               (t("ADR"), fmt_num(s["adr"], 0), TEXT), (t("KAST"), fmt_pct(s["kast"]), TEXT),
                                               (t("HS %"), fmt_pct(s["hs"]), TEXT)):
            col = QVBoxLayout()
            col.addWidget(label(title_text, "cardTitle"))
            v = label(value, "bigValue")
            v.setStyleSheet(f"color: {value_color};")
            col.addWidget(v)
            row.addLayout(col)
            row.addSpacing(14)
        if m.get("rank_type") == 11 and m.get("rank_new"):
            change = m.get("rank_change") or 0
            col = QVBoxLayout()
            col.addWidget(label(t("PREMIER"), "cardTitle"))
            badge = QLabel(f"{fmt_num(m['rank_new'], 0)}  ({change:+.0f})")
            badge.setStyleSheet(f"color: {GOOD if change >= 0 else BAD}; font-size: 18px; font-weight: 800;")
            col.addWidget(badge)
            row.addLayout(col)
        body.addWidget(head)

        board, layout = card(t("Tabla de la partida"), t("Rating, ADR y KAST calculados de la demo para los 10 jugadores"))
        widget = table([t("Jugador"), t("Premier"), "K", "D", "A", "+/-", t("ADR"), t("KAST"), t("HS %"), t("1er duelo"), t("Rating")])
        for col in range(1, 11):
            widget.horizontalHeader().setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        rows = m["scoreboard"]
        widget.setRowCount(len(rows) + 1)
        index = 0
        for ally in (True, False):
            if not ally:
                for col in range(11):
                    widget.setItem(index, col, cell(t("RIVALES") if col == 0 else "", SUBTLE, True))
                index += 1
            for p in [p for p in rows if p["ally"] == ally]:
                st = p.get("stats") or {}
                tint = ACCENT if p.get("me") else None
                diff = p["kills"] - p["deaths"]
                values = [cell(p["name"], tint, bool(p.get("me"))), cell(fmt_num(p.get("premier"), 0) if p.get("premier") else "—", CT_COLOR),
                          cell(str(p["kills"]), center=True), cell(str(p["deaths"]), center=True), cell(str(p["assists"]), center=True),
                          cell(f"{diff:+d}", GOOD if diff > 0 else BAD if diff < 0 else MUTED, center=True),
                          cell(fmt_num(p["adr"], 0), center=True), cell(fmt_pct(st.get("kast")), center=True),
                          cell(fmt_pct(p["hs"] / p["kills"] if p["kills"] else None), center=True),
                          cell(f"{st.get('opening_kills', 0)}-{st.get('opening_deaths', 0)}", center=True),
                          rating_cell(p.get("rating"))]
                for col, item in enumerate(values):
                    widget.setItem(index, col, item)
                index += 1
        widget.setRowCount(index)
        fit_table(widget)
        layout.addWidget(widget)
        body.addWidget(board)

        rounds_box, layout = card(t("Ronda por ronda"), t("Pasá el mouse por una ronda para ver el detalle"))
        strip = RoundStrip()
        strip.set_rounds(m["rounds"])
        layout.addWidget(strip)
        body.addWidget(rounds_box)

        grid = QGridLayout()
        grid.setSpacing(10)
        stats = [(t("Primeros duelos"), f"{s['opening_kills']} ganados, {s['opening_deaths']} perdidos"),
                 (t("Clutches"), f"{s['clutches_won']} de {s['clutches']}"),
                 (t("Muertes vengadas"), f"{s['tradeable_deaths'] - s['untraded_deaths']} de {s['tradeable_deaths']}"),
                 (t("Morís primero"), t('{0} de {1} rondas').format(s['first_team_deaths'], s['rounds'])),
                 (t("Utilidad"), f"{s['flashes']} flashes, {s['smokes']} humos, {s['molotovs']} molotovs, {s['hes']} HE"),
                 (t("Flashes efectivas"), t('{0} enemigos, {1} compañeros').format(s['enemies_flashed'], s['team_flashed'])),
                 (t("Daño de granadas"), fmt_num(s["util_damage"], 0)),
                 (t("Kills de cambio"), str(s["trade_kills"]))]
        for index, (title_text, value) in enumerate(stats):
            box = panel("cardFlat")
            col = QVBoxLayout(box)
            col.setContentsMargins(12, 8, 12, 8)
            col.addWidget(label(title_text.upper(), "cardTitle"))
            col.addWidget(label(value, "midValue", wrap=True))
            grid.addWidget(box, index // 4, index % 4)
        body.addLayout(grid)
        body.addStretch(1)

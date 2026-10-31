"""Jugadas: clips automáticos de tus partidas, sin abrir el juego ni bajar la demo de nuevo.

Lo mejor (as, 4K, 3K, clutches ganados) y los errores (morir sin disparar, flashes que cegaron a tu equipo), cada uno
como un tramo corto de la repetición 2D que se mira acá o se guarda como MP4 o GIF."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QButtonGroup, QGridLayout, QHBoxLayout, QPushButton, QVBoxLayout

from ..i18n import t
from ..metrics import map_label
from ..replay import FAILS, HIGHLIGHTS
from .motion import hover_glow
from .pages import Page, card, chip, empty_state, short_date
from .replay import ReplayPlayer, ReplayScene, moment_title, save_clip
from .theme import ACCENT, BAD, MUTED, button, label, panel

KIND_NAMES = {"ace": t("As"), "4k": "4K", "3k": "3K", "clutch": t("Clutch"), "no_shots": t("Sin disparar"),
              "team_flash": t("Flash a tu equipo")}
PAGE_SIZE = 24


class ClipsPage(Page):
    """Tus jugadas de todas las partidas con repetición. Elegís una y se reproduce arriba en bucle."""

    open_in_game = Signal(int, int, float)   # partida, ronda y segundo

    def __init__(self, parent=None):
        super().__init__(parent)
        self.store = None
        self.view = None
        self.filter = "all"
        self.limit = PAGE_SIZE
        self.selected: tuple[str, int] | None = None
        self.cache: dict[str, dict] = {}

    def replay(self, match_key: str) -> dict | None:
        if match_key not in self.cache:
            if len(self.cache) > 6:
                self.cache.pop(next(iter(self.cache)))
            self.cache[match_key] = self.store.replay(match_key) if self.store else None
        return self.cache[match_key]

    def update_view(self, view: dict) -> None:
        self.view = view
        self.rebuild()
        body = self.body
        index = self.store.replay_index() if self.store else {}
        matches = {m["match_key"]: m for m in view["all_matches"]}
        items = []
        for key, entry in index.items():
            match = matches.get(key)
            if not match or entry["status"] != "ok":
                continue
            for number, moment in enumerate(entry["moments"]):
                items.append((match, number, moment))
        items.sort(key=lambda item: (item[0]["played_at"] or "", -item[2]["round"]), reverse=True)
        covered = sum(1 for key in matches if index.get(key, {}).get("status") == "ok")
        if not items:
            body.addWidget(empty_state(
                t("Las jugadas salen de las partidas con repetición 2D. Las nuevas la traen sola y las últimas 20 se "
                  "completan cuando la app busca partidas, mientras Valve tenga la demo ({0} de {1} partidas listas).")
                .format(covered, len(matches)), t("Conectar Steam"), "conectar", self.go_to.emit))
            body.addStretch(1)
            return
        best = [i for i in items if i[2]["kind"] in HIGHLIGHTS]
        fails = [i for i in items if i[2]["kind"] in FAILS]
        top = QHBoxLayout()
        top.setSpacing(6)
        group = QButtonGroup(self)
        for key, title in (("all", t("Todas ({0})").format(len(items))), ("best", t("Lo mejor ({0})").format(len(best))),
                           ("fails", t("Errores ({0})").format(len(fails)))):
            seg = QPushButton(title)
            seg.setObjectName("segment")
            seg.setCheckable(True)
            seg.setChecked(key == self.filter)
            seg.setCursor(Qt.CursorShape.PointingHandCursor)
            seg.clicked.connect(lambda _=False, k=key: self._filter(k))
            group.addButton(seg)
            top.addWidget(seg)
        top.addStretch(1)
        top.addWidget(label(t("{0} de {1} partidas con repetición").format(covered, len(matches)), "smallMuted"))
        body.addLayout(top)
        shown = {"all": items, "best": best, "fails": fails}[self.filter]
        chosen = next((i for i in items if (i[0]["match_key"], i[1]) == self.selected), None)
        if chosen is None and shown:
            chosen = shown[0]
            self.selected = (chosen[0]["match_key"], chosen[1])
        if chosen:
            body.addWidget(self._viewer(*chosen))
        grid = QGridLayout()
        grid.setSpacing(12)
        for position, (match, number, moment) in enumerate(shown[:self.limit]):
            grid.addWidget(self._tile(match, number, moment), position // 3, position % 3)
        for col in range(3):
            grid.setColumnStretch(col, 1)
        body.addLayout(grid)
        if len(shown) > self.limit:
            more = button(t("Mostrar más jugadas"))
            more.clicked.connect(self._more)
            body.addWidget(more, 0, Qt.AlignmentFlag.AlignCenter)
        body.addStretch(1)

    def _viewer(self, match: dict, number: int, moment: dict):
        title = moment_title(moment)
        box, layout = card(title, t("{0} · ronda {1} · {2}").format(map_label(match["map"]), moment["round"],
                                                                   short_date(match["played_at"])))
        data = self.replay(match["match_key"])
        if not data:
            layout.addWidget(label(t("No se pudo abrir la repetición de esta partida."), "muted"))
            return box
        player = ReplayPlayer(data, (self.view or {}).get("grids", {}).get(match["map"]), clip=moment,
                              title=f"{title} · {map_label(match['map'])}")
        player.open_in_game.connect(lambda number, at: self.open_in_game.emit(match["id"], number, at))
        player.canvas.setMinimumHeight(460)
        layout.addWidget(player)
        open_match = QPushButton(t("Ver la partida completa  →"))
        open_match.setObjectName("linkButton")
        open_match.setCursor(Qt.CursorShape.PointingHandCursor)
        open_match.clicked.connect(lambda: self.open_match.emit(match["id"]))
        layout.addWidget(open_match, 0, Qt.AlignmentFlag.AlignLeft)
        return box

    def _tile(self, match: dict, number: int, moment: dict):
        fail = moment["kind"] in FAILS
        on = (match["match_key"], number) == self.selected
        frame = panel("challenge")
        if on:
            frame.setStyleSheet(f"QFrame#challenge {{ border: 1px solid {ACCENT}; background: rgba(34,211,166,22); }}")
        hover_glow(frame, BAD if fail else ACCENT, 24, 90)
        col = QVBoxLayout(frame)
        col.setContentsMargins(14, 10, 12, 12)
        col.setSpacing(6)
        head = QHBoxLayout()
        head.addWidget(chip(KIND_NAMES.get(moment["kind"], moment["kind"]), "chipBad" if fail else "chipGood"))
        head.addStretch(1)
        length = max(1, round(moment["to"] - moment["from"]))
        head.addWidget(label(t("{0} s").format(length), "smallMuted"))
        col.addLayout(head)
        col.addWidget(label(moment_title(moment), "insightTitle", wrap=True))
        sub = label(t("{0} · ronda {1} · {2}").format(map_label(match["map"]), moment["round"], short_date(match["played_at"])),
                    "smallMuted", wrap=True)
        sub.setStyleSheet(f"color: {MUTED};")
        col.addWidget(sub)
        row = QHBoxLayout()
        row.setSpacing(6)
        watch = button(t("Ver"), "play", primary=not on)
        watch.clicked.connect(lambda: self._pick(match["match_key"], number))
        row.addWidget(watch)
        save = button(t("Guardar"), "film")
        save.clicked.connect(lambda: self._save(match, moment))
        row.addWidget(save)
        in_game = button(t("Abrir en CS2"), "external")
        in_game.clicked.connect(lambda: self.open_in_game.emit(match["id"], moment["round"], moment["from"]))
        row.addWidget(in_game)
        row.addStretch(1)
        col.addLayout(row)
        return frame

    def _filter(self, key: str) -> None:
        self.filter, self.limit, self.selected = key, PAGE_SIZE, None
        if self.view:
            self.update_view(self.view)

    def _more(self) -> None:
        self.limit += PAGE_SIZE
        if self.view:
            self.update_view(self.view)

    def _pick(self, match_key: str, number: int) -> None:
        self.selected = (match_key, number)
        if self.view:
            self.update_view(self.view)
            self.scroll.verticalScrollBar().setValue(0)

    def _save(self, match: dict, moment: dict) -> None:
        data = self.replay(match["match_key"])
        if data:
            scene = ReplayScene(data, (self.view or {}).get("grids", {}).get(match["map"]))
            save_clip(self, scene, moment["round"] - 1, moment["from"], moment["to"],
                      f"{moment_title(moment)} · {map_label(match['map'])}")

"""Pre-partida: armás el lobby (tu grupo de Steam, una sala de FACEIT o lo que pegues) y la app te dice qué mapas
pickear o banear y a qué rivales tener en cuenta."""

from __future__ import annotations

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLineEdit, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget

from ..assets import player_avatar
from ..i18n import t
from ..metrics import map_label
from ..prematch import analyze
from .hud import TierProgress
from .pages import Page, card, chip, clear
from .theme import ACCENT, BAD, CT_COLOR, GOOD, MUTED, TEXT, button, fmt_num, fmt_pct, label, panel
from .visual import Avatar

TAGS = {"awp": (t("AWPer"), "chipBad"), "entry": (t("Entry fragger"), "chipBad"), "danger": (t("Peligroso"), "chipBad")}


def pool_label(key: str) -> str:
    """Nombre del mapa a partir de la clave del análisis ("dust ii" → Dust II)."""
    return map_label("de_" + key.replace(" ii", "2").replace(" ", "")) if key else "—"


class SideBars(QWidget):
    """Una fila por mapa: victorias de tu equipo contra las de los rivales, y si conviene pickearlo o banearlo."""

    def __init__(self, rows: list[dict], parent=None):
        super().__init__(parent)
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(8)
        for col, title in enumerate((t("MAPA"), t("TU EQUIPO"), t("RIVALES"), t("DIFERENCIA"), "")):
            grid.addWidget(label(title, "cardTitle"), 0, col)
        for index, row in enumerate(rows, start=1):
            name = label(pool_label(row["map"]), "body")
            name.setStyleSheet("font-weight: 700;")
            grid.addWidget(name, index, 0)
            for col, (value, games, color) in enumerate(((row["ours"], row["our_games"], ACCENT),
                                                         (row["theirs"], row["their_games"], CT_COLOR)), start=1):
                cell = QHBoxLayout()
                cell.setSpacing(8)
                bar = TierProgress(value, color)
                bar.setMinimumWidth(120)
                cell.addWidget(bar, 1)
                text = label(f"{fmt_pct(value)}  ·  {t('{0} partidas').format(games) if games else t('sin datos')}", "smallMuted")
                text.setMinimumWidth(130)
                cell.addWidget(text)
                grid.addLayout(cell, index, col)
            edge = label(f"{row['edge'] * 100:+.0f} pts", "body")
            edge.setStyleSheet(f"color: {GOOD if row['edge'] > 0.02 else BAD if row['edge'] < -0.02 else MUTED}; font-weight: 800;")
            grid.addWidget(edge, index, 3)
            verdict = {"pick": (t("Pickear"), "chipGood"), "ban": (t("Banear"), "chipBad")}.get(row["verdict"], (t("Neutro"), "chip"))
            grid.addWidget(chip(*verdict), index, 4)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 1)


class PrematchPage(Page):
    detect_requested = Signal()
    analyze_requested = Signal(str, str, str, str)   # compañeros, rivales, sala de FACEIT, clave de FACEIT

    def __init__(self, parent=None):
        super().__init__(parent)
        self.view: dict | None = None
        self.collected: dict | None = None
        body = self.body
        body.addWidget(label(t("Cuando estés en el lobby de Premier o FACEIT, cargá a tus compañeros y a los rivales: la app "
                               "cruza sus números en tus demos (y en FACEIT, si querés) para sugerirte mapas y avisarte "
                               "a quién tener en cuenta."), "pageLead", wrap=True))
        box, layout = card(t("Armá el lobby"))
        columns = QHBoxLayout()
        columns.setSpacing(14)
        self.mates = self._box(t("Pegá links de perfiles de Steam, SteamID64 o nombres (uno por línea)"))
        self.rivals = self._box(t("Rivales: links, SteamID64, nombres o la salida de status de la consola"))
        for title, edit, extra in ((t("TU EQUIPO"), self.mates, True), (t("RIVALES"), self.rivals, False)):
            col = QVBoxLayout()
            col.setSpacing(6)
            head = QHBoxLayout()
            head.addWidget(label(title, "cardTitle"))
            head.addStretch(1)
            if extra:
                detect = QPushButton(t("Detectar mi grupo de Steam"))
                detect.setObjectName("linkButton")
                detect.setCursor(Qt.CursorShape.PointingHandCursor)
                detect.setToolTip(t("Busca a tus amigos que están en tu mismo lobby de CS2 ahora"))
                detect.clicked.connect(self.detect_requested.emit)
                head.addWidget(detect)
            col.addLayout(head)
            col.addWidget(edit)
            columns.addLayout(col, 1)
        layout.addLayout(columns)
        faceit = QHBoxLayout()
        faceit.setSpacing(8)
        self.room = QLineEdit()
        self.room.setPlaceholderText(t("Link de la sala de FACEIT (opcional): trae a los 10 jugadores solos"))
        faceit.addWidget(self.room, 3)
        self.key = QLineEdit()
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        self.key.setPlaceholderText(t("Clave de la API de datos de FACEIT"))
        faceit.addWidget(self.key, 2)
        get_key = QPushButton(t("Conseguir una clave"))
        get_key.setObjectName("linkButton")
        get_key.setCursor(Qt.CursorShape.PointingHandCursor)
        get_key.setToolTip(t("En developers.faceit.com: creá una app y copiá una clave del lado del servidor (Server side)"))
        get_key.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://developers.faceit.com/")))
        faceit.addWidget(get_key)
        layout.addLayout(faceit)
        actions = QHBoxLayout()
        self.go_button = button(t("Analizar el lobby"), "duel", primary=True)
        self.go_button.clicked.connect(self._analyze)
        actions.addWidget(self.go_button)
        clear_button = button(t("Limpiar"))
        clear_button.clicked.connect(self._clear)
        actions.addWidget(clear_button)
        self.status = label("", "smallMuted", wrap=True)
        actions.addWidget(self.status, 1)
        layout.addLayout(actions)
        layout.addWidget(label(t("Lo que pegás se cruza con tus demos. Con la sala de FACEIT y tu clave se suman los números de "
                                 "FACEIT de cada jugador; la clave se guarda cifrada en tu PC y solo se usa para leer esa sala."),
                               "smallMuted", wrap=True))
        body.addWidget(box)
        self.report = QVBoxLayout()
        self.report.setSpacing(16)
        body.addLayout(self.report)
        body.addStretch(1)

    @staticmethod
    def _box(placeholder: str) -> QPlainTextEdit:
        edit = QPlainTextEdit()
        edit.setObjectName("lobbyBox")
        edit.setPlaceholderText(placeholder)
        edit.setFixedHeight(110)
        return edit

    # La página no se rearma con cada actualización: así no se pierde lo que escribiste.
    def update_view(self, view: dict) -> None:
        self.view = view
        if self.collected:
            self._render()

    def rebuild(self) -> None:
        pass

    def set_key(self, key: str) -> None:
        self.key.setText(key)

    def set_mates(self, names: list[str]) -> None:
        current = [line for line in self.mates.toPlainText().splitlines() if line.strip()]
        self.mates.setPlainText("\n".join(current + [n for n in names if n not in current]))

    def set_busy(self, busy: bool, text: str = "") -> None:
        self.go_button.setEnabled(not busy)
        self.status.setText(text)
        self.status.setStyleSheet("")

    def show_error(self, text: str) -> None:
        self.go_button.setEnabled(True)
        self.status.setText(text)
        self.status.setStyleSheet(f"color: {BAD};")

    def _analyze(self) -> None:
        if not (self.mates.toPlainText().strip() or self.rivals.toPlainText().strip() or self.room.text().strip()):
            self.show_error(t("Cargá al menos un jugador o el link de la sala."))
            return
        self.analyze_requested.emit(self.mates.toPlainText(), self.rivals.toPlainText(), self.room.text().strip(),
                                    self.key.text().strip())

    def _clear(self) -> None:
        self.mates.clear()
        self.rivals.clear()
        self.room.clear()
        self.collected = None
        clear(self.report)
        self.status.setText("")

    def show_collected(self, collected: dict) -> None:
        self.collected = collected
        notes = collected.get("notes") or []
        self.set_busy(False, " ".join(notes) if notes else t("Listo: {0} compañeros y {1} rivales.").format(
            len(collected["mates"]), len(collected["rivals"])))
        self._render()

    def _render(self) -> None:
        clear(self.report)
        if not self.view or not self.collected:
            return
        view = self.view
        me = next((int(p["steamid"]) for m in reversed(view["all_matches"]) for p in m["scoreboard"] if p.get("me")), 0)
        games = view["all_history"] or view["all_matches"]
        result = analyze(me, self.collected["mates"], self.collected["rivals"], view["all_matches"], games)
        box, layout = card(t("Mapas"), t("Victorias por mapa: vos y tus compañeros contra los rivales"))
        picks = [r for r in result["maps"] if r["verdict"] == "pick"]
        bans = [r for r in result["maps"] if r["verdict"] == "ban"]

        def names(rows: list[dict]) -> str:
            return ", ".join(pool_label(r["map"]) for r in rows)
        summary = []
        if picks:
            summary.append(t("Pickeá {0}.").format(names(picks)))
        if bans:
            summary.append(t("Baneá {0}.").format(names(bans)))
        headline = label(" ".join(summary) or t("Ningún mapa se despega: con más partidas juntos la sugerencia mejora."),
                         "insightTitle", wrap=True)
        headline.setStyleSheet(f"color: {TEXT};")
        layout.addWidget(headline)
        layout.addWidget(SideBars(result["maps"]))
        layout.addWidget(label(t("Con pocas partidas cada mapa se acerca al 50 %, para no exagerar con un par de resultados."),
                               "smallMuted", wrap=True))
        self.report.addWidget(box)
        if result["rivals"]:
            box, layout = card(t("Rivales a tener en cuenta"), t("De tus demos y de FACEIT"))
            grid = QGridLayout()
            grid.setSpacing(10)
            for index, rival in enumerate(result["rivals"]):
                grid.addWidget(self._rival(rival), index // 2, index % 2)
            grid.setColumnStretch(0, 1)
            grid.setColumnStretch(1, 1)
            layout.addLayout(grid)
            self.report.addWidget(box)

    def _rival(self, rival: dict) -> QWidget:
        frame = panel("badCard" if "danger" in rival["tags"] else "challenge")
        row = QHBoxLayout(frame)
        row.setContentsMargins(12, 10, 12, 10)
        row.setSpacing(10)
        row.addWidget(Avatar(rival["name"], 44, photo=player_avatar(rival["steamid"]) if rival["steamid"] else None,
                             color=CT_COLOR, circle=True))
        col = QVBoxLayout()
        col.setSpacing(4)
        top = QHBoxLayout()
        top.setSpacing(6)
        name = label(rival["name"], "insightTitle")
        top.addWidget(name)
        for tag in rival["tags"]:
            top.addWidget(chip(*TAGS[tag]))
        if rival.get("level"):
            top.addWidget(chip(t("FACEIT nivel {0}").format(rival["level"])))
        top.addStretch(1)
        col.addLayout(top)
        parts = []
        if rival["games"]:
            parts.append(t("te cruzaste 1 vez") if rival["games"] == 1 else t("te cruzaste {0} veces").format(rival["games"]))
        if rival["rating"] is not None:
            parts.append(t("rating {0}").format(fmt_num(rival["rating"], 2)))
        if rival["adr"] is not None:
            parts.append(t("ADR {0}").format(fmt_num(rival["adr"], 0)))
        if rival["opening_pr"] is not None:
            parts.append(t("pelea el primer duelo en el {0} de las rondas").format(fmt_pct(rival["opening_pr"])))
        if rival["awp"] is not None and rival["awp"] >= 0.1:
            parts.append(t("{0} de sus kills con AWP").format(fmt_pct(rival["awp"])))
        if rival.get("kd") is not None and rival["rating"] is None:
            parts.append(f"K/D {fmt_num(rival['kd'], 2)}")
        if rival.get("win_rate") is not None:
            parts.append(t("gana el {0} en FACEIT").format(fmt_pct(rival["win_rate"])))
        for key, value in list((rival.get("extra") or {}).items())[:2]:
            parts.append(f"{key}: {value}")
        col.addWidget(label(" · ".join(parts) or t("Sin datos: no apareció en tus demos."), "smallMuted", wrap=True))
        tips = {"awp": t("Ojo con los ángulos largos: tirá smoke o flash antes de cruzar."),
                "entry": t("Suele abrir la ronda: jugá con un compañero cerca para cambiarlo.")}
        for tag in rival["tags"]:
            if tag in tips:
                tip = label(tips[tag], "smallMuted", wrap=True)
                tip.setStyleSheet("color: #ffb2a6;")
                col.addWidget(tip)
        row.addLayout(col, 1)
        return frame

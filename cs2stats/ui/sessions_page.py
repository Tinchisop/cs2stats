"""Sesiones: cómo te va según cuántas partidas seguidas llevás, si venís de perder y el horario."""

from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout

from ..i18n import t
from ..sessions import MIN_GAMES, Bucket, Report, analyze_sessions, current_advice
from .pages import Page, card, cell, chip, empty_state, fit_table, rating_cell, table
from .theme import BAD, GOOD, MUTED, fmt_num, fmt_pct, label, panel


class SessionsPage(Page):
    def update_view(self, view: dict) -> None:
        self.rebuild()
        body = self.body
        report = analyze_sessions(view["rows"])
        if not report.games:
            body.addWidget(empty_state(t("Las sesiones se arman con la fecha de tus partidas. Traé tu historial de Steam "
                                         "para verlas."), t("Conectar Steam"), "conectar", self.go_to.emit))
            body.addStretch(1)
            return
        body.addWidget(label(t("Una sesión son las partidas que jugás con menos de 3 horas entre una y otra. "
                               "{0} partidas en {1} sesiones, con {2} partidas por sesión en promedio.").format(
            report.games, report.sessions, fmt_num(report.average_length, 1)), "pageLead", wrap=True))
        if report.current:
            body.addWidget(self._current(report))
        body.addWidget(self._findings(report))
        body.addWidget(self._table(t("Según la partida de la sesión"), t("Si el cansancio te pesa, se ve acá"), report.positions))
        body.addWidget(self._table(t("Según cómo venías"), t("Dentro de la misma sesión"), report.momentum))
        body.addWidget(self._table(t("Según el horario"), t("Hora de tu PC"), report.bands))
        body.addStretch(1)

    def _current(self, report: Report):
        games = report.current
        wins = sum(1 for g in games if g["result"] == "W")
        losses = sum(1 for g in games if g["result"] == "L")
        box, layout = card(t("Tu sesión de ahora"), t("{0} partidas · {1} ganadas · {2} perdidas").format(len(games), wins, losses))
        advice = current_advice(report)
        layout.addWidget(label(advice or t("Por ahora, nada que te haga cortar."), "body", wrap=True))
        return box

    def _findings(self, report: Report):
        box, layout = card(t("Lo que dicen tus números"))
        if not report.findings:
            layout.addWidget(label(t("Por ahora no se ve un patrón claro: las diferencias de abajo pueden ser casualidad. "
                                     "La app solo avisa cuando cada grupo tiene al menos {0} partidas y la diferencia "
                                     "alcanza para confiar en ella.").format(MIN_GAMES), "muted", wrap=True))
        for finding in report.findings:
            frame = panel("challenge")
            col = QVBoxLayout(frame)
            col.setContentsMargins(14, 10, 14, 12)
            col.setSpacing(5)
            top = QHBoxLayout()
            top.addWidget(label(finding.title, "insightTitle", wrap=True), 1)
            top.addWidget(chip(t("A cuidar") if finding.bad else t("A favor"), "chipBad" if finding.bad else "chipGood"))
            col.addLayout(top)
            col.addWidget(label(finding.detail, "body", wrap=True))
            layout.addWidget(frame)
        return box

    def _table(self, title: str, note: str, buckets: list[Bucket]):
        box, layout = card(title, note)
        widget = table(["", t("Partidas"), t("Victorias"), "K/D", t("Rating")])
        widget.setRowCount(len(buckets))
        for row, bucket in enumerate(buckets):
            few = bucket.games < MIN_GAMES
            rate = bucket.win_rate
            widget.setItem(row, 0, cell(bucket.title, bold=True))
            widget.setItem(row, 1, cell(str(bucket.games), MUTED if few else None, center=True))
            color = MUTED if few or rate is None else GOOD if rate >= 0.5 else BAD
            widget.setItem(row, 2, cell(fmt_pct(rate), color, True, center=True))
            widget.setItem(row, 3, cell(fmt_num(bucket.kd, 2), center=True))
            widget.setItem(row, 4, rating_cell(bucket.rating))
        fit_table(widget)
        layout.addWidget(widget)
        layout.addWidget(label(t("En gris, los grupos con menos de {0} partidas. El rating solo sale de las partidas con demo.").format(MIN_GAMES),
                               "smallMuted", wrap=True))
        return box

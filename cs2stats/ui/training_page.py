"""Entrenamiento: retos de la semana y mapas del Workshop para practicar justo lo que te cuesta."""

from __future__ import annotations

from datetime import datetime, timedelta

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QVBoxLayout

from ..i18n import t
from ..training import past_weeks, recommend, weekly_challenges
from .hud import TierProgress
from .pages import Page, card, chip
from .theme import CT_COLOR, GOOD, button, fmt_num, label, panel


class TrainingPage(Page):
    def update_view(self, view: dict) -> None:
        self.rebuild()
        body = self.body
        now = datetime.now()
        matches = view["all_matches"]
        body.addWidget(label(t("Retos nuevos cada lunes armados con tus puntos flojos, y mapas del Workshop de CS2 para "
                               "practicar cada cosa. El avance cuenta tus partidas con demo de la semana."),
                             "pageLead", wrap=True))
        body.addWidget(self._week(matches, now))
        body.addWidget(self._workouts(view))
        body.addStretch(1)

    def _week(self, matches: list[dict], now: datetime):
        challenges, start = weekly_challenges(matches, now)
        end = start + timedelta(days=6)
        left = (start + timedelta(days=7) - now).days
        done = sum(1 for c in challenges if c.done)
        box, layout = card(t("Retos de la semana"), t("Del {0} al {1} · {2}").format(
            start.strftime("%d/%m"), end.strftime("%d/%m"),
            t("último día") if left <= 0 else t("quedan {0} días").format(left + 1)))
        for challenge in challenges:
            row = panel("challengeDone" if challenge.done else "challenge")
            col = QVBoxLayout(row)
            col.setContentsMargins(14, 10, 14, 12)
            col.setSpacing(5)
            top = QHBoxLayout()
            top.addWidget(label(challenge.title, "insightTitle", wrap=True), 1)
            decimals = 0 if float(challenge.goal).is_integer() else 1
            top.addWidget(label(f"{fmt_num(min(challenge.value, challenge.goal), decimals)} / {fmt_num(challenge.goal, decimals)}",
                                "midValue"))
            top.addWidget(chip(t("¡Cumplido!") if challenge.done else t("En curso"), "chipGood" if challenge.done else "chip"))
            col.addLayout(top)
            col.addWidget(label(challenge.detail, "smallMuted", wrap=True))
            col.addWidget(TierProgress(challenge.share, GOOD if challenge.done else CT_COLOR))
            layout.addWidget(row)
        history = past_weeks(matches, now)
        footer = QHBoxLayout()
        footer.setSpacing(6)
        footer.addWidget(label(t("Esta semana: {0} de {1}").format(done, len(challenges)), "body"))
        footer.addSpacing(10)
        if history:
            footer.addWidget(label(t("Semanas anteriores:"), "smallMuted"))
            for monday, won, total in history:
                footer.addWidget(chip(f"{monday.strftime('%d/%m')} · {won}/{total}", "chipGood" if won == total else "chip",
                                      t("Semana del {0}").format(monday.strftime("%d/%m/%Y"))))
        footer.addStretch(1)
        layout.addLayout(footer)
        return box

    def _workouts(self, view: dict):
        picks = recommend(view["all_matches"], view.get("recent_comparisons") or view.get("comparisons") or [])
        box, layout = card(t("Entrenamiento recomendado"), t("Mapas gratis del Workshop de CS2"))
        layout.addWidget(label(t("Suscribite al mapa en el Workshop y abrilo desde CS2: Jugar › Mapas del Workshop. "
                                 "Son mapas de práctica sin conexión: no afectan tu cuenta."), "smallMuted", wrap=True))
        for workout, reason, weak in picks:
            frame = panel("challenge")
            col = QVBoxLayout(frame)
            col.setContentsMargins(14, 10, 14, 12)
            col.setSpacing(5)
            top = QHBoxLayout()
            top.addWidget(label(workout.focus, "insightTitle"), 1)
            top.addWidget(chip(t("{0} min").format(workout.minutes)))
            col.addLayout(top)
            why = label(reason, "body", wrap=True)
            if weak:
                why.setStyleSheet("color: #ffb2a6;")
            col.addWidget(why)
            col.addWidget(label(t("{0}: {1}").format(workout.title, workout.routine), "smallMuted", wrap=True))
            actions = QHBoxLayout()
            actions.setSpacing(6)
            steam = button(t("Abrir en Steam"), "external", primary=True)
            steam.clicked.connect(lambda _=False, w=workout: QDesktopServices.openUrl(
                QUrl(f"steam://url/CommunityFilePage/{w.workshop_id}")))
            actions.addWidget(steam)
            web = button(t("Ver en el navegador"))
            web.clicked.connect(lambda _=False, w=workout: QDesktopServices.openUrl(
                QUrl(f"https://steamcommunity.com/sharedfiles/filedetails/?id={w.workshop_id}")))
            actions.addWidget(web)
            if workout.command:
                copy = button(t("Copiar comando de consola"))
                copy.setToolTip(workout.command)
                copy.clicked.connect(lambda _=False, w=workout, b=copy: (QGuiApplication.clipboard().setText(w.command),
                                                                          b.setText(t("Copiado"))))
                actions.addWidget(copy)
            if workout.key == "yprac":
                nades = QPushButton(t("Ver latas en la app  →"))
                nades.setObjectName("linkButton")
                nades.setCursor(Qt.CursorShape.PointingHandCursor)
                nades.clicked.connect(lambda: self.go_to.emit("latas"))
                actions.addWidget(nades)
            actions.addStretch(1)
            col.addLayout(actions)
            layout.addWidget(frame)
        return box

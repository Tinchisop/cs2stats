"""Progreso: logros con medallas, metas propias y pronóstico del rating de Premier. Todo sale de tus partidas."""

from __future__ import annotations

import math
from dataclasses import dataclass

from .i18n import t
from .metrics import map_label


@dataclass
class Achievement:
    key: str
    title: str
    detail: str
    icon: str          # ícono de theme.icon
    tier: str          # "bronce", "plata" u "oro"
    value: float       # cuánto llevás
    goal: float        # cuánto hace falta

    @property
    def unlocked(self) -> bool:
        return self.value >= self.goal

    @property
    def share(self) -> float:
        return min(1.0, self.value / self.goal) if self.goal else 1.0


def best_streak(results: list[str]) -> int:
    best = run = 0
    for result in results:
        run = run + 1 if result == "W" else 0
        best = max(best, run)
    return best


def top_rated(m: dict) -> bool:
    """Fuiste el de mejor rating de la partida (el "MVP" de la partida)."""
    ratings = [p.get("rating") or 0 for p in m.get("scoreboard") or []]
    mine = next((p.get("rating") or 0 for p in m.get("scoreboard") or [] if p.get("me")), None)
    return bool(ratings) and mine is not None and mine >= max(ratings)


def achievements(matches: list[dict], history: list[dict]) -> list[Achievement]:
    """Medallas: las ganadas y cuánto falta para las demás. matches: partidas con demo (con m["s"]); history: Steam."""
    rounds = [r for m in matches for r in m["rounds"]]
    kills_in_round = [r["kills"] for r in rounds]
    clutches_won = [r for r in rounds if r.get("clutch_vs") and r.get("clutch_won")]
    games = sorted(history or matches, key=lambda g: g["played_at"] or "")
    per_map: dict[str, int] = {}
    for g in games:
        if g["result"] == "W":
            key = map_label(g["map"]).lower() if g["map"].startswith("de_") else g["map"].lower()
            per_map[key] = per_map.get(key, 0) + 1
    best_premier = max((m.get("rank_new") or 0 for m in matches if m.get("rank_type") == 11), default=0)
    stats = [m["s"] for m in matches]

    def most(key: str) -> float:
        return max((s.get(key) or 0 for s in stats), default=0)
    pistol_wins = sum(1 for r in rounds if r.get("buy") == "pistola" and r["won"])
    eco_wins = sum(1 for r in rounds if r.get("team_buy") == "ahorro" and r["won"])
    return [
        Achievement("ace", t("As"), t("5 kills en una ronda"), "crown", "oro", sum(1 for k in kills_in_round if k >= 5), 1),
        Achievement("4k", t("Cuatro de cuatro"), t("4 kills en una ronda"), "burst", "plata",
                    sum(1 for k in kills_in_round if k >= 4), 1),
        Achievement("3k", t("Triple"), t("10 rondas con 3 kills o más"), "burst", "bronce",
                    sum(1 for k in kills_in_round if k >= 3), 10),
        Achievement("clutch", t("Sangre fría"), t("Ganá un clutch"), "shield", "bronce", len(clutches_won), 1),
        Achievement("clutch2", t("Imposible"), t("Ganá un clutch contra 2 o más"), "shield", "plata",
                    sum(1 for r in clutches_won if r["clutch_vs"] >= 2), 1),
        Achievement("clutch10", t("El último en pie"), t("10 clutches ganados"), "shield", "oro", len(clutches_won), 10),
        Achievement("streak", t("En racha"), t("5 victorias seguidas"), "bolt", "plata",
                    best_streak([g["result"] for g in games]), 5),
        Achievement("30k", t("Máquina"), t("30 kills en una partida"), "skull", "plata", most("kills"), 30),
        Achievement("adr", t("Demoledor"), t("150 de ADR en una partida"), "target", "oro", most("adr"), 150),
        Achievement("rating2", t("Partidazo"), t("Rating 2,00 en una partida"), "rank", "oro", most("rating"), 2.0),
        Achievement("mvp", t("El mejor de la cancha"), t("10 partidas con el mejor rating de los 10"), "crown", "plata",
                    sum(1 for m in matches if top_rated(m)), 10),
        Achievement("map", t("Dueño del mapa"), t("20 victorias en un mismo mapa"), "map", "plata",
                    max(per_map.values(), default=0), 20),
        Achievement("100", t("Veterano"), t("100 partidas jugadas"), "history", "bronce", len(games), 100),
        Achievement("500", t("Leyenda"), t("500 partidas jugadas"), "history", "oro", len(games), 500),
        Achievement("pistol", t("Pistolero"), t("Ganá 20 rondas de pistola"), "target", "bronce", pistol_wins, 20),
        Achievement("eco", t("Con lo justo"), t("Ganá 5 rondas en ahorro"), "bolt", "plata", eco_wins, 5),
        Achievement("flash", t("Encandilador"), t("10 enemigos cegados en una partida"), "flash", "bronce",
                    most("enemies_flashed"), 10),
        Achievement("nades", t("Artillero"), t("300 de daño con granadas en una partida"), "grenade", "plata",
                    most("util_damage"), 300),
        Achievement("premier10", t("Rango azul"), t("Llegá a 10.000 de Premier"), "rank", "plata", best_premier, 10000),
        Achievement("premier20", t("Rango rosa"), t("Llegá a 20.000 de Premier"), "rank", "oro", best_premier, 20000),
    ]


@dataclass
class Forecast:
    current: int
    expected: int
    low: int
    high: int
    per_match: float
    games: int
    points: list[float]     # rating esperado después de cada una de las próximas partidas


def premier_forecast(matches: list[dict], ahead: int = 10, window: int = 15) -> Forecast | None:
    """Dónde vas a estar en Premier dentro de unas partidas si seguís como en las últimas.

    Usa el promedio de lo que sumaste o perdiste por partida, con un margen según cuánto varía."""
    premier = [m for m in matches if m.get("rank_type") == 11 and m.get("rank_new")]
    changes = [float(m.get("rank_change") or 0) for m in premier[-window:]]
    if len(changes) < 5:
        return None
    mean = sum(changes) / len(changes)
    spread = math.sqrt(sum((c - mean) ** 2 for c in changes) / (len(changes) - 1))
    current = int(premier[-1]["rank_new"])
    margin = ahead * spread / math.sqrt(len(changes))   # error del promedio, llevado a las partidas que vienen
    expected = current + mean * ahead
    return Forecast(current, round(expected), round(expected - margin), round(expected + margin), mean, len(changes),
                    [current + mean * (i + 1) for i in range(ahead)])


# Metas: tipo → (nombre, cómo leer tu valor actual). Las de métricas usan tus últimas 10 partidas con demo.
GOAL_KINDS = {
    "premier": t("Rating de Premier"), "rating": t("Rating"), "adr": t("ADR"), "kast": t("KAST"), "hs": t("HS %"),
    "kd": "K/D", "win_rate": t("Victorias"),
}


def goal_value(kind: str, matches: list[dict], recent: dict) -> float | None:
    if kind == "premier":
        premier = [m for m in matches if m.get("rank_type") == 11 and m.get("rank_new")]
        return float(premier[-1]["rank_new"]) if premier else None
    if kind == "win_rate":
        last = matches[-10:]
        return sum(1 for m in last if m["result"] == "W") / len(last) if last else None
    return recent.get(kind)


def goal_progress(goal: dict, current: float | None) -> float:
    """0 a 1: cuánto recorriste desde donde estabas al ponerte la meta hasta el objetivo."""
    if current is None:
        return 0.0
    start, target = goal.get("start"), goal["target"]
    if start is None or start >= target:
        return min(1.0, max(0.0, current / target)) if target else 1.0
    return min(1.0, max(0.0, (current - start) / (target - start)))

"""Sesiones: cómo rendís según cuántas partidas seguidas llevás, si venís de perder y el horario.

Un consejo solo aparece si la diferencia alcanza para no ser casualidad: con pocas partidas o una diferencia chica
se muestran los números, pero la app no saca conclusiones."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta

from .i18n import t

SESSION_GAP = timedelta(hours=3)   # más tiempo que esto entre dos partidas: empieza otra sesión
MIN_GAMES = 15                     # partidas mínimas en cada grupo para comparar
SIGNIFICANT = 1.96                 # diferencia que solo saldría por azar 1 de cada 20 veces
POSITIONS = 5                      # la última fila agrupa de la 5.ª partida en adelante
BANDS = (("madrugada", t("Madrugada (0 a 6)"), 0, 6), ("manana", t("Mañana (6 a 12)"), 6, 12),
         ("tarde", t("Tarde (12 a 19)"), 12, 19), ("noche", t("Noche (19 a 24)"), 19, 24))


@dataclass
class Bucket:
    title: str
    games: int = 0
    wins: int = 0
    kills: int = 0
    deaths: int = 0
    rating_sum: float = 0.0
    rated: int = 0

    def add(self, row: dict) -> None:
        self.games += 1
        self.wins += row["result"] == "W"
        self.kills += row.get("k") or 0
        self.deaths += row.get("d") or 0
        if row.get("rating") is not None:
            self.rating_sum += row["rating"]
            self.rated += 1

    @property
    def win_rate(self) -> float | None:
        return self.wins / self.games if self.games else None

    @property
    def kd(self) -> float | None:
        return self.kills / self.deaths if self.deaths else None

    @property
    def rating(self) -> float | None:
        return self.rating_sum / self.rated if self.rated else None


@dataclass
class Finding:
    key: str
    title: str
    detail: str
    bad: bool


@dataclass
class Report:
    sessions: int
    games: int
    average_length: float
    positions: list[Bucket]
    momentum: list[Bucket]
    bands: list[Bucket]
    findings: list[Finding]
    stop_after: int | None      # desde qué partida de la sesión te conviene cortar (None: no se nota)
    current: list[dict]         # las partidas de la sesión en curso (vacío si no estás jugando)


def _when(row: dict) -> datetime | None:
    try:
        return datetime.fromisoformat(row["played_at"])
    except (TypeError, ValueError, KeyError):
        return None


def split_sessions(rows: list[dict]) -> list[list[dict]]:
    """Agrupa las partidas con fecha real en sesiones, de la más vieja a la más nueva."""
    dated = sorted(((w, r) for r in rows if r.get("date_ok", True) and (w := _when(r))), key=lambda item: item[0])
    sessions: list[list[dict]] = []
    previous = None
    for when, row in dated:
        if previous is None or when - previous > SESSION_GAP:
            sessions.append([])
        sessions[-1].append(row)
        previous = when
    return sessions


def gap_score(a: Bucket, b: Bucket) -> float:
    """Qué tan distinta es la tasa de victorias de dos grupos, en desvíos (prueba z de dos proporciones)."""
    if a.games < MIN_GAMES or b.games < MIN_GAMES:
        return 0.0
    pooled = (a.wins + b.wins) / (a.games + b.games)
    spread = math.sqrt(pooled * (1 - pooled) * (1 / a.games + 1 / b.games))
    return (a.win_rate - b.win_rate) / spread if spread else 0.0


def _pct(value: float) -> str:
    return f"{value * 100:.0f} %"


def _fatigue(sessions: list[list[dict]]) -> tuple[int | None, Finding | None]:
    """Busca desde qué partida de la sesión ganás claramente menos que en las anteriores."""
    best: tuple[float, int, Bucket, Bucket] | None = None
    for start in range(2, POSITIONS + 1):
        early, late = Bucket(""), Bucket("")
        for session in sessions:
            for position, row in enumerate(session, 1):
                (late if position >= start else early).add(row)
        score = gap_score(late, early)
        if score <= -SIGNIFICANT and (best is None or score < best[0]):
            best = (score, start, early, late)
    if best is None:
        return None, None
    _score, start, early, late = best
    return start, Finding("fatigue", t("Rendís menos desde la partida {0} de cada sesión").format(start),
                          t("Desde esa partida ganás el {0} ({1} partidas), contra el {2} antes ({3} partidas). "
                            "Es un buen punto para cortar.").format(_pct(late.win_rate), late.games,
                                                                    _pct(early.win_rate), early.games), True)


def analyze_sessions(rows: list[dict], now: datetime | None = None) -> Report:
    now = now or datetime.now()
    sessions = split_sessions(rows)
    positions = [Bucket(t("Partida {0}").format(i)) for i in range(1, POSITIONS)] + [Bucket(t("Partida {0} o más").format(POSITIONS))]
    after_win, after_loss, after_two = Bucket(t("Después de ganar")), Bucket(t("Después de perder")), Bucket(t("Después de perder 2 seguidas"))
    bands = [Bucket(title) for _key, title, _low, _high in BANDS]
    for session in sessions:
        for position, row in enumerate(session):
            positions[min(position, POSITIONS - 1)].add(row)
            when = _when(row)
            next(b for b, band in zip(bands, BANDS) if band[2] <= when.hour < band[3]).add(row)
            if position:
                previous = session[position - 1]["result"]
                if previous == "W":
                    after_win.add(row)
                elif previous == "L":
                    after_loss.add(row)
                    if position > 1 and session[position - 2]["result"] == "L":
                        after_two.add(row)

    findings: list[Finding] = []
    stop_after, fatigue = _fatigue(sessions)
    if fatigue:
        findings.append(fatigue)
    if gap_score(after_loss, after_win) <= -SIGNIFICANT:
        findings.append(Finding("tilt", t("Una derrota te pesa en la partida siguiente"),
                                t("Después de perder ganás el {0} ({1} partidas); después de ganar, el {2} ({3} partidas). "
                                  "Tomate un descanso antes de volver a buscar.").format(
                                    _pct(after_loss.win_rate), after_loss.games, _pct(after_win.win_rate), after_win.games), True))
    rest_scores = []
    for band in bands:
        rest = Bucket("")
        rest.games = sum(b.games for b in bands) - band.games
        rest.wins = sum(b.wins for b in bands) - band.wins
        rest_scores.append((gap_score(band, rest), band, rest))
    if rest_scores:
        score, band, rest = max(rest_scores, key=lambda item: abs(item[0]))
        if abs(score) >= SIGNIFICANT:
            findings.append(Finding("hours", (t("Tu mejor horario: {0}") if score > 0 else t("Tu peor horario: {0}")).format(band.title),
                                    t("En esa franja ganás el {0} ({1} partidas), contra el {2} en el resto.").format(
                                        _pct(band.win_rate), band.games, _pct(rest.win_rate)), score < 0))
    current: list[dict] = []
    if sessions:
        last = _when(sessions[-1][-1])
        if timedelta(0) <= now - last <= SESSION_GAP:
            current = sessions[-1]
    games = sum(len(s) for s in sessions)
    return Report(len(sessions), games, games / len(sessions) if sessions else 0.0, positions,
                  [after_win, after_loss, after_two], bands, findings, stop_after, current)


def current_advice(report: Report) -> str:
    """Qué conviene hacer ahora, según la sesión que estás jugando. Vacío si no hay nada que decir."""
    games = report.current
    if not games:
        return ""
    if report.stop_after and len(games) + 1 >= report.stop_after:
        return t("La próxima sería tu partida {0} de hoy, y desde la {1} te suele ir peor. Buen momento para cortar.").format(
            len(games) + 1, report.stop_after)
    if len(games) >= 2 and all(g["result"] == "L" for g in games[-2:]):
        return t("Venís de 2 derrotas seguidas. Un descanso corto antes de la próxima no te hace mal.")
    return ""

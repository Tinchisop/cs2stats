"""Promedios por rango de Premier y dónde destacás.

La referencia sale de tus propias partidas: cada demo trae a los otros 9 jugadores con su rating de Premier,
así que se comparan tus números con los de jugadores de tu mismo rango que jugaron con vos o contra vos.
"""

from __future__ import annotations

from .i18n import t

from dataclasses import dataclass

TIERS = [  # rango de Premier, nombre, color del juego
    (0, 4999, "Gris", "#b0c3d9"), (5000, 9999, "Celeste", "#8cc6ff"), (10000, 14999, "Azul", "#6a7dff"),
    (15000, 19999, "Violeta", "#c166ff"), (20000, 24999, "Rosa", "#f03cff"), (25000, 29999, "Rojo", "#eb4b4b"),
    (30000, 10 ** 9, "Dorado", "#fed700"),
]
MIN_ROUNDS = 10          # jugadores que jugaron menos rondas no sirven de referencia
MIN_SAMPLES = 12         # con menos jugadores en tu rango se usa el promedio de todos tus lobbies


@dataclass(frozen=True)
class Metric:
    key: str
    label: str
    category: str
    kind: str            # "num2", "num1", "num0", "pct"
    higher_better: bool = True
    help: str = ""


METRICS = [
    Metric("rating", t("Rating"), t("General"), "num2", help=t("Impacto general. 1,00 es el promedio.")),
    Metric("adr", t("ADR"), t("General"), "num1", help=t("Daño por ronda.")),
    Metric("kd", "K/D", t("General"), "num2", help=t("Kills por cada muerte.")),
    Metric("kast", t("KAST"), t("General"), "pct", help=t("Rondas con kill, asistencia, supervivencia o muerte vengada.")),
    Metric("kpr", t("Kills por ronda"), t("Duelos"), "num2"),
    Metric("hs", t("HS %"), t("Puntería"), "pct", help=t("Kills a la cabeza.")),
    Metric("opening_win", t("Primeros duelos ganados"), t("Duelos"), "pct"),
    Metric("opening_rate", t("Participación en primeros duelos"), t("Duelos"), "pct",
           help=t("En cuántas rondas peleás el primer duelo.")),
    Metric("first_team_death", t("Morís primero"), t("Posicionamiento"), "pct", higher_better=False,
           help=t("Rondas en las que sos la primera baja de tu equipo.")),
    Metric("traded", t("Muertes vengadas"), t("Posicionamiento"), "pct", help=t("Tu equipo mata a tu asesino en 5 s.")),
    Metric("trade_kills_pr", t("Kills de cambio por ronda"), t("Posicionamiento"), "num2",
           help=t("Vengás a un compañero en 5 s.")),
    Metric("util_adr", t("Daño de granadas por ronda"), t("Utilidad"), "num1"),
    Metric("flashes_per_round", t("Flashes por ronda"), t("Utilidad"), "num2"),
    Metric("blinded_per_flash", t("Enemigos cegados por flash"), t("Utilidad"), "num2"),
    Metric("team_flash_rate", t("Compañeros cegados por flash"), t("Utilidad"), "num2", higher_better=False),
    Metric("clutch_rate", t("Clutches ganados"), t("Clutch"), "pct"),
]
BY_KEY = {m.key: m for m in METRICS}


def tier_of(rating: int | None) -> tuple | None:
    if not rating:
        return None
    return next((t for t in TIERS if t[0] <= rating <= t[1]), None)


def tier_label(tier: tuple) -> str:
    low, high = tier[0], tier[1]
    top = "+" if high >= 10 ** 8 else f"–{high + 1:,}".replace(",", ".")
    return f"{low:,}".replace(",", ".") + top


def derived(stats: dict) -> dict:
    """Agrega métricas que no vienen directas del resumen."""
    values = dict(stats)
    rounds = stats.get("rounds") or 0
    values["trade_kills_pr"] = stats.get("trade_kills", 0) / rounds if rounds else None
    flashes = stats.get("flashes") or 0
    values["team_flash_rate"] = (stats.get("team_flashed", 0) / flashes) if flashes >= 3 else None
    if (stats.get("blinded_per_flash") is not None) and flashes < 3:
        values["blinded_per_flash"] = None
    clutches = stats.get("clutches") or 0
    values["clutch_rate"] = stats.get("clutches_won", 0) / clutches if clutches >= 2 else None
    return values


def lobby_samples(matches: list[dict]) -> list[dict]:
    """Un registro por jugador y partida (sin vos), con su rating de Premier si lo tenía."""
    samples = []
    for m in matches:
        for player in m.get("scoreboard") or []:
            stats = player.get("stats")
            if player.get("me") or not stats or (stats.get("rounds") or 0) < MIN_ROUNDS:
                continue
            samples.append({"premier": player.get("premier"), "values": derived(stats), "source": m.get("source")})
    return samples


@dataclass
class Comparison:
    metric: Metric
    mine: float | None
    average: float | None
    percentile: float | None   # 0 a 100: porcentaje de jugadores de referencia que te quedan por debajo
    samples: int

    @property
    def delta(self) -> float | None:
        if self.mine is None or self.average is None:
            return None
        return self.mine - self.average

    @property
    def score(self) -> float | None:
        """Percentil "orientado": alto siempre es bueno, aunque la métrica sea de las que conviene tener bajas."""
        if self.percentile is None:
            return None
        return self.percentile if self.metric.higher_better else 100 - self.percentile


def compare(my_stats: dict, samples: list[dict], my_rating: int | None) -> tuple[list[Comparison], str, int]:
    """Compara tus números con tu rango. Devuelve (comparaciones, descripción de la referencia, jugadores)."""
    tier = tier_of(my_rating)
    pool = [s for s in samples if tier and tier_of(s["premier"]) == tier]
    if tier and len(pool) >= MIN_SAMPLES:
        reference = t('jugadores {0} ({1}) de tus partidas').format(tier[2].lower(), tier_label(tier))
    else:
        pool = samples
        reference = t("todos los jugadores de tus partidas")
    mine = derived(my_stats)
    result = []
    for metric in METRICS:
        values = sorted(v for v in (s["values"].get(metric.key) for s in pool) if v is not None)
        value = mine.get(metric.key)
        average = sum(values) / len(values) if values else None
        percentile = None
        if value is not None and len(values) >= 5:
            below = sum(1 for v in values if v < value) + 0.5 * sum(1 for v in values if v == value)
            percentile = 100 * below / len(values)
        result.append(Comparison(metric, value, average, percentile, len(values)))
    return result, reference, len(pool)


def highlights(comparisons: list[Comparison], count: int = 3) -> tuple[list[Comparison], list[Comparison]]:
    """Dónde destacás (percentil alto) y dónde quedás más abajo de tu rango."""
    ranked = [c for c in comparisons if c.score is not None and c.samples >= 5]
    ranked.sort(key=lambda c: -c.score)
    strong = [c for c in ranked if c.score >= 60][:count]
    weak = [c for c in reversed(ranked) if c.score <= 40][:count]
    return strong, weak

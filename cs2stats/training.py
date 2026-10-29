"""Entrenamiento: retos de la semana armados con tus puntos flojos y mapas del Workshop para practicar cada cosa.

Los retos se eligen solos cada lunes con tus partidas anteriores a esa semana (así no cambian a mitad de semana) y el
avance cuenta las partidas con demo que jugás de lunes a domingo."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from .i18n import t
from .insights import pct
from .metrics import aim_summary, map_label


@dataclass(frozen=True)
class Workout:
    key: str
    workshop_id: int
    title: str           # nombre del mapa en el Workshop (no se traduce)
    focus: str
    routine: str
    minutes: int
    command: str = ""    # para la consola de CS2, si se conoce el nombre del mapa


# Mapas del Workshop de CS2 (IDs revisados en la API de Steam).
WORKOUTS = {w.key: w for w in [
    Workout("aim_botz", 3070244462, "Aim Botz - Aim Training (CS2)", t("Mira a la altura de la cabeza"),
            t("3 series de 100 bots con AK-47. Entre bot y bot la mira no baja de la altura de la cabeza: movés el mouse "
              "de costado, no de arriba a abajo."), 10, "map_workshop 3070244462 aim_botz"),
    Workout("reflex", 3070758981, "FAST AIM/REFLEX TRAINING [CS2]", t("Reacción: pegarle antes al rival"),
            t("5 minutos en el modo rápido. Tirá apenas aparece el blanco, sin perseguirlo con la mira; si fallás mucho, "
              "bajá la velocidad y volvé a subirla."), 8),
    Workout("recoil", 3100869952, "Recoil Master - Spray Training (CS2)", t("Control de la ráfaga"),
            t("10 ráfagas de 15 balas con AK-47 y 10 con M4 siguiendo el dibujo de la pared. Después, las mismas sin "
              "mirar el dibujo."), 8, "map_workshop 3100869952 recoil_master"),
    Workout("refrag", 3416003536, "Refrag.gg - Aim, Movement, Crosshair, Prefire!", t("Counter-strafe y movimiento"),
            t("Caminá de lado a lado y frená con la tecla contraria antes de cada tiro. Solo disparás cuando estás quieto: "
              "al principio lento, después más rápido."), 10),
    Workout("yprac", 3070715607, "Yprac Hub by Yesber", t("Prefires y latas de cada mapa"),
            t("Elegí tu mapa más jugado en modo Prefire y limpiá cada ángulo como T y como CT. Después repasá las flashes "
              "del sitio que más atacás."), 15),
    Workout("mirage_prefire", 3267302800, "Mirage Prefire", t("Primeros duelos en Mirage"),
            t("Hacé el recorrido de cada sitio en dificultad normal hasta no fallar ningún ángulo; después subí la "
              "dificultad."), 12),
    Workout("dust2_prefire", 3295650711, "Dust 2 Prefire", t("Primeros duelos en Dust II"),
            t("Hacé el recorrido de cada sitio en dificultad normal hasta no fallar ningún ángulo; después subí la "
              "dificultad."), 12),
    Workout("duels", 3101654056, "CS2: 1v1 AIM MAP", t("Duelos contra un amigo"),
            t("10 rondas contra un amigo, solo rifles. Sirve para los primeros duelos y para no apurar el tiro."), 15),
]}
PREFIRE_MAPS = {"de_mirage": "mirage_prefire", "de_dust2": "dust2_prefire"}


def my_aim(matches: list[dict], count: int = 10) -> dict | None:
    """Tu puntería sumando las cuentas crudas de tus últimas partidas con puntería medida."""
    total: dict[str, float] = {}
    used = 0
    for m in reversed(matches):
        me = next((p for p in m.get("scoreboard") or [] if p.get("me")), None)
        raw = (m.get("aim") or {}).get(str(me["steamid"])) if me else None
        if not raw:
            continue
        for key, value in raw.items():
            total[key] = total.get(key, 0) + (value or 0)
        used += 1
        if used >= count:
            break
    return aim_summary(total) if used else None


def recommend(matches: list[dict], comparisons: list) -> list[tuple[Workout, str, bool]]:
    """Mapas para practicar lo que más te cuesta: (mapa, el porqué en tus números, si es un punto flojo).
    Si no hay nada flojo, un calentamiento."""
    picks: list[tuple[Workout, str, bool]] = []
    aim = my_aim(matches) or {}

    def add(key: str, reason: str, weak: bool = True) -> None:
        if key not in {w.key for w, _r, _w in picks}:
            picks.append((WORKOUTS[key], reason, weak))
    if (aim.get("time_to_damage") or 0) > 600:
        add("reflex", t("Tardás {0} ms en pegarle a un rival desde que aparece (bien: menos de 450).").format(
            round(aim["time_to_damage"])))
    if (aim.get("crosshair") or 0) > 7:
        add("aim_botz", t("Cuando aparece un rival, tu mira está a {0}° de su cabeza (bien: menos de 5°).").format(
            f"{aim['crosshair']:.1f}"))
    if aim.get("spray_accuracy") is not None and aim["spray_accuracy"] < 0.2:
        add("recoil", t("Solo pega el {0} de tus balas de ráfaga (bien: más del 30 %).").format(pct(aim["spray_accuracy"])))
    if aim.get("counter_strafe") is not None and aim["counter_strafe"] < 0.7:
        add("refrag", t("Solo el {0} de tus primeros tiros sale con el arma quieta (bien: más del 85 %).").format(
            pct(aim["counter_strafe"])))
    weak = {c.metric.key: c for c in comparisons if c.score is not None and c.score < 40}
    if "opening_win" in weak or "first_team_death" in weak:
        played: dict[str, int] = {}
        for m in matches[-20:]:
            played[m["map"]] = played.get(m["map"], 0) + 1
        top = max(played, key=played.get) if played else ""
        comp = weak.get("opening_win") or weak["first_team_death"]
        reason = t("{0}: vos {1}, tu rango {2}.").format(comp.metric.label, _fmt(comp.mine, comp.metric.kind),
                                                          _fmt(comp.average, comp.metric.kind))
        add(PREFIRE_MAPS.get(top, "yprac"), reason)
    if "blinded_per_flash" in weak or "team_flash_rate" in weak or "util_adr" in weak:
        comp = weak.get("team_flash_rate") or weak.get("blinded_per_flash") or weak["util_adr"]
        add("yprac", t("{0}: vos {1}, tu rango {2}. Repasá las flashes y las latas del mapa.").format(
            comp.metric.label, _fmt(comp.mine, comp.metric.kind), _fmt(comp.average, comp.metric.kind)))
    if not picks:
        add("aim_botz", t("Calentamiento antes de jugar: no hay un punto flojo claro en tu puntería."), False)
        add("recoil", t("Mantené la ráfaga afilada aunque vengas bien."), False)
    return picks[:4]


def _fmt(value, kind: str) -> str:
    if value is None:
        return "—"
    if kind == "pct":
        return pct(value)
    return f"{value:.2f}" if kind == "num2" else f"{value:.1f}"


# Retos de la semana ─────────────────────────────────────────────────────────────────────────────────────────────

@dataclass
class Challenge:
    key: str
    title: str
    detail: str
    value: float
    goal: float

    @property
    def done(self) -> bool:
        return self.value >= self.goal

    @property
    def share(self) -> float:
        return min(1.0, self.value / self.goal) if self.goal else 1.0


def week_start(now: datetime) -> datetime:
    monday = now - timedelta(days=now.weekday())
    return monday.replace(hour=0, minute=0, second=0, microsecond=0)


def _round_to(value: float, step: int) -> int:
    return int(round(value / step) * step)


def _streak(flags: list[bool]) -> int:
    best = run = 0
    for flag in flags:
        run = run + 1 if flag else 0
        best = max(best, run)
    return best


def weekly_challenges(matches: list[dict], now: datetime) -> tuple[list[Challenge], datetime]:
    """Los 3 retos de la semana de `now`: los 2 de tus puntos más flojos y 1 que rota cada semana.

    matches: tus partidas con demo, con su resumen en m["s"]."""
    start = week_start(now)
    end = start + timedelta(days=7)
    begin, finish = start.isoformat(timespec="seconds"), end.isoformat(timespec="seconds")
    before = [m for m in matches if (m["played_at"] or "") < begin and m.get("s")][-20:]
    week = [m for m in matches if begin <= (m["played_at"] or "") < finish and m.get("s")]

    def average(key: str, default: float) -> float:
        values = [m["s"].get(key) for m in before if m["s"].get(key) is not None]
        return sum(values) / len(values) if values else default
    rounds = sum(m["s"]["rounds"] for m in before) or 1
    played: dict[str, int] = {}
    for m in before or week:
        played[m["map"]] = played.get(m["map"], 0) + 1
    top_map = max(played, key=played.get) if played else ""
    flashes = sum(m["s"].get("flashes") or 0 for m in before)
    team_rate = sum(m["s"].get("team_flashed") or 0 for m in before) / flashes if flashes else 0
    per_flash = sum(m["s"].get("enemies_flashed") or 0 for m in before) / flashes if flashes else 0
    adr_goal = max(70, min(110, _round_to(average("adr", 75) + 5, 5)))
    kast_goal = max(0.65, min(0.85, round(average("kast", 0.68) + 0.05, 2)))
    blind_goal = max(15, min(40, _round_to(average("enemies_flashed", 5) * 3, 5)))
    trade_goal = max(4, min(10, round(sum(m["s"].get("trade_kills") or 0 for m in before) / max(1, len(before)) * 2.5)))

    # Cada reto: (clave, qué tan flojo estás en eso (0 a 1), cómo se arma).
    options = {
        "trades": (min(1.0, max(0.0, (0.14 - sum(m["s"].get("trade_kills") or 0 for m in before) / rounds) / 0.14)),
                   lambda: Challenge("trades", t("Conseguí {0} kills de cambio en {1}").format(trade_goal, map_label(top_map)),
                                     t("Vengá a un compañero en menos de 5 segundos. Jugá cerca del que entra primero."),
                                     sum(m["s"].get("trade_kills") or 0 for m in week if m["map"] == top_map), trade_goal)),
        "adr": (min(1.0, max(0.0, (85 - average("adr", 85)) / 25)),
                lambda: Challenge("adr", t("Mantené {0} de ADR o más en 3 partidas seguidas").format(adr_goal),
                                  t("Que cada ronda cuente: daño con la utilidad y no regalar el arma en los ahorros."),
                                  _streak([(m["s"].get("adr") or 0) >= adr_goal for m in week]), 3)),
        "clean_flash": (min(1.0, team_rate / 0.4),
                        lambda: Challenge("clean_flash", t("Jugá 3 partidas tirando flashes sin cegar a ningún compañero"),
                                          t("Avisá antes de tirarla y tirala por encima o rebotada, no por delante de tu equipo."),
                                          sum(1 for m in week if (m["s"].get("flashes") or 0) >= 3 and not m["s"].get("team_flashed")), 3)),
        "blind": (min(1.0, max(0.0, (1.0 - per_flash) / 1.0)),
                  lambda: Challenge("blind", t("Cegá a {0} rivales con tus flashes").format(blind_goal),
                                    t("Usá las flashes de la sección Latas para tu mapa: las que se explotan arriba del ángulo."),
                                    sum(m["s"].get("enemies_flashed") or 0 for m in week), blind_goal)),
        "openings": (min(1.0, max(0.0, (0.5 - average("opening_win", 0.5)) / 0.2)),
                     lambda: Challenge("openings", t("Ganá 8 primeros duelos"),
                                       t("Peleá el primero con ayuda: una flash propia o de un compañero antes de asomar."),
                                       sum(m["s"].get("opening_kills") or 0 for m in week), 8)),
        "first_death": (min(1.0, max(0.0, (average("first_team_death", 0.15) - 0.12) / 0.12)),
                        lambda: Challenge("first_death", t("Jugá 3 partidas siendo el primero en morir en menos del 12 % de las rondas"),
                                          t("No seas el primero en asomar sin información; entrá de segundo para poder cambiar."),
                                          sum(1 for m in week if (m["s"].get("first_team_death") or 0) < 0.12), 3)),
        "kast": (min(1.0, max(0.0, (0.72 - average("kast", 0.72)) / 0.12)),
                 lambda: Challenge("kast", t("Hacé {0} de KAST o más en 3 partidas").format(pct(kast_goal)),
                                   t("En cada ronda: una kill, una asistencia, sobrevivir o que te venguen."),
                                   sum(1 for m in week if (m["s"].get("kast") or 0) >= kast_goal), 3)),
        "clutch": (0.2, lambda: Challenge("clutch", t("Ganá 2 clutches"),
                                          t("Quedando último: escuchá, usá el tiempo y peleá de a un rival por vez."),
                                          sum(m["s"].get("clutches_won") or 0 for m in week), 2)),
    }
    if not top_map:
        options.pop("trades")   # sin partidas todavía no hay un mapa para el reto
    ranked = sorted(options, key=lambda k: -options[k][0])
    chosen = ranked[:2]
    rest = [k for k in ranked if k not in chosen]
    chosen.append(rest[start.isocalendar()[1] % len(rest)])
    return [options[k][1]() for k in chosen], start


def past_weeks(matches: list[dict], now: datetime, count: int = 6) -> list[tuple[datetime, int, int]]:
    """Cómo te fue en los retos de las semanas anteriores: (lunes, cumplidos, total), de la más vieja a la más nueva."""
    result = []
    for back in range(count, 0, -1):
        challenges, start = weekly_challenges(matches, week_start(now) - timedelta(days=7 * back))
        if any(m for m in matches if start.isoformat() <= (m["played_at"] or "") < (start + timedelta(days=7)).isoformat()):
            result.append((start, sum(1 for c in challenges if c.done), len(challenges)))
    return result

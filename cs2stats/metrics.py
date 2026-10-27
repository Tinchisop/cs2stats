"""Cuentas sobre rondas ya leídas. Todo sale de las listas de rondas guardadas."""

from __future__ import annotations

from .i18n import t

import math
from collections import Counter
from typing import Iterable

MAP_NAMES = {
    "de_mirage": t("Mirage"), "de_inferno": t("Inferno"), "de_nuke": t("Nuke"), "de_ancient": t("Ancient"),
    "de_anubis": t("Anubis"), "de_dust2": t("Dust II"), "de_train": t("Train"), "de_overpass": t("Overpass"),
    "de_vertigo": t("Vertigo"), "de_cache": t("Cache"), "de_italy": t("Italy"), "de_office": t("Office"),
}
SOURCE_NAMES = {"premier": t("Premier"), "faceit": t("FACEIT"), "competitivo": t("Competitivo"),
                "wingman": t("Wingman"), "valve": t("Valve"), "otro": t("Otra")}
WEAPON_NAMES = {
    "ak47": t("AK-47"), "m4a1_silencer": "M4A1-S", "m4a1": "M4A4", "awp": t("AWP"), "deagle": t("Desert Eagle"),
    "usp_silencer": t("USP-S"), "hkp2000": "P2000", "glock": t("Glock-18"), "p250": "P250", "tec9": t("Tec-9"),
    "fiveseven": t("Five-SeveN"), "cz75a": t("CZ75-Auto"), "elite": t("Dual Berettas"), "revolver": "R8",
    "galilar": t("Galil AR"), "famas": t("FAMAS"), "aug": t("AUG"), "sg556": t("SG 553"), "ssg08": t("SSG 08"),
    "mac10": t("MAC-10"), "mp9": t("MP9"), "mp7": t("MP7"), "mp5sd": t("MP5-SD"), "ump45": t("UMP-45"), "p90": "P90",
    "bizon": t("PP-Bizon"), "nova": t("Nova"), "xm1014": t("XM1014"), "mag7": t("MAG-7"), "sawedoff": t("Sawed-Off"),
    "negev": t("Negev"), "m249": "M249", "g3sg1": t("G3SG1"), "scar20": t("SCAR-20"), "hegrenade": t("Granada HE"),
    "inferno": t("Molotov"), "knife": t("Cuchillo"), "knife_t": t("Cuchillo"), "taser": t("Zeus"),
}


def map_label(raw: str) -> str:
    return MAP_NAMES.get(raw, raw.removeprefix("de_").replace("_", " ").title())


def weapon_label(raw: str) -> str:
    if raw.startswith("knife") or raw.startswith("bayonet"):
        return t("Cuchillo")
    return WEAPON_NAMES.get(raw, raw.upper())


def ratio(part: float, whole: float) -> float | None:
    return part / whole if whole else None


def summarize(rounds: Iterable[dict]) -> dict:
    """Resumen de un conjunto de rondas (de una partida, de un mapa, de un lado, etc.)."""
    rounds = list(rounds)
    n = len(rounds)
    kills = sum(r["kills"] for r in rounds)
    deaths = sum(1 for r in rounds if r["died"])
    assists = sum(r["assists"] for r in rounds)
    hs = sum(r["hs_kills"] for r in rounds)
    damage = sum(r["damage"] for r in rounds)
    multi = Counter(min(r["kills"], 5) for r in rounds if r["kills"])
    openings = [r["opening"] for r in rounds if r["opening"]]
    lived = [r for r in rounds if r["died_live"]]
    clutches = [r for r in rounds if r["clutch_vs"]]
    flashes = sum(r["flash"] for r in rounds)
    # Rating 1.0 de HLTV (aproximado): kills, supervivencia y rondas con varias kills.
    if n:
        kill_rating = kills / n / 0.679
        survival_rating = (n - deaths) / n / 0.317
        multi_rating = (multi[1] + 4 * multi[2] + 9 * multi[3] + 16 * multi[4] + 25 * multi[5]) / n / 1.277
        rating = (kill_rating + 0.7 * survival_rating + multi_rating) / 2.7
    else:
        rating = None
    return {
        "rounds": n,
        "won": sum(1 for r in rounds if r["won"]),
        "win_rate": ratio(sum(1 for r in rounds if r["won"]), n),
        "kills": kills, "deaths": deaths, "assists": assists,
        "kd": kills / deaths if deaths else (float(kills) if kills else None),
        "adr": ratio(damage, n),
        "hs": ratio(hs, kills),
        "kast": ratio(sum(1 for r in rounds if r["kast"]), n),
        "rating": rating,
        "kpr": ratio(kills, n),
        "multi": dict(multi),
        "opening_duels": len(openings),
        "opening_kills": openings.count("kill"),
        "opening_deaths": openings.count("death"),
        "opening_win": ratio(openings.count("kill"), len(openings)),
        "opening_rate": ratio(len(openings), n),
        "first_team_death": ratio(sum(1 for r in rounds if r["first_team_death"]), n),
        "first_team_deaths": sum(1 for r in rounds if r["first_team_death"]),
        "traded": ratio(sum(1 for r in lived if r["traded"]), sum(1 for r in lived if r["tradeable"])),
        "tradeable_deaths": sum(1 for r in lived if r["tradeable"]),
        "untraded_deaths": sum(1 for r in lived if r["tradeable"] and not r["traded"]),
        "live_deaths": len(lived),
        "trade_kills": sum(r["trade_kills"] for r in rounds),
        "early_deaths": sum(1 for r in lived if r["death_time"] is not None and r["death_time"] < 25),
        "avg_death_time": ratio(sum(r["death_time"] for r in lived), len(lived)),
        "clutches": len(clutches),
        "clutches_won": sum(1 for r in clutches if r["clutch_won"]),
        "clutch_1v1": sum(1 for r in clutches if r["clutch_vs"] == 1),
        "clutch_1v1_won": sum(1 for r in clutches if r["clutch_vs"] == 1 and r["clutch_won"]),
        "flashes": flashes,
        "smokes": sum(r["smoke"] for r in rounds),
        "molotovs": sum(r["molotov"] for r in rounds),
        "hes": sum(r["he"] for r in rounds),
        "util_thrown": sum(r["flash"] + r["smoke"] + r["he"] + r["molotov"] for r in rounds),
        "enemies_flashed": sum(r["enemies_flashed"] for r in rounds),
        "team_flashed": sum(r["team_flashed"] for r in rounds),
        "blind_time": sum(r["blind_time"] for r in rounds),
        "flash_assists": sum(r["flash_assists"] for r in rounds),
        "util_damage": sum(r["util_damage"] for r in rounds),
        "util_adr": ratio(sum(r["util_damage"] for r in rounds), n),
        "flashes_per_round": ratio(flashes, n),
        "blinded_per_flash": ratio(sum(r["enemies_flashed"] for r in rounds), flashes),
        "he_damage": sum(r.get("he_damage", 0) for r in rounds),
        "he_team_damage": sum(r.get("he_team_damage", 0) for r in rounds),
    }


def scale_value(value: float | None, worst: float, best: float) -> float | None:
    """0 a 100 entre el peor y el mejor valor razonable (sirve aunque menos sea mejor)."""
    if value is None:
        return None
    return max(0.0, min(100.0, (value - worst) / (best - worst) * 100))


# Peor y mejor valor de cada parte de la nota de puntería.
AIM_SCALE = {"time_to_damage": (800, 300), "crosshair": (10, 2), "head_accuracy": (0.05, 0.40),
             "seen_accuracy": (0.12, 0.42), "counter_strafe": (0.45, 0.95), "spray_accuracy": (0.10, 0.45)}


def aim_rating(aim: dict | None) -> float | None:
    """Nota de puntería de 0 a 100: promedio de reacción, mira, cabeza, precisión, counter-strafe y ráfaga."""
    if not aim or not aim.get("shots"):
        return None
    parts = [scale_value(aim.get(key), *limits) for key, limits in AIM_SCALE.items()]
    parts = [p for p in parts if p is not None]
    return sum(parts) / len(parts) if parts else None


def utility_rating(stats: dict, unused: list | None = None) -> dict:
    """Nota de utilidad de 0 a 100 = raíz de (cantidad × calidad), como la de Leetify.

    Cantidad: granadas por ronda. Calidad: cuánto cegaron las flashes, el daño de las HE y cuántos compañeros cegaste."""
    rounds = max(1, stats.get("rounds") or 0)
    thrown = stats.get("util_thrown") or 0
    flashes, hes = stats.get("flashes") or 0, stats.get("hes") or 0
    enemies = stats.get("enemies_flashed") or 0
    blind = ratio(stats.get("blind_time") or 0, enemies)
    he_avg = ratio(stats.get("he_damage") or 0, hes)
    per_flash = ratio(enemies, flashes)
    friends = ratio(stats.get("team_flashed") or 0, flashes)
    quantity = 100 * (1 - math.exp(-0.7 * thrown / rounds))
    score = 0.6 * (per_flash or 0) * (blind or 0) + 0.6 * (he_avg or 0) / 20 - 0.3 * (friends or 0)
    quality = 100 * (1 - math.exp(-0.6 * max(0.0, score))) if thrown else 0.0
    return {
        "rating": math.sqrt(quantity * quality), "quality": quality, "quantity": quantity,
        "flash_assists": stats.get("flash_assists") or 0, "enemies_per_flash": per_flash, "friends_per_flash": friends,
        "blind_time": blind, "he_avg": he_avg, "he_team_avg": ratio(stats.get("he_team_damage") or 0, hes),
        "flashes": flashes, "smokes": stats.get("smokes") or 0, "hes": hes, "molotovs": stats.get("molotovs") or 0,
        "unused": ratio(unused[0], unused[1]) if unused else None,
    }


def impact_rating(entry: dict | None) -> dict:
    """Impacto (como el rating de Leetify): cuánto movés la probabilidad de ganar de tu equipo, promedio por ronda × 100."""
    if not entry or not entry.get("rounds"):
        return {"total": None, "T": None, "CT": None, "cats": {}, "rounds": {}}
    rounds, sides = entry["rounds"], entry.get("sides", {})

    def mean(values: list[float]) -> float | None:
        return sum(values) / len(values) * 100 if values else None
    return {"total": mean(list(rounds.values())),
            "T": mean([v for n, v in rounds.items() if sides.get(n) == "T"]),
            "CT": mean([v for n, v in rounds.items() if sides.get(n) == "CT"]),
            "cats": {k: v * 100 for k, v in entry.get("cats", {}).items()},
            "rounds": {int(n): v * 100 for n, v in rounds.items()}, "sides": {int(n): s for n, s in sides.items()}}


def player_numbers(match: dict, steamid) -> dict:
    """Todos los números de un jugador en una partida (los de la tabla, la puntería, la utilidad y el impacto)."""
    row = next((p for p in match.get("scoreboard", []) if str(p["steamid"]) == str(steamid)), None)
    if not row:
        return {}
    stats = row.get("stats") or {}
    detail = match.get("detail") or {}
    aim = aim_summary((match.get("aim") or {}).get(str(steamid))) or {}
    util = utility_rating(stats, (detail.get("unused") or {}).get(str(steamid)))
    impact = impact_rating((detail.get("impact") or {}).get(str(steamid)))
    if impact["total"] is not None and len(impact["rounds"]) < (stats.get("rounds") or 0):
        # Si estuvo conectado pero sin jugar (desconectado o AFK), esas rondas también cuentan para el promedio.
        impact["total"] = sum(impact["rounds"].values()) / stats["rounds"]
    rounds = max(1, stats.get("rounds") or 0)
    return {
        "impact": impact["total"], "impact_t": impact["T"], "impact_ct": impact["CT"],
        "aim_rating": aim_rating(aim), "utility_rating": util["rating"] if stats.get("util_thrown") is not None else None,
        "rating": row.get("rating"), "kills": row["kills"], "deaths": row["deaths"], "assists": row["assists"],
        "kd": row["kills"] / row["deaths"] if row["deaths"] else float(row["kills"]), "adr": row["adr"],
        "kast": stats.get("kast"), "hs": row["hs"] / row["kills"] if row["kills"] else None,
        "opening_attempts": ratio(stats.get("opening_duels") or 0, rounds), "opening_kills": stats.get("opening_kills"),
        "clutches_won": stats.get("clutches_won"), "trade_kills": stats.get("trade_kills"),
        "enemies_flashed": stats.get("enemies_flashed"), "util_damage": stats.get("util_damage"),
        **{key: aim.get(key) for key in ("time_to_damage", "crosshair", "head_accuracy", "seen_accuracy", "counter_strafe",
                                          "spray_accuracy", "accuracy")},
    }


def aim_summary(raw: dict | None) -> dict | None:
    """Puntería de un jugador a partir de las cuentas crudas de la demo (se pueden sumar entre partidas)."""
    if not raw:
        return None
    return {
        "seen_accuracy": ratio(raw["seen_hits"], raw["seen_shots"]),
        "time_to_damage": ratio(raw["ttd_sum"], raw["ttd_n"]),
        "crosshair": ratio(raw["xhair_sum"], raw["xhair_n"]),
        "head_accuracy": ratio(raw["head_hits"], raw["gun_hits"]),
        "first_bullet": ratio(raw["first_hits"], raw["first_shots"]),
        "spray_accuracy": ratio(raw["spray_hits"], raw["spray_shots"]),
        "counter_strafe": ratio(raw["strafe_ok"], raw["strafe_shots"]),
        "accuracy": ratio(raw["hits"], raw["shots"]),
        "shots": raw["shots"],
    }


def by_key(rounds: Iterable[dict], key) -> dict:
    groups: dict = {}
    for r in rounds:
        groups.setdefault(key(r), []).append(r)
    return groups

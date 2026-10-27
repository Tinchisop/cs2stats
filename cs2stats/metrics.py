"""Cuentas sobre rondas ya leídas. Todo sale de las listas de rondas guardadas."""

from __future__ import annotations

from .i18n import t

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
    }


def by_key(rounds: Iterable[dict], key) -> dict:
    groups: dict = {}
    for r in rounds:
        groups.setdefault(key(r), []).append(r)
    return groups

"""Vos y tus amigos: los compañeros con los que más jugaste, comparados en las mismas partidas."""

from __future__ import annotations

from .i18n import t

# Métricas del cara a cara: clave, nombre, formato ("num2", "num1", "pct"), más es mejor.
FACE_OFF = [
    ("rating", t("Rating"), "num2", True), ("adr", t("ADR"), "num1", True), ("kd", "K/D", "num2", True),
    ("kast", t("KAST"), "pct", True), ("hs", t("HS %"), "pct", True), ("opening_win", t("Primeros duelos ganados"), "pct", True),
    ("kpr", t("Kills por ronda"), "num2", True), ("first_team_death", t("Morís primero"), "pct", False),
    ("util_adr", t("Daño de granadas por ronda"), "num1", True), ("clutch_rate", t("Clutches ganados"), "pct", True),
]


def combine(stats: list[dict]) -> dict:
    """Junta los resúmenes de varias partidas pesando cada una por sus rondas."""
    rounds = sum(s.get("rounds") or 0 for s in stats)
    if not rounds:
        return {}

    def total(key: str) -> float:
        return sum(s.get(key) or 0 for s in stats)

    def weighted(key: str) -> float | None:
        pairs = [(s.get(key), s.get("rounds") or 0) for s in stats if s.get(key) is not None]
        weight = sum(w for _v, w in pairs)
        return sum(v * w for v, w in pairs) / weight if weight else None
    kills, deaths = total("kills"), total("deaths")
    openings = total("opening_duels")
    clutches = total("clutches")
    return {
        "rounds": rounds, "kills": kills, "deaths": deaths, "rating": weighted("rating"), "adr": weighted("adr"),
        "kd": kills / deaths if deaths else None, "kast": weighted("kast"), "kpr": kills / rounds,
        "hs": weighted("hs"), "opening_win": total("opening_kills") / openings if openings else None,
        "first_team_death": weighted("first_team_death"), "util_adr": weighted("util_adr"),
        "clutch_rate": total("clutches_won") / clutches if clutches else None,
    }


def friends(matches: list[dict], minimum: int = 2) -> list[dict]:
    """Compañeros de equipo que aparecen en al menos `minimum` de tus partidas con demo, con los números de los dos
    en esas mismas partidas. Ordenados por cantidad de partidas juntos."""
    together: dict[str, dict] = {}
    for m in matches:
        board = m.get("scoreboard") or []
        me = next((p for p in board if p.get("me")), None)
        if not me or not me.get("stats"):
            continue
        for p in board:
            if p.get("me") or not p.get("ally") or not p.get("stats"):
                continue
            entry = together.setdefault(str(p["steamid"]), {"steamid": p["steamid"], "name": p.get("name") or "",
                                                            "matches": [], "mine": [], "theirs": []})
            entry["name"] = p.get("name") or entry["name"]
            entry["matches"].append(m)
            entry["mine"].append(me["stats"])
            entry["theirs"].append(p["stats"])
    result = []
    for entry in together.values():
        games = entry["matches"]
        if len(games) < minimum:
            continue
        wins = sum(1 for g in games if g["result"] == "W")
        result.append({"steamid": entry["steamid"], "name": entry["name"], "games": len(games), "wins": wins,
                       "win_rate": wins / len(games), "mine": combine(entry["mine"]), "theirs": combine(entry["theirs"]),
                       "matches": games})
    result.sort(key=lambda f: (-f["games"], -f["win_rate"]))
    return result


def score(friend: dict) -> tuple[int, int]:
    """Cuántas métricas gana cada uno: (vos, tu amigo)."""
    mine = theirs = 0
    for key, _title, _kind, higher in FACE_OFF:
        a, b = friend["mine"].get(key), friend["theirs"].get(key)
        if a is None or b is None or a == b:
            continue
        if (a > b) == higher:
            mine += 1
        else:
            theirs += 1
    return mine, theirs

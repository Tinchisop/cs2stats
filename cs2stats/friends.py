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
        # Juego en equipo (por ronda): flashes que cegaron rivales, asistencias de flash, cambios y quedar último vivo.
        "flashes_pr": total("enemies_flashed") / rounds, "flash_assists_pr": total("flash_assists") / rounds,
        "trade_pr": total("trade_kills") / rounds, "last_alive_pr": clutches / rounds,
        "survival": 1 - deaths / rounds, "opening_pr": openings / rounds,
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


def synergy(friend: dict, matches: list[dict]) -> dict:
    """Cuánto ganás con tu amigo y sin tu amigo, y cuánto te ayuda en la ronda (lo que hizo en las partidas juntos)."""
    together = {m["id"] for m in friend["matches"]}
    apart = [m for m in matches if m["id"] not in together and m.get("scoreboard")]
    theirs = friend["theirs"]
    return {
        "with": friend["win_rate"], "games": friend["games"],
        "without": sum(1 for m in apart if m["result"] == "W") / len(apart) if apart else None, "apart": len(apart),
        "flashes_pr": theirs.get("flashes_pr"), "flash_assists": theirs.get("flash_assists_pr"),
        "trade_pr": theirs.get("trade_pr"), "rating_with_you": friend["mine"].get("rating"),
    }


def team_roles(found: list[dict], me: dict, my_name: str) -> dict[str, list[dict]]:
    """Quién abre los sitios con utilidad y cambios (Entry Assistant) y quién queda más veces último vivo (Lurk / Saver).

    found: la lista de friends(); me: tus números combinados de todas tus partidas con demo."""
    people = [{"name": my_name, "me": True, "stats": me}] + [{"name": f["name"], "me": False, "stats": f["theirs"],
                                                               "steamid": f["steamid"]} for f in found[:8]]
    people = [p for p in people if p["stats"].get("rounds")]
    for person in people:
        s = person["stats"]
        person["entry_score"] = (s.get("flashes_pr") or 0) + 3 * (s.get("flash_assists_pr") or 0) + 2 * (s.get("trade_pr") or 0)
        person["lurk_score"] = 2 * (s.get("last_alive_pr") or 0) + 0.5 * (s.get("survival") or 0)
    return {"entry": sorted(people, key=lambda p: -p["entry_score"]),
            "lurk": sorted(people, key=lambda p: -p["lurk_score"])}

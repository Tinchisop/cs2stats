"""FACEIT: tu nivel, tu ELO y tus partidas con sus números, con la API de datos de FACEIT y una clave tuya (gratis).

Las partidas se guardan en el historial con el modo "faceit", aparte de Premier: cada pantalla las muestra separadas
con el filtro de modo. Para puntería, utilidad e impacto hace falta la demo (se baja desde la sala del partido)."""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Callable

from .i18n import t
from .metrics import map_label
from .prematch import FACEIT_API, LobbyError, _get
from .store import Settings, Store

STATS_PER_SYNC = 60      # partidas nuevas que se completan en cada búsqueda (una consulta cada una)
HISTORY_PAGES = 10       # hasta 1000 partidas hacia atrás
LEVELS_PER_SYNC = 60     # jugadores de tus demos de FACEIT a los que se les busca el nivel en cada búsqueda
ELO_PER_WIN = 25         # lo que suele dar una victoria, hasta tener tus propios números
MAX_FORECAST = 200       # más partidas que esto no es un pronóstico: se dice que no venís subiendo
LEVEL_MAX_DAYS = 7       # después de estos días se vuelve a preguntar el nivel de cada jugador
# Nivel de FACEIT en CS2 según el ELO: (nivel, desde).
LEVELS = [(1, 100), (2, 501), (3, 751), (4, 901), (5, 1051), (6, 1201), (7, 1351), (8, 1531), (9, 1751), (10, 2001)]
LEVEL_COLORS = {1: "#eeeeee", 2: "#1ce400", 3: "#1ce400", 4: "#ffc800", 5: "#ffc800", 6: "#ffc800", 7: "#ffc800",
                8: "#ff6309", 9: "#ff6309", 10: "#fe1f00"}


def level_progress(elo: int | None) -> tuple[float, int, int] | None:
    """(cuánto llevás hacia el próximo nivel de 0 a 1, ELO que falta, próximo nivel). None si ya sos nivel 10."""
    if not elo:
        return None
    for (level, start), (following, end) in zip(LEVELS, LEVELS[1:]):
        if elo < end:
            return max(0.0, (elo - start) / (end - start)), end - elo, following
    return None


def level_at(when: str, log: list[dict], current: dict) -> dict:
    """Tu nivel y ELO cuando jugaste, según lo guardado en cada búsqueda. Antes del primer dato, el más viejo que hay."""
    known = [row for row in log if row["at"] <= (when or "")]
    return known[-1] if known else log[0] if log else current


def _finished_at(row: dict) -> str:
    """Cuándo terminó una partida del historial de FACEIT. Vacío si no se sabe."""
    try:
        return (datetime.fromisoformat(row["played_at"])
                + timedelta(minutes=int(str(row.get("duration") or "").split()[0]))).isoformat(timespec="seconds")
    except (KeyError, TypeError, ValueError, IndexError):
        return ""


def elo_changes(history: list[dict], log: list[dict]) -> dict[str, int]:
    """ELO ganado o perdido por partida. FACEIT no lo da: sale de tu ELO guardado en cada búsqueda, y solo cuando entre
    dos datos hubo una sola partida (con dos o más no se puede saber cuánto fue cada una)."""
    ends = [(_finished_at(h), h["key"]) for h in history if h.get("mode") == "faceit"]
    changes = {}
    for before, after in zip(log, log[1:]):
        inside = [key for end, key in ends if end and before["at"] < end <= after["at"]]
        if len(inside) == 1:
            changes[inside[0]] = after["elo"] - before["elo"]
    return changes


def link_demo_changes(matches: list[dict], history: list[dict], changes: dict[str, int]) -> None:
    """Le pasa a cada partida con demo el ELO de su partida del historial (mismo mapa y resultado, hasta 48 horas)."""
    for match in matches:
        match["elo_change"] = None
        if match.get("source") != "faceit":
            continue
        try:
            when = datetime.fromisoformat(match["played_at"])
        except (TypeError, ValueError):
            continue
        near = []
        for row in history:
            if (row.get("key") in changes and row["map"].lower() == map_label(match["map"]).lower()
                    and (row["score_us"], row["score_them"]) == (match["score_us"], match["score_them"])):
                gap = abs((datetime.fromisoformat(row["played_at"]) - when).total_seconds())
                if gap <= 48 * 3600:
                    near.append((gap, row["key"]))
        if near:
            match["elo_change"] = changes[min(near)[1]]


def games_to_level(elo: int | None, history: list[dict], changes: dict[str, int]) -> tuple[int, int | None, bool] | None:
    """(victorias seguidas que alcanzan, partidas que faltan a tu ritmo, si hay datos de tu ritmo). None en nivel 10."""
    progress = level_progress(elo)
    if not progress:
        return None
    missing = progress[1]
    games = sorted((h for h in history if h.get("mode") == "faceit"), key=lambda h: h["played_at"] or "")
    recent = [changes[h["key"]] for h in games if h["key"] in changes][-15:]
    gains = [c for c in recent if c > 0]
    wins = math.ceil(missing / (sum(gains) / len(gains) if gains else ELO_PER_WIN))
    if len(recent) >= 5:
        per_game = sum(recent) / len(recent)
    elif len(games) >= 5:
        results = [h["result"] for h in games[-20:]]
        per_game = ELO_PER_WIN * (2 * results.count("W") / len(results) - 1)
    else:
        return wins, None, False
    needed = math.ceil(missing / per_game) if per_game > 0 else None
    return wins, needed if needed and needed <= MAX_FORECAST else None, True


def _headers(key: str) -> dict:
    return {"Authorization": f"Bearer {key}"}


def profile(key: str, steamid: int) -> dict:
    """Tu cuenta de FACEIT a partir de tu SteamID."""
    try:
        data = _get(f"{FACEIT_API}/players?game=cs2&game_player_id={steamid}", _headers(key))
    except LobbyError as error:
        if t("No se encontró (revisá el link).") == str(error):
            raise LobbyError(t("No hay una cuenta de FACEIT con CS2 asociada a tu cuenta de Steam.")) from error
        raise
    game = (data.get("games") or {}).get("cs2") or {}
    return {"player_id": data.get("player_id", ""), "nickname": data.get("nickname", ""), "avatar": data.get("avatar", ""),
            "elo": game.get("faceit_elo"), "level": game.get("skill_level"), "region": game.get("region", ""),
            "url": (data.get("faceit_url") or "").replace("{lang}", "es")}


def _number(value) -> float | None:
    try:
        return float(str(value).replace(",", ".").strip())
    except (TypeError, ValueError):
        return None


def match_row(key: str, item: dict, player_id: str) -> dict | None:
    """Una partida tuya de FACEIT con tus números, lista para el historial. None si no se puede leer."""
    match_id = item.get("match_id", "")
    stats = _get(f"{FACEIT_API}/matches/{match_id}/stats", _headers(key))
    rounds = stats.get("rounds") or []
    if not rounds:
        return None
    first = rounds[0]
    teams = first.get("teams") or []
    mine = next((team for team in teams if any(p.get("player_id") == player_id for p in team.get("players") or [])), None)
    if not mine:
        return None
    others = [team for team in teams if team is not mine]
    me = next(p for p in mine["players"] if p.get("player_id") == player_id)
    numbers = me.get("player_stats") or {}
    ours = _number((mine.get("team_stats") or {}).get("Final Score"))
    theirs = _number((others[0].get("team_stats") or {}).get("Final Score")) if others else None
    won = str(numbers.get("Result", "")) == "1"
    if ours is None or theirs is None:
        # Sin el resultado por equipo, sale del marcador "13 / 9": el número más alto es del que ganó.
        score = [_number(part) for part in str((first.get("round_stats") or {}).get("Score", "")).split("/")]
        if len(score) == 2 and None not in score:
            high, low = max(score), min(score)
            ours, theirs = (high, low) if won else (low, high)
    ours, theirs = int(ours or 0), int(theirs or 0)
    result = "W" if won else ("T" if ours == theirs else "L")
    started, finished = item.get("started_at") or 0, item.get("finished_at") or 0
    raw_map = str((first.get("round_stats") or {}).get("Map", ""))
    return {
        "key": f"faceit:{match_id}", "mode": "faceit", "map": map_label(raw_map) if raw_map else "?",
        "played_at": datetime.fromtimestamp(started).isoformat(timespec="seconds") if started else "",
        "duration": f"{max(0, finished - started) // 60} min" if started and finished else "",
        "score_us": ours, "score_them": theirs, "result": result,
        "kills": int(_number(numbers.get("Kills")) or 0), "assists": int(_number(numbers.get("Assists")) or 0),
        "deaths": int(_number(numbers.get("Deaths")) or 0), "mvps": int(_number(numbers.get("MVPs")) or 0),
        "hsp": int(round(_number(numbers.get("Headshots %")) or 0)), "score": 0, "demo_url": "",
        "adr": _number(numbers.get("ADR")),
        "team": [p.get("nickname", "") for p in mine["players"] if p.get("player_id") != player_id],
        "rivals": [p.get("nickname", "") for team in others for p in team.get("players") or []],
    }


def update_levels(key: str, settings: Settings, matches: list[dict]) -> None:
    """Guarda el nivel actual de los jugadores de tus demos de FACEIT (la demo no lo trae). Sin cuenta queda sin nivel."""
    levels = dict(settings["faceit_levels"])
    now = datetime.now()
    pending = []
    for match in reversed(matches):
        if match.get("source") != "faceit":
            continue
        for player in match.get("scoreboard") or []:
            steamid = str(player["steamid"])
            saved = levels.get(steamid)
            old = not saved or (now - datetime.fromisoformat(saved["at"])).days >= LEVEL_MAX_DAYS
            if old and not player.get("me") and steamid not in pending:
                pending.append(steamid)
    missing_account = t("No hay una cuenta de FACEIT con CS2 asociada a tu cuenta de Steam.")
    for steamid in pending[:LEVELS_PER_SYNC]:
        try:
            found = profile(key, int(steamid))
        except LobbyError as error:
            if str(error) != missing_account:
                break  # sin conexión o demasiadas consultas: sigue en la próxima búsqueda
            found = {}
        levels[steamid] = {"level": found.get("level"), "elo": found.get("elo"), "at": now.isoformat(timespec="seconds")}
    if pending:
        settings.set("faceit_levels", levels)


def sync_faceit(store: Store, settings: Settings, log: Callable[[str], None]) -> int:
    """Trae tu perfil y las partidas de FACEIT que todavía no están. Devuelve cuántas partidas nuevas se guardaron."""
    key = settings.secret("faceit_key")
    if not key:
        return 0
    steamid = settings["steamid"]
    log(t("Leyendo tu cuenta de FACEIT"))
    me = profile(key, steamid)
    settings.set("faceit_profile", me)
    if me.get("elo"):
        store.add_faceit_elo(datetime.now().isoformat(timespec="seconds"), int(me["elo"]), int(me.get("level") or 0))
    known = store.history_keys("faceit:")
    fresh: list[dict] = []
    for page in range(HISTORY_PAGES):
        data = _get(f"{FACEIT_API}/players/{me['player_id']}/history?game=cs2&offset={page * 100}&limit=100",
                    _headers(key))
        items = data.get("items") or []
        new = [i for i in items if f"faceit:{i.get('match_id')}" not in known and str(i.get("status", "")).upper() == "FINISHED"]
        fresh.extend(new)
        if len(items) < 100 or (items and not new) or len(fresh) >= STATS_PER_SYNC:
            break
    rows = []
    for index, item in enumerate(fresh[:STATS_PER_SYNC]):
        if index % 10 == 0:
            log(t("Partidas de FACEIT: {0} de {1}").format(index, min(len(fresh), STATS_PER_SYNC)))
        try:
            row = match_row(key, item, me["player_id"])
        except LobbyError as error:
            log(str(error))
            break
        if row:
            rows.append(row)
    if rows:
        store.save_history(steamid, rows)
    update_levels(key, settings, store.matches(steamid))
    settings.set("faceit_synced_at", datetime.now().isoformat(timespec="seconds"))
    log(t("FACEIT: {0} partidas nuevas").format(len(rows)))
    return len(rows)

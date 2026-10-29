"""FACEIT: tu nivel, tu ELO y tus partidas con sus números, con la API de datos de FACEIT y una clave tuya (gratis).

Las partidas se guardan en el historial con el modo "faceit", aparte de Premier: cada pantalla las muestra separadas
con el filtro de modo. Para puntería, utilidad e impacto hace falta la demo (se baja desde la sala del partido)."""

from __future__ import annotations

from datetime import datetime
from typing import Callable

from .i18n import t
from .metrics import map_label
from .prematch import FACEIT_API, LobbyError, _get
from .store import Settings, Store

STATS_PER_SYNC = 60      # partidas nuevas que se completan en cada búsqueda (una consulta cada una)
HISTORY_PAGES = 10       # hasta 1000 partidas hacia atrás
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
    settings.set("faceit_synced_at", datetime.now().isoformat(timespec="seconds"))
    log(t("FACEIT: {0} partidas nuevas").format(len(rows)))
    return len(rows)

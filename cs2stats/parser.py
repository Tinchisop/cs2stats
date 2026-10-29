"""Lee una demo de CS2 (.dem) y arma las métricas ronda por ronda, tuyas y de los otros 9 jugadores.

Solo abre el archivo de la demo con demoparser2: no toca el juego ni su memoria.
"""

from __future__ import annotations

import bisect
import hashlib
import math
from typing import Any

from demoparser2 import DemoParser

from .i18n import t as tr
from .metrics import summarize

TICKRATE = 64
TRADE_WINDOW = 5 * TICKRATE          # una muerte se considera cambiada si vengan al asesino en 5 s
EFFECTIVE_BLIND = 0.7                # segundos de ceguera que cuentan como flash efectiva
GRENADE_THROWS = {
    "weapon_flashbang": "flash", "weapon_smokegrenade": "smoke", "weapon_hegrenade": "he",
    "weapon_molotov": "molotov", "weapon_incgrenade": "molotov", "weapon_decoy": "decoy",
}
UTILITY_DAMAGE = {"hegrenade", "inferno", "molotov", "incgrenade"}
NOT_A_GUN = {"knife", "knife_t", "world", "", "hegrenade", "inferno", "molotov", "incgrenade",
             "flashbang", "smokegrenade", "decoy", "c4", "planted_c4"}
EVENTS = ["begin_new_match", "cs_pre_restart", "round_freeze_end", "round_end", "buytime_ended", "player_death",
          "player_hurt", "player_blind", "weapon_fire", "rank_update", "smokegrenade_detonate", "flashbang_detonate",
          "hegrenade_detonate", "inferno_startburn", "bomb_planted", "bomb_defused"]
# Latas: tiro (weapon_fire) y dónde explotó (evento de detonación del mismo jugador y tipo).
NADE_THROWS = {"weapon_smokegrenade": "smoke", "weapon_flashbang": "flash", "weapon_hegrenade": "he",
               "weapon_molotov": "molotov", "weapon_incgrenade": "molotov"}
NADE_LANDINGS = {"smokegrenade_detonate": "smoke", "flashbang_detonate": "flash", "hegrenade_detonate": "he",
                 "inferno_startburn": "molotov"}
GRID = 48   # tamaño de celda (unidades del juego) del mapa armado con las posiciones de los jugadores
TICK_PROPS = ["team_num", "is_alive", "balance", "cash_spent_this_round", "current_equip_value", "mvps"]
MVP_DELAY = 8  # el MVP de la ronda se anota apenas después del fin de ronda
RANK_SOURCES = {11: "premier", 12: "competitivo", 7: "wingman"}


class DemoError(Exception):
    """La demo no se puede usar (rota, vacía o sin el jugador)."""


class NotInDemo(DemoError):
    """El jugador elegido no jugó esta partida."""


def sid(value: Any) -> int:
    """SteamID64 como entero; 0 si falta (daño del mundo, caída, etc.)."""
    if value is None:
        return 0
    try:
        if isinstance(value, float) and math.isnan(value):
            return 0
        return int(value)
    except (TypeError, ValueError):
        return 0


def weapon_name(raw: Any) -> str:
    text = str(raw or "").strip().lower()
    return text.removeprefix("weapon_")


def _records(frame: Any) -> list[dict]:
    if frame is None or isinstance(frame, list):
        return []
    return sorted(frame.to_dict("records"), key=lambda row: row.get("tick", 0))


def _buy_type(equip: float, pistol: bool) -> str:
    if pistol:
        return "pistola"
    if equip < 1250:
        return "ahorro"
    if equip < 3500:
        return "forzada"
    return "completa"


def parse_demo(path: str, steamid: int) -> dict:
    try:
        parser = DemoParser(path)
        header = parser.parse_header()
        events = {name: _records(frame) for name, frame in parser.parse_events(EVENTS)}
    except (KeyboardInterrupt, SystemExit):
        raise
    except BaseException as error:  # demoparser2 lanza PanicException (BaseException) con demos rotas
        raise DemoError(tr("No se pudo leer la demo: {0}").format(error)) from error

    map_name = str(header.get("map_name") or "desconocido")
    server = str(header.get("server_name") or "")

    starts = [row["tick"] for row in events.get("begin_new_match", [])]
    match_start = max(starts) if starts else 0
    ends: list[dict] = []
    for row in events.get("round_end", []):
        if row["tick"] > match_start and row.get("winner") in ("T", "CT"):
            if not ends or row["tick"] != ends[-1]["tick"]:
                ends.append(row)
    if not ends:
        raise DemoError(tr("La demo no tiene rondas jugadas."))

    freeze_ticks = [row["tick"] for row in events.get("round_freeze_end", []) if row["tick"] > match_start]
    buy_ticks = [row["tick"] for row in events.get("buytime_ended", []) if row["tick"] > match_start]
    restart_ticks = [row["tick"] for row in events.get("cs_pre_restart", []) if row["tick"] > match_start]
    # Cada ronda abre en el reinicio (antes del tiempo de compra) y se le suman las kills posteriores
    # a su final hasta que arranca la siguiente; "start" es cuando se puede mover (fin del freeze).
    windows = []
    previous_end = match_start
    for row in ends:
        candidates = [t for t in freeze_ticks if previous_end < t < row["tick"]]
        start = candidates[-1] if candidates else previous_end + 1
        restarts = [t for t in restart_ticks if previous_end < t <= start]
        opening = restarts[-1] if restarts else (previous_end + 1 if not windows else start)
        buys = [t for t in buy_ticks if start < t <= row["tick"]]
        buy = buys[0] if buys else min(start + 20 * TICKRATE, row["tick"])
        windows.append({"open": opening, "start": start, "buy": buy, "end": row["tick"], "winner": row["winner"],
                        "reason": str(row.get("reason") or "")})
        previous_end = row["tick"]
    for index, window in enumerate(windows):
        window["until"] = windows[index + 1]["open"] if index + 1 < len(windows) else float("inf")

    snapshot_ticks = sorted({w["start"] for w in windows} | {w["buy"] for w in windows} | {w["end"] + MVP_DELAY for w in windows})
    try:
        ticks = parser.parse_ticks(TICK_PROPS, ticks=snapshot_ticks)
    except (KeyboardInterrupt, SystemExit):
        raise
    except BaseException as error:
        raise DemoError(tr("No se pudo leer el estado de los jugadores: {0}").format(error)) from error
    states: dict[int, dict[int, dict]] = {}
    names: dict[int, str] = {}
    for row in ticks.to_dict("records"):
        player = sid(row.get("steamid"))
        if not player:
            continue
        states.setdefault(int(row["tick"]), {})[player] = row
        names[player] = str(row.get("name") or names.get(player) or "")
    if not any(steamid in states.get(w["start"], {}) for w in windows):
        raise NotInDemo(tr("No jugaste esta partida (tu cuenta no aparece en la demo)."))

    deaths = events.get("player_death", [])
    _add_death_spots(parser, deaths)
    hurts = events.get("player_hurt", [])
    blinds = events.get("player_blind", [])
    all_fires = events.get("weapon_fire", [])

    def in_window(rows: list[dict], window: dict) -> list[dict]:
        return [row for row in rows if window["open"] <= row["tick"] < window["until"]]

    # Equipos por ronda (los mismos para todos los jugadores).
    round_teams: list[dict[int, int]] = []
    last_team: dict[int, int] = {}
    for window in windows:
        team = dict(last_team)
        for player, row in states.get(window["start"], {}).items():
            if row.get("team_num") in (2, 3):
                team[player] = int(row["team_num"])
        last_team.update(team)
        round_teams.append(team)
    half_rounds = 12
    # Quiénes arrancaron vivos cada ronda (para la probabilidad de ganar, jugador por jugador).
    # Si la demo trae vacío el estado de un jugador conectado (pasa), se lo toma como vivo.
    round_alive = [{p for p, row in states.get(w["start"], {}).items()
                    if (row.get("is_alive") is None or bool(row.get("is_alive"))) and round_teams[i].get(p) in (2, 3)}
                   for i, w in enumerate(windows)]
    for row in events.get("player_death", []) + events.get("player_hurt", []):
        # A veces la demo no trae el estado de un jugador justo en ese tick: si murió o pegó en la ronda, estaba vivo.
        index = next((i for i, w in enumerate(windows) if w["start"] <= row["tick"] <= w["end"]), None)
        for player in (sid(row.get("user_steamid")), sid(row.get("attacker_steamid"))):
            if index is not None and player and round_teams[index].get(player) in (2, 3):
                round_alive[index].add(player)

    def player_rounds(target: int) -> tuple[list[dict], dict[str, dict]]:
        """Rondas y armas de un jugador. Se usa para vos (completo) y para los otros 9 (promedios del rango)."""
        fires = [row for row in all_fires if sid(row.get("user_steamid")) == target]
        # player_hurt informa el arma base (M4A1-S figura como "m4a1", USP-S como "hkp2000"):
        # se toma la última arma de fuego que disparó antes del impacto.
        gun_fire_ticks: list[int] = []
        gun_fire_names: list[str] = []
        for row in fires:
            gun = weapon_name(row.get("weapon"))
            if str(row.get("weapon") or "") not in GRENADE_THROWS and not gun.startswith("knife") and gun not in NOT_A_GUN:
                gun_fire_ticks.append(row["tick"])
                gun_fire_names.append(gun)

        def fired_gun(tick: int, fallback: str) -> str:
            index = bisect.bisect_right(gun_fire_ticks, tick) - 1
            if index >= 0 and tick - gun_fire_ticks[index] <= 2 * TICKRATE:
                return gun_fire_names[index]
            return fallback

        rounds: list[dict] = []
        weapons: dict[str, dict] = {}

        def weapon_row(name: str) -> dict:
            return weapons.setdefault(name, {"kills": 0, "hs": 0, "damage": 0.0, "shots": 0, "hits": 0})

        for number, window in enumerate(windows, start=1):
            start_state = states.get(window["start"], {})
            buy_state = states.get(window["buy"], {})
            team = round_teams[number - 1]
            mine = team.get(target)
            if mine not in (2, 3) or target not in start_state:
                continue  # estaba desconectado o mirando esta ronda
            side = "CT" if mine == 3 else "T"
            alive = {p for p, row in start_state.items() if row.get("is_alive") and team.get(p) in (2, 3)}

            me_buy = buy_state.get(target) or start_state.get(target) or {}
            me_start = start_state.get(target) or {}
            equip = max(float(me_buy.get("current_equip_value") or 0), float(me_start.get("current_equip_value") or 0))
            money = float(me_buy.get("balance") or 0) + float(me_buy.get("cash_spent_this_round") or 0)
            mates = [p for p in alive if team.get(p) == mine]
            team_equip = 0.0
            for player in mates:
                row_b, row_s = buy_state.get(player) or {}, start_state.get(player) or {}
                team_equip += max(float(row_b.get("current_equip_value") or 0), float(row_s.get("current_equip_value") or 0))
            team_equip /= max(1, len(mates))
            pistol = number in (1, half_rounds + 1)

            info = {
                "n": number, "side": side, "won": window["winner"] == side, "reason": window["reason"],
                "kills": 0, "hs_kills": 0, "assists": 0, "flash_assists": 0, "died": False, "died_live": False,
                "death_time": None, "damage": 0.0, "util_damage": 0.0, "opening": None, "first_team_death": False,
                "traded": False, "tradeable": False, "trade_kills": 0, "clutch_vs": None, "clutch_won": False,
                "equip": equip, "money": money, "team_equip": round(team_equip),
                "buy": _buy_type(equip, pistol), "team_buy": _buy_type(team_equip, pistol),
                "flash": 0, "smoke": 0, "he": 0, "molotov": 0, "decoy": 0,
                "enemies_flashed": 0, "blind_time": 0.0, "team_flashed": 0, "kill_weapons": [],
                "he_damage": 0.0, "he_team_damage": 0.0, "kill_spots": [], "death_spot": None,
                "mvp": float((states.get(window["end"] + MVP_DELAY, {}).get(target) or {}).get("mvps") or 0)
                > float(me_start.get("mvps") or 0),
            }

            # Muertes: K/D/A, primer duelo, cambios y clutch.
            live_kills: list[tuple[int, int, int]] = []  # (tick, asesino, víctima)
            first_live = True
            team_first_done = False
            death_tick, my_killer = 0, 0
            for row in in_window(deaths, window):
                victim, killer, helper = sid(row.get("user_steamid")), sid(row.get("attacker_steamid")), sid(row.get("assister_steamid"))
                live = row["tick"] <= window["end"]
                victim_team, killer_team = team.get(victim), team.get(killer)
                enemy_kill = bool(killer) and killer != victim and killer_team != victim_team
                if live and first_live:
                    first_live = False
                    if enemy_kill and killer == target:
                        info["opening"] = "kill"
                    elif enemy_kill and victim == target:
                        info["opening"] = "death"
                if live and victim_team == mine and not team_first_done:
                    team_first_done = True
                    info["first_team_death"] = victim == target
                if killer == target and enemy_kill:
                    info["kills"] += 1
                    gun = weapon_name(row.get("weapon"))
                    info["kill_weapons"].append(gun)
                    if row.get("killer_spot"):
                        info["kill_spots"].append(row["killer_spot"])
                    weapon_row(gun)["kills"] += 1
                    if row.get("headshot"):
                        info["hs_kills"] += 1
                        weapon_row(gun)["hs"] += 1
                    if live and any(row["tick"] - t <= TRADE_WINDOW and k == victim and team.get(v) == mine and v != target
                                    for t, k, v in live_kills):
                        info["trade_kills"] += 1
                if helper == target and victim_team != mine and victim:
                    info["assists"] += 1
                    if row.get("assistedflash"):
                        info["flash_assists"] += 1
                if live:
                    if enemy_kill:
                        live_kills.append((row["tick"], killer, victim))
                    alive.discard(victim)
                    mates_alive = [p for p in alive if team.get(p) == mine]
                    enemies_alive = [p for p in alive if team.get(p) not in (mine, None)]
                    if info["clutch_vs"] is None and mates_alive == [target] and enemies_alive:
                        info["clutch_vs"] = len(enemies_alive)
                if victim == target:
                    info["died"] = True
                    info["death_spot"] = row.get("victim_spot")
                    if live:
                        info["died_live"] = True
                        death_tick = row["tick"]
                        info["death_time"] = round(max(0, row["tick"] - window["start"]) / TICKRATE, 1)
                        # Solo se puede cambiar una muerte si quedaba algún compañero vivo.
                        info["tradeable"] = enemy_kill and any(team.get(p) == mine for p in alive)
                        my_killer = killer if enemy_kill else 0
            if info["tradeable"]:
                info["traded"] = any(v == my_killer and team.get(k) == mine and 0 <= t - death_tick <= TRADE_WINDOW
                                     for t, k, v in live_kills)
            if info["clutch_vs"] is not None:
                info["clutch_won"] = info["won"]

            # Daño real: nunca más que la vida que le quedaba a la víctima.
            health: dict[int, float] = {}
            for row in in_window(hurts, window):
                victim, attacker = sid(row.get("user_steamid")), sid(row.get("attacker_steamid"))
                before = health.get(victim, 100.0)
                dealt = max(0.0, min(float(row.get("dmg_health") or 0), before))
                health[victim] = float(row.get("health") or 0)
                if attacker == target and victim != target and team.get(attacker) == team.get(victim)                         and weapon_name(row.get("weapon")) == "hegrenade":
                    info["he_team_damage"] += dealt
                if attacker != target or attacker == victim or team.get(attacker) == team.get(victim):
                    continue
                gun = weapon_name(row.get("weapon"))
                if gun not in NOT_A_GUN and not gun.startswith("knife"):
                    gun = fired_gun(row["tick"], gun)
                info["damage"] += dealt
                if gun in UTILITY_DAMAGE:
                    info["util_damage"] += dealt
                if gun == "hegrenade":
                    info["he_damage"] += dealt
                weapon_row(gun)["damage"] += dealt
                if gun not in NOT_A_GUN:
                    weapon_row(gun)["hits"] += 1

            for row in in_window(blinds, window):
                if sid(row.get("attacker_steamid")) != target:
                    continue
                victim = sid(row.get("user_steamid"))
                duration = float(row.get("blind_duration") or 0)
                if victim == target or duration < EFFECTIVE_BLIND:
                    continue
                if team.get(victim) == mine:
                    info["team_flashed"] += 1
                else:
                    info["enemies_flashed"] += 1
                    info["blind_time"] += duration

            for row in in_window(fires, window):
                raw = str(row.get("weapon") or "")
                if raw in GRENADE_THROWS:
                    info[GRENADE_THROWS[raw]] += 1
                else:
                    gun = weapon_name(raw)
                    if gun and not gun.startswith("knife") and gun not in NOT_A_GUN:
                        weapon_row(gun)["shots"] += 1

            info["damage"] = round(info["damage"], 1)
            info["util_damage"] = round(info["util_damage"], 1)
            info["he_damage"] = round(info["he_damage"], 1)
            info["he_team_damage"] = round(info["he_team_damage"], 1)
            info["blind_time"] = round(info["blind_time"], 2)
            info["kast"] = bool(info["kills"] or info["assists"] or not info["died_live"] or info["traded"])
            rounds.append(info)
        for stats in weapons.values():
            stats["damage"] = round(stats["damage"], 1)
        return rounds, weapons

    rounds, weapons = player_rounds(steamid)
    if not rounds:
        raise NotInDemo(tr("No jugaste ninguna ronda de esta partida."))

    ranks: dict[int, dict] = {}
    for row in events.get("rank_update", []):
        player = sid(row.get("user_steamid"))
        if player:
            ranks[player] = {"type": int(row.get("rank_type_id") or 0), "old": int(row.get("rank_old") or 0),
                             "new": int(row.get("rank_new") or 0), "change": float(row.get("rank_change") or 0),
                             "wins": int(row.get("num_wins") or 0)}
    rank = ranks.get(steamid) or {"type": None, "old": None, "new": None, "change": None, "wins": None}
    if "faceit" in server.lower():
        source = "faceit"
    elif rank["type"] in RANK_SOURCES:
        source = RANK_SOURCES[rank["type"]]
    elif "valve" in server.lower():
        source = "valve"
    else:
        source = "otro"

    fingerprint = "|".join(f"{row['tick']}:{sid(row.get('attacker_steamid'))}:{sid(row.get('user_steamid'))}"
                           for row in deaths[:30])
    match_key = hashlib.sha1(f"{map_name}|{fingerprint}".encode()).hexdigest()
    won = sum(1 for r in rounds if r["won"])
    lost = sum(1 for w in windows if w["winner"] in ("T", "CT")) - won

    # Tabla de los 10 jugadores, con las mismas métricas que las tuyas: de acá salen los promedios por rango.
    scoreboard = []
    for player, team_num in last_team.items():
        if team_num not in (2, 3):
            continue
        their_rounds = rounds if player == steamid else player_rounds(player)[0]
        if len(their_rounds) < 5:
            continue  # se fue enseguida o entró al final: no sirve como referencia
        stats = summarize(their_rounds)
        stats.pop("multi", None)
        their_rank = ranks.get(player) or {}
        scoreboard.append({
            "steamid": player, "name": names.get(player, ""), "me": player == steamid,
            "ally": team_num == last_team.get(steamid), "kills": stats["kills"], "deaths": stats["deaths"],
            "assists": stats["assists"], "adr": round(stats["adr"] or 0, 1),
            "hs": round((stats["hs"] or 0) * stats["kills"]), "rating": stats["rating"],
            "premier": their_rank.get("old") if their_rank.get("type") == 11 and their_rank.get("old") else None,
            "stats": {k: (round(v, 4) if isinstance(v, float) else v) for k, v in stats.items()},
        })
    scoreboard.sort(key=lambda r: (not r["ally"], -(r["rating"] or 0)))

    return {
        "match_key": match_key, "map": map_name, "server": server, "source": source,
        "my_name": names.get(steamid, ""), "steamid": steamid,
        "score_us": won, "score_them": lost,
        "result": "W" if won > lost else "L" if lost > won else "T",
        "rank": rank, "rounds": rounds, "weapons": weapons, "scoreboard": scoreboard,
        "grenades": _grenades(parser, events, windows, round_teams, names, steamid),
        "grid": _position_grid(parser, windows),
        "aim": _aim(parser, events, windows),
        "detail": _detail(parser, events, windows, round_teams, round_alive),
    }


SPRAY_GAP = 20          # ticks (0,3 s): un disparo tan seguido del anterior ya es parte de una ráfaga
STOPPED_SPEED = 100     # unidades por segundo: por debajo, el arma ya dispara precisa (counter-strafe bien hecho)
SIGHT_GAP = TICKRATE    # para contar como "apareció", el rival tuvo que estar sin verse al menos 1 s
SIGHT_LEAD = 6          # el aviso de "visto" llega unos ticks tarde: la mira se mide un poco antes
DAMAGE_WINDOW = 3 * TICKRATE


def _aim(parser, events, windows) -> dict:
    """Puntería de cada jugador, al estilo de Leetify: cuentas crudas que metrics.aim_summary vuelve porcentajes.

    "Visto" usa lo que el propio juego marca como enemigo a la vista (approximate_spotted_by)."""
    import numpy as np

    if not windows:
        return {}
    live = [t for w in windows for t in range(w["start"], w["end"] + 1)]
    try:
        frame = parser.parse_ticks(["X", "Y", "Z", "pitch", "yaw", "is_alive", "team_num", "ducking",
                                    "approximate_spotted_by"], ticks=live)
    except (KeyboardInterrupt, SystemExit):
        raise
    except BaseException:
        return {}
    if frame is None or not len(frame):
        return {}
    frame = frame[frame["steamid"].notna()]
    first, last = live[0], live[-1]
    size = last - first + 1
    players = sorted({sid(s) for s in frame["steamid"]} - {0})
    index = {player: i for i, player in enumerate(players)}
    count = len(players)
    rows = frame["steamid"].map(sid).map(index).to_numpy()
    cols = frame["tick"].to_numpy(dtype=np.int64) - first

    def grid(column: str, kind=float, empty=np.nan):
        out = np.full((count, size), empty, dtype=kind)
        out[rows, cols] = frame[column].fillna(empty).to_numpy(dtype=kind)
        return out

    x, y, z, pitch, yaw = (grid(c) for c in ("X", "Y", "Z", "pitch", "yaw"))
    alive = grid("is_alive", bool, False)
    team = grid("team_num", np.int8, 0)
    eye = z + np.where(grid("ducking", bool, False), 46.0, 64.0)
    speed = np.zeros((count, size))
    speed[:, 1:] = np.hypot(np.diff(x, axis=1), np.diff(y, axis=1)) * TICKRATE
    # seen[a, b, t]: el jugador a tiene a la vista al rival b.
    seen = np.zeros((count, count, size), dtype=bool)
    for victim, tick, spotters in zip(rows, cols, frame["approximate_spotted_by"]):
        for spotter in spotters if isinstance(spotters, (list, tuple)) else ():
            a = index.get(sid(spotter))
            if a is not None and a != victim:
                seen[a, victim, tick] = True
    enemy = (team[:, None, :] != team[None, :, :]) & (team[None, :, :] > 0) & alive[None, :, :] & alive[:, None, :]
    seen &= enemy
    any_seen = seen.any(axis=1)

    def is_gun(raw) -> bool:
        gun = weapon_name(raw)
        return bool(gun) and str(raw or "") not in GRENADE_THROWS and not gun.startswith("knife") \
            and gun not in NOT_A_GUN and gun != "taser"

    def at(tick: int) -> int | None:
        return tick - first if first <= tick <= last else None

    shots: dict[int, list[tuple[int, str]]] = {}
    for row in events.get("weapon_fire", []):
        player, tick = sid(row.get("user_steamid")), at(row["tick"])
        if player in index and tick is not None and is_gun(row.get("weapon")):
            shots.setdefault(player, []).append((tick, weapon_name(row.get("weapon"))))
    hits: dict[int, list[tuple[int, int, bool]]] = {}  # (tick, víctima, a la cabeza)
    for row in events.get("player_hurt", []):
        attacker, victim, tick = sid(row.get("attacker_steamid")), sid(row.get("user_steamid")), at(row["tick"])
        if attacker in index and victim in index and tick is not None and is_gun(row.get("weapon")) \
                and team[index[attacker], tick] != team[index[victim], tick]:
            hits.setdefault(attacker, []).append((tick, index[victim], str(row.get("hitgroup") or "") == "head"))

    result = {}
    for player in players:
        a = index[player]
        mine = shots.get(player, [])
        landed = hits.get(player, [])
        hit_ticks = sorted(t for t, _v, _h in landed)
        raw = {"shots": len(mine), "hits": 0, "seen_shots": 0, "seen_hits": 0, "first_shots": 0, "first_hits": 0,
               "spray_shots": 0, "spray_hits": 0, "strafe_shots": 0, "strafe_ok": 0, "gun_hits": len(landed),
               "head_hits": sum(1 for *_x, head in landed if head), "ttd_sum": 0.0, "ttd_n": 0,
               "xhair_sum": 0.0, "xhair_n": 0}
        previous = (-SPRAY_GAP - 1, "")
        for tick, gun in mine:
            j = bisect.bisect_left(hit_ticks, tick)
            hit = j < len(hit_ticks) and hit_ticks[j] - tick <= 1
            raw["hits"] += hit
            spray = tick - previous[0] <= SPRAY_GAP and gun == previous[1]
            previous = (tick, gun)
            if not any_seen[a, tick]:
                continue
            raw["seen_shots"] += 1
            raw["seen_hits"] += hit
            kind = "spray" if spray else "first"
            raw[f"{kind}_shots"] += 1
            raw[f"{kind}_hits"] += hit
            if not spray:
                raw["strafe_shots"] += 1
                raw["strafe_ok"] += bool(speed[a, tick] < STOPPED_SPEED)
        # Cada vez que un rival aparece: dónde estaba la mira y cuánto tardaste en pegarle.
        for b in range(count):
            visible = seen[a, b]
            if b == a or not visible.any():
                continue
            damage = sorted(t for t, v, _h in landed if v == b)
            for tick in np.flatnonzero(visible[1:] & ~visible[:-1]) + 1:
                if visible[max(0, tick - SIGHT_GAP):tick].any():
                    continue
                j = bisect.bisect_left(damage, tick)
                if j < len(damage) and damage[j] - tick <= DAMAGE_WINDOW:
                    raw["ttd_sum"] += (damage[j] - tick) / TICKRATE * 1000
                    raw["ttd_n"] += 1
                u = max(0, tick - SIGHT_LEAD)
                dx, dy, dz = x[b, u] - x[a, u], y[b, u] - y[a, u], eye[b, u] - eye[a, u]
                want_yaw = math.degrees(math.atan2(dy, dx))
                want_pitch = -math.degrees(math.atan2(dz, math.hypot(dx, dy)))
                angle = math.hypot((yaw[a, u] - want_yaw + 180) % 360 - 180, pitch[a, u] - want_pitch)
                if math.isfinite(angle):
                    raw["xhair_sum"] += angle
                    raw["xhair_n"] += 1
        raw["ttd_sum"] = round(raw["ttd_sum"], 1)
        raw["xhair_sum"] = round(raw["xhair_sum"], 2)
        result[str(player)] = {k: (int(v) if isinstance(v, (bool, np.bool_, np.integer)) else v) for k, v in raw.items()}
    return result


UTILITY_PRICES = {"Flashbang": 200, "Smoke Grenade": 300, "High Explosive Grenade": 300, "Molotov": 400,
                  "Incendiary Grenade": 500, "Decoy Grenade": 50}
PLANT_ODDS = 2.2   # con la bomba plantada, a los T les alcanza con aguantar: sus chances se multiplican


def win_chance_t(t_alive: int, ct_alive: int, planted: bool) -> float:
    """Probabilidad de que ganen los T según cuántos quedan vivos de cada lado (y si la bomba está plantada)."""
    if ct_alive <= 0:
        return 1.0
    if t_alive <= 0:
        return 0.15 if planted else 0.0
    odds = (t_alive / ct_alive) ** 2.5 * (PLANT_ODDS if planted else 1.0)
    return odds / (1 + odds)


def _detail(parser, events, windows, round_teams, round_alive) -> dict:
    """Lo que necesitan las pestañas del detalle, para los 10 jugadores:

    * impact: cuánto movió cada jugador la probabilidad de ganar de su equipo en cada ronda (como el rating de Leetify),
      separado por tipo de jugada.
    * kills y damage: quién mató a quién, con qué, y el daño entre cada par de jugadores (cara a cara).
    * unused: plata en granadas que cada uno tenía encima al morir."""
    impact: dict[str, dict] = {}
    kills: list[list] = []
    damage: dict[str, float] = {}
    deaths_at: list[tuple[int, int]] = []

    def entry(player: int) -> dict:
        return impact.setdefault(str(player), {"rounds": {}, "sides": {}, "cats": {}})

    def credit(player: int, number: int, category: str, value: float) -> None:
        if not player or not value:
            return
        item = entry(player)
        item["rounds"][str(number)] = item["rounds"].get(str(number), 0.0) + value
        item["cats"][category] = item["cats"].get(category, 0.0) + value

    timeline = [(row["tick"], 0, "hurt", row) for row in events.get("player_hurt", [])]
    timeline += [(row["tick"], 1, "death", row) for row in events.get("player_death", [])]
    timeline += [(row["tick"], 2, "plant", row) for row in events.get("bomb_planted", [])]
    timeline += [(row["tick"], 2, "defuse", row) for row in events.get("bomb_defused", [])]
    timeline.sort(key=lambda item: (item[0], item[1]))
    ticks = [item[0] for item in timeline]

    for index, window in enumerate(windows):
        number = index + 1
        team = round_teams[index]
        for player in round_alive[index]:
            item = entry(player)
            item["rounds"].setdefault(str(number), 0.0)
            item["sides"][str(number)] = "T" if team.get(player) == 2 else "CT"
        alive = set(round_alive[index])
        planted, first = False, True
        health: dict[int, float] = {}
        hurt_by: dict[int, dict[int, float]] = {}
        recent: list[tuple[int, int, int]] = []  # (tick, asesino, víctima) para los cambios

        def chance() -> float:
            return win_chance_t(sum(1 for p in alive if team.get(p) == 2), sum(1 for p in alive if team.get(p) == 3), planted)

        def kind(player: int, opening: bool, solo: bool) -> str:
            if opening:
                return "opening"
            if planted:
                return "afterplant" if team.get(player) == 2 else "retake"
            return "clutch" if solo else "midround"

        start = bisect.bisect_left(ticks, window["start"])
        end = bisect.bisect_right(ticks, window["end"])
        for tick, _order, what, row in timeline[start:end]:
            if what == "hurt":
                victim, attacker = sid(row.get("user_steamid")), sid(row.get("attacker_steamid"))
                before = health.get(victim, 100.0)
                dealt = max(0.0, min(float(row.get("dmg_health") or 0), before))
                health[victim] = float(row.get("health") or 0)
                if attacker and attacker != victim and team.get(attacker) not in (None, team.get(victim)):
                    hurt_by.setdefault(victim, {})[attacker] = hurt_by.get(victim, {}).get(attacker, 0.0) + dealt
                    key = f"{attacker}>{victim}"
                    damage[key] = round(damage.get(key, 0.0) + dealt, 1)
                continue
            if what == "plant":
                before = chance()
                planted = True
                credit(sid(row.get("user_steamid")), number, "afterplant", chance() - before)
                continue
            if what == "defuse":
                credit(sid(row.get("user_steamid")), number, "retake", chance())
                continue
            victim, killer = sid(row.get("user_steamid")), sid(row.get("attacker_steamid"))
            if victim not in alive:
                continue
            side = team.get(victim)
            victim_solo = sum(1 for p in alive if team.get(p) == side) == 1
            killer_solo = sum(1 for p in alive if team.get(p) == team.get(killer)) == 1
            before = chance()
            alive.discard(victim)
            after = chance()
            lost = (before - after) if side == 2 else (after - before)  # lo que perdió el equipo de la víctima
            deaths_at.append((tick, victim))
            credit(victim, number, kind(victim, first, victim_solo), -lost)
            if killer and killer != victim and team.get(killer) not in (None, side):
                kills.append([number, str(killer), str(victim), weapon_name(row.get("weapon")), bool(row.get("headshot"))])
                shares = {p: d for p, d in hurt_by.get(victim, {}).items() if d > 0}
                total = sum(shares.values())
                if killer not in shares or not total:
                    shares, total = {killer: 1.0}, 1.0
                # Si con esta kill vengó a un compañero, la mitad del crédito es para el que murió primero.
                traded = [v for t, k, v in recent if k == victim and team.get(v) == team.get(killer) and tick - t <= TRADE_WINDOW]
                for player, dealt in shares.items():
                    part = lost * dealt / total
                    if player != killer:
                        credit(player, number, "damage_assist", part)
                    elif traded:
                        credit(player, number, kind(player, first, killer_solo), part / 2)
                        credit(traded[-1], number, "traded", part / 2)
                    else:
                        credit(player, number, kind(player, first, killer_solo), part)
                recent.append((tick, killer, victim))
            first = False

    # Granadas que cada uno tenía encima al morir.
    unused: dict[str, list] = {}
    if deaths_at:
        try:
            frame = parser.parse_ticks(["inventory"], ticks=sorted({max(0, t - 1) for t, _v in deaths_at}))
            inventory = {(int(r["tick"]), sid(r.get("steamid"))): r.get("inventory") for r in frame.to_dict("records")}
        except (KeyboardInterrupt, SystemExit):
            raise
        except BaseException:
            inventory = {}
        for tick, victim in deaths_at:
            items = inventory.get((max(0, tick - 1), victim))
            total = unused.setdefault(str(victim), [0, 0])
            total[0] += sum(UTILITY_PRICES.get(str(name), 0) for name in items) if isinstance(items, (list, tuple)) else 0
            total[1] += 1
    for item in impact.values():
        item["rounds"] = {n: round(v, 4) for n, v in item["rounds"].items()}
        item["cats"] = {c: round(v, 4) for c, v in item["cats"].items()}
    return {"impact": impact, "kills": kills, "damage": damage, "unused": unused}


def _grenades(parser, events, windows, round_teams, names, steamid) -> list[dict]:
    """Cada granada tirada en la partida (de los 10 jugadores): desde dónde, mirando a dónde y dónde cayó."""
    throws = []
    for row in events.get("weapon_fire", []):
        kind = NADE_THROWS.get(str(row.get("weapon") or ""))
        if not kind:
            continue
        index = next((i for i, w in enumerate(windows) if w["open"] <= row["tick"] < w["until"]), None)
        if index is None:
            continue
        throws.append((row["tick"], sid(row.get("user_steamid")), kind, index))
    if not throws:
        return []
    ticks = sorted({t for t, *_ in throws} | {max(0, t - 8) for t, *_ in throws})
    try:
        frame = parser.parse_ticks(["X", "Y", "Z", "pitch", "yaw", "last_place_name", "is_airborne", "ducking"], ticks=ticks)
    except (KeyboardInterrupt, SystemExit):
        raise
    except BaseException:
        return []
    state = {(int(r["tick"]), sid(r.get("steamid"))): r for r in frame.to_dict("records")}
    landings: dict[tuple[int, str], list[dict]] = {}
    for event, kind in NADE_LANDINGS.items():
        for row in events.get(event, []):
            landings.setdefault((sid(row.get("user_steamid")), kind), []).append(row)
    used: set[tuple[str, int]] = set()
    result = []
    for tick, player, kind, index in throws:
        now, before = state.get((tick, player)), state.get((max(0, tick - 8), player))
        if not now or now.get("X") is None:
            continue
        speed = 0.0
        if before and before.get("X") is not None:
            speed = math.hypot(now["X"] - before["X"], now["Y"] - before["Y"]) / (8 / TICKRATE)
        land, flight = None, None
        for det in landings.get((player, kind), []):
            key = (kind, det["tick"])
            if det["tick"] > tick and det["tick"] - tick < 20 * TICKRATE and key not in used:
                used.add(key)
                land = [round(float(det["x"]), 1), round(float(det["y"]), 1), round(float(det["z"]), 1)]
                flight = round((det["tick"] - tick) / TICKRATE, 2)
                break
        team = round_teams[index].get(player)
        result.append({
            "type": kind, "steamid": player, "name": names.get(player, ""), "me": player == steamid,
            "side": "CT" if team == 3 else "T" if team == 2 else "", "round": index + 1,
            "t": round(max(0, tick - windows[index]["start"]) / TICKRATE, 1),
            "pos": [round(float(now["X"]), 1), round(float(now["Y"]), 1), round(float(now["Z"]), 1)],
            "ang": [round(float(now["pitch"]), 2), round(float(now["yaw"]), 2)],
            "place": str(now.get("last_place_name") or ""), "air": bool(now.get("is_airborne")),
            "duck": bool(now.get("ducking")), "speed": round(speed), "land": land, "flight": flight,
        })
    return result


def _add_death_spots(parser, deaths: list[dict]) -> None:
    """Dónde estaban el que mató y el que murió en cada muerte (X, Y del juego), para el mapa de calor."""
    try:
        rows = _records(parser.parse_event("player_death", player=["X", "Y"]))
    except (KeyboardInterrupt, SystemExit):
        raise
    except BaseException:
        return
    spots = {}
    for row in rows:
        def point(prefix: str):
            x, y = row.get(f"{prefix}_X"), row.get(f"{prefix}_Y")
            if x is None or y is None or x != x or y != y:   # NaN si no hay jugador (muerte por caída)
                return None
            return [round(float(x)), round(float(y))]
        spots[(row["tick"], sid(row.get("user_steamid")))] = (point("attacker"), point("user"))
    for row in deaths:
        killer, victim = spots.get((row["tick"], sid(row.get("user_steamid"))), (None, None))
        row["killer_spot"], row["victim_spot"] = killer, victim


def _position_grid(parser, windows) -> list[list]:
    """Dónde estuvieron los jugadores (celdas de 48 unidades, con su altura y nombre de zona).

    Sirve para dibujar el mapa de las latas y para nombrar dónde cae cada granada."""
    ticks = list(range(windows[0]["start"], windows[-1]["end"], 2 * TICKRATE))
    try:
        frame = parser.parse_ticks(["X", "Y", "Z", "last_place_name", "is_alive"], ticks=ticks)
    except (KeyboardInterrupt, SystemExit):
        raise
    except BaseException:
        return []
    cells: dict[tuple[int, int], list] = {}
    for row in frame.to_dict("records"):
        if not row.get("is_alive") or row.get("X") is None:
            continue
        key = (int(row["X"] // GRID), int(row["Y"] // GRID))
        cell = cells.setdefault(key, [0, 0.0, {}])
        cell[0] += 1
        cell[1] += float(row["Z"])
        place = str(row.get("last_place_name") or "")
        if place:
            cell[2][place] = cell[2].get(place, 0) + 1
    return [[gx, gy, round(z / n), max(places, key=places.get) if places else "", n]
            for (gx, gy), (n, z, places) in cells.items()]

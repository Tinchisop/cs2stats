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
          "hegrenade_detonate", "inferno_startburn"]
# Latas: tiro (weapon_fire) y dónde explotó (evento de detonación del mismo jugador y tipo).
NADE_THROWS = {"weapon_smokegrenade": "smoke", "weapon_flashbang": "flash", "weapon_hegrenade": "he",
               "weapon_molotov": "molotov", "weapon_incgrenade": "molotov"}
NADE_LANDINGS = {"smokegrenade_detonate": "smoke", "flashbang_detonate": "flash", "hegrenade_detonate": "he",
                 "inferno_startburn": "molotov"}
GRID = 48   # tamaño de celda (unidades del juego) del mapa armado con las posiciones de los jugadores
TICK_PROPS = ["team_num", "is_alive", "balance", "cash_spent_this_round", "current_equip_value"]
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

    snapshot_ticks = sorted({w["start"] for w in windows} | {w["buy"] for w in windows})
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
                if attacker != target or attacker == victim or team.get(attacker) == team.get(victim):
                    continue
                gun = weapon_name(row.get("weapon"))
                if gun not in NOT_A_GUN and not gun.startswith("knife"):
                    gun = fired_gun(row["tick"], gun)
                info["damage"] += dealt
                if gun in UTILITY_DAMAGE:
                    info["util_damage"] += dealt
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
    }


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

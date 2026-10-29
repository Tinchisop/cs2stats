"""Repetición 2D: dónde estuvo cada jugador en cada ronda, con kills, granadas, bomba, disparos y cegueras.

Se arma al leer la demo (posiciones 8 veces por segundo) y se guarda comprimida aparte de la partida. De ahí también
salen tus jugadas para los clips: multikills, clutches ganados, muertes sin disparar y flashes que cegaron a tu equipo.
"""

from __future__ import annotations

import json
import math

from .parser import GRENADE_THROWS, NOT_A_GUN, TICKRATE, sid, weapon_name

VERSION = 1
STEP = 8                    # ticks entre muestras (8 por segundo; la pantalla interpola entre una y otra)
TAIL = 4 * TICKRATE         # segundos que se siguen mostrando después del fin de ronda
CELL = 24                   # celdas del mapa armado con las posiciones de esta partida
FLASH_GROUP = 0.15          # segundos: cegueras de la misma flash
MAX_CLIP = 25               # segundos como máximo de un clip de multikill
HIGHLIGHTS = ("ace", "4k", "3k", "clutch")
FAILS = ("no_shots", "team_flash")


def _seconds(tick: int, start: int) -> float:
    return round((tick - start) / TICKRATE, 2)


def build(parser, events: dict, windows: list[dict], round_teams: list[dict], names: dict, steamid: int,
          rounds: list[dict], grenades: list[dict], map_name: str) -> dict | None:
    """Arma la repetición de la partida. Devuelve None si la demo no trae las posiciones."""
    plan = []   # (ronda, primer tick, último tick)
    ticks: list[int] = []
    for index, w in enumerate(windows):
        stop = w["end"] + TAIL if math.isinf(w["until"]) else min(w["end"] + TAIL, int(w["until"]) - 1)
        span = list(range(w["start"], int(stop) + 1, STEP))
        plan.append((index, w["start"], span[-1] if span else w["start"]))
        ticks.extend(span)
    if not ticks:
        return None
    try:
        frame = parser.parse_ticks(["X", "Y", "Z", "yaw", "health", "is_alive"], ticks=ticks)
    except (KeyboardInterrupt, SystemExit):
        raise
    except BaseException:
        return None
    if frame is None or not len(frame):
        return None
    frame = frame[frame["steamid"].notna()]

    where: dict[int, tuple[int, int]] = {}   # tick → (ronda, muestra)
    for index, start, last in plan:
        for sample, tick in enumerate(range(start, last + 1, STEP)):
            where[tick] = (index, sample)
    sizes = [(last - start) // STEP + 1 for _i, start, last in plan]
    raw: list[dict[int, list]] = [{} for _ in windows]
    cells: dict[tuple[int, int], list[float]] = {}
    columns = [frame[c].to_numpy() for c in ("tick", "steamid", "X", "Y", "Z", "yaw", "health", "is_alive")]
    for tick, player, x, y, z, yaw, health, alive in zip(*columns):
        spot = where.get(int(tick))
        player = sid(player)
        if spot is None or not player or x != x or y != y:
            continue
        index, sample = spot
        if round_teams[index].get(player) not in (2, 3):
            continue
        track = raw[index].setdefault(player, [None] * sizes[index])
        alive = bool(alive) and (health or 0) > 0
        track[sample] = (round(float(x)), round(float(y)), round(float(yaw or 0)) % 360, int(health or 0) if alive else 0)
        if alive and z == z:
            cell = cells.setdefault((int(x // CELL), int(y // CELL)), [0.0, 0])
            cell[0] += float(z)
            cell[1] += 1

    result_rounds = []
    for index, w in enumerate(windows):
        start = w["start"]
        end_tick = plan[index][2]
        teams = {str(p): "T" if team == 2 else "CT" for p, team in round_teams[index].items() if team in (2, 3)}
        tracks = {}
        for player, samples in raw[index].items():
            tracks[str(player)] = _fill(samples)

        def inside(row: dict) -> bool:
            return start <= row["tick"] <= end_tick

        kills = []
        for row in events.get("player_death", []):
            if inside(row):
                kills.append([_seconds(row["tick"], start), str(sid(row.get("attacker_steamid"))),
                              str(sid(row.get("user_steamid"))), weapon_name(row.get("weapon")), bool(row.get("headshot"))])
        shots: dict[str, list[float]] = {}
        for row in events.get("weapon_fire", []):
            raw_weapon = str(row.get("weapon") or "")
            gun = weapon_name(raw_weapon)
            if inside(row) and raw_weapon not in GRENADE_THROWS and gun and not gun.startswith("knife") \
                    and gun not in NOT_A_GUN:
                shots.setdefault(str(sid(row.get("user_steamid"))), []).append(_seconds(row["tick"], start))
        blinds = []
        for row in events.get("player_blind", []):
            duration = float(row.get("blind_duration") or 0)
            if inside(row) and duration >= 0.7:
                blinds.append([_seconds(row["tick"], start), str(sid(row.get("attacker_steamid"))),
                               str(sid(row.get("user_steamid"))), round(duration, 2)])
        nades = []
        for g in grenades:
            if g["round"] == index + 1 and g.get("pos"):
                land = g.get("land") or [None, None]
                nades.append([g["t"], str(g["steamid"]), g["type"], round(g["pos"][0]), round(g["pos"][1]),
                              round(land[0]) if land[0] is not None else None,
                              round(land[1]) if land[1] is not None else None, g.get("flight") or 0])
        bomb = []
        plant_spot = None
        for kind, event in (("plant", "bomb_planted"), ("defuse", "bomb_defused"), ("explode", "bomb_exploded")):
            for row in events.get(event, []):
                if not inside(row):
                    continue
                at = _seconds(row["tick"], start)
                who = str(sid(row.get("user_steamid")))
                spot = _position(tracks.get(who), at) if who in tracks else None
                if kind == "plant":
                    plant_spot = spot
                spot = spot if kind == "plant" else (plant_spot or spot)
                if spot:
                    bomb.append([at, kind, spot[0], spot[1]])
        bomb.sort(key=lambda item: item[0])
        result_rounds.append({
            "n": index + 1, "winner": w["winner"], "reason": w["reason"], "end": _seconds(w["end"], start),
            "length": round((sizes[index] - 1) * STEP / TICKRATE, 2), "teams": teams, "tracks": tracks,
            "kills": kills, "shots": shots, "blinds": blinds, "nades": nades, "bomb": bomb,
        })
    data = {
        "v": VERSION, "step": STEP, "map": map_name, "me": str(steamid),
        "players": {str(p): n for p, n in names.items()},
        "cells": [[gx, gy, round(z / n)] for (gx, gy), (z, n) in cells.items() if n >= 2],
        "rounds": result_rounds,
    }
    data["moments"] = find_moments(data, rounds)
    return data


def _fill(samples: list) -> list[int]:
    """Las muestras que faltan copian la anterior (o la siguiente al principio). Los muertos quedan donde cayeron."""
    out: list[int] = []
    last = next((s for s in samples if s is not None), (0, 0, 0, 0))
    dead_at = None
    for sample in samples:
        if sample is None:
            sample = last
        if sample[3] <= 0:
            if dead_at is None:
                dead_at = (last[0], last[1]) if last[3] > 0 else (sample[0], sample[1])
            sample = (dead_at[0], dead_at[1], sample[2], 0)
        else:
            dead_at = None
        out.extend(sample)
        last = sample
    return out


def _position(track: list[int] | None, at: float) -> tuple[int, int] | None:
    if not track:
        return None
    index = max(0, min(len(track) // 4 - 1, round(at * TICKRATE / STEP)))
    return track[index * 4], track[index * 4 + 1]


def find_moments(data: dict, rounds: list[dict]) -> list[dict]:
    """Tus jugadas para clips: lo mejor (as, 4K, 3K, clutch ganado) y los errores (morir sin disparar, flashes a tu equipo)."""
    me = data["me"]
    by_number = {r["n"]: r for r in rounds}
    moments = []
    for rnd in data["rounds"]:
        info = by_number.get(rnd["n"])
        if not info:
            continue
        teams, length, end = rnd["teams"], rnd["length"], rnd["end"]
        mine = teams.get(me)
        my_kills = [k for k in rnd["kills"] if k[1] == me and k[2] != me and teams.get(k[2]) not in (None, mine) and k[0] <= end]
        count = len(my_kills)
        if count >= 3:
            kind = "ace" if count >= 5 else "4k" if count == 4 else "3k"
            weapons = [k[3] for k in my_kills]
            # Si las kills están muy separadas, el clip muestra el tramo de hasta 25 s con más kills juntas.
            times = [k[0] for k in my_kills]
            first = max(range(count), key=lambda i: (sum(1 for x in times if times[i] <= x <= times[i] + MAX_CLIP - 5), -i))
            inside = [x for x in times if times[first] <= x <= times[first] + MAX_CLIP - 5]
            moments.append({"kind": kind, "round": rnd["n"], "at": inside[0], "count": count,
                            "weapon": max(set(weapons), key=weapons.count),
                            "from": max(0.0, inside[0] - 3), "to": min(length, inside[-1] + 2)})
        if info.get("clutch_vs") and info.get("clutch_won"):
            mates = [k[0] for k in rnd["kills"] if k[2] != me and teams.get(k[2]) == mine and k[0] <= end]
            begin = mates[-1] if mates else 0.0
            moments.append({"kind": "clutch", "round": rnd["n"], "at": begin, "vs": info["clutch_vs"],
                            "from": max(0.0, begin - 2), "to": min(length, max(begin + 6, min(end + 1.5, begin + 30)))})
        if info.get("died_live") and info.get("death_time") is not None:
            death = next((k[0] for k in rnd["kills"] if k[2] == me and k[0] <= end), None)
            if death is not None and not any(t <= death for t in rnd["shots"].get(me, [])):
                moments.append({"kind": "no_shots", "round": rnd["n"], "at": death,
                                "weapon": next((k[3] for k in rnd["kills"] if k[2] == me), ""),
                                "from": max(0.0, death - 8), "to": min(length, death + 2)})
        flashed = sorted(b for b in rnd["blinds"] if b[1] == me and b[2] != me and teams.get(b[2]) == mine)
        groups: list[list] = []
        for blind in flashed:
            if groups and blind[0] - groups[-1][0][0] <= FLASH_GROUP:
                groups[-1].append(blind)
            else:
                groups.append([blind])
        for group in groups:
            victims = {b[2] for b in group}
            if len(victims) >= 2:
                at = group[0][0]
                moments.append({"kind": "team_flash", "round": rnd["n"], "at": at, "count": len(victims),
                                "from": max(0.0, at - 5), "to": min(length, at + 4)})
    for moment in moments:
        moment["from"], moment["to"] = round(moment["from"], 2), round(moment["to"], 2)
    return moments


def encode(data: dict) -> bytes:
    import zstandard
    return zstandard.ZstdCompressor(level=9).compress(json.dumps(data, separators=(",", ":")).encode())


def decode(blob: bytes) -> dict:
    import zstandard
    return json.loads(zstandard.ZstdDecompressor().decompress(blob))

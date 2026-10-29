"""Asistente pre-partida: con tus compañeros y los rivales del lobby, qué mapas pickear o banear y a quién tener en cuenta.

De dónde salen los jugadores:
* Tu grupo de Steam: tus amigos que están en el mismo lobby que vos (Steam Web API, con tu clave).
* Una sala de FACEIT: los 10 jugadores con sus números por mapa (API de datos de FACEIT, con una clave tuya, opcional).
* Lo que pegues: links de perfiles de Steam, SteamID64 o nombres (la salida de `status` de la consola también sirve).

Los números salen de tus demos (cada jugador que se cruzó con vos) y, si hay sala de FACEIT, de sus estadísticas ahí."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field

from .friends import combine
from .i18n import t
from .metrics import map_label

STEAM_API = "https://api.steampowered.com"
FACEIT_API = "https://open.faceit.com/data/v4"
DEFAULT_POOL = ["de_ancient", "de_anubis", "de_dust2", "de_inferno", "de_mirage", "de_nuke", "de_overpass", "de_train"]
FACEIT_CAP = 30        # partidas de FACEIT por mapa que cuentan como máximo (para que no tapen lo de tus demos)
PRIOR = 5              # partidas "de 50 %" que se suman a cada mapa: con pocos datos no se exagera
ROOM = re.compile(r"room/(1-[0-9a-f-]{36})", re.I)
STEAMID = re.compile(r"\b(7656119\d{10})\b")
VANITY = re.compile(r"steamcommunity\.com/id/([\w-]+)", re.I)
QUOTED = re.compile(r"'([^']{2,32})'|\"([^\"]{2,32})\"")


class LobbyError(Exception):
    """No se pudo leer el lobby (clave inválida, perfil privado, sin conexión)."""


@dataclass
class Person:
    name: str = ""
    steamid: int = 0
    faceit_id: str = ""
    faceit: dict = field(default_factory=dict)
    source: str = ""


def _get(url: str, headers: dict | None = None) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": "CS2Stats", **(headers or {})})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        if error.code in (401, 403):
            raise LobbyError(t("La clave no sirve o no tiene permiso para esto.")) from error
        if error.code == 404:
            raise LobbyError(t("No se encontró (revisá el link).")) from error
        raise LobbyError(t("El servidor respondió con un error ({0}).").format(error.code)) from error
    except (urllib.error.URLError, TimeoutError, ValueError) as error:
        raise LobbyError(t("No hay conexión: {0}").format(error)) from error


# Lo que pega el usuario ───────────────────────────────────────────────────────────────────────────────────────────

def known_players(matches: list[dict]) -> dict[str, tuple[int, str]]:
    """Nombre (en minúsculas) → (SteamID, nombre) de cada jugador que apareció en tus demos."""
    known = {}
    for m in matches:
        for p in m.get("scoreboard") or []:
            if p.get("name") and not p.get("me"):
                known[p["name"].strip().lower()] = (int(p["steamid"]), p["name"])
    return known


def parse_people(text: str, known: dict[str, tuple[int, str]]) -> tuple[list[Person], list[str], str]:
    """Personas, nombres de perfil (/id/...) para resolver con Steam y la sala de FACEIT que aparezcan en el texto."""
    people: list[Person] = []
    vanities: list[str] = []
    room = ""
    seen: set = set()
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        found = ROOM.search(line)
        if found:
            room = found.group(1)
            continue
        ids = STEAMID.findall(line)
        if ids:
            for value in ids:
                if int(value) not in seen:
                    seen.add(int(value))
                    people.append(Person(steamid=int(value), source="steam"))
            continue
        vanity = VANITY.search(line)
        if vanity:
            vanities.append(vanity.group(1))
            continue
        names = [a or b for a, b in QUOTED.findall(line)] or ([line] if len(line) <= 32 and not line.startswith("#") else [])
        for name in names:
            match = known.get(name.strip().lower())
            key = match[0] if match else name.lower()
            if key in seen:
                continue
            seen.add(key)
            people.append(Person(name=match[1] if match else name.strip(), steamid=match[0] if match else 0,
                                 source="historial" if match else "nombre"))
    return people, vanities, room


# Steam ────────────────────────────────────────────────────────────────────────────────────────────────────────────

def resolve_vanity(api_key: str, name: str) -> int:
    query = urllib.parse.urlencode({"key": api_key, "vanityurl": name})
    data = _get(f"{STEAM_API}/ISteamUser/ResolveVanityURL/v1/?{query}").get("response", {})
    return int(data.get("steamid") or 0) if data.get("success") == 1 else 0


def summaries(api_key: str, steamids: list[int]) -> dict[int, dict]:
    result = {}
    for start in range(0, len(steamids), 100):
        chunk = ",".join(str(s) for s in steamids[start:start + 100])
        query = urllib.parse.urlencode({"key": api_key, "steamids": chunk})
        for player in _get(f"{STEAM_API}/ISteamUser/GetPlayerSummaries/v2/?{query}").get("response", {}).get("players", []):
            result[int(player["steamid"])] = player
    return result


def detect_party(api_key: str, me: int) -> list[Person]:
    """Tus amigos de Steam que están en tu mismo lobby de CS2 ahora."""
    if not api_key:
        raise LobbyError(t("Falta la clave de Web API de Steam (se carga en Conectar Steam)."))
    mine = summaries(api_key, [me]).get(me, {})
    lobby = mine.get("lobbysteamid")
    if not lobby:
        raise LobbyError(t("Steam no muestra tu lobby: abrí CS2 y armá el grupo, y revisá que tu perfil y tus detalles "
                           "de juego sean públicos."))
    query = urllib.parse.urlencode({"key": api_key, "steamid": me, "relationship": "friend"})
    try:
        friends = [int(f["steamid"]) for f in _get(f"{STEAM_API}/ISteamUser/GetFriendList/v1/?{query}")
                   .get("friendslist", {}).get("friends", [])]
    except LobbyError as error:
        raise LobbyError(t("Steam no deja ver tu lista de amigos (tiene que ser pública).")) from error
    party = []
    for steamid, player in summaries(api_key, friends).items():
        if player.get("lobbysteamid") == lobby:
            party.append(Person(name=player.get("personaname", ""), steamid=steamid, source="steam"))
    return party


# FACEIT ───────────────────────────────────────────────────────────────────────────────────────────────────────────

def faceit_room(api_key: str, room: str, me: int) -> tuple[list[Person], list[Person]]:
    """Los dos equipos de una sala de FACEIT: (tu equipo, rivales)."""
    data = _get(f"{FACEIT_API}/matches/{room}", {"Authorization": f"Bearer {api_key}"})
    teams = []
    for faction in ("faction1", "faction2"):
        roster = (data.get("teams", {}).get(faction) or {}).get("roster") or []
        teams.append([Person(name=p.get("nickname", ""), steamid=int(p.get("game_player_id") or 0),
                             faceit_id=p.get("player_id", ""), source="faceit") for p in roster])
    if len(teams) != 2 or not (teams[0] or teams[1]):
        raise LobbyError(t("La sala de FACEIT todavía no tiene los equipos armados."))
    if any(p.steamid == me for p in teams[1]):
        teams.reverse()
    return teams[0], teams[1]


def faceit_numbers(api_key: str, person: Person) -> dict:
    """Nivel, K/D, victorias y victorias por mapa de un jugador en FACEIT."""
    headers = {"Authorization": f"Bearer {api_key}"}
    if not person.faceit_id and person.steamid:
        query = urllib.parse.urlencode({"game": "cs2", "game_player_id": person.steamid})
        try:
            person.faceit_id = _get(f"{FACEIT_API}/players?{query}", headers).get("player_id", "")
        except LobbyError:
            return {}
    if not person.faceit_id:
        return {}
    profile = _get(f"{FACEIT_API}/players/{person.faceit_id}", headers)
    game = (profile.get("games") or {}).get("cs2") or {}
    stats = _get(f"{FACEIT_API}/players/{person.faceit_id}/stats/cs2", headers)
    life = stats.get("lifetime") or {}

    def number(value) -> float | None:
        try:
            return float(str(value).replace(",", "."))
        except (TypeError, ValueError):
            return None
    maps = {}
    for segment in stats.get("segments") or []:
        if str(segment.get("type", "")).lower() != "map" or str(segment.get("mode", "5v5")).lower() != "5v5":
            continue
        values = segment.get("stats") or {}
        games, rate = number(values.get("Matches")), number(values.get("Win Rate %"))
        if games and rate is not None:
            maps[_key(str(segment.get("label", "")))] = [int(games), rate / 100]
    extra = {k: v for k, v in life.items() if "Entry" in k or "Sniper" in k}
    return {"level": game.get("skill_level"), "elo": game.get("faceit_elo"), "kd": number(life.get("Average K/D Ratio")),
            "win_rate": (number(life.get("Win Rate %")) or 0) / 100 if life.get("Win Rate %") else None,
            "matches": number(life.get("Matches")), "hs": number(life.get("Average Headshots %")), "maps": maps,
            "extra": extra, "nickname": profile.get("nickname") or person.name}


# Juntar todo (corre en segundo plano) ───────────────────────────────────────────────────────────────────────────

def collect(api_key: str, faceit_key: str, me: int, mates_text: str, rivals_text: str, room: str,
            matches: list[dict], say) -> dict:
    """Arma las dos listas de jugadores con todo lo que se pueda leer. Devuelve {"mates", "rivals", "notes"}."""
    known = known_players(matches)
    notes: list[str] = []
    mates, mate_vanities, room_a = parse_people(mates_text, known)
    rivals, rival_vanities, room_b = parse_people(rivals_text, known)
    if room:
        found = ROOM.search(room) or ROOM.search(f"room/{room.strip()}")
        room = found.group(1) if found else ""
    room = room or room_a or room_b
    if room:
        if not faceit_key:
            notes.append(t("Para leer la sala de FACEIT falta tu clave de la API de FACEIT."))
        else:
            say(t("Leyendo la sala de FACEIT"))
            team, enemies = faceit_room(faceit_key, room, me)
            ids = {p.steamid for p in mates + rivals if p.steamid}
            mates += [p for p in team if p.steamid != me and p.steamid not in ids]
            rivals += [p for p in enemies if p.steamid not in ids]
    if (mate_vanities or rival_vanities) and api_key:
        say(t("Buscando los perfiles de Steam"))
        for vanities, target in ((mate_vanities, mates), (rival_vanities, rivals)):
            for name in vanities:
                steamid = resolve_vanity(api_key, name)
                if steamid:
                    target.append(Person(steamid=steamid, source="steam"))
                else:
                    notes.append(t("No encontré el perfil {0}.").format(name))
    elif mate_vanities or rival_vanities:
        notes.append(t("Para los links /id/ hace falta la clave de Web API de Steam."))
    mates = [p for p in mates if p.steamid != me]
    missing = [p.steamid for p in mates + rivals if p.steamid and not p.name]
    if missing and api_key:
        found = summaries(api_key, missing)
        for p in mates + rivals:
            if p.steamid in found and not p.name:
                p.name = found[p.steamid].get("personaname", "")
    for p in mates + rivals:
        p.name = p.name or (known_name(matches, p.steamid) or str(p.steamid))
    if faceit_key and (room or any(p.faceit_id for p in mates + rivals)):
        for person in mates + rivals:
            say(t("Números de FACEIT de {0}").format(person.name))
            try:
                person.faceit = faceit_numbers(faceit_key, person)
            except LobbyError as error:
                notes.append(f"{person.name}: {error}")
    return {"mates": [asdict(p) for p in mates], "rivals": [asdict(p) for p in rivals], "notes": notes}


def known_name(matches: list[dict], steamid: int) -> str:
    for m in reversed(matches):
        for p in m.get("scoreboard") or []:
            if int(p["steamid"]) == steamid and p.get("name"):
                return p["name"]
    return ""


# Análisis ─────────────────────────────────────────────────────────────────────────────────────────────────────────

def _key(raw: str) -> str:
    """El mismo mapa escrito como en las demos (de_dust2), en Steam (Dust II) o en FACEIT (Dust2)."""
    name = (map_label(raw) if raw.lower().startswith("de_") else raw).strip().lower()
    return "dust ii" if name.replace(" ", "") in ("dust2", "dustii") else name


def appearances(matches: list[dict], steamid: int) -> list[dict]:
    """Cada partida tuya en la que jugó ese jugador: el mapa, si ganó su equipo, sus números y sus kills con AWP."""
    result = []
    for m in matches:
        row = next((p for p in m.get("scoreboard") or [] if int(p["steamid"]) == steamid), None)
        if not row or not row.get("stats"):
            continue
        won = (m["result"] == "W") if row.get("ally") else (m["result"] == "L")
        kills = [k for k in (m.get("detail") or {}).get("kills", []) if k[1] == str(steamid)]
        result.append({"map": _key(m["map"]), "won": won, "stats": row["stats"], "ally": bool(row.get("ally")),
                       "awp": sum(1 for k in kills if k[3] == "awp"), "kills": len(kills)})
    return result


def analyze(me: int, mates: list[dict], rivals: list[dict], matches: list[dict], games: list[dict]) -> dict:
    """Mapas (con tu equipo contra los rivales) y rivales a tener en cuenta.

    games: tu historial completo (de Steam o tus demos) para tus propias victorias por mapa."""
    recent = sorted({_key(g["map"]) for g in games[-60:] if g.get("map") and (g.get("mode") or g.get("source")) != "wingman"})
    pool = recent if len(recent) >= 5 else [_key(m) for m in DEFAULT_POOL]

    def tally(people: list[dict], include_me: bool) -> dict[str, list[float]]:
        totals = {m: [0.0, 0.0] for m in pool}
        if include_me:
            for g in games:
                key = _key(g["map"])
                if key in totals:
                    totals[key][0] += g["result"] == "W"
                    totals[key][1] += 1
        for person in people:
            for seen in appearances(matches, int(person.get("steamid") or 0)) if person.get("steamid") else []:
                if seen["map"] in totals:
                    totals[seen["map"]][0] += seen["won"]
                    totals[seen["map"]][1] += 1
            for name, (count, rate) in ((person.get("faceit") or {}).get("maps") or {}).items():
                if name in totals:
                    used = min(count, FACEIT_CAP)
                    totals[name][0] += rate * used
                    totals[name][1] += used
        return totals
    ours, theirs = tally(mates, True), tally(rivals, False)
    rows = []
    for key in pool:
        (w1, g1), (w2, g2) = ours[key], theirs[key]
        our = (w1 + PRIOR / 2) / (g1 + PRIOR)
        their = (w2 + PRIOR / 2) / (g2 + PRIOR)
        rows.append({"map": key, "ours": our, "our_games": int(g1), "theirs": their, "their_games": int(g2),
                     "edge": our - their, "verdict": ""})
    rows.sort(key=lambda r: -r["edge"])
    for row in rows[:2]:
        if row["edge"] > 0.02 and row["our_games"]:
            row["verdict"] = "pick"
    for row in rows[-2:]:
        if row["edge"] < -0.02:
            row["verdict"] = "ban"

    cards = []
    for person in rivals:
        seen = appearances(matches, int(person.get("steamid") or 0)) if person.get("steamid") else []
        stats = combine([s["stats"] for s in seen]) if seen else {}
        kills = sum(s["kills"] for s in seen)
        awp = sum(s["awp"] for s in seen) / kills if kills >= 6 else None
        faceit = person.get("faceit") or {}
        cards.append({"name": person.get("name") or "?", "steamid": person.get("steamid") or 0, "games": len(seen),
                      "against": sum(1 for s in seen if not s["ally"]), "rating": stats.get("rating"),
                      "adr": stats.get("adr"), "opening_pr": stats.get("opening_pr"), "awp": awp,
                      "level": faceit.get("level"), "elo": faceit.get("elo"), "kd": faceit.get("kd") or stats.get("kd"),
                      "win_rate": faceit.get("win_rate"), "extra": faceit.get("extra") or {}, "tags": []})
    entries = [c["opening_pr"] for c in cards if c["opening_pr"] is not None]
    for c in cards:
        if c["awp"] is not None and c["awp"] >= 0.3:
            c["tags"].append("awp")
        if c["opening_pr"] is not None and c["opening_pr"] >= 0.18 and c["opening_pr"] == max(entries):
            c["tags"].append("entry")
        # Con una sola partida un buen día no alcanza: el rating cuenta desde 2 cruces (FACEIT cuenta siempre).
        strong_here = (c["rating"] or 0) >= 1.15 and c["games"] >= 2
        strong_faceit = bool(c["level"]) and ((c["kd"] or 0) >= 1.25 or c["level"] >= 9)
        if strong_here or strong_faceit:
            c["tags"].append("danger")
        c["threat"] = (c["rating"] or (c["kd"] or 1.0)) + 0.3 * len(c["tags"]) + 0.03 * (c["level"] or 0)
    cards.sort(key=lambda c: -c["threat"])
    return {"maps": rows, "rivals": cards, "mates": mates}

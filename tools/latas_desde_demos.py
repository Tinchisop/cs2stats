"""Propone latas nuevas a partir de tiros reales: los que varios jugadores distintos repitieron igual en las demos.

Uso: python tools/latas_desde_demos.py salida.json
Solo se quedan posiciones, ángulos y caídas: ningún nombre ni cuenta. Antes de sumarlas a data/latas.json hay que tirarlas en
CS2 y comprobar dónde caen (record_lineups con verify_demo)."""

from __future__ import annotations

import json
import math
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cs2stats.nades import MapGrid, load_lineups, place_label  # noqa: E402
from cs2stats.parser import GRID  # noqa: E402
from cs2stats.store import Store  # noqa: E402

SAME_SPOT, SAME_AIM, SAME_LAND = 40, 2.5, 200   # unidades, grados, unidades
MIN_PLAYERS, MIN_THROWS = 2, 3
KNOWN_NEAR = 250                                # una lata conocida que cae acá cerca y sale de cerca es la misma
QUOTA = {"smoke": 7, "molotov": 3, "flash": 3, "he": 2}   # cuántas nuevas, como mucho, por mapa
ACTIONS = {"smoke": ("smoke", "smokes"), "flash": ("flash", "flashes"), "molotov": ("molotov", "molotovs"), "he": ("he", "hes")}
EYE = 64
TECHNIQUE_STEPS = {
    ("left", False): ("Soltá con clic izquierdo, sin moverte", "Release with left click, without moving"),
    ("left_jump", False): ("Saltá y soltá con clic izquierdo al mismo tiempo (jumpthrow)", "Jump and release with left click at the same time (jumpthrow)"),
    ("left", True): ("Agachate y soltá con clic izquierdo", "Crouch and release with left click"),
    ("left_jump", True): ("Agachate, saltá y soltá con clic izquierdo al mismo tiempo", "Crouch, jump and release with left click at the same time"),
}


def _slug(text: str) -> str:
    return "".join(c.lower() if c.isalnum() else "-" for c in text).strip("-")


def _groups(throws: list[dict]) -> list[list[dict]]:
    groups: list[list[dict]] = []
    for throw in throws:
        for group in groups:
            first = group[0]
            yaw = abs((throw["ang"][1] - first["ang"][1] + 180) % 360 - 180)
            if (throw["type"] == first["type"] and bool(throw.get("air")) == bool(first.get("air"))
                    and bool(throw.get("duck")) == bool(first.get("duck"))
                    and math.dist(throw["pos"][:2], first["pos"][:2]) <= SAME_SPOT
                    and yaw <= SAME_AIM and abs(throw["ang"][0] - first["ang"][0]) <= SAME_AIM
                    and math.dist(throw["land"][:2], first["land"][:2]) <= SAME_LAND):
                group.append(throw)
                break
        else:
            groups.append([throw])
    return groups


def _ground(grid: MapGrid, group: list[dict]) -> float:
    x, y = group[0]["pos"][:2]
    cell = grid.cells.get((int(x // GRID), int(y // GRID)))
    return cell[0] if cell else min(t["pos"][2] for t in group)


def propose(nade_data: list[dict]) -> list[dict]:
    throws_by_map: dict[str, list[dict]] = {}
    grids_raw: dict[str, list] = {}
    for match in nade_data:
        throws_by_map.setdefault(match["map"], []).extend(match["grenades"])
        grids_raw.setdefault(match["map"], []).extend(match["grid"])
    known = load_lineups()
    result = []
    for map_name in sorted({l.map for l in known}):
        grid = MapGrid(grids_raw.get(map_name, []))
        usable = [t for t in throws_by_map.get(map_name, []) if t.get("land") and t.get("ang") and t.get("flight")
                  and t["type"] in QUOTA and (t.get("speed") or 0) <= 10]
        groups = [g for g in _groups(usable) if len(g) >= MIN_THROWS and len({t["steamid"] for t in g}) >= MIN_PLAYERS]
        groups.sort(key=lambda g: (-len({t["steamid"] for t in g}), -len(g)))
        taken: dict[str, int] = {}
        names = set()
        for group in groups:
            kind = group[0]["type"]
            # Se copia un tiro real, el más parecido a los demás: un promedio de tiros puede caer en cualquier lado.
            model = min(group, key=lambda a: sum(math.dist(a["land"][:2], b["land"][:2]) for b in group))
            pos, ang, land = model["pos"][:2], model["ang"][:2], model["land"][:3]
            if taken.get(kind, 0) >= QUOTA[kind]:
                continue
            if any(l.map == map_name and l.type == kind and math.dist(l.land[:2], land[:2]) <= KNOWN_NEAR
                   and math.dist(l.pos[:2], pos) <= KNOWN_NEAR for l in known):
                continue
            place_to, place_from = grid.place_at(*land[:2]), grid.place_at(*pos)
            if not place_to or not place_from or (kind, place_to, place_from) in names:
                continue
            names.add((kind, place_to, place_from))
            taken[kind] = taken.get(kind, 0) + 1
            jump, duck = bool(group[0].get("air")), bool(group[0].get("duck"))
            technique = "left_jump" if jump else "left"
            step_es, step_en = TECHNIQUE_STEPS[(technique, duck)]
            to_name, from_name = place_label(place_to), place_label(place_from)
            sides = [t["side"] for t in group]
            result.append({
                "id": f"{map_name.removeprefix('de_')}-{ACTIONS[kind][1]}-{_slug(place_to)}-from-{_slug(place_from)}",
                "map": map_name, "type": kind, "side": max(set(sides), key=sides.count), "to": to_name, "frm": from_name,
                "technique": technique, "movement": "crouched_stationary" if duck else "stationary",
                "pos": [round(pos[0], 2), round(pos[1], 2), round(_ground(grid, group) + EYE, 2)],
                "ang": [round(ang[0], 2), round(ang[1], 2)], "land": [round(v, 1) for v in land],
                "flight": round(statistics.median(t["flight"] for t in group), 1),
                "steps": [f"Parate en {from_name}, en el lugar que marca el clip", "Apuntá adonde marca el clip", step_es],
                "move_key": "", "move_time": 0.0, "source": "demos",
                "to_en": to_name, "frm_en": from_name,
                "steps_en": [f"Stand in {from_name}, on the spot the clip marks", "Aim where the clip marks", step_en],
            })
    return result


if __name__ == "__main__":
    proposals = propose(Store().nade_data())
    Path(sys.argv[1]).write_text(json.dumps(proposals, ensure_ascii=False, indent=1), encoding="utf-8")
    print(len(proposals), "latas propuestas")

"""Latas: los lineups más conocidos de cada mapa, probados uno por uno en CS2.

La lista vive en data/latas.json: lugar exacto (setpos/setang), técnica, pasos y dónde cae (medido tirándola en el
juego). De tus demos se cuenta cuántas veces se usó cada uno en tus partidas y cuántas la tiraste vos.
"""

from __future__ import annotations

import json
import math
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .i18n import language, t
from .parser import GRID

TYPES = {"smoke": t("Smoke"), "flash": t("Flash"), "molotov": t("Molotov"), "he": t("HE")}
TYPE_COLORS = {"smoke": "#c9ced6", "flash": "#f2d14e", "molotov": "#ff7a3d", "he": "#5fd18f"}
TECHNIQUES = {"stationary": t("parado"), "running": t("corriendo"), "walking": t("caminando"),
              "crouched_stationary": t("agachado"), "crouched_walking": t("agachado caminando")}

# Nombres de zonas que trae el juego, traducidos a como se dicen en la comunidad. Lo que no esté acá se separa en palabras.
PLACES = {
    "TSpawn": t("Spawn T"), "CTSpawn": t("Spawn CT"), "BombsiteA": t("Sitio A"), "BombsiteB": t("Sitio B"), "TopofMid": t("Top Mid"),
    "Middle": t("Mid"), "SnipersNest": t("Ventana"), "Apartments": t("Apartamentos"), "PalaceInterior": t("Palacio"),
    "PalaceAlley": t("Palacio"), "Catwalk": t("Short"), "Connector": t("Conector"), "Jungle": t("Jungla"), "Stairs": t("Cabezinha"),
    "Underpass": t("Underpass"), "Shop": t("Market"), "SideAlley": t("Side Alley"), "BackAlley": t("Back Alley"), "TRamp": t("Rampa T"),
    "Truck": t("Truck"), "Ladder": t("Ladder"), "House": t("Kitchen"), "Scaffolding": t("Andamio"), "CTStart": t("CT"),
    "LongDoors": t("Puertas de Long"), "LongA": t("Long A"), "ShortStairs": t("Short"), "Pit": t("Pit"), "ExtendedA": t("A Long"),
    "OutsideLong": t("Afuera de Long"), "UpperTunnel": t("Túneles de arriba"), "LowerTunnel": t("Túneles de abajo"), "BDoors": t("Puertas B"),
    "Banana": t("Banana"), "Arch": t("Arco"), "Library": t("Biblioteca"), "Balcony": t("Balcón"), "Graveyard": t("Coffins"), "Quad": t("Quad"),
    "Outside": t("Afuera"), "Ramp": t("Rampa"), "Hut": t("Hut"), "Heaven": t("Heaven"), "Hell": t("Hell"), "Vents": t("Vent"),
    "Secret": t("Secret"), "Silo": t("Silo"), "Garage": t("Garage"), "Mini": t("Mini"), "Lobby": t("Lobby"),
}

MATCH_DIST = 56          # unidades: tu tiro salió del mismo lugar que el lineup
MATCH_ANGLE = 3.0        # grados de diferencia en la mira


def place_label(raw: str) -> str:
    if not raw:
        return t("zona sin nombre")
    return PLACES.get(raw) or re.sub(r"(?<=[a-z])(?=[A-Z0-9])", " ", raw)


def data_path() -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / "cs2stats" / "data" / "latas.json"


class MapGrid:
    """Mapa armado con las posiciones de los jugadores: para dibujarlo y para nombrar dónde cae cada granada."""

    def __init__(self, cells: list[list]):
        self.cells: dict[tuple[int, int], tuple[float, str, int]] = {}
        for gx, gy, z, place, n in cells:
            old = self.cells.get((gx, gy))
            if not old or n > old[2]:
                self.cells[(gx, gy)] = (z, place, n if not old else old[2] + n)

    def place_at(self, x: float, y: float) -> str:
        gx, gy = int(x // GRID), int(y // GRID)
        best, best_d = "", 99
        for dx in range(-4, 5):
            for dy in range(-4, 5):
                cell = self.cells.get((gx + dx, gy + dy))
                if cell and cell[1] and dx * dx + dy * dy < best_d:
                    best, best_d = cell[1], dx * dx + dy * dy
        return best

    def bounds(self) -> tuple[float, float, float, float]:
        xs = [k[0] for k in self.cells] or [0]
        ys = [k[1] for k in self.cells] or [0]
        return min(xs) * GRID, min(ys) * GRID, (max(xs) + 1) * GRID, (max(ys) + 1) * GRID


@dataclass
class Lineup:
    id: str
    map: str
    type: str
    side: str
    to: str
    frm: str
    technique: str           # left, left_jump, both, both_jump
    movement: str            # stationary, running, walking, crouched_stationary, crouched_walking
    pos: list[float]         # altura de los ojos, como la usa setpos
    ang: list[float]
    land: list[float]
    flight: float
    steps: list[str]
    move_key: str = ""       # +forward, +right o +left si hay que moverse al tirar
    move_time: float = 0.0
    to_en: str = ""          # callout, lugar y pasos en inglés (los originales de csnades)
    frm_en: str = ""
    steps_en: list[str] = field(default_factory=list)
    throws: list[dict] = field(default_factory=list)

    @property
    def target(self) -> str:
        return self.to_en if language() == "en" and self.to_en else self.to

    @property
    def origin(self) -> str:
        return self.frm_en if language() == "en" and self.frm_en else self.frm

    @property
    def step_list(self) -> list[str]:
        return self.steps_en if language() == "en" and self.steps_en else self.steps

    @property
    def count(self) -> int:
        return len(self.throws)

    @property
    def mine(self) -> int:
        return sum(1 for t in self.throws if t["me"])

    @property
    def main(self) -> dict:
        return {"pos": self.pos, "land": self.land}

    @property
    def jump(self) -> bool:
        return self.technique.endswith("jump")

    @property
    def technique_label(self) -> str:
        parts = [TECHNIQUES.get(self.movement, t("parado"))]
        if self.jump:
            parts.append(t("salto"))
        if self.technique.startswith("both"):
            parts.append(t("clic izquierdo y derecho"))
        return " · ".join(parts)

    @property
    def title(self) -> str:
        return f"{TYPES[self.type]} {self.target}"

    @property
    def subtitle(self) -> str:
        return t("Desde {0} · {1} · lado {2}").format(self.origin, self.technique_label, self.side or t("cualquiera"))

    @property
    def practice_command(self) -> str:
        x, y, z = self.pos
        pitch, yaw = self.ang
        return f"setpos {x:.2f} {y:.2f} {z:.2f}; setang {pitch:.2f} {yaw:.2f} 0"


def load_lineups() -> list[Lineup]:
    try:
        items = json.loads(data_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [Lineup(**{k: v for k, v in item.items() if k != "source"}) for item in items]


def _same_throw(lineup: Lineup, throw: dict) -> bool:
    if throw["type"] != lineup.type or math.dist(throw["pos"][:2], lineup.pos[:2]) > MATCH_DIST:
        return False
    yaw = abs((throw["ang"][1] - lineup.ang[1] + 180) % 360 - 180)
    return yaw <= MATCH_ANGLE and abs(throw["ang"][0] - lineup.ang[0]) <= MATCH_ANGLE


def build_lineups(nade_data: list[dict]) -> tuple[dict[str, list[Lineup]], dict[str, MapGrid]]:
    """Los lineups conocidos por mapa (con los tiros de tus demos que coinciden) y el mapa armado de cada uno."""
    throws_by_map: dict[str, list[dict]] = {}
    grids_raw: dict[str, list] = {}
    for match in nade_data:
        throws_by_map.setdefault(match["map"], []).extend(match["grenades"])
        grids_raw.setdefault(match["map"], []).extend(match["grid"])
    grids = {name: MapGrid(cells) for name, cells in grids_raw.items()}
    result: dict[str, list[Lineup]] = {}
    for lineup in load_lineups():
        lineup.throws = [t for t in throws_by_map.get(lineup.map, []) if _same_throw(lineup, t)]
        result.setdefault(lineup.map, []).append(lineup)
    for items in result.values():
        order = list(TYPES)
        items.sort(key=lambda l: (order.index(l.type), l.side != "T", -l.count))
    return result, grids

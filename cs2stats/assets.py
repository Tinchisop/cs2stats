"""Recursos visuales sacados de los archivos de CS2 instalados (solo lectura del disco) y tu foto de Steam.

* Fotos oficiales de cada mapa: vienen como PNG dentro de los .vtex_c de pak01_dir.vpk.
* Íconos de armas y de mapas: SVG dentro de los .vsvg_c.
"""

from __future__ import annotations

import logging
import re
import urllib.request
from pathlib import Path

from .finder import cs2_game_dir
from .store import data_dir

log = logging.getLogger("cs2stats")
VERSION = "1"
MAPS = ["de_mirage", "de_inferno", "de_nuke", "de_ancient", "de_anubis", "de_dust2", "de_train", "de_overpass",
        "de_vertigo", "de_cache"]


def assets_dir() -> Path:
    folder = data_dir() / "recursos"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def map_image(map_name: str, variant: int = 0) -> Path | None:
    name = map_name if map_name.startswith("de_") else "de_" + map_name.lower().replace(" ii", "2").replace(" ", "")
    for candidate in ([f"{name}_{variant}.jpg"] if variant else []) + [f"{name}.jpg"]:
        path = assets_dir() / "mapas" / candidate
        if path.exists():
            return path
    return None


def map_images(map_name: str) -> list[Path]:
    return sorted((assets_dir() / "mapas").glob(f"{map_name}*.jpg"))


def weapon_icon(weapon: str) -> Path | None:
    path = assets_dir() / "armas" / f"{weapon}.svg"
    return path if path.exists() else None


def avatar_path() -> Path:
    return assets_dir() / "avatar.jpg"


def _png_inside(data: bytes) -> bytes | None:
    start = data.find(b"\x89PNG\r\n\x1a\n")
    if start < 0:
        return None
    end = data.find(b"IEND", start)
    return data[start:end + 8] if end > 0 else None


def _svg_inside(data: bytes) -> bytes | None:
    start = data.find(b"<svg")
    end = data.rfind(b"</svg>")
    return data[start:end + 6] if start >= 0 and end > start else None


def extract_game_assets(force: bool = False) -> bool:
    """Saca fotos de mapas e íconos del juego. Devuelve True si hay recursos listos."""
    root = assets_dir()
    marker = root / "version.txt"
    if not force and marker.exists() and marker.read_text() == VERSION:
        return True
    game = cs2_game_dir()
    if not game or not (game / "pak01_dir.vpk").exists():
        return False
    import vpk
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage
    pak = vpk.open(str(game / "pak01_dir.vpk"))
    (root / "mapas").mkdir(exist_ok=True)
    (root / "armas").mkdir(exist_ok=True)
    pattern = re.compile(r"panorama/images/map_icons/screenshots/1080p/(de_[a-z0-9]+?)(?:_(\d))?_png\.vtex_c$")
    for name in pak:
        found = pattern.match(name)
        if found and found.group(1) in MAPS:
            png = _png_inside(pak.get_file(name).read())
            if not png:
                continue
            image = QImage.fromData(png, "PNG")
            if image.isNull():
                continue
            image = image.scaledToWidth(960, Qt.TransformationMode.SmoothTransformation)
            suffix = f"_{found.group(2)}" if found.group(2) else ""
            image.save(str(root / "mapas" / f"{found.group(1)}{suffix}.jpg"), "JPG", 86)
        elif name.startswith("panorama/images/icons/equipment/") and name.endswith(".vsvg_c"):
            svg = _svg_inside(pak.get_file(name).read())
            if svg:
                (root / "armas" / (name.rsplit("/", 1)[1][:-len(".vsvg_c")] + ".svg")).write_bytes(svg)
        elif name.startswith("panorama/images/map_icons/map_icon_de_") and name.endswith(".vsvg_c"):
            svg = _svg_inside(pak.get_file(name).read())
            if svg:
                (root / "mapas" / (name.rsplit("/", 1)[1][len("map_icon_"):-len(".vsvg_c")] + "_icono.svg")).write_bytes(svg)
    marker.write_text(VERSION)
    log.info("Recursos del juego extraídos")
    return True


AVATAR_MAX_AGE = 7 * 86400   # las fotos de los demás jugadores se vuelven a bajar una vez por semana


def player_avatar(steamid) -> Path | None:
    """Foto de perfil guardada de otro jugador (la de Steam, pública)."""
    path = assets_dir() / "avatares" / f"{steamid}.jpg"
    return path if path.exists() else None


def download_player_avatars(steamids, api_key: str = "") -> int:
    """Baja las fotos de perfil públicas de los jugadores que faltan o están viejas. Devuelve cuántas bajó.

    Con clave de Web API pide 100 jugadores por consulta; sin clave, lee el perfil público de cada uno en XML."""
    import json
    import time
    folder = assets_dir() / "avatares"
    folder.mkdir(exist_ok=True)
    now = time.time()
    wanted = []
    for steamid in {str(s) for s in steamids if s}:
        path = folder / f"{steamid}.jpg"
        if not path.exists() or now - path.stat().st_mtime > AVATAR_MAX_AGE:
            wanted.append(steamid)
    urls: dict[str, str] = {}
    if api_key:
        for start in range(0, len(wanted), 100):
            batch = ",".join(wanted[start:start + 100])
            query = f"https://api.steampowered.com/ISteamUser/GetPlayerSummaries/v2/?key={api_key}&steamids={batch}"
            try:
                with urllib.request.urlopen(query, timeout=15) as response:
                    for player in json.loads(response.read())["response"]["players"]:
                        urls[str(player["steamid"])] = player.get("avatarfull") or player.get("avatarmedium") or ""
            except (OSError, ValueError, KeyError) as error:
                log.warning("No se pudieron pedir las fotos de los jugadores: %s", error)
                break
    done = 0
    for steamid in wanted:
        url = urls.get(steamid, "")
        try:
            if not url and not api_key:
                with urllib.request.urlopen(f"https://steamcommunity.com/profiles/{steamid}/?xml=1", timeout=15) as response:
                    found = re.search(rb"<avatarFull><!\[CDATA\[(.*?)\]\]>", response.read())
                    url = found.group(1).decode() if found else ""
            if not url:
                continue
            with urllib.request.urlopen(url, timeout=15) as response:
                (folder / f"{steamid}.jpg").write_bytes(response.read())
            done += 1
        except (OSError, ValueError) as error:
            log.warning("No se pudo bajar la foto de %s: %s", steamid, error)
    return done


def download_avatar(steamid: int, api_key: str = "") -> bool:
    """Baja tu foto de perfil de Steam (la pública). Usa la Web API si hay clave; si no, el perfil en XML."""
    url = ""
    try:
        if api_key:
            query = f"https://api.steampowered.com/ISteamUser/GetPlayerSummaries/v2/?key={api_key}&steamids={steamid}"
            with urllib.request.urlopen(query, timeout=15) as response:
                import json
                players = json.loads(response.read())["response"]["players"]
                url = players[0].get("avatarfull", "") if players else ""
        if not url:
            with urllib.request.urlopen(f"https://steamcommunity.com/profiles/{steamid}/?xml=1", timeout=15) as response:
                found = re.search(rb"<avatarFull><!\[CDATA\[(.*?)\]\]>", response.read())
                url = found.group(1).decode() if found else ""
        if not url:
            return False
        with urllib.request.urlopen(url, timeout=15) as response:
            avatar_path().write_bytes(response.read())
        return True
    except (OSError, ValueError, KeyError) as error:
        log.warning("No se pudo bajar la foto de perfil: %s", error)
        return False

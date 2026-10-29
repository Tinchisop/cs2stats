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


# Música de cada mapa: la radio o la música que suena dentro del mapa; si no hay, el fondo del menú de ese mapa.
MUSIC_VERSION = "1"
MAP_MUSIC = {
    "de_anubis": ["ambient/anubis/anubis_music", "ui/panorama/bg_anubis_01"],
    "de_inferno": ["ambient/inferno/church_music_upper", "ambient/inferno/inferno_radio_01", "ui/panorama/bg_inferno_01"],
    "de_nuke": ["ambient/nuke/truck_music", "ui/panorama/bg_nuke_01"],
    "de_train": ["ambient/train/music_de_train_radio", "ambient/de_train_radio", "ui/panorama/bg_train_01"],
    "de_overpass": ["ambient/techno_overpass", "ui/panorama/bg_overpass_01"],
    "de_dust2": ["ambient/dust2/music_attribution_01", "ui/panorama/bg_dust2_01"],
    "de_cache": ["ambient/cache/cache_music_pop", "ui/panorama/bg_cache_01"],
    "de_mirage": ["ambient/mirame_radio_thru_wall", "ambient/latin", "ui/panorama/bg_mirage_01"],
    "de_ancient": ["ambient/aztec2/aztec_music_flute", "ui/panorama/bg_ancient_day_01"],
    "de_vertigo": ["ui/panorama/bg_vertigo_01"],
    "de_italy": ["ui/panorama/bg_italy_01"],
    "de_office": ["ui/panorama/bg_office_01"],
}
MENU_MUSIC = "music/valve_cs2_01/mainmenu"   # para mapas sin música propia
RATES = (11025, 16000, 22050, 24000, 32000, 44100, 48000)


def music_dir() -> Path:
    folder = assets_dir() / "musica"
    folder.mkdir(exist_ok=True)
    return folder


def map_music(map_name: str) -> Path | None:
    """Archivo de música ya sacado del juego para el mapa (o la del menú si el mapa no tiene)."""
    name = map_name if map_name.startswith("de_") else "de_" + map_name.lower().replace(" ii", "2").replace(" ", "")
    for stem in (name, "menu"):
        for ext in ("mp3", "wav"):
            path = music_dir() / f"{stem}.{ext}"
            if path.exists():
                return path
    return None


def vsnd_audio(data: bytes) -> tuple[str, bytes] | None:
    """Audio de un .vsnd_c de Source 2: ("mp3", datos) o ("wav", datos con cabecera RIFF).

    El sonido va después de la cabecera del recurso; el bloque DATA dice frecuencia, formato (0 PCM de 16 bits,
    1 PCM de 8 bits, 2 MP3) y canales en un mismo entero."""
    import struct
    if len(data) < 16:
        return None
    header = struct.unpack_from("<I", data, 0)[0]
    block_offset, block_count = struct.unpack_from("<II", data, 8)
    info = b""
    for index in range(block_count):
        pos = 8 + block_offset + index * 12
        if data[pos:pos + 4] == b"DATA":
            offset, size = struct.unpack_from("<II", data, pos + 4)
            info = data[pos + 4 + offset:pos + 4 + offset + size]
    audio = data[header:]
    for at in range(0, len(info) - 3, 4):
        value = struct.unpack_from("<I", info, at)[0]
        rate, kind, channels = value & 0xFFFF, (value >> 16) & 0xFF, value >> 24
        if rate not in RATES or kind not in (0, 1, 2) or channels not in (1, 2):
            continue
        if kind == 2:
            return "mp3", audio
        bits = 16 if kind == 0 else 8
        block = channels * bits // 8
        audio = audio[:len(audio) - len(audio) % block]
        head = struct.pack("<4sI4s4sIHHIIHH4sI", b"RIFF", 36 + len(audio), b"WAVE", b"fmt ", 16, 1, channels, rate,
                           rate * block, block, bits, b"data", len(audio))
        return "wav", head + audio
    # Formato nuevo: los datos van en un bloque CTRL (KV3); si el sonido arranca con un cuadro MP3, alcanza.
    if len(audio) > 4 and audio[0] == 0xFF and audio[1] & 0xE0 == 0xE0:
        return "mp3", audio
    return None


def extract_map_music(force: bool = False) -> bool:
    """Saca del juego (solo lectura) la música de cada mapa. Devuelve True si quedó lista."""
    folder = music_dir()
    marker = folder / "version.txt"
    if not force and marker.exists() and marker.read_text() == MUSIC_VERSION:
        return True
    game = cs2_game_dir()
    if not game or not (game / "pak01_dir.vpk").exists():
        return False
    import vpk
    pak = vpk.open(str(game / "pak01_dir.vpk"))

    def save(stem: str, sources: list[str]) -> None:
        for source in sources:
            try:
                found = vsnd_audio(pak.get_file(f"sounds/{source}.vsnd_c").read())
            except (KeyError, OSError, ValueError):
                continue
            if found:
                kind, audio = found
                for old in folder.glob(f"{stem}.*"):
                    old.unlink()
                (folder / f"{stem}.{kind}").write_bytes(audio)
                return
    for map_name, sources in MAP_MUSIC.items():
        save(map_name, sources)
    save("menu", [MENU_MUSIC])
    marker.write_text(MUSIC_VERSION)
    log.info("Música de los mapas extraída")
    return True


def map_icon(map_name: str) -> Path | None:
    path = assets_dir() / "mapas" / f"{map_name}_icono.svg"
    return path if path.exists() else None


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

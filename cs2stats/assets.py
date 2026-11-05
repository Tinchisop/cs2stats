"""Recursos visuales sacados de los archivos de CS2 instalados (solo lectura del disco) y tu foto de Steam.

* Fotos oficiales de cada mapa: vienen como PNG dentro de los .vtex_c de pak01_dir.vpk.
* Íconos de armas y de mapas: SVG dentro de los .vsvg_c.
* Radar de cada mapa (el mismo del juego): textura BGRA comprimida con LZ4, con su escala en resource/overviews.
"""

from __future__ import annotations

import logging
import re
import urllib.request
from pathlib import Path

from .finder import cs2_game_dir
from .store import data_dir

log = logging.getLogger("cs2stats")
VERSION = "2"
# Mapas de rehenes: el resto de los mapas de CS2 empiezan con de_ (bomba).
HOSTAGE_MAPS = {"office", "italy", "shelter", "assault", "agency", "militia"}
# Variantes que el juego guarda aparte y no son otro mapa (de noche, versiones viejas, Wingman, vista previa).
VARIANTS = re.compile(r"_(night|v\d|s2|2v2|preview)$")


def assets_dir() -> Path:
    folder = data_dir() / "recursos"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def map_key(map_name: str) -> str:
    """Nombre interno del mapa (de_dust2, cs_office) a partir del de la demo o del historial de Steam ("Dust II")."""
    if map_name[:3] in ("de_", "cs_", "ar_"):
        return map_name
    stem = map_name.lower().replace(" ii", "2").replace(" ", "").replace("-", "")
    return f"cs_{stem}" if stem in HOSTAGE_MAPS else f"de_{stem}"


def map_image(map_name: str, variant: int = 0) -> Path | None:
    name = map_key(map_name)
    for candidate in ([f"{name}_{variant}.jpg"] if variant else []) + [f"{name}.jpg"]:
        path = assets_dir() / "mapas" / candidate
        if path.exists():
            return path
    return None


def map_images(map_name: str) -> list[Path]:
    name = map_key(map_name)
    folder = assets_dir() / "mapas"
    return sorted([*folder.glob(f"{name}.jpg"), *folder.glob(f"{name}_[0-9].jpg")])


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
    pattern = re.compile(r"panorama/images/map_icons/screenshots/1080p/((?:de|cs)_[a-z0-9_]+?)(?:_(\d))?_png\.vtex_c$")
    for name in pak:
        found = pattern.match(name)
        if found and not VARIANTS.search(found.group(1)):
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
        elif name.startswith(("panorama/images/map_icons/map_icon_de_", "panorama/images/map_icons/map_icon_cs_")) \
                and name.endswith(".vsvg_c"):
            svg = _svg_inside(pak.get_file(name).read())
            if svg:
                (root / "mapas" / (name.rsplit("/", 1)[1][len("map_icon_"):-len(".vsvg_c")] + "_icono.svg")).write_bytes(svg)
    marker.write_text(VERSION)
    log.info("Recursos del juego extraídos")
    return True


# Música de cada mapa: la radio o la música que suena dentro del mapa; si no hay, el fondo del menú de ese mapa.
MUSIC_VERSION = "2"
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
    "cs_italy": ["ui/panorama/bg_italy_01"],
    "cs_office": ["ambient/office/elevator_muzak", "ui/panorama/bg_office_01"],
}
MENU_MUSIC = "music/valve_cs2_01/mainmenu"   # para mapas sin música propia
RATES = (11025, 16000, 22050, 24000, 32000, 44100, 48000)


def music_dir() -> Path:
    folder = assets_dir() / "musica"
    folder.mkdir(exist_ok=True)
    return folder


def map_music(map_name: str) -> Path | None:
    """Archivo de música ya sacado del juego para el mapa (o la del menú si el mapa no tiene)."""
    for stem in (map_key(map_name), "menu"):
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


RADAR_VERSION = "1"
# Formatos de textura que se saben leer: bytes por píxel (RGBA/BGRA) o por bloque de 4x4 (DXT1/DXT5).
TEXTURE_FORMATS = {1: ("dxt1", 8), 2: ("dxt5", 16), 4: ("rgba", 4), 28: ("bgra", 4)}


def _level_bytes(kind: int, width: int, height: int) -> int:
    name, size = TEXTURE_FORMATS[kind]
    if name.startswith("dxt"):
        return ((width + 3) // 4) * ((height + 3) // 4) * size
    return width * height * size


def dxt_pixels(raw: bytes, width: int, height: int, with_alpha: bool) -> bytes:
    """Píxeles BGRA de una textura DXT1 (sin alfa propio) o DXT5 (con alfa), decodificada con numpy."""
    import numpy as np
    across, down = (width + 3) // 4, (height + 3) // 4
    size = 16 if with_alpha else 8
    blocks = np.frombuffer(raw[:across * down * size], np.uint8).reshape(across * down, size)
    count = len(blocks)
    color = blocks[:, 8:] if with_alpha else blocks
    words = color.astype(np.uint32)
    c0, c1 = words[:, 0] | (words[:, 1] << 8), words[:, 2] | (words[:, 3] << 8)

    def rgb(value):
        return np.stack([(value & 31) * 255 // 31, ((value >> 5) & 63) * 255 // 63, ((value >> 11) & 31) * 255 // 31],
                        axis=1).astype(np.int32)   # en orden B, G, R
    p0, p1 = rgb(c0), rgb(c1)
    four = (c0 > c1) | with_alpha
    p2 = np.where(four[:, None], (2 * p0 + p1) // 3, (p0 + p1) // 2)
    p3 = np.where(four[:, None], (p0 + 2 * p1) // 3, 0)
    palette = np.stack([p0, p1, p2, p3], axis=1)
    bits = words[:, 4] | (words[:, 5] << 8) | (words[:, 6] << 16) | (words[:, 7] << 24)
    index = ((bits[:, None] >> (2 * np.arange(16, dtype=np.uint32))) & 3).astype(np.int64)
    colors = np.take_along_axis(palette, index[:, :, None].repeat(3, axis=2), axis=1)
    if with_alpha:
        a0, a1 = blocks[:, 0].astype(np.int32), blocks[:, 1].astype(np.int32)
        eight = a0 > a1
        alphas = np.zeros((count, 8), np.int32)
        alphas[:, 0], alphas[:, 1] = a0, a1
        for j in range(2, 8):
            six = ((6 - j) * a0 + (j - 1) * a1) // 5 if j < 6 else np.full(count, 0 if j == 6 else 255)
            alphas[:, j] = np.where(eight, ((8 - j) * a0 + (j - 1) * a1) // 7, six)
        packed = np.zeros(count, np.uint64)
        for k in range(6):
            packed |= blocks[:, 2 + k].astype(np.uint64) << np.uint64(8 * k)
        alpha_index = ((packed[:, None] >> (np.uint64(3) * np.arange(16, dtype=np.uint64))) & np.uint64(7)).astype(np.int64)
        alpha = np.take_along_axis(alphas, alpha_index, axis=1)
    else:
        alpha = np.where(~four[:, None] & (index == 3), 0, 255)
    pixels = np.concatenate([colors, alpha[:, :, None]], axis=2).astype(np.uint8)
    pixels = pixels.reshape(down, across, 4, 4, 4).transpose(0, 2, 1, 3, 4).reshape(down * 4, across * 4, 4)
    return np.ascontiguousarray(pixels[:height, :width]).tobytes()


def lz4_block(data: bytes, size: int) -> bytes:
    """Descomprime un bloque LZ4 sin marco, como vienen las texturas de CS2.

    Usa el LZ4 de pyarrow (que ya trae la app); si no está, lo hace en Python (más lento, pero anda igual)."""
    try:
        import pyarrow
        return pyarrow.decompress(data, size, codec="lz4_raw", asbytes=True)
    except Exception:  # noqa: BLE001 - sin pyarrow o sin ese códec: la versión en Python
        pass
    out = bytearray()
    i, n = 0, len(data)
    while i < n:
        token = data[i]
        i += 1
        length = token >> 4
        if length == 15:
            while True:
                extra = data[i]
                i += 1
                length += extra
                if extra != 255:
                    break
        out += data[i:i + length]
        i += length
        if i >= n:
            break
        offset = data[i] | (data[i + 1] << 8)
        i += 2
        match = token & 15
        if match == 15:
            while True:
                extra = data[i]
                i += 1
                match += extra
                if extra != 255:
                    break
        match += 4
        start = len(out) - offset
        if offset >= match:
            out += out[start:start + match]
        else:   # la copia se pisa a sí misma: es el mismo patrón repetido
            pattern = bytes(out[start:start + offset])
            out += (pattern * (match // offset + 1))[:match]
    return bytes(out)


def vtex_image(data: bytes):
    """Imagen (QImage) de una textura de Source 2 (.vtex_c) sin comprimir en bloques, o el PNG que traiga adentro.

    La cabecera del recurso lista sus bloques; el DATA dice ancho, alto, formato y niveles. Los píxeles van después
    de ese bloque, del nivel más chico al más grande, y si hay datos extra de tipo 4 cada nivel viene en LZ4."""
    import struct
    from PySide6.QtGui import QImage
    try:
        block_offset, block_count = struct.unpack_from("<II", data, 8)
        info = None
        for index in range(block_count):
            pos = 8 + block_offset + index * 12
            if data[pos:pos + 4] == b"DATA":
                offset, size = struct.unpack_from("<II", data, pos + 4)
                info = (pos + 4 + offset, size)
        if info is None:
            return None
        start, size = info
        width, height, depth = struct.unpack_from("<HHH", data, start + 20)
        kind, levels = data[start + 26], max(1, data[start + 27])
        if kind not in TEXTURE_FORMATS:
            png = _png_inside(data)
            image = QImage.fromData(png, "PNG") if png else None
            return image if image is not None and not image.isNull() else None
        extra_offset, extra_count = struct.unpack_from("<II", data, start + 32)
        compressed: tuple[int, ...] | None = None
        for index in range(extra_count):
            pos = start + 32 + extra_offset + index * 12
            extra_kind, offset, _size = struct.unpack_from("<III", data, pos)
            if extra_kind == 4:
                at = pos + 4 + offset
                flag, sizes_offset, count = struct.unpack_from("<III", data, at)
                if flag == 1:
                    compressed = struct.unpack_from(f"<{count}I", data, at + 4 + sizes_offset)
        body = start + size
        full = _level_bytes(kind, width, height) * max(1, depth)
        if compressed:
            begin = body + sum(compressed[1:])
            pixels = lz4_block(data[begin:begin + compressed[0]], full)
        else:
            sizes = [_level_bytes(kind, max(1, width >> level), max(1, height >> level)) for level in range(levels)]
            begin = body + sum(sizes[1:])
            pixels = data[begin:begin + full]
        if len(pixels) < _level_bytes(kind, width, height):
            return None
        name = TEXTURE_FORMATS[kind][0]
        if name.startswith("dxt"):
            pixels, name = dxt_pixels(pixels, width, height, name == "dxt5"), "bgra"
        layout = QImage.Format.Format_ARGB32 if name == "bgra" else QImage.Format.Format_RGBA8888
        # copy(): la imagen queda con sus propios píxeles y no depende de los bytes de acá, que se liberan al salir.
        return QImage(pixels[:width * height * 4], width, height, width * 4, layout).convertToFormat(
            QImage.Format.Format_ARGB32).copy()
    except (struct.error, IndexError, ValueError):
        return None


def _clean_alpha(image, below: int = 112):
    """Borra lo casi transparente del radar: la grilla tenue y las líneas del borde que se verían como rayas."""
    import numpy
    from PySide6.QtGui import QImage
    image = image.convertToFormat(QImage.Format.Format_ARGB32)
    width, height, line = image.width(), image.height(), image.bytesPerLine()
    pixels = numpy.frombuffer(image.constBits(), numpy.uint8).reshape(height, line).copy()
    alpha = pixels[:, 3:width * 4:4]
    faint = alpha < below
    faint[:2, :] = faint[-2:, :] = True   # el marco de la imagen: algunos radares traen ahí una línea suelta
    faint[:, :2] = faint[:, -2:] = True
    for channel in range(4):
        pixels[:, channel:width * 4:4][faint] = 0
    return QImage(pixels.tobytes(), width, height, line, QImage.Format.Format_ARGB32).copy()


def _opaque_box(image) -> list[int]:
    """Rectángulo (en píxeles) donde está dibujado el mapa, sin el borde transparente ni la grilla tenue."""
    import numpy
    width, height = image.width(), image.height()
    alpha = numpy.frombuffer(image.constBits(), numpy.uint8).reshape(height, image.bytesPerLine())[:, 3:width * 4:4]
    solid = alpha > 160
    rows = numpy.flatnonzero(solid.sum(axis=1) > width * 0.01)
    cols = numpy.flatnonzero(solid.sum(axis=0) > height * 0.01)
    if not len(rows) or not len(cols):
        return [0, 0, width, height]
    return [int(cols[0]), int(rows[0]), int(cols[-1]) + 1, int(rows[-1]) + 1]


def radars_dir() -> Path:
    folder = assets_dir() / "radares"
    folder.mkdir(exist_ok=True)
    return folder


def extract_radars(force: bool = False) -> bool:
    """Saca del juego (solo lectura) el radar de cada mapa, su escala y dónde están los sitios y los spawns.

    En radares/: <mapa>.png, <mapa>_lower.png (Nuke, Vertigo y Train tienen un piso de abajo) y radares.json con
    cómo pasar de coordenadas del juego a píxeles. Los sitios y spawns van a overviews.json, como antes."""
    import json
    folder = radars_dir()
    marker = folder / "version.txt"
    if not force and marker.exists() and marker.read_text() == RADAR_VERSION:
        return True
    game = cs2_game_dir()
    if not game or not (game / "pak01_dir.vpk").exists():
        return False
    import vpk
    pak = vpk.open(str(game / "pak01_dir.vpk"))
    names = sorted(found.group(1) for found in (re.match(r"resource/overviews/((?:de|cs)_[a-z0-9_]+)\.txt$", path)
                                                 for path in pak) if found and not VARIANTS.search(found.group(1)))
    radars, markers = {}, {}

    def texture(stem: str):
        for suffix in ("_radar_psd", "_radar_tga", "_radar"):
            try:
                image = vtex_image(pak.get_file(f"panorama/images/overheadmaps/{stem}{suffix}.vtex_c").read())
            except (KeyError, OSError, ValueError):
                continue
            if image is not None and not image.isNull():
                return _clean_alpha(image)
        return None

    for name in names:
        try:
            text = pak.get_file(f"resource/overviews/{name}.txt").read().decode("utf-8", "replace")
        except (KeyError, OSError, ValueError):
            continue
        values = dict(re.findall(r'"(\w+)"\s+"([-\d.]+)"', text))
        try:
            x0, y0, scale = float(values["pos_x"]), float(values["pos_y"]), float(values["scale"])
        except (KeyError, ValueError):
            continue
        spots = {}
        for key, title in (("bombA", "A"), ("bombB", "B"), ("CTSpawn", "CT"), ("TSpawn", "T")):
            if f"{key}_x" in values and f"{key}_y" in values:
                # Las marcas vienen como fracción de la imagen del radar (1024 px).
                spots[title] = [round(x0 + float(values[f"{key}_x"]) * 1024 * scale),
                                round(y0 - float(values[f"{key}_y"]) * 1024 * scale)]
        markers[name] = spots
        image = texture(name)
        if image is None:
            continue
        image.save(str(folder / f"{name}.png"), "PNG")
        entry = {"x": x0, "y": y0, "scale": scale, "size": [image.width(), image.height()], "box": _opaque_box(image)}
        lower = re.search(r'"lower"[^{]*\{\s*"AltitudeMax"\s*"([-\d.]+)"', text)
        lower_image = texture(f"{name}_lower") if lower else None
        if lower_image is not None:
            lower_image.save(str(folder / f"{name}_lower.png"), "PNG")
            entry["lower_below"] = float(lower.group(1))
        radars[name] = entry
    if not radars:
        return False
    (folder / "radares.json").write_text(json.dumps(radars), encoding="utf-8")
    (assets_dir() / "overviews.json").write_text(json.dumps(markers), encoding="utf-8")
    marker.write_text(RADAR_VERSION)
    log.info("Radares de %d mapas extraídos", len(radars))
    return True


def map_radar(map_name: str) -> dict | None:
    """Radar del mapa: {"image": ruta, "lower": ruta o None, "x", "y", "scale", "size", "box"} o None si no está."""
    import json
    name = map_key(map_name)
    folder = assets_dir() / "radares"
    try:
        entry = json.loads((folder / "radares.json").read_text(encoding="utf-8")).get(name)
    except (OSError, ValueError):
        return None
    image = folder / f"{name}.png"
    if not entry or not image.exists():
        return None
    lower = folder / f"{name}_lower.png"
    return {**entry, "image": image, "lower": lower if lower.exists() else None}


def map_markers(map_name: str) -> dict[str, list[int]]:
    """Sitios A y B y spawns del mapa en coordenadas del juego ({} si todavía no se sacaron del juego)."""
    import json
    try:
        return json.loads((assets_dir() / "overviews.json").read_text(encoding="utf-8")).get(map_key(map_name), {})
    except (OSError, ValueError):
        return {}


def map_icon(map_name: str) -> Path | None:
    path = assets_dir() / "mapas" / f"{map_key(map_name)}_icono.svg"
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

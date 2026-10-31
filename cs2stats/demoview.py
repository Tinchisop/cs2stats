"""Abre una jugada en CS2: reproduce la demo real y salta al momento exacto, con la cámara en tu jugador.

La consola remota de CS2 solo abre con -insecure. Por eso nunca se le manda nada a un CS2 abierto a mano: si ya está
abierto sin la consola, se le pasan los comandos a la persona para que los pegue ella. Así no se corta ninguna partida."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import steamapi
from .finder import cs2_game_dir, remove_quietly
from .i18n import t
from .parser import TICKRATE, DemoError, round_start_ticks
from .recorder import NETCON_PORT, NetCon, cs2_running
from .store import Store

DEMO_FOLDER = "replays/cs2stats"   # subcarpeta: la búsqueda de demos nuevas no entra y no la vuelve a importar
LOAD_TIMEOUT = 180                 # segundos para que CS2 abra y cargue la demo
TICK_MARGIN = 2 * TICKRATE         # CS2 cae en el tick pedido; esto solo evita confundirlo con un salto anterior
SKIP_DONE = re.compile(r"Demo Skipping finished at tick (\d+)")
DEMO_STATUS = "[DEMO]"             # lo que muestra "status" cuando hay una demo cargada
SETTLE_SECONDS = 5                 # margen después de cargar, antes de pedir el salto
JUMP_WAIT = 15                     # segundos para que CS2 confirme un salto antes de volver a pedirlo

_loaded = ""                       # la demo que esta sesión de la app ya cargó en CS2
_ticks: dict[str, list[int]] = {}  # rondas de la última demo leída (leerlas tarda varios segundos)


class DemoViewError(Exception):
    pass


@dataclass
class OpenResult:
    """Qué pasó. Sin comandos, CS2 ya quedó en la jugada; con comandos, hay que pegarlos en su consola."""
    commands: list[str]


def _copy_or_link(source: Path, target: Path) -> None:
    try:
        os.link(source, target)   # sin duplicar cientos de MB si están en el mismo disco
    except OSError:
        shutil.copyfile(source, target)


def _clean(folder: Path, keep: Path) -> None:
    """Solo queda la última demo abierta: cada una pesa cientos de MB."""
    for old in folder.glob("*.dem"):
        if old != keep:
            remove_quietly(old)


def prepare_demo(store: Store, match: dict, game: Path, say: Callable[[str], None]) -> tuple[Path, str]:
    """Deja la demo donde CS2 la pueda abrir. Devuelve el archivo y su ruta relativa a game\\csgo."""
    path, url = store.demo_sources(match["match_key"])
    local = Path(path) if path and path.lower().endswith(".dem") and Path(path).exists() else None
    if local and local.resolve().is_relative_to(game.resolve()):
        return local, local.resolve().relative_to(game.resolve()).as_posix()
    folder = game / DEMO_FOLDER
    folder.mkdir(parents=True, exist_ok=True)
    if local:
        target = folder / local.name
        if not target.exists():
            say(t("Preparando la demo para CS2"))
            _copy_or_link(local, target)
    elif url:
        target = folder / url.rsplit("/", 1)[-1].removesuffix(".bz2")
        if not target.exists():
            say(t("Bajando la demo de los servidores de Valve"))
            try:
                target = steamapi.download_demo(url, folder)
            except steamapi.SteamError as error:
                raise DemoViewError(str(error)) from error
    else:
        raise DemoViewError(t("La demo de esta partida ya no está en tu PC y no hay de dónde bajarla."))
    _clean(folder, target)
    return target, f"{DEMO_FOLDER}/{target.name}"


def target_tick(path: Path, round_number: int, seconds: float) -> int:
    key = str(path)
    if key not in _ticks:
        _ticks.clear()
        try:
            _ticks[key] = round_start_ticks(key)
        except DemoError as error:
            raise DemoViewError(str(error)) from error
    starts = _ticks[key]
    if not 1 <= round_number <= len(starts):
        raise DemoViewError(t("La demo no tiene la ronda {0}.").format(round_number))
    return starts[round_number - 1] + max(0, round(seconds * TICKRATE))


def console_commands(relative: str, tick: int) -> list[str]:
    return [f'playdemo "{relative}"', f"demo_gototick {tick} 0 0"]


def launch_for_demo(game: Path, relative: str) -> None:
    exe = game.parent / "bin" / "win64" / "cs2.exe"
    if not exe.exists():
        raise DemoViewError(t("No se encontró CS2 en esta PC."))
    subprocess.Popen([str(exe), "-steam", "-novid", "-insecure", "-netconport", str(NETCON_PORT), "+playdemo", relative],
                     cwd=str(exe.parent))


def _wait(console: NetCon, seconds: float, done: Callable[[str], bool]) -> str:
    """Lee la consola hasta que aparece lo que se espera o se acaba el tiempo."""
    text, end = "", time.monotonic() + seconds
    while time.monotonic() < end and not done(text):
        text += console.drain()
    return text


def _demo_playing(console: NetCon) -> bool:
    console.push("status")
    return DEMO_STATUS in _wait(console, 2, lambda text: DEMO_STATUS in text)


def _connect(timeout: float) -> NetCon | None:
    console, end = NetCon(), time.monotonic() + timeout
    while True:
        if console.connect():
            return console
        if time.monotonic() >= end:
            return None
        time.sleep(1)


def jump(console: NetCon, tick: int, player: str, timeout: float = LOAD_TIMEOUT) -> bool:
    """Espera a que la demo esté cargada y pide el salto hasta que CS2 confirma que llegó.

    Durante la carga no se le pide saltar: el pedido cae en el tick 0 y mandarlo seguido puede cerrar el juego."""
    end = time.monotonic() + timeout
    while not _demo_playing(console):
        if time.monotonic() >= end:
            return False
        time.sleep(1)
    time.sleep(SETTLE_SECONDS)

    def arrived(text: str) -> bool:
        return any(abs(int(found) - tick) <= TICK_MARGIN for found in SKIP_DONE.findall(text))

    while time.monotonic() < end:
        console.push(f"demo_gototick {tick} 0 0")
        if arrived(_wait(console, JUMP_WAIT, arrived)):
            if player:
                console.push('spec_player "{0}"'.format(player.replace('"', "")))
            return True
    return False


def open_moment(store: Store, match: dict, round_number: int, seconds: float, say: Callable[[str], None]) -> OpenResult:
    """Abre la partida en CS2 en esa ronda y ese segundo (contado desde el fin del freeze)."""
    global _loaded
    game = cs2_game_dir()
    if not game:
        raise DemoViewError(t("No se encontró CS2 en esta PC."))
    path, relative = prepare_demo(store, match, game, say)
    say(t("Buscando la ronda en la demo"))
    tick = target_tick(path, round_number, seconds)
    running = cs2_running()
    console = _connect(0) if running else None
    if running and not console:
        return OpenResult(console_commands(relative, tick))
    if not running:
        say(t("Abriendo CS2"))
        launch_for_demo(game, relative)
        _loaded = relative
        console = _connect(LOAD_TIMEOUT)
        if not console:
            return OpenResult(console_commands(relative, tick))
    try:
        if running and (_loaded != relative or not _demo_playing(console)):
            console.push(f'playdemo "{relative}"')
            _loaded = relative
            time.sleep(4)   # para no saltar dentro de la demo anterior antes de que se cierre
        say(t("Yendo a la jugada"))
        if not jump(console, tick, match.get("my_name") or ""):
            return OpenResult(console_commands(relative, tick))
    finally:
        console.close()
    return OpenResult([])

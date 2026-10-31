"""Grabación de clips de latas en CS2.

Cómo funciona, sin tocar la memoria del juego ni simular el teclado:
* CS2 se abre en modo práctica con las opciones oficiales "-insecure" (sin VAC en esa sesión, solo servidor propio)
  y "-netconport", que deja mandarle comandos de consola por la red local de la PC (127.0.0.1).
* Por cada lata: la cámara se acerca caminando al lugar donde hay que pararse, después te pone en el lugar exacto
  (setpos/setang), te da la granada y la tira con la técnica del lineup.
* Se graba solo la ventana de CS2 y el clip queda como WebP animado en tu PC, con un .json al lado que dice en qué
  segundos se muestra dónde pararse y adónde apuntar (la app lo marca encima del clip).
"""

from __future__ import annotations

import heapq
import json
import logging
import math
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable

from .i18n import t as tr
from .store import data_dir

log = logging.getLogger("cs2stats")
NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
NETCON_PORT = 2121
LAUNCH_URL = f"steam://run/730//-insecure -netconport {NETCON_PORT} -novid/"
WEAPONS = {"smoke": "weapon_smokegrenade", "flash": "weapon_flashbang", "molotov": "weapon_molotov", "he": "weapon_hegrenade"}
PRACTICE_SETUP = [
    "sv_cheats 1", "mp_warmup_end", "bot_kick", "mp_freezetime 0", "mp_roundtime 60", "mp_roundtime_defuse 60",
    "mp_buytime 9999", "mp_buy_anywhere 1", "sv_infinite_ammo 0", "ammo_grenade_limit_total 5",
    "mp_respawn_on_death_t 1", "mp_respawn_on_death_ct 1", "sv_falldamage_scale 0", "sv_grenade_trajectory_prac_pipreview 0",
    # Sin HUD (el juego esconde la mira con él): la app marca el punto de mira encima del clip.
    "cl_drawhud 0", "firstperson",
    "ent_fire func_breakable break",   # ventanas que en partida se rompen antes de tirar (Nuke)
    "mp_restartgame 1",
]
HUD_RESTORE = "cl_drawhud 1; cl_draw_only_deathnotices 0; r_drawviewmodel 1"
CLIP_FPS = 60
CLIP_WIDTH = 1280
CLIP_CROP = 0.92
APPROACH_SECONDS = 2.2   # sin lugar para caminar, cuánto tarda en girar mostrando dónde te parás
EYE = 64
CAMERA_RATE = 90         # veces por segundo que se le manda la mira a CS2 mientras se mueve
WALK_MIN, WALK_MAX = 72, 480   # unidades que se camina hasta el lugar de tiro
WALK_LOOK = 200          # desde esta distancia empieza a mirar el piso donde va a pararse
ROUTE_FLOOR = 70         # diferencia de altura para aceptar que una celda es el piso del lugar de tiro
ROUTE_STEP = 34          # desnivel máximo entre dos celdas vecinas (escaleras sí, techos y cajas no)
ROUTE_QUIET = 12         # cuánto evita la ruta las celdas por donde casi no pasa nadie
ROUTE_AHEAD = 72         # a esta distancia de un punto de la ruta ya apunta al siguiente
WALK_SLOW = 70           # a esta distancia pasa a caminar con shift, para frenar justo
WALK_ARRIVED = 10
WALK_ENOUGH = 24         # si le falta menos que esto, se nota nada al acomodarlo en el lugar exacto
REHEARSALS = 5           # intentos de encontrar una ruta sin trabarse
WALK_TIMEOUT = 7.0
WALK_STUCK = 0.7         # segundos sin acercarse: se chocó con algo
WALK_MAX_PITCH = 30.0
TURN_SECONDS = 1.1       # giro hasta el punto de mira
POSITION = re.compile(r"setpos\s+(-?[\d.]+)\s+(-?[\d.]+)\s+(-?[\d.]+)")


class RecorderError(Exception):
    pass


def clips_dir() -> Path:
    folder = data_dir() / "clips"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def bundled_clips_dir() -> Path | None:
    """Clips que vienen con la descarga de la app (carpeta clips junto al .exe): así no hace falta grabarlos."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent / "clips"
    return None


def _clip_file(name: str) -> Path:
    own = clips_dir() / name
    bundled = bundled_clips_dir()
    if own.exists() or not bundled or not (bundled / name).exists():
        return own
    return bundled / name


def clip_path(lineup_id: str) -> Path:
    """El clip propio si lo grabaste; si no, el que viene con la app."""
    return _clip_file(f"{lineup_id}.mp4")


def clip_meta(lineup_id: str) -> dict:
    """Tramos del clip en segundos: position (dónde pararse) y aim (adónde apuntar). Los clips viejos no traen .json."""
    try:
        return json.loads(_clip_file(f"{lineup_id}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"fps": 20, "position": None, "aim": [0.0, 2.3]}


def walking_route(lineup, grid, blocked: set | None = None) -> list[tuple[float, float, float]] | None:
    """Por dónde llegar caminando al lugar de tiro: puntos (x, y, piso) sobre las celdas por donde caminan los jugadores en
    las demos, prefiriendo las más transitadas (lejos de paredes y cajas) y sin pasar por las celdas bloqueadas.
    None si el lugar no conecta con el piso."""
    if not grid or not grid.cells:
        return None
    from .parser import GRID
    x, y, z = lineup.pos
    floor = z - EYE
    home = (int(x // GRID), int(y // GRID))
    blocked = blocked or set()
    starts = sorted(((home[0] + i, home[1] + j) for i in range(-2, 3) for j in range(-2, 3)),
                    key=lambda c: abs(c[0] - home[0]) + abs(c[1] - home[1]))
    start = next((c for c in starts if c in grid.cells and abs(grid.cells[c][0] - floor) <= ROUTE_FLOOR), None)
    if start is None:
        return None
    best = {start: 0.0}
    came: dict[tuple[int, int], tuple[int, int]] = {}
    length = {start: 0.0}
    heap = [(0.0, start)]
    far = start
    while heap:
        cost, cell = heapq.heappop(heap)
        if cost > best[cell]:
            continue
        if length[cell] > length[far]:
            far = cell
        if length[cell] >= WALK_MAX:
            far = cell
            break
        for i, j in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)):
            near = (cell[0] + i, cell[1] + j)
            info = grid.cells.get(near)
            if not info or near in blocked or abs(info[0] - grid.cells[cell][0]) > ROUTE_STEP:
                continue
            if i and j and ((cell[0] + i, cell[1]) not in grid.cells or (cell[0], cell[1] + j) not in grid.cells):
                continue    # no cortar esquinas
            step = GRID * math.hypot(i, j)
            total = cost + step * (1 + ROUTE_QUIET / max(1, info[2]))
            if total < best.get(near, math.inf):
                best[near], came[near], length[near] = total, cell, length[cell] + step
                heapq.heappush(heap, (total, near))
    if length[far] < WALK_MIN:
        return None
    route = []
    cell = far
    while cell != start:
        route.append(((cell[0] + 0.5) * GRID, (cell[1] + 0.5) * GRID, grid.cells[cell][0]))
        cell = came[cell]
    route.append((x, y, floor))
    return route


def ffmpeg_path() -> str | None:
    found = shutil.which("ffmpeg")
    if found:
        return found
    winget = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages"
    for candidate in winget.glob("Gyan.FFmpeg*/*/bin/ffmpeg.exe"):
        return str(candidate)
    return None


def cs2_running() -> bool:
    try:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq cs2.exe", "/NH"], capture_output=True, text=True,
                             creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0).stdout
        return "cs2.exe" in out.lower()
    except OSError:
        return False


def launch_practice() -> None:
    """Abre CS2 con las opciones de práctica. Se abre el ejecutable directo (con Steam abierto se conecta igual):
    la URL steam://run ignora las opciones de inicio."""
    from .finder import cs2_game_dir
    game = cs2_game_dir()
    exe = game.parent / "bin" / "win64" / "cs2.exe" if game else None
    if exe and exe.exists():
        subprocess.Popen([str(exe), "-steam", "-insecure", "-netconport", str(NETCON_PORT), "-novid"], cwd=str(exe.parent))
    else:
        os.startfile(LAUNCH_URL)  # noqa: S606 - URL oficial de Steam como alternativa


class NetCon:
    """Consola remota oficial de CS2 (opción -netconport), solo en 127.0.0.1."""

    def __init__(self):
        self.sock: socket.socket | None = None

    def connect(self, timeout: float = 2.0) -> bool:
        try:
            self.sock = socket.create_connection(("127.0.0.1", NETCON_PORT), timeout=timeout)
            self.sock.settimeout(0.2)
            return True
        except OSError:
            self.sock = None
            return False

    def send(self, command: str) -> None:
        if not self.sock:
            raise RecorderError(tr("Se perdió la conexión con la consola de CS2."))
        try:
            self.sock.sendall((command + "\n").encode("utf-8"))
        except OSError as error:
            raise RecorderError(tr("Se perdió la conexión con la consola de CS2.")) from error
        self.drain()

    def push(self, command: str) -> None:
        """Como send, pero sin esperar la respuesta: para mandar muchos comandos seguidos (cámara en movimiento)."""
        if not self.sock:
            raise RecorderError(tr("Se perdió la conexión con la consola de CS2."))
        try:
            self.sock.sendall((command + "\n").encode("utf-8"))
        except OSError as error:
            raise RecorderError(tr("Se perdió la conexión con la consola de CS2.")) from error

    def drain(self) -> str:
        """Lee y descarta lo que la consola devuelve (si no, se llena el búfer)."""
        chunks = []
        try:
            while self.sock:
                data = self.sock.recv(65536)
                if not data:
                    break
                chunks.append(data)
        except OSError:
            pass
        return b"".join(chunks).decode("utf-8", "replace")

    def close(self) -> None:
        if self.sock:
            self.sock.close()
            self.sock = None


def wait_for_console(timeout: float, should_stop: Callable[[], bool]) -> NetCon:
    con = NetCon()
    end = time.time() + timeout
    while time.time() < end and not should_stop():
        if con.connect():
            return con
        time.sleep(2)
    raise RecorderError(tr("No pude conectarme a CS2. Asegurate de haberlo abierto con el botón de la app y de aceptar "
                        "las opciones de inicio en Steam."))


def _release_steps(lineup) -> list[tuple[str, float]]:
    """Comandos y esperas para soltar la granada con la técnica del lineup (con el seguro ya tirado)."""
    both = lineup.technique.startswith("both")
    release = "-attack; -attack2" if both else "-attack"
    steps = []
    if lineup.move_key:
        if lineup.movement == "walking":
            steps.append(("+speed", 0.0))
        steps.append((lineup.move_key, lineup.move_time))
    steps.append((f"+jump; {release}" if lineup.jump else release, 0.15))
    steps.append(("-jump; -forward; -right; -left; -speed", 0.0))
    return steps


def record_lineups(map_name: str, lineups: list, log_cb: Callable[[str], None], should_stop: Callable[[], bool],
                   grid=None, verify_demo: str = "") -> int:
    """Graba un clip por lata. Devuelve cuántos clips quedaron guardados.

    Con verify_demo, CS2 además graba esa demo: de ahí se puede leer dónde cayó de verdad cada granada."""
    ffmpeg = ffmpeg_path()
    if not ffmpeg:
        raise RecorderError(tr("Falta ffmpeg para grabar la pantalla."))
    log_cb(tr("Esperando la consola de CS2"))
    con = wait_for_console(240, should_stop)
    log_cb(tr("Cargando {0} en un servidor propio").format(map_name))
    time.sleep(8)  # que termine de abrir el menú
    con.send("sv_cheats 1")
    con.send(f"map {map_name}")
    for _ in range(40):  # el mapa tarda en cargar; la consola sigue respondiendo mientras tanto
        if should_stop():
            return 0
        time.sleep(1)
    con.close()
    if not con.connect(5):
        raise RecorderError(tr("CS2 cerró la consola al cambiar de mapa."))
    for command in PRACTICE_SETUP:
        con.send(command)
    time.sleep(3)
    for command in PRACTICE_SETUP[:-1]:  # después del reinicio de ronda
        con.send(command)
    saved = 0
    temp = data_dir() / "temporal"
    temp.mkdir(exist_ok=True)
    if verify_demo:
        con.send(f"record {verify_demo}")
    for index, lineup in enumerate(lineups, start=1):
        if should_stop():
            break
        log_cb(tr("Grabando {0} de {1}: {2}").format(index, len(lineups), lineup.title))
        if _record_one(con, ffmpeg, lineup, temp, grid):
            saved += 1
    if verify_demo:
        con.send("stop")
        time.sleep(2)
    con.send(HUD_RESTORE)
    con.close()
    close_capture()
    log_cb(tr("Terminando de armar los clips"))
    wait_encoding()
    return saved


class WindowCapture:
    """Captura de la ventana de CS2 con Windows Graphics Capture (lo de arriba, como otras ventanas, no sale).
    Se abre una sola vez por tanda de clips: abrirla y cerrarla en cada clip hace caer a la librería."""

    def __init__(self, title: str = "Counter-Strike 2"):
        self.title = title
        self.latest = None
        self.control = None
        self.closed = False

    def start(self) -> bool:
        from windows_capture import WindowsCapture
        capture = WindowsCapture(cursor_capture=False, draw_border=False, window_name=self.title)

        @capture.event
        def on_frame_arrived(frame, _control):  # noqa: ANN001 - firma de windows_capture
            self.latest = frame.frame_buffer.copy()

        @capture.event
        def on_closed():
            self.closed = True

        try:
            self.control = capture.start_free_threaded()
        except Exception as error:  # ventana no encontrada u otro problema de captura
            log.warning("Captura de ventana: %s", error)
            return False
        return True

    def stop(self) -> None:
        try:
            self.control.stop()
            self.control.wait()
        except Exception:  # la captura ya pudo haber terminado sola
            pass


_CAPTURE: WindowCapture | None = None


def window_capture() -> WindowCapture | None:
    global _CAPTURE
    if _CAPTURE is None or _CAPTURE.closed:
        _CAPTURE = WindowCapture()
        if not _CAPTURE.start():
            _CAPTURE = None
    return _CAPTURE


def close_capture() -> None:
    global _CAPTURE
    if _CAPTURE:
        _CAPTURE.stop()
        _CAPTURE = None


class WindowRecorder:
    """Graba solo la ventana de CS2 con Windows Graphics Capture (lo de arriba, como otras ventanas, no sale)
    y la manda a ffmpeg, que arma un MP4: pesa mucho menos que un WebP animado y se reproduce más fluido."""

    def __init__(self, ffmpeg: str, out: Path, fps: int = CLIP_FPS):
        self.ffmpeg, self.out, self.fps = ffmpeg, out, fps
        self.capture: WindowCapture | None = None
        self.running = False
        self.process: subprocess.Popen | None = None
        self.writer: threading.Thread | None = None
        self.ready = threading.Event()     # se escribió el primer cuadro: desde acá cuentan los segundos del clip
        self.started_at = 0.0
        self.raw = out.with_suffix(".grabando.mp4")

    def elapsed(self) -> float:
        return time.perf_counter() - self.started_at

    def start(self) -> bool:
        self.capture = window_capture()
        if not self.capture:
            return False
        self.running = True
        self.writer = threading.Thread(target=self._write, daemon=True)
        self.writer.start()
        return True

    def _write(self) -> None:
        import cv2
        for _ in range(100):
            if self.capture.latest is not None or not self.running:
                break
            time.sleep(0.05)
        if self.capture.latest is None:
            return
        source_h, source_w = self.capture.latest.shape[:2]
        width = min(CLIP_WIDTH, source_w)
        height = int(source_h * width / source_w) // 2 * 2
        # En vivo se graba un video rápido de comprimir (así no se pierden cuadros); el definitivo se arma al final.
        self.process = subprocess.Popen(
            [self.ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgra",
             "-s", f"{width}x{height}", "-r", str(self.fps), "-i", "-",
             "-c:v", "libx264", "-preset", "ultrafast", "-crf", "14", "-pix_fmt", "yuv420p", str(self.raw)],
            stdin=subprocess.PIPE, creationflags=NO_WINDOW)
        interval = 1 / self.fps
        self.started_at = next_time = time.perf_counter()
        self.ready.set()
        while self.running:
            frame = self.capture.latest
            if frame is not None and frame.shape[:2] == (source_h, source_w):
                try:
                    small = cv2.resize(frame, (width, height), interpolation=cv2.INTER_AREA)
                    self.process.stdin.write(small.tobytes())
                except OSError:
                    break
            next_time += interval
            time.sleep(max(0.0, next_time - time.perf_counter()))

    def stop(self, on_done: Callable[[bool], None] | None = None) -> bool:
        """Corta la grabación y arma el clip en segundo plano. Devuelve si se grabó el video;
        on_done(ok) avisa cuando quedó listo."""
        self.running = False
        if self.writer:
            self.writer.join(timeout=5)
        if self.process:
            try:
                self.process.stdin.close()
                self.process.wait(timeout=60)
            except (OSError, subprocess.TimeoutExpired):
                self.process.kill()
        if not (self.raw.exists() and self.raw.stat().st_size > 10_000):
            self.raw.unlink(missing_ok=True)
            return False
        thread = threading.Thread(target=self._encode, args=(on_done,), daemon=True)
        thread.start()
        ENCODING.append(thread)
        return True

    def _encode(self, on_done) -> None:
        partial = self.out.with_suffix(".parcial.mp4")
        try:
            subprocess.run([self.ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(self.raw),
                            # Se recorta parejo: saca los datos de rendimiento de los bordes y la mira sigue en el centro.
                            "-vf", f"crop=iw*{CLIP_CROP}:ih*{CLIP_CROP},scale={CLIP_WIDTH}:-2:flags=lanczos",
                            "-c:v", "libx264", "-preset", "slow", "-crf", "26", "-pix_fmt", "yuv420p", "-an",
                            "-g", "30", "-movflags", "+faststart", str(partial)],
                           check=True, timeout=600, creationflags=NO_WINDOW)
            partial.replace(self.out)
            ok = True
        except (OSError, subprocess.SubprocessError) as error:
            log.warning("No se pudo armar el clip %s: %s", self.out.name, error)
            partial.unlink(missing_ok=True)
            ok = False
        self.raw.unlink(missing_ok=True)
        if on_done:
            on_done(ok)


ENCODING: list[threading.Thread] = []


def wait_encoding() -> None:
    """Espera a que terminen de armarse los clips que quedaron en segundo plano."""
    while ENCODING:
        ENCODING.pop().join()


def landing_view(main: dict) -> tuple[str, str]:
    """Cámara para ver dónde cae: un poco antes del punto de caída (del lado de quien tira) y más alta, mirándolo."""
    lx, ly, lz = main["land"]
    px, py, _pz = main["pos"]
    dx, dy = px - lx, py - ly
    length = math.hypot(dx, dy) or 1.0
    cx, cy, cz = lx + dx / length * 380, ly + dy / length * 380, lz + 280
    yaw = math.degrees(math.atan2(ly - cy, lx - cx))
    pitch = math.degrees(math.atan2(cz - lz, math.hypot(lx - cx, ly - cy)))  # positivo = mirar hacia abajo
    return f"setpos {cx:.1f} {cy:.1f} {cz - EYE:.1f}", f"setang {pitch:.1f} {yaw:.1f} 0"   # en noclip, pies = ojos - EYE


def _look_around(con: NetCon, lineup, window: WindowRecorder) -> list[float]:
    """Cuando no hay por dónde acercar la cámara: desde el lugar mismo, gira desde atrás hasta donde se tira,
    para que se vean las paredes y la esquina donde hay que pararse. Devuelve el tramo [desde, hasta]."""
    x, y, z = lineup.pos
    pitch, yaw = lineup.ang
    start = window.elapsed()
    steps = int(APPROACH_SECONDS * CLIP_FPS)
    for i in range(steps + 1):
        t = i / steps
        ease = t * t * (3 - 2 * t)
        look_yaw = yaw + 180 * (1 - ease)
        look_pitch = 35 + (pitch - 35) * ease
        con.push(f"setpos {x:.2f} {y:.2f} {z:.2f}; setang {look_pitch:.1f} {look_yaw:.1f} 0")
        time.sleep(max(0.0, start + APPROACH_SECONDS * t - window.elapsed()))
    con.drain()
    return [round(start, 2), round(window.elapsed(), 2)]


def _walk_to(con: NetCon, lineup, route: list[tuple[float, float, float]], window) -> tuple[list[float], tuple[float, float], float, tuple[float, float]]:
    """Camina de verdad, con la física del juego, siguiendo la ruta hasta el lugar de tiro; al final mira el piso de ese lugar.

    Devuelve el tramo [desde, hasta], hacia dónde quedó mirando (pitch, yaw), cuánto le faltó para llegar y dónde quedó."""
    tx, ty = route[-1][:2]
    x, y = route[0][:2]
    begin = window.elapsed()
    last_good, moved_from = begin, (x, y)
    yaw = math.degrees(math.atan2(route[1][1] - y, route[1][0] - x))
    pitch = 0.0
    slow = False
    buffer = ""
    frame = 0
    point = 1
    con.sock.settimeout(0.001)
    con.push("+forward")
    distance = math.dist((x, y), (tx, ty))
    while window.elapsed() - begin < WALK_TIMEOUT:
        try:
            buffer += con.sock.recv(65536).decode("utf-8", "replace")
        except OSError:
            pass
        found = POSITION.findall(buffer)
        if found:
            x, y = float(found[-1][0]), float(found[-1][1])
            buffer = ""
        distance = math.dist((x, y), (tx, ty))
        if distance <= WALK_ARRIVED:
            break
        if math.dist((x, y), moved_from) >= 8:
            last_good, moved_from = window.elapsed(), (x, y)
        elif window.elapsed() - last_good > WALK_STUCK:
            break   # chocó con algo que las demos no muestran
        while point < len(route) - 1 and math.dist((x, y), route[point][:2]) < ROUTE_AHEAD:
            point += 1
        if distance < WALK_SLOW and not slow:
            con.push("+speed")
            slow = True
        wanted = math.degrees(math.atan2(route[point][1] - y, route[point][0] - x))
        yaw += ((wanted - yaw + 180) % 360 - 180) * 0.12        # gira de a poco, como una mano en el mouse
        look = math.degrees(math.atan2(EYE, max(distance, 1.0))) if distance < WALK_LOOK else 0.0
        pitch += (min(WALK_MAX_PITCH, look) - pitch) * 0.08
        command = f"setang {pitch:.2f} {yaw:.2f} 0"
        frame += 1
        if frame % 3 == 0:
            command += "; getpos"
        con.push(command)
        time.sleep(1 / CAMERA_RATE)
    con.push("-forward; -speed")
    time.sleep(0.15)
    con.sock.settimeout(0.2)
    con.drain()
    return [round(begin, 2), round(window.elapsed(), 2)], (pitch, yaw), round(distance), (x, y)


class _Clock:
    """Reloj para ensayar la caminata sin estar grabando."""

    def __init__(self):
        self.begin = time.perf_counter()

    def elapsed(self) -> float:
        return time.perf_counter() - self.begin


def _place_at_start(con: NetCon, route: list[tuple[float, float, float]]) -> tuple[float, float]:
    sx, sy, sz = route[0]
    facing = (0.0, math.degrees(math.atan2(route[1][1] - sy, route[1][0] - sx)))
    con.send(f"setpos {sx:.1f} {sy:.1f} {sz + EYE:.1f}; setang {facing[0]:.2f} {facing[1]:.2f} 0")
    return facing


def rehearsed_route(con: NetCon, lineup, grid) -> list[tuple[float, float, float]] | None:
    """Ensaya la caminata antes de grabar. Si se traba con algo que las demos no muestran, bloquea esa zona y busca otra ruta."""
    from .parser import GRID
    blocked: set[tuple[int, int]] = set()
    best, best_short = None, math.inf
    for _ in range(REHEARSALS):
        route = walking_route(lineup, grid, blocked)
        if not route:
            break
        _place_at_start(con, route)
        time.sleep(0.7)
        _span, _facing, short, spot = _walk_to(con, lineup, route, _Clock())
        if short < best_short:
            best, best_short = route, short
        if short <= WALK_ENOUGH:
            break
        cell = (int(spot[0] // GRID), int(spot[1] // GRID))
        blocked |= {(cell[0] + i, cell[1] + j) for i in (-1, 0, 1) for j in (-1, 0, 1)}
    return best


def _turn_to(con: NetCon, source: tuple[float, float], target: tuple[float, float], seconds: float = TURN_SECONDS) -> None:
    """Gira la vista de a poco, por el lado más corto, hasta el punto de mira."""
    yaw_change = (target[1] - source[1] + 180) % 360 - 180
    begin = time.perf_counter()
    while (share := (time.perf_counter() - begin) / seconds) < 1:
        ease = share * share * (3 - 2 * share)
        con.push(f"setang {source[0] + (target[0] - source[0]) * ease:.2f} {source[1] + yaw_change * ease:.2f} 0")
        time.sleep(1 / CAMERA_RATE)
    con.push(f"setang {target[0]:.2f} {target[1]:.2f} 0")
    con.drain()


def _record_one(con: NetCon, ffmpeg: str, lineup, temp: Path, grid=None) -> bool:
    x, y, z = lineup.pos                    # altura de los ojos, como la pide setpos
    pitch, yaw = lineup.ang
    crouch = lineup.movement.startswith("crouched")
    con.send("ent_fire smokegrenade_projectile kill; ent_fire inferno kill; ent_fire molotov_projectile kill; "
             "ent_fire flashbang_projectile kill")
    con.send(f"give {WEAPONS[lineup.type]}")
    con.send("slot4; cl_drawhud 0; r_drawviewmodel 1")
    route = rehearsed_route(con, lineup, grid)
    facing = (35.0, yaw + 180)
    if route:
        facing = _place_at_start(con, route)
    else:
        con.send(f"setpos {x:.2f} {y:.2f} {z:.2f}")
        con.send(f"setang {facing[0]:.2f} {facing[1]:.2f} 0")
    time.sleep(1.0)                         # que apoye los pies antes de arrancar
    linger = {"smoke": 1.5, "molotov": 1.5, "flash": 0.4, "he": 0.6}[lineup.type]   # después de que explota
    flight = min(lineup.flight or 3.0, 9.0)
    window = WindowRecorder(ffmpeg, clips_dir() / f"{lineup.id}.mp4")   # lo grabado va siempre a tu carpeta
    if not window.start() or not window.ready.wait(5):
        window.stop()
        return False
    meta = {"fps": CLIP_FPS, "position": None, "position_mode": "walk" if route else "around"}
    if route:
        meta["position"], facing, meta["short"], _spot = _walk_to(con, lineup, route, window)
    else:
        meta["position"] = _look_around(con, lineup, window)
        facing = (pitch, yaw)
    if crouch:
        con.send("+duck")
    con.send(f"setpos {x:.2f} {y:.2f} {z:.2f}")
    aim_start = window.elapsed()
    _turn_to(con, facing, (pitch, yaw))
    time.sleep(1.0)                         # se ve la mira quieta en el punto antes de tirar
    con.send(f"setang {pitch:.2f} {yaw:.2f} 0")
    throw_start = window.elapsed()
    meta["aim"] = [round(aim_start, 2), round(throw_start, 2)]
    con.send("+attack; +attack2" if lineup.technique.startswith("both") else "+attack")
    time.sleep(0.6)                         # tirar del seguro
    for command, wait in _release_steps(lineup):
        con.send(command)
        time.sleep(wait)
    meta["throw"] = [round(throw_start, 2), round(window.elapsed() + 0.3, 2)]
    if crouch:
        con.send("-duck")
    time.sleep(min(flight, 2.0))            # se ve salir la granada desde tus ojos
    position, angle = landing_view(lineup.main)
    con.send("noclip 1; r_drawviewmodel 0")  # la cámara se pasa arriba del punto de caída, sin armas en la mano
    con.send(position)
    con.send(angle)
    time.sleep(max(0.0, flight - 2.0) + linger)
    recorded = window.stop()
    con.send(f"setpos {x:.2f} {y:.2f} {z:.2f}; noclip 0")   # volver al piso antes de sacar el noclip: sin caída
    if not recorded:
        return False
    (clips_dir() / f"{lineup.id}.json").write_text(json.dumps(meta), encoding="utf-8")
    return True    # el clip se termina de armar en segundo plano (wait_encoding)

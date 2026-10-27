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

import json
import logging
import math
import os
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
CLIP_FPS = 30
CLIP_WIDTH = 1280
APPROACH_SECONDS = 2.2   # la cámara camina hacia el lugar donde hay que pararse
APPROACH_STOP = 90       # ...y frena a esta distancia, mirando el piso de ese lugar
EYE = 64
CAMERA_UP = 100          # la cámara del acercamiento va un poco más alta que los ojos, para ver más alrededor


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
    return _clip_file(f"{lineup_id}.webp")


def clip_meta(lineup_id: str) -> dict:
    """Tramos del clip en segundos: position (dónde pararse) y aim (adónde apuntar). Los clips viejos no traen .json."""
    try:
        return json.loads(_clip_file(f"{lineup_id}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"fps": 20, "position": None, "aim": [0.0, 2.3]}


def approach_path(lineup, grid) -> tuple[tuple[float, float], float] | None:
    """Desde qué lado acercar la cámara al lugar de tiro: la dirección con más piso libre (según dónde caminaron los
    jugadores en tus demos), así no atraviesa paredes. Devuelve (dirección, distancia) o None si no hay lugar."""
    if not grid or not grid.cells:
        return None
    from .parser import GRID
    x, y, z = lineup.pos
    floor = z - EYE
    front = math.radians(lineup.ang[1])
    best = None
    for step in range(16):
        angle = front + step * math.pi / 8
        dx, dy = math.cos(angle), math.sin(angle)
        free = 0
        for d in range(24, 330, 24):
            cell = grid.cells.get((int((x + dx * d) // GRID), int((y + dy * d) // GRID)))
            if not cell or abs(cell[0] - floor) > 40:
                break
            free = d
        # Mejor desde adelante (hacia donde se tira): la cámara mira el lugar con la esquina o la pared de fondo.
        score = free - min(step, 16 - step) * 12
        if free >= 96 and (best is None or score > best[0]):
            best = (score, (dx, dy), free)
    return (best[1], min(best[2], 300)) if best else None


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
                   grid=None) -> int:
    """Graba un clip por lata. Devuelve cuántos clips quedaron guardados."""
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
    for index, lineup in enumerate(lineups, start=1):
        if should_stop():
            break
        log_cb(tr("Grabando {0} de {1}: {2}").format(index, len(lineups), lineup.title))
        if _record_one(con, ffmpeg, lineup, temp, grid):
            saved += 1
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
    y la manda a ffmpeg, que arma el WebP animado directamente."""

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
        # En vivo se graba un video rápido de comprimir (así no se pierden cuadros); el WebP se arma al final.
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
        """Corta la grabación y arma el WebP en segundo plano (tarda más que el clip). Devuelve si se grabó el video;
        on_done(ok) avisa cuando el WebP quedó listo."""
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
        partial = self.out.with_suffix(".parcial.webp")
        try:
            subprocess.run([self.ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(self.raw),
                            "-c:v", "libwebp_anim", "-loop", "0", "-quality", "70", "-f", "webp", str(partial)],
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
    """Espera a que terminen de armarse los WebP que quedaron en segundo plano."""
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


def _approach(con: NetCon, lineup, path, window: WindowRecorder) -> list[float]:
    """La cámara camina hacia el lugar de tiro mirando el piso donde hay que pararse. Devuelve el tramo [desde, hasta]."""
    (dx, dy), distance = path
    x, y, z = lineup.pos
    floor = z - EYE
    start = window.elapsed()
    stop = min(APPROACH_STOP, distance * 0.45)
    steps = int(APPROACH_SECONDS * CLIP_FPS)
    for i in range(steps + 1):
        t = i / steps
        ease = t * t * (3 - 2 * t)
        d = distance + (stop - distance) * ease
        cx, cy = x + dx * d, y + dy * d
        yaw = math.degrees(math.atan2(y - cy, x - cx))
        pitch = math.degrees(math.atan2(CAMERA_UP - 2, d))     # positivo = mirar hacia abajo, al piso del lugar
        # En noclip setpos ubica los pies: los ojos (la cámara) quedan EYE unidades más arriba.
        con.push(f"setpos {cx:.1f} {cy:.1f} {floor + CAMERA_UP - EYE:.1f}; setang {pitch:.1f} {yaw:.1f} 0")
        time.sleep(max(0.0, start + APPROACH_SECONDS * t - window.elapsed()))
    con.drain()
    return [round(start, 2), round(window.elapsed(), 2)]


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


def _record_one(con: NetCon, ffmpeg: str, lineup, temp: Path, grid=None) -> bool:
    x, y, z = lineup.pos                    # altura de los ojos, como la pide setpos
    pitch, yaw = lineup.ang
    crouch = lineup.movement.startswith("crouched")
    path = approach_path(lineup, grid)
    con.send("ent_fire smokegrenade_projectile kill; ent_fire inferno kill; ent_fire molotov_projectile kill; "
             "ent_fire flashbang_projectile kill")
    con.send(f"give {WEAPONS[lineup.type]}")
    con.send("slot4; cl_drawhud 0")
    if path:
        (dx, dy), distance = path
        con.send("noclip 1; r_drawviewmodel 0")   # sin las manos, para que se vea el piso donde pararse
        con.send(f"setpos {x + dx * distance:.1f} {y + dy * distance:.1f} {z - 2 * EYE + CAMERA_UP:.1f}")
    else:
        con.send("r_drawviewmodel 0")
        con.send(f"setpos {x:.2f} {y:.2f} {z:.2f}")
        con.send(f"setang 35 {yaw + 180:.2f} 0")
    time.sleep(0.8)
    linger = {"smoke": 1.5, "molotov": 1.5, "flash": 0.4, "he": 0.6}[lineup.type]   # después de que explota
    flight = min(lineup.flight or 3.0, 9.0)
    window = WindowRecorder(ffmpeg, clips_dir() / f"{lineup.id}.webp")   # lo grabado va siempre a tu carpeta
    if not window.start() or not window.ready.wait(5):
        window.stop()
        return False
    meta = {"fps": CLIP_FPS, "position": None, "position_mode": "approach" if path else "around"}
    if path:
        meta["position"] = _approach(con, lineup, path, window)
        con.send("noclip 0; r_drawviewmodel 1")
    else:
        meta["position"] = _look_around(con, lineup, window)
        con.send("r_drawviewmodel 1")
    if crouch:
        con.send("+duck")
    con.send(f"setpos {x:.2f} {y:.2f} {z:.2f}; setang {pitch:.2f} {yaw:.2f} 0")
    aim_start = window.elapsed()
    time.sleep(1.2)                         # se ve la mira quieta en el punto antes de tirar
    con.send(f"setang {pitch:.2f} {yaw:.2f} 0")
    con.send("+attack; +attack2" if lineup.technique.startswith("both") else "+attack")
    time.sleep(1.0)                         # tirar del seguro
    meta["aim"] = [round(aim_start, 2), round(window.elapsed(), 2)]
    for command, wait in _release_steps(lineup):
        con.send(command)
        time.sleep(wait)
    if crouch:
        con.send("-duck")
    time.sleep(min(flight, 2.0))            # se ve salir la granada desde tus ojos
    position, angle = landing_view(lineup.main)
    con.send("noclip 1")                    # la cámara flota sobre el punto de caída
    con.send(position)
    con.send(angle)
    time.sleep(max(0.0, flight - 2.0) + linger)
    recorded = window.stop()
    con.send(f"setpos {x:.2f} {y:.2f} {z:.2f}; noclip 0")   # volver al piso antes de sacar el noclip: sin caída
    if not recorded:
        return False
    (clips_dir() / f"{lineup.id}.json").write_text(json.dumps(meta), encoding="utf-8")
    return True    # el WebP se termina de armar en segundo plano (wait_encoding)

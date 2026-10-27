"""Game State Integration oficial de Valve.

CS2 lee un archivo de texto de su carpeta cfg y le manda a esta app, por la red local de la PC
(127.0.0.1), el estado de la partida. Es lo mismo que usan los overlays de torneos: no toca el
proceso del juego ni su memoria.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable

CFG_NAME = "gamestate_integration_cs2stats.cfg"


def cfg_path(game_dir: Path) -> Path:
    return game_dir / "cfg" / CFG_NAME


def cfg_text(port: int, token: str) -> str:
    return f'''"CS2 Stats"
{{
    "uri"       "http://127.0.0.1:{port}/"
    "timeout"   "5.0"
    "buffer"    "0.5"
    "throttle"  "1.0"
    "heartbeat" "30.0"
    "auth"
    {{
        "token" "{token}"
    }}
    "data"
    {{
        "provider"           "1"
        "map"                "1"
        "round"              "1"
        "player_id"          "1"
        "player_state"       "1"
        "player_match_stats" "1"
    }}
}}
'''


def install(game_dir: Path, port: int, token: str) -> Path:
    path = cfg_path(game_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(cfg_text(port, token), encoding="utf-8")
    return path


def is_installed(game_dir: Path | None, port: int, token: str) -> bool:
    if not game_dir:
        return False
    try:
        return cfg_path(game_dir).read_text(encoding="utf-8") == cfg_text(port, token)
    except OSError:
        return False


def uninstall(game_dir: Path) -> None:
    try:
        cfg_path(game_dir).unlink()
    except OSError:
        pass


class MatchTracker:
    """Sigue el estado que manda CS2 y avisa una sola vez cuando termina cada partida tuya."""

    def __init__(self, steamid: int, on_match_end: Callable[[dict], None], on_activity: Callable[[str], None] | None = None):
        self.steamid = str(steamid)
        self.on_match_end = on_match_end
        self.on_activity = on_activity
        self.last_me: dict = {}
        self.reported = False
        self.last_phase = ""

    def feed(self, payload: dict) -> None:
        game_map = payload.get("map") or {}
        player = payload.get("player") or {}
        provider = payload.get("provider") or {}
        if str(provider.get("steamid")) != self.steamid:
            return  # CS2 abierto con otra cuenta
        phase = str(game_map.get("phase") or "")
        if self.on_activity and phase != self.last_phase:
            self.on_activity(phase)
        if phase in ("warmup", "live") and self.last_phase == "gameover":
            self.reported = False
        if phase == "warmup":
            self.reported = False
        self.last_phase = phase
        if str(player.get("steamid")) == self.steamid and player.get("match_stats"):
            self.last_me = {"team": player.get("team"), "stats": player.get("match_stats") or {}}
        if phase != "gameover" or self.reported or not self.last_me:
            return
        self.reported = True
        side = str(self.last_me.get("team") or "")
        ct = int((game_map.get("team_ct") or {}).get("score") or 0)
        t = int((game_map.get("team_t") or {}).get("score") or 0)
        stats = self.last_me["stats"]
        self.on_match_end({
            "ended_at": datetime.now().isoformat(timespec="seconds"),
            "map": str(game_map.get("name") or ""), "mode": str(game_map.get("mode") or ""), "side": side,
            "score_us": ct if side == "CT" else t, "score_them": t if side == "CT" else ct,
            "kills": int(stats.get("kills") or 0), "assists": int(stats.get("assists") or 0),
            "deaths": int(stats.get("deaths") or 0), "mvps": int(stats.get("mvps") or 0),
            "score": int(stats.get("score") or 0),
        })


class GsiServer:
    def __init__(self, port: int, token: str, tracker: MatchTracker):
        self.port, self.token, self.tracker = port, token, tracker
        self.httpd: ThreadingHTTPServer | None = None

    def start(self) -> bool:
        server = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                length = min(int(self.headers.get("Content-Length") or 0), 1_000_000)
                try:
                    payload = json.loads(self.rfile.read(length) or b"{}")
                except ValueError:
                    payload = {}
                self.send_response(200)
                self.end_headers()
                if (payload.get("auth") or {}).get("token") == server.token:
                    try:
                        server.tracker.feed(payload)
                    except Exception:  # un dato raro de CS2 no debe tirar el servidor
                        pass

            def log_message(self, *_args):
                pass

        try:
            self.httpd = ThreadingHTTPServer(("127.0.0.1", self.port), Handler)
        except OSError:
            return False
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        return True

    def stop(self) -> None:
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()
            self.httpd = None

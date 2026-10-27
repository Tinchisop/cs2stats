"""Historial local en SQLite y ajustes en JSON, dentro de %LOCALAPPDATA%\\CS2Stats."""

from __future__ import annotations

import json
import os
import secrets
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from .secure import protect, unprotect


def data_dir() -> Path:
    base = Path(os.environ.get("CS2STATS_HOME") or Path(os.environ.get("LOCALAPPDATA", Path.home())) / "CS2Stats")
    base.mkdir(parents=True, exist_ok=True)
    return base


PARSER_VERSION = 3  # si cambia, las demos se vuelven a leer (las de Valve se vuelven a bajar mientras existan)


class Settings:
    DEFAULTS = {"steamid": 0, "language": "", "extra_folders": [], "recent_n": 10, "gsi_enabled": True,
                "gsi_port": 47321, "gsi_token": "", "auto_import": False, "parser_version": 1,
                # Conexión con Steam (los secretos se guardan cifrados con DPAPI)
                "api_key": "", "auth_code": "", "last_sharecode": "", "gc_token": "", "gc_account": "",
                "history_synced_at": "", "steam_synced_at": "", "steam_error": "",
                # Mensaje de Steam al terminar cada partida (lo manda la cuenta secundaria a tu cuenta)
                "steam_message": True, "message_pending": {}, "message_status": ""}
    SECRETS = {"api_key", "auth_code", "gc_token"}

    def __init__(self, path: Path | None = None):
        self.path = path or data_dir() / "ajustes.json"
        self.values = dict(self.DEFAULTS)
        try:
            self.values.update(json.loads(self.path.read_text(encoding="utf-8-sig")))
        except (OSError, ValueError):
            pass
        if not self.values["gsi_token"]:
            self.values["gsi_token"] = secrets.token_hex(16)
            self.save()
        if not self.values["steamid"]:
            # La primera vez se mide la última cuenta que inició sesión en Steam en esta PC (se cambia en Demos y aviso).
            from .finder import steam_accounts
            accounts = steam_accounts()
            if accounts:
                self.values["steamid"] = accounts[0][0]
                self.save()

    def __getitem__(self, key: str) -> Any:
        return self.values[key]

    def set(self, key: str, value: Any) -> None:
        if key in self.SECRETS:
            value = protect(str(value or ""))
        self.values[key] = value
        self.save()

    def secret(self, key: str) -> str:
        return unprotect(self.values.get(key) or "")

    _lock = threading.Lock()  # la búsqueda de partidas y la lectura del historial pueden guardar a la vez

    def save(self) -> None:
        with self._lock:
            self.path.write_text(json.dumps(self.values, indent=2, ensure_ascii=False), encoding="utf-8")


SCHEMA = """
CREATE TABLE IF NOT EXISTS matches (
    id INTEGER PRIMARY KEY,
    match_key TEXT UNIQUE NOT NULL,
    steamid INTEGER NOT NULL,
    source TEXT, map TEXT, played_at TEXT, file_name TEXT,
    rounds_n INTEGER, score_us INTEGER, score_them INTEGER, result TEXT, my_name TEXT,
    rank_type INTEGER, rank_old INTEGER, rank_new INTEGER, rank_change REAL,
    rounds_json TEXT, weapons_json TEXT, scoreboard_json TEXT, imported_at TEXT
);
CREATE TABLE IF NOT EXISTS files (
    path TEXT PRIMARY KEY, size INTEGER, mtime REAL, status TEXT, match_key TEXT, message TEXT, seen_at TEXT
);
CREATE TABLE IF NOT EXISTS gsi_matches (
    id INTEGER PRIMARY KEY, ended_at TEXT, map TEXT, mode TEXT, side TEXT,
    score_us INTEGER, score_them INTEGER, kills INTEGER, assists INTEGER, deaths INTEGER, mvps INTEGER, score INTEGER,
    match_id INTEGER
);
CREATE TABLE IF NOT EXISTS sharecodes (
    code TEXT PRIMARY KEY, status TEXT, demo_url TEXT, match_time INTEGER, message TEXT, match_key TEXT,
    added_at TEXT, tries INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS history (
    key TEXT PRIMARY KEY, steamid INTEGER, mode TEXT, map TEXT, played_at TEXT, duration TEXT,
    score_us INTEGER, score_them INTEGER, result TEXT, kills INTEGER, assists INTEGER, deaths INTEGER,
    mvps INTEGER, hsp INTEGER, score INTEGER, demo_url TEXT, players_json TEXT
);
"""


class Store:
    def __init__(self, path: Path | None = None):
        self.path = path or data_dir() / "historial.db"
        self.lock = threading.Lock()
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        columns = {row[1] for row in self.db.execute("PRAGMA table_info(matches)")}
        for column in ("grenades_json", "grid_json", "aim_json", "detail_json"):
            if column not in columns:
                self.db.execute(f"ALTER TABLE matches ADD COLUMN {column} TEXT")
        self.db.commit()

    # Partidas
    def has_match(self, match_key: str) -> bool:
        with self.lock:
            return self.db.execute("SELECT 1 FROM matches WHERE match_key=?", (match_key,)).fetchone() is not None

    def add_match(self, match: dict, file_name: str, played_at: str) -> int:
        rank = match["rank"]
        with self.lock:
            cursor = self.db.execute(
                """INSERT INTO matches (match_key, steamid, source, map, played_at, file_name, rounds_n, score_us,
                   score_them, result, my_name, rank_type, rank_old, rank_new, rank_change, rounds_json, weapons_json,
                   scoreboard_json, imported_at, grenades_json, grid_json, aim_json, detail_json)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (match["match_key"], match["steamid"], match["source"], match["map"], played_at, file_name,
                 len(match["rounds"]), match["score_us"], match["score_them"], match["result"], match["my_name"],
                 rank["type"], rank["old"], rank["new"], rank["change"], json.dumps(match["rounds"]),
                 json.dumps(match["weapons"]), json.dumps(match["scoreboard"]), datetime.now().isoformat(timespec="seconds"),
                 json.dumps(match.get("grenades") or []), json.dumps(match.get("grid") or []),
                 json.dumps(match["aim"]) if "aim" in match else None,
                 json.dumps(match["detail"]) if "detail" in match else None))
            self.db.commit()
            match_id = int(cursor.lastrowid)
        self.link_gsi(match_id, match["map"], played_at)
        return match_id

    def matches(self, steamid: int) -> list[dict]:
        """Todas las partidas del jugador, de la más vieja a la más nueva, con sus rondas."""
        with self.lock:
            rows = self.db.execute("SELECT * FROM matches WHERE steamid=? ORDER BY played_at, id", (steamid,)).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item.pop("grenades_json", None)  # las latas se leen aparte (son pesadas y solo las usa su pantalla)
            item.pop("grid_json", None)
            item["rounds"] = json.loads(item.pop("rounds_json") or "[]")
            item["weapons"] = json.loads(item.pop("weapons_json") or "{}")
            item["scoreboard"] = json.loads(item.pop("scoreboard_json") or "[]")
            aim = item.pop("aim_json")
            item["aim"] = json.loads(aim) if aim is not None else None  # None: se importó antes de medir la puntería
            detail = item.pop("detail_json")
            item["detail"] = json.loads(detail) if detail is not None else None  # impacto, duelos y utilidad
            for r in item["rounds"]:
                r["match_id"] = item["id"]
                r["map"] = item["map"]
            result.append(item)
        return result

    def nade_data(self) -> list[dict]:
        """Granadas y posiciones de todas las partidas analizadas (de todos los jugadores), por mapa."""
        with self.lock:
            rows = self.db.execute("SELECT map, played_at, grenades_json, grid_json FROM matches").fetchall()
        return [{"map": r[0], "played_at": r[1], "grenades": json.loads(r[2] or "[]"), "grid": json.loads(r[3] or "[]")}
                for r in rows]

    def refresh_match(self, match_id: int, match: dict | None) -> None:
        """Guarda lo que sale de volver a leer la demo con el lector nuevo. Sin demo, queda marcada como no disponible."""
        with self.lock:
            if match is None:
                self.db.execute("UPDATE matches SET aim_json=COALESCE(aim_json, '{}'), detail_json='{}' WHERE id=?", (match_id,))
            else:
                self.db.execute("UPDATE matches SET rounds_json=?, weapons_json=?, scoreboard_json=?, aim_json=?, detail_json=? "
                                "WHERE id=?", (json.dumps(match["rounds"]), json.dumps(match["weapons"]),
                                              json.dumps(match["scoreboard"]), json.dumps(match["aim"]),
                                              json.dumps(match["detail"]), match_id))
            self.db.commit()

    def demo_sources(self, match_key: str) -> tuple[str, str]:
        """Dónde volver a buscar la demo de una partida: el archivo en la PC y la URL de Valve."""
        with self.lock:
            path = self.db.execute("SELECT path FROM files WHERE match_key=? AND status='importada'", (match_key,)).fetchone()
            url = self.db.execute("SELECT demo_url FROM sharecodes WHERE match_key=? AND demo_url IS NOT NULL", (match_key,)).fetchone()
        return (path[0] if path else ""), (url[0] if url else "")

    def delete_match(self, match_id: int) -> None:
        with self.lock:
            key = self.db.execute("SELECT match_key FROM matches WHERE id=?", (match_id,)).fetchone()
            self.db.execute("DELETE FROM matches WHERE id=?", (match_id,))
            if key:
                # Si se borra a mano, que no vuelva a importarse sola.
                self.db.execute("UPDATE files SET status='borrada' WHERE match_key=?", (key[0],))
            self.db.commit()

    # Archivos ya vistos
    def file_status(self, path: str) -> dict | None:
        with self.lock:
            row = self.db.execute("SELECT * FROM files WHERE path=?", (path,)).fetchone()
        return dict(row) if row else None

    def remember_file(self, path: str, size: int, mtime: float, status: str, match_key: str = "", message: str = "") -> None:
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO files VALUES (?,?,?,?,?,?,?)",
                            (path, size, mtime, status, match_key, message, datetime.now().isoformat(timespec="seconds")))
            self.db.commit()

    def forget_demo_matches(self) -> None:
        """Para volver a leer las demos con una versión nueva del lector."""
        with self.lock:
            self.db.execute("DELETE FROM matches")
            self.db.execute("DELETE FROM files")
            # Las que ya tienen URL se vuelven a bajar directo; las demás vuelven a pasar por el Game Coordinator.
            self.db.execute("UPDATE sharecodes SET status = CASE WHEN demo_url IS NOT NULL AND demo_url != '' "
                            "THEN 'con_url' ELSE 'nueva' END, tries=0 WHERE status IN ('importada', 'vencida')")
            self.db.commit()

    def set_played_at(self, match_key: str, played_at: str) -> None:
        with self.lock:
            self.db.execute("UPDATE matches SET played_at=? WHERE match_key=?", (played_at, match_key))
            self.db.commit()

    # Códigos de partida (Match History API)
    def add_sharecodes(self, codes: list[str]) -> int:
        added = 0
        with self.lock:
            for code in codes:
                cursor = self.db.execute(
                    "INSERT OR IGNORE INTO sharecodes (code, status, added_at, tries) VALUES (?, 'nueva', ?, 0)",
                    (code, datetime.now().isoformat(timespec="seconds")))
                added += cursor.rowcount
            self.db.commit()
        return added

    def sharecodes(self, statuses: tuple[str, ...] | None = None) -> list[dict]:
        with self.lock:
            rows = self.db.execute("SELECT * FROM sharecodes ORDER BY added_at, code").fetchall()
        items = [dict(row) for row in rows]
        return [i for i in items if not statuses or i["status"] in statuses]

    def update_sharecode(self, code: str, **fields) -> None:
        if not fields:
            return
        names = ", ".join(f"{k}=?" for k in fields)
        with self.lock:
            self.db.execute(f"UPDATE sharecodes SET {names} WHERE code=?", (*fields.values(), code))
            self.db.commit()

    # Historial completo (Datos personales del juego)
    def save_history(self, steamid: int, rows: list[dict]) -> int:
        added = 0
        with self.lock:
            for row in rows:
                if not row["played_at"] or row["played_at"] < "2023-09-27":
                    continue  # partidas de CS:GO, antes de que saliera CS2
                key = f"{row['played_at']}|{row['map']}"
                cursor = self.db.execute(
                    """INSERT OR REPLACE INTO history VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (key, steamid, row["mode"], row["map"], row["played_at"], row["duration"], row["score_us"],
                     row["score_them"], row["result"], row["kills"], row["assists"], row["deaths"], row["mvps"],
                     row["hsp"], row["score"], row["demo_url"],
                     json.dumps({"team": row["team"], "rivals": row["rivals"]}, ensure_ascii=False)))
                added += cursor.rowcount
            self.db.commit()
        return added

    def history(self, steamid: int) -> list[dict]:
        with self.lock:
            rows = self.db.execute("SELECT * FROM history WHERE steamid=? ORDER BY played_at", (steamid,)).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            players = json.loads(item.pop("players_json") or "{}")
            item["team"], item["rivals"] = players.get("team", []), players.get("rivals", [])
            items.append(item)
        return items

    # Avisos de fin de partida (GSI)
    def add_gsi_match(self, data: dict) -> int:
        with self.lock:
            cursor = self.db.execute(
                """INSERT INTO gsi_matches (ended_at, map, mode, side, score_us, score_them, kills, assists, deaths, mvps,
                   score, match_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,NULL)""",
                (data["ended_at"], data["map"], data["mode"], data["side"], data["score_us"], data["score_them"],
                 data["kills"], data["assists"], data["deaths"], data["mvps"], data["score"]))
            self.db.commit()
            return int(cursor.lastrowid)

    def pending_gsi(self) -> list[dict]:
        with self.lock:
            rows = self.db.execute("SELECT * FROM gsi_matches WHERE match_id IS NULL ORDER BY ended_at DESC").fetchall()
        return [dict(row) for row in rows]

    def dismiss_gsi(self, gsi_id: int) -> None:
        with self.lock:
            self.db.execute("UPDATE gsi_matches SET match_id=0 WHERE id=?", (gsi_id,))
            self.db.commit()

    def link_gsi(self, match_id: int, map_name: str, played_at: str) -> None:
        """Marca como resuelto el aviso de la misma partida (mismo mapa, hasta 2 días antes de la demo)."""
        try:
            when = datetime.fromisoformat(played_at)
        except ValueError:
            return
        for item in self.pending_gsi():
            try:
                ended = datetime.fromisoformat(item["ended_at"])
            except ValueError:
                continue
            if item["map"] == map_name and -6 * 3600 <= (when - ended).total_seconds() <= 2 * 86400:
                with self.lock:
                    self.db.execute("UPDATE gsi_matches SET match_id=? WHERE id=?", (match_id, item["id"]))
                    self.db.commit()
                return

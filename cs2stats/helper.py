"""Maneja el ayudante de Node (helper/helper.js) que habla con Steam: login con QR y Game Coordinator."""

from __future__ import annotations

from .i18n import t

import json
import queue
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from typing import Callable


def helper_paths() -> tuple[str, Path] | None:
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "helper"
        node = base / "node.exe"
        return (str(node), base) if node.exists() else None
    base = Path(__file__).resolve().parent.parent / "helper"
    node = shutil.which("node")
    return (node, base) if node and (base / "helper.js").exists() else None


class HelperError(Exception):
    pass


class Helper:
    """Proceso del ayudante. Los mensajes llegan por on_event (desde otro hilo) y también a una cola."""

    def __init__(self, on_event: Callable[[dict], None] | None = None):
        paths = helper_paths()
        if not paths:
            raise HelperError(t("Falta el ayudante de Steam junto a la app."))
        node, base = paths
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        self.proc = subprocess.Popen([node, "helper.js"], cwd=base, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL, text=True, encoding="utf-8", creationflags=flags)
        self.events: queue.Queue = queue.Queue()
        self.on_event = on_event
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self) -> None:
        for line in self.proc.stdout:
            try:
                message = json.loads(line)
            except ValueError:
                continue
            self.events.put(message)
            if self.on_event:
                self.on_event(message)
        self.events.put({"event": "closed"})
        if self.on_event:
            self.on_event({"event": "closed"})

    def send(self, cmd: str, **data) -> None:
        try:
            self.proc.stdin.write(json.dumps({"cmd": cmd, **data}) + "\n")
            self.proc.stdin.flush()
        except OSError as error:
            raise HelperError(t("El ayudante de Steam se cerró.")) from error

    def next_event(self, timeout: float) -> dict:
        try:
            return self.events.get(timeout=timeout)
        except queue.Empty as error:
            raise HelperError(t("Steam tardó demasiado en responder.")) from error

    def close(self) -> None:
        try:
            self.send("quit")
        except HelperError:
            pass
        try:
            self.proc.wait(3)
        except subprocess.TimeoutExpired:
            self.proc.kill()


def _raise_for(message: dict) -> None:
    text = message.get("message") or t("El ayudante de Steam se cerró.")
    if t("AccessDenied") in text or t("InvalidPassword") in text or t("Expired") in text or message.get("eresult") in (5, 15, 27):
        raise HelperError(t("La sesión de la cuenta secundaria venció. Volvé a conectarla en Conectar Steam."))
    if t("LoggedInElsewhere") in text:
        raise HelperError(t("La cuenta secundaria está abierta en otro lado. Cerrala ahí y probá de nuevo."))
    raise HelperError(text)


def send_steam_message(refresh_token: str, to: int, text: str) -> tuple[str, str]:
    """La cuenta secundaria le escribe a `to` por el chat de Steam. Devuelve (resultado, token renovado o '').
    resultado: 'sent', 'request_sent' (le mandó solicitud de amistad), 'not_friends' o 'limited'."""
    helper = Helper()
    new_token = ""
    try:
        if helper.next_event(20).get("event") != "ready":
            raise HelperError(t("El ayudante de Steam no arrancó."))
        helper.send("send_message", refreshToken=refresh_token, to=str(to), text=text)
        while True:
            message = helper.next_event(90)
            kind = message.get("event")
            if kind == "refreshToken":
                new_token = message.get("refreshToken", "")
            elif kind == "done":
                return ("sent" if message.get("sent") else message.get("reason") or "not_friends"), new_token
            elif kind in ("error", "closed"):
                _raise_for(message)
    finally:
        helper.close()


def fetch_games(refresh_token: str, sharecodes: list[str], status: Callable[[str], None]) -> tuple[list[dict], str]:
    """Pide al Game Coordinator la URL de la demo de cada código. Devuelve (resultados, token renovado o '')."""
    helper = Helper()
    results, new_token = [], ""
    try:
        if helper.next_event(20).get("event") != "ready":
            raise HelperError(t("El ayudante de Steam no arrancó."))
        helper.send("fetch_games", refreshToken=refresh_token, sharecodes=sharecodes)
        while True:
            message = helper.next_event(120)
            kind = message.get("event")
            if kind == "status":
                status(message.get("message", ""))
            elif kind == "refreshToken":
                new_token = message.get("refreshToken", "")
            elif kind == "game":
                results.append(message)
                status(t('Partida {0} de {1} encontrada en Steam').format(len(results), len(sharecodes)))
            elif kind == "done":
                break
            elif kind in ("error", "closed"):
                _raise_for(message)
    finally:
        helper.close()
    return results, new_token

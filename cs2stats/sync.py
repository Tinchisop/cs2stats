"""Sincronización con Steam: códigos nuevos, URL de cada demo, descarga e importación."""

from __future__ import annotations

import shutil
from datetime import datetime
from typing import Callable

from . import steamapi
from .finder import remove_quietly
from .helper import fetch_games, send_steam_message
from .i18n import t
from .metrics import map_label
from .parser import DemoError, NotInDemo, parse_demo
from .resumen import gsi_message, match_message
from .store import Settings, Store, data_dir

MAX_TRIES = 4


def steam_ready(settings: Settings) -> dict:
    """Qué partes de la conexión están listas."""
    return {
        "codes": bool(settings.secret("api_key") and settings.secret("auth_code") and settings["last_sharecode"]),
        "gc": bool(settings.secret("gc_token")),
        "history": bool(settings["history_synced_at"]),
    }


def sync_steam(store: Store, settings: Settings, log: Callable[[str], None]) -> int:
    """Hace todo lo posible y devuelve cuántas partidas nuevas se importaron. Lanza SteamError/HelperError."""
    steamid = settings["steamid"]
    imported = 0
    ready = steam_ready(settings)

    # 1. Códigos nuevos con la Match History API.
    if ready["codes"]:
        last = settings["last_sharecode"]
        store.add_sharecodes([last])
        log(t("Preguntando a Steam si hay partidas nuevas"))
        codes = steamapi.next_sharecodes(settings.secret("api_key"), steamid, settings.secret("auth_code"), last)
        if codes:
            store.add_sharecodes(codes)
            settings.set("last_sharecode", codes[-1])
            log(t('Steam encontró {0} {1}').format(len(codes), t('partida nueva') if len(codes) == 1 else t('partidas nuevas')))

    # 2. URL de la demo de cada código, con la cuenta secundaria en el Game Coordinator.
    waiting = [c for c in store.sharecodes(("nueva", "reintentar")) if (c["tries"] or 0) < MAX_TRIES]
    if waiting and ready["gc"]:
        log(t("Conectando la cuenta secundaria al Game Coordinator de CS2"))
        results, renewed = fetch_games(settings.secret("gc_token"), [c["code"] for c in waiting], log)
        if renewed:
            settings.set("gc_token", renewed)
        tries = {c["code"]: (c["tries"] or 0) + 1 for c in waiting}
        for item in results:
            code = item["sharecode"]
            if item.get("ok") and item.get("demoUrl"):
                store.update_sharecode(code, status="con_url", demo_url=item["demoUrl"],
                                       match_time=int(item.get("matchTime") or 0), message="", tries=tries[code])
            else:
                final = tries[code] >= MAX_TRIES
                store.update_sharecode(code, status="sin_datos" if final else "reintentar",
                                       message=item.get("message", ""), tries=tries[code])

    # 3. Descarga e importación.
    for item in store.sharecodes(("con_url",)):
        imported += _download_and_import(store, settings, item["code"], item["demo_url"], item.get("match_time") or 0, log)

    # 4. Demos que el historial de Steam todavía ofrece para bajar (sin pasar por el Game Coordinator).
    known_urls = {c["demo_url"] for c in store.sharecodes() if c["demo_url"]}
    analyzed = [(map_label(m["map"]).lower(), m["played_at"], m["score_us"], m["score_them"]) for m in store.matches(steamid)]

    def already_analyzed(row: dict) -> bool:
        for name, played, us, them in analyzed:
            try:
                gap = abs((datetime.fromisoformat(played) - datetime.fromisoformat(row["played_at"])).total_seconds())
            except ValueError:
                continue
            if name == row["map"].lower() and (us, them) == (row["score_us"], row["score_them"]) and gap <= 3 * 3600:
                return True
        return False

    for row in reversed(store.history(steamid)):  # primero las más nuevas
        url = row.get("demo_url") or ""
        if url and url not in known_urls and not already_analyzed(row):
            code = "historial:" + url.rsplit("/", 1)[-1]
            store.add_sharecodes([code])
            store.update_sharecode(code, status="con_url", demo_url=url)
            imported += _download_and_import(store, settings, code, url, 0, log, played_at=row["played_at"])
    settings.set("steam_synced_at", datetime.now().isoformat(timespec="seconds"))
    settings.set("steam_error", "")
    if ready["gc"]:
        deliver_pending_message(store, settings, log)
    return imported


MESSAGE_WAIT = 30 * 60    # si en 30 minutos no llegó la demo, el mensaje sale con lo que mandó CS2


def deliver_pending_message(store: Store, settings: Settings, log: Callable[[str], None]) -> None:
    """Si terminó una partida y ya se analizó su demo (o pasó demasiado tiempo), te manda el resumen por Steam."""
    pending = settings["message_pending"]
    if not pending or not settings["steam_message"]:
        return
    ended = datetime.fromisoformat(pending["ended_at"])
    matches = store.matches(settings["steamid"])
    match = next((m for m in reversed(matches) if m["map"] == pending["map"]
                  and (m["score_us"], m["score_them"]) == (pending["score_us"], pending["score_them"])
                  and abs((datetime.fromisoformat(m["played_at"]) - ended).total_seconds()) <= 3 * 3600), None)
    if match:
        text = match_message(match, [m for m in matches if m["played_at"] < match["played_at"]])
    elif (datetime.now() - ended).total_seconds() >= MESSAGE_WAIT:
        text = gsi_message(pending)
    else:
        return
    send_summary(settings, text, log)
    settings.set("message_pending", {})


def send_summary(settings: Settings, text: str, log: Callable[[str], None]) -> str:
    """Manda el texto a tu cuenta desde la cuenta secundaria y guarda cómo salió."""
    result, renewed = send_steam_message(settings.secret("gc_token"), settings["steamid"], text)
    if renewed:
        settings.set("gc_token", renewed)
    notes = {"sent": t("Mensaje enviado por Steam."),
             "request_sent": t("La cuenta secundaria te mandó una solicitud de amistad en Steam: aceptala y los "
                               "próximos resúmenes te llegan por chat."),
             "not_friends": t("Falta que aceptes la solicitud de amistad de la cuenta secundaria en Steam."),
             "limited": t("La cuenta secundaria no puede mandar solicitudes de amistad (es una cuenta limitada). "
                          "Agregala vos desde tu cuenta principal y la app la acepta sola.")}
    settings.set("message_status", result)
    log(notes.get(result, result))
    return result


def _download_and_import(store: Store, settings: Settings, code: str, url: str, match_time: int,
                         log: Callable[[str], None], played_at: str = "") -> int:
    log(t("Bajando la demo de los servidores de Valve"))
    shown = {"step": -1}

    def progress(done: int, total: int) -> None:
        step = done * 4 // total if total else -1
        if step != shown["step"] and step >= 0:
            shown["step"] = step
            log(t('Bajando la demo: {0} %').format(done * 100 // total))
    try:
        demo = steamapi.download_demo(url, data_dir() / "descargas", progress)
    except steamapi.SteamError as error:
        vencida = t("borró") in str(error)
        store.update_sharecode(code, status="vencida" if vencida else "con_url", message=str(error))
        log(str(error))
        return 0
    try:
        log(t("Leyendo la demo"))
        match = parse_demo(str(demo), settings["steamid"])
    except NotInDemo as error:
        store.update_sharecode(code, status="no_es_tuya", message=str(error))
        return 0
    except DemoError as error:
        store.update_sharecode(code, status="error", message=str(error))
        return 0
    finally:
        remove_quietly(demo)
    if match_time:
        played_at = datetime.fromtimestamp(match_time).isoformat(timespec="seconds")
    played_at = played_at or datetime.now().isoformat(timespec="seconds")
    if store.has_match(match["match_key"]):
        store.update_sharecode(code, status="importada", match_key=match["match_key"], message="Ya estaba")
        if match_time:
            store.set_played_at(match["match_key"], played_at)
        return 0
    store.add_match(match, url.rsplit("/", 1)[-1], played_at)
    store.update_sharecode(code, status="importada", match_key=match["match_key"], message="")
    log(f"Importada: {map_label(match['map'])} {match['score_us']} a {match['score_them']}")
    return 1


def sync_history(store: Store, settings: Settings, cookies: list[str], log: Callable[[str], None]) -> int:
    folder, fresh = data_dir() / "historial_steam", data_dir() / "historial_steam_nuevo"
    shutil.rmtree(fresh, ignore_errors=True)
    rows = steamapi.fetch_history(cookies, settings["steamid"], log, save_raw=fresh)
    if rows:  # la lectura nueva reemplaza a la guardada solo si salió bien
        shutil.rmtree(folder, ignore_errors=True)
        fresh.rename(folder)
    added = store.save_history(settings["steamid"], rows)
    settings.set("history_synced_at", datetime.now().isoformat(timespec="seconds"))
    log(t('Historial de Steam: {0} partidas leídas').format(len(rows)))
    return added


def reload_saved_history(store: Store, settings: Settings) -> int:
    """Rearma el historial desde las páginas guardadas (por ejemplo, después de mejorar el lector)."""
    rows = steamapi.parse_saved_history(data_dir() / "historial_steam", settings["steamid"])
    if not rows:
        return 0
    store.save_history(settings["steamid"], rows)
    if not settings["history_synced_at"]:
        settings.set("history_synced_at", datetime.now().isoformat(timespec="seconds"))
    return len(rows)

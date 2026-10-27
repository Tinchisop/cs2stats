"""Fuentes oficiales de Steam:

* Match History API de Valve (ICSGOPlayers_730/GetNextMatchSharingCode): con tu código de autenticación y un
  código de partida, devuelve los códigos de tus partidas siguientes.
* Servidores de repeticiones de Valve: descarga la demo (.dem.bz2) que indica el Game Coordinator.
* "Datos personales del juego" (gcpd/730) de tu perfil: el historial completo de partidas de Premier y Competitivo.
"""

from __future__ import annotations

from .i18n import t

import bz2
import html
import json
import logging
import re
import shutil
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

USER_AGENT = t("CS2Stats/2.0 (+uso personal)")
SHARECODE_RE = re.compile(r"^CSGO(-[A-Za-z0-9]{5}){5}$")
AUTHCODE_RE = re.compile(r"^[A-Za-z0-9]{4}-[A-Za-z0-9]{5}-[A-Za-z0-9]{4}$")
# "matchhistorycompetitive" (sin "permap") es la pestaña de CS:GO: en CS2 no trae partidas nuevas y Steam la
# sigue paginando vacía, así que no se lee.
HISTORY_TABS = {"matchhistorypremier": "premier", "matchhistorycompetitivepermap": "competitivo",
                "matchhistorywingman": "wingman"}
MAX_EMPTY_PAGES = 40     # páginas seguidas sin partidas: no queda más historial en esa pestaña
CS2_RELEASE = "2023-09-27"


class SteamError(Exception):
    pass


def clean_sharecode(text: str) -> str:
    text = (text or "").strip()
    match = re.search(r"CSGO(-[A-Za-z0-9]{5}){5}", text)
    return match.group(0) if match else ""


def next_sharecodes(api_key: str, steamid: int, auth_code: str, known_code: str, limit: int = 50) -> list[str]:
    """Códigos de las partidas posteriores a known_code, de la más vieja a la más nueva."""
    codes: list[str] = []
    current = known_code
    for _ in range(limit):
        query = urllib.parse.urlencode({"key": api_key, "steamid": steamid, "steamidkey": auth_code, "knowncode": current})
        url = f"https://api.steampowered.com/ICSGOPlayers_730/GetNextMatchSharingCode/v1?{query}"
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                status = response.status
                body = response.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as error:
            if error.code == 403:
                raise SteamError(t("Steam rechazó la clave de Web API o el código de autenticación. Revisalos en Conectar.")) from error
            if error.code == 412:
                raise SteamError(t("El último código de partida ya no sirve (tiene más de 30 días o no es tuyo). "
                                 "Pegá uno nuevo en Conectar.")) from error
            if error.code == 429:
                raise SteamError(t("Steam pidió esperar un rato antes de volver a consultar.")) from error
            raise SteamError(t('Steam respondió con un error ({0}).').format(error.code)) from error
        except (urllib.error.URLError, TimeoutError) as error:
            raise SteamError(t("No hay conexión con Steam en este momento.")) from error
        if status == 202:
            break
        try:
            nxt = json.loads(body)["result"]["nextcode"]
        except (ValueError, KeyError) as error:
            raise SteamError(t("Steam devolvió una respuesta inesperada.")) from error
        if not nxt or nxt == "n/a":
            break
        codes.append(nxt)
        current = nxt
    return codes


def download_demo(url: str, target_dir: Path, progress: Callable[[int, int], None] | None = None) -> Path:
    """Baja la demo de los servidores de repeticiones de Valve y la descomprime (.dem.bz2 a .dem)."""
    target_dir.mkdir(parents=True, exist_ok=True)
    name = url.rsplit("/", 1)[-1]
    packed = target_dir / name
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=60) as response, open(packed, "wb") as out:
            total = int(response.headers.get(t("Content-Length")) or 0)
            done = 0
            while True:
                chunk = response.read(1 << 20)
                if not chunk:
                    break
                out.write(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
    except urllib.error.HTTPError as error:
        packed.unlink(missing_ok=True)
        if error.code == 404:
            raise SteamError(t("Valve ya borró esa demo de sus servidores.")) from error
        raise SteamError(t('No se pudo bajar la demo ({0}).').format(error.code)) from error
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        packed.unlink(missing_ok=True)
        raise SteamError(t("Se cortó la descarga de la demo.")) from error
    if not name.endswith(".bz2"):
        return packed
    demo = target_dir / name[:-4]
    try:
        with bz2.open(packed, "rb") as source, open(demo, "wb") as out:
            shutil.copyfileobj(source, out, 1 << 20)
    finally:
        packed.unlink(missing_ok=True)
    return demo


# Historial completo: "Datos personales del juego" (gcpd/730)

def cookie_header(cookies: list[str], domain: str = "steamcommunity.com") -> tuple[str, str]:
    """Arma el encabezado Cookie para un sitio de Steam y saca sessionid.

    El login devuelve una cookie steamLoginSecure por cada sitio (tienda, comunidad, login...): hay que usar
    solo las del sitio que se consulta, si no Steam muestra la página como si no hubieras iniciado sesión.
    """
    pairs: dict[str, str] = {}
    for raw in cookies:
        parts = [p.strip() for p in raw.split(";")]
        first = parts[0]
        if "=" not in first:
            continue
        cookie_domain = next((p.split("=", 1)[1].lstrip(".").lower() for p in parts[1:] if p.lower().startswith("domain=")), "")
        if cookie_domain and cookie_domain != domain:
            continue
        key, value = first.split("=", 1)
        pairs[key.strip()] = value.strip()
    return "; ".join(f"{k}={v}" for k, v in pairs.items()), pairs.get("sessionid", "")


def _get(url: str, cookie: str, attempts: int = 4) -> str:
    """GET con reintentos: si Steam pide ir más despacio (429), espera y vuelve a probar."""
    import time
    for attempt in range(attempts):
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Cookie": cookie})
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as error:
            if error.code in (429, 503) and attempt < attempts - 1:
                logging.getLogger("cs2stats").info("Steam pidió esperar (%d), reintento %d", error.code, attempt + 1)
                time.sleep(20 * (attempt + 1))
                continue
            if error.code == 429:
                raise SteamError(t("Steam pidió esperar un rato antes de seguir leyendo el historial. Probá de nuevo en unos minutos.")) from error
            raise SteamError(t('Steam no dejó leer el historial ({0}).').format(error.code)) from error
        except (urllib.error.URLError, TimeoutError) as error:
            raise SteamError(t("No hay conexión con Steam en este momento.")) from error
    raise SteamError(t("Steam no respondió."))


def _cells(row_html: str) -> list[str]:
    return [_text(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", row_html, flags=re.S)]


def _text(fragment: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", " ", fragment)).replace("\xa0", " ").strip()


def _int(text: str) -> int:
    match = re.search(r"-?\d+", text or "")
    return int(match.group(0)) if match else 0


def parse_history(page: str, steamid: int, mode: str) -> list[dict]:
    """Lee la página del historial: cada partida es un par de tablas inner_left (mapa, fecha) e inner_right (jugadores).

    Steam pone todas las partidas como filas de una sola tabla csgo_scoreboard_root (y las páginas de "Cargar más"
    traen solo filas), así que se corta por cada inner_left.
    """
    matches = []
    for block in re.split(r'class="csgo_scoreboard_inner_left"', page)[1:]:
        left = re.search(r'^(.*?)</table>', block, flags=re.S)
        right = re.search(r'csgo_scoreboard_inner_right(.*?)</table>', block, flags=re.S)
        if not left or not right:
            continue
        info = [t for t in (_text(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", left.group(1), flags=re.S)) if t]
        when = next((t for t in info if re.match(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", t)), "")
        title = info[0] if info else ""
        map_name = re.sub(r"^(Premier|Competitive|Wingman|Competitivo)\s+", "", title).strip()
        duration = next((t.split(":", 1)[1].strip() for t in info if t.lower().startswith("match duration")), "")
        demo = re.search(r'href="(https?://replay[^"]+\.dem\.bz2)"', left.group(1))
        players, score_row, my_index = [], None, None
        for row in re.findall(r"<tr[^>]*>(.*?)</tr>", right.group(1), flags=re.S):
            if "csgo_scoreboard_score" in row:
                score_row = _text(row)
                players.append(None)  # separador entre equipos
                continue
            cells = _cells(row)
            if len(cells) < 7:
                continue
            link = re.search(r'steamcommunity\.com/profiles/(\d+)', row)
            link_id = re.search(r'steamcommunity\.com/id/([^"/]+)', row)
            player = {"name": cells[0], "steamid": int(link.group(1)) if link else 0,
                      "vanity": link_id.group(1) if link_id else "",
                      "ping": _int(cells[1]), "kills": _int(cells[2]), "assists": _int(cells[3]), "deaths": _int(cells[4]),
                      "mvps": _int(cells[5].replace("★", "1") if cells[5].strip() == "★" else cells[5]),
                      "hsp": _int(cells[6]), "score": _int(cells[7]) if len(cells) > 7 else 0}
            if player["steamid"] == steamid:
                my_index = len(players)
            players.append(player)
        if score_row is None or my_index is None:
            continue
        split = players.index(None)
        first, second = (_int(x) for x in (score_row.split(":") + ["0", "0"])[:2])
        mine_first = my_index < split
        us, them = (first, second) if mine_first else (second, first)
        me = players[my_index]
        team = [p for p in (players[:split] if mine_first else players[split + 1:]) if p]
        rivals = [p for p in (players[split + 1:] if mine_first else players[:split]) if p]
        try:
            played = datetime.strptime(when.replace(" GMT", ""), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            played_at = played.astimezone().replace(tzinfo=None).isoformat(timespec="seconds")
        except ValueError:
            played_at = ""
        matches.append({
            "mode": mode, "map": map_name, "played_at": played_at, "duration": duration,
            "score_us": us, "score_them": them, "result": "W" if us > them else "L" if them > us else "T",
            "kills": me["kills"], "assists": me["assists"], "deaths": me["deaths"], "mvps": me["mvps"],
            "hsp": me["hsp"], "score": me["score"], "demo_url": demo.group(1) if demo else "",
            "team": [p for p in team if p is not me], "rivals": rivals,
        })
    return matches


def fetch_history(cookies: list[str], steamid: int, progress: Callable[[str], None] | None = None,
                  save_raw: Path | None = None, max_pages: int = 400) -> list[dict]:
    """Recorre todas las pestañas del historial, con "Cargar más" incluido."""
    import time
    cookie, session = cookie_header(cookies)
    if "steamLoginSecure=" not in cookie:
        raise SteamError(t("Steam no devolvió la sesión de la comunidad. Probá escanear el QR de nuevo."))
    base = f"https://steamcommunity.com/profiles/{steamid}/gcpd/730/"
    found: list[dict] = []
    problems: list[str] = []
    for tab, mode in HISTORY_TABS.items():
        if progress:
            progress(t('Leyendo el historial de {0}').format(mode))
        page = _get(f"{base}?tab={tab}&l=english", cookie)
        if save_raw:
            save_raw.mkdir(parents=True, exist_ok=True)
            (save_raw / f"{tab}.html").write_text(page, encoding="utf-8")
        if re.search(r"g_steamID\s*=\s*false", page):
            raise SteamError(t("Steam no reconoció la sesión. Probá escanear el QR de nuevo."))
        if "csgo_scoreboard_root" not in page and "g_sGcContinueToken" not in page:
            continue  # pestaña sin partidas
        found += parse_history(page, steamid, mode)
        token = re.search(r"g_sGcContinueToken\s*=\s*'([^']*)'", page)
        token = token.group(1) if token else ""
        pages = empty = 0
        while token and pages < max_pages:
            pages += 1
            if progress:
                total_mode = len([r for r in found if r["mode"] == mode])
                progress(t('Leyendo {0} ({1} de {2}): {3} partidas de {4}, {5} en total').format(mode, list(HISTORY_TABS).index(tab) + 1, len(HISTORY_TABS), total_mode, mode, len(found)))
            if pages % 10 == 0:
                logging.getLogger("cs2stats").info("Historial %s: página %d, %d partidas", mode, pages, len(found))
            time.sleep(2.5)  # sin apurar a Steam: más rápido devuelve 429 y obliga a esperar
            query = urllib.parse.urlencode({"ajax": 1, "tab": tab, "continue_token": token, "sessionid": session, "l": "english"})
            try:
                raw = _get(f"{base}?{query}", cookie)
            except SteamError as error:
                problems.append(str(error))
                break  # se guarda lo leído hasta acá
            try:
                data = json.loads(raw)
            except ValueError:
                break
            if not data.get("success"):
                break
            if save_raw:
                (save_raw / f"{tab}_{pages:03d}.html").write_text(data.get("html", ""), encoding="utf-8")
            rows = parse_history(data.get("html", ""), steamid, mode)
            found += rows
            token = data.get("continue_token") or ""
            # Steam pagina por períodos: hay páginas vacías (semanas sin jugar). Se corta tras muchas seguidas
            # o al llegar a partidas anteriores a CS2.
            empty = 0 if rows else empty + 1
            if empty >= MAX_EMPTY_PAGES or any(r["played_at"] and r["played_at"] < CS2_RELEASE for r in rows):
                break
        time.sleep(1.5)
    if not found and problems:
        raise SteamError(problems[0])
    return found


def parse_saved_history(folder: Path, steamid: int) -> list[dict]:
    """Vuelve a leer las páginas del historial guardadas, sin pedirle nada a Steam."""
    rows: list[dict] = []
    if not folder.exists():
        return rows
    for path in sorted(folder.glob("*.html")):
        tab = path.stem.split("_")[0]
        mode = HISTORY_TABS.get(tab)
        if mode:
            rows += parse_history(path.read_text(encoding="utf-8", errors="replace"), steamid, mode)
    return rows

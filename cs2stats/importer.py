"""Une la búsqueda, el lector y el historial: decide qué demos son nuevas y las importa."""

from __future__ import annotations

import os
from dataclasses import dataclass

from .finder import DemoFile, decompress, list_demos, remove_quietly, watched_folders
from .i18n import t
from .metrics import map_label
from .parser import DemoError, NotInDemo, parse_demo
from .store import Settings, Store, data_dir

DONE = {"importada", "duplicada", "no_es_tuya", "borrada"}


@dataclass
class ImportResult:
    demo: DemoFile
    status: str          # importada, duplicada, no_es_tuya, error
    message: str
    match_id: int | None = None


def file_key(demo: DemoFile) -> str:
    """La misma demo puede aparecer como C:\\Program Files o c:\\program files según de dónde salió la ruta."""
    return os.path.normcase(os.path.normpath(str(demo.path)))


def pending_demos(store: Store, settings: Settings) -> list[DemoFile]:
    pending = []
    for demo in list_demos(watched_folders(settings["extra_folders"])):
        known = store.file_status(file_key(demo))
        if known and (known["status"] in DONE or (known["size"] == demo.size and known["mtime"] == demo.mtime)):
            continue
        pending.append(demo)
    return pending


def import_demo(store: Store, demo: DemoFile, steamid: int) -> ImportResult:
    path = file_key(demo)
    temp = None
    try:
        source = decompress(demo, data_dir() / "temporal")
        temp = source if source != demo.path else None
        match = parse_demo(str(source), steamid)
    except NotInDemo as error:
        store.remember_file(path, demo.size, demo.mtime, "no_es_tuya", message=str(error))
        return ImportResult(demo, "no_es_tuya", str(error))
    except (DemoError, OSError, ValueError) as error:
        store.remember_file(path, demo.size, demo.mtime, "error", message=str(error))
        return ImportResult(demo, "error", str(error))
    except Exception as error:  # zstandard y otros pueden lanzar errores propios
        store.remember_file(path, demo.size, demo.mtime, "error", message=str(error))
        return ImportResult(demo, "error", t('No se pudo abrir el archivo: {0}').format(error))
    finally:
        if temp:
            remove_quietly(temp)
    label = f"{map_label(match['map'])} {match['score_us']} a {match['score_them']}"
    if store.has_match(match["match_key"]):
        store.remember_file(path, demo.size, demo.mtime, "duplicada", match["match_key"], "Ya estaba importada")
        return ImportResult(demo, "duplicada", t("{0}: ya estaba en tu historial").format(label))
    match_id = store.add_match(match, demo.path.name, demo.played_at)
    store.remember_file(path, demo.size, demo.mtime, "importada", match["match_key"])
    return ImportResult(demo, "importada", label, match_id)

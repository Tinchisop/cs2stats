"""Encuentra CS2, tus cuentas de Steam y las demos nuevas en la PC."""

from __future__ import annotations

import bz2
import gzip
import os
import re
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

DEMO_SUFFIXES = (".dem", ".dem.zst", ".dem.gz", ".dem.bz2")
STEAM_ID_BASE = 76561197960265728


def steam_root() -> Path | None:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
            path = Path(winreg.QueryValueEx(key, "SteamPath")[0])
            if path.exists():
                return path
    except OSError:
        pass
    default = Path(r"C:\Program Files (x86)\Steam")
    return default if default.exists() else None


def cs2_game_dir() -> Path | None:
    """Carpeta game\\csgo de CS2, buscando en todas las bibliotecas de Steam."""
    root = steam_root()
    if not root:
        return None
    libraries = []
    try:
        # Las rutas de libraryfolders.vdf respetan mayúsculas; la del registro suele venir en minúsculas.
        text = (root / "steamapps" / "libraryfolders.vdf").read_text(encoding="utf-8", errors="ignore")
        libraries += [Path(p.replace("\\\\", "\\")) for p in re.findall(r'"path"\s+"([^"]+)"', text)]
    except OSError:
        pass
    libraries.append(root)
    for library in libraries:
        candidate = library / "steamapps" / "common" / "Counter-Strike Global Offensive" / "game" / "csgo"
        if candidate.exists():
            return candidate
    return None


def steam_accounts() -> list[tuple[int, str]]:
    """(SteamID64, nombre visible) de las cuentas que iniciaron sesión en esta PC; primero la última que se usó."""
    root = steam_root()
    if not root:
        return []
    try:
        text = (root / "config" / "loginusers.vdf").read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []
    accounts = []
    for steamid, body in re.findall(r'"(7656\d{13})"\s*\{(.*?)\}', text, flags=re.S):
        name = re.search(r'"PersonaName"\s+"([^"]*)"', body)
        recent = re.search(r'"MostRecent"\s+"1"', body) is not None
        accounts.append((not recent, int(steamid), name.group(1) if name else steamid))
    return [(steamid, name) for _, steamid, name in sorted(accounts, key=lambda a: a[0])]


def account_name(steamid: int) -> str:
    return next((name for sid, name in steam_accounts() if sid == steamid), str(steamid))


def downloads_dir() -> Path:
    try:
        import winreg
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            return Path(winreg.QueryValueEx(key, "{374DE290-123F-4565-9164-39C4925E467B}")[0])
    except OSError:
        return Path.home() / "Downloads"


def watched_folders(extra: list[str] | None = None) -> list[Path]:
    folders = []
    game = cs2_game_dir()
    if game:
        folders += [game / "replays", game]
    folders.append(downloads_dir())
    folders += [Path(p) for p in (extra or [])]
    seen, unique = set(), []
    for folder in folders:
        key = str(folder).casefold()
        if key not in seen and folder.exists():
            seen.add(key)
            unique.append(folder)
    return unique


@dataclass
class DemoFile:
    path: Path
    size: int
    mtime: float

    @property
    def compressed(self) -> bool:
        return not self.path.name.lower().endswith(".dem")

    @property
    def played_at(self) -> str:
        return datetime.fromtimestamp(self.mtime).isoformat(timespec="seconds")


def list_demos(folders: list[Path]) -> list[DemoFile]:
    """Demos en las carpetas, sin entrar en subcarpetas. Primero las sin comprimir."""
    found: dict[str, DemoFile] = {}
    for folder in folders:
        try:
            entries = list(folder.iterdir())
        except OSError:
            continue
        for entry in entries:
            name = entry.name.lower()
            if not name.endswith(DEMO_SUFFIXES):
                continue
            try:
                stat = entry.stat()
            except OSError:
                continue
            if stat.st_size < 1_000_000 or not entry.is_file():
                continue  # vacías o a medio descargar
            found[str(entry).casefold()] = DemoFile(entry, stat.st_size, stat.st_mtime)
    return sorted(found.values(), key=lambda d: (d.compressed, d.mtime))


def decompress(demo: DemoFile, target_dir: Path) -> Path:
    """Descomprime .zst/.gz/.bz2 a una copia temporal. Devuelve la ruta de la .dem."""
    if not demo.compressed:
        return demo.path
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / (demo.path.name.rsplit(".", 1)[0])
    name = demo.path.name.lower()
    with open(demo.path, "rb") as source, open(target, "wb") as out:
        if name.endswith(".zst"):
            import zstandard
            zstandard.ZstdDecompressor().copy_stream(source, out)
        elif name.endswith(".gz"):
            with gzip.GzipFile(fileobj=source) as stream:
                shutil.copyfileobj(stream, out, 1 << 20)
        else:
            with bz2.BZ2File(source) as stream:
                shutil.copyfileobj(stream, out, 1 << 20)
    return target


def remove_quietly(path: Path) -> None:
    try:
        os.remove(path)
    except OSError:
        pass

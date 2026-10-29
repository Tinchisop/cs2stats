"""Música del mapa: suena en loop con entrada y salida suaves mientras mirás una partida o un mapa.

Usa MCI de Windows (winmm), que reproduce MP3 y WAV sin bibliotecas extra."""

from __future__ import annotations

import ctypes
import logging
import sys
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal

log = logging.getLogger("cs2stats")
ALIAS = "cs2statsmusica"
FADE_IN_MS = 1400
FADE_OUT_MS = 700
STEP_MS = 40


def _mci(command: str) -> int:
    if sys.platform != "win32":
        return 1
    buffer = ctypes.create_unicode_buffer(128)
    return ctypes.windll.winmm.mciSendStringW(command, buffer, 128, 0)


class MapMusic(QObject):
    """Un solo tema a la vez. volume va de 0 a 100."""

    changed = Signal(str)   # mapa que suena ("" si nada)
    ended = Signal()        # terminó un tema que no estaba en loop (la radio pasa al siguiente)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.volume = 45
        self.level = 0.0          # 0 a 1, para las entradas y salidas
        self.target = 0.0
        self.path: Path | None = None
        self.map_name = ""
        self.open = False
        self.loop = True
        self.timer = QTimer(self)
        self.timer.setInterval(STEP_MS)
        self.timer.timeout.connect(self._step)
        self.watch = QTimer(self)      # mira si terminó el tema (solo sin loop)
        self.watch.setInterval(700)
        self.watch.timeout.connect(self._check_end)

    @property
    def playing(self) -> bool:
        return self.open and self.target > 0

    def play(self, map_name: str, path: Path | None, loop: bool = True) -> None:
        if path is None:
            self.stop()
            return
        if self.open and path == self.path and loop == self.loop:
            self.target = 1.0
            self.timer.start()
            return
        self._close()
        if _mci(f'open "{path}" type mpegvideo alias {ALIAS}') != 0:
            log.warning("No se pudo abrir la música %s", path)
            return
        self.open, self.path, self.map_name = True, path, map_name
        self.level = 0.0
        self._apply()
        self.loop = loop
        _mci(f"play {ALIAS} repeat" if loop else f"play {ALIAS}")
        if loop:
            self.watch.stop()
        else:
            self.watch.start()
        self.target = 1.0
        self.timer.start()
        self.changed.emit(map_name)

    def stop(self) -> None:
        if not self.open:
            return
        self.target = 0.0
        self.timer.start()
        self.changed.emit("")

    def set_volume(self, volume: int) -> None:
        self.volume = max(0, min(100, int(volume)))
        self._apply()

    def _apply(self) -> None:
        # Curva cuadrática: el oído percibe mejor así la subida y la bajada.
        if self.open:
            _mci(f"setaudio {ALIAS} volume to {int(self.volume * 10 * self.level ** 2)}")

    def _step(self) -> None:
        span = FADE_IN_MS if self.target > self.level else FADE_OUT_MS
        delta = STEP_MS / span
        if self.target > self.level:
            self.level = min(self.target, self.level + delta)
        else:
            self.level = max(self.target, self.level - delta)
        self._apply()
        if self.level == self.target:
            self.timer.stop()
            if self.target == 0.0:
                self._close()

    def _check_end(self) -> None:
        if not self.open or self.loop or self.target == 0.0:
            self.watch.stop()
            return
        if sys.platform != "win32":
            return
        buffer = ctypes.create_unicode_buffer(32)
        if ctypes.windll.winmm.mciSendStringW(f"status {ALIAS} mode", buffer, 32, 0) == 0 and buffer.value == "stopped":
            self.watch.stop()
            self.ended.emit()

    def _close(self) -> None:
        self.watch.stop()
        if self.open:
            _mci(f"close {ALIAS}")
        self.open, self.path, self.map_name = False, None, ""
        self.level = 0.0

    def shutdown(self) -> None:
        self.timer.stop()
        self._close()

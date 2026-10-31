"""Reproductor de clips de latas: decodifica el MP4 en otro hilo y muestra cada cuadro a su hora exacta.

La interfaz nunca decodifica ni escala: recibe cuadros ya listos, al tamaño justo, y por eso no se traba."""

from __future__ import annotations

import queue
import threading
from pathlib import Path

from PySide6.QtCore import QElapsedTimer, QObject, Qt, QTimer, Signal
from PySide6.QtGui import QImage

BUFFER_FRAMES = 12


class ClipPlayer(QObject):
    frame_changed = Signal()

    def __init__(self, path: Path, width: int, parent=None):
        super().__init__(parent)
        self.path = path
        self.width = max(64, width)
        self.fps = 60.0
        self.frames = 0
        self.image: QImage | None = None
        self.number = -1                    # cuadro que se está mostrando
        self.frames_known = threading.Event()
        self.queue: queue.Queue = queue.Queue(BUFFER_FRAMES)
        self.running = True
        self.thread = threading.Thread(target=self._decode, daemon=True)
        self.clock = QElapsedTimer()
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.setInterval(8)
        self.timer.timeout.connect(self._tick)
        self.pending = None

    def start(self) -> None:
        self.thread.start()
        self.clock.start()
        self.timer.start()

    def stop(self) -> None:
        self.running = False
        self.timer.stop()
        try:                                # destraba al hilo si estaba esperando lugar en la cola
            while True:
                self.queue.get_nowait()
        except queue.Empty:
            pass

    def _decode(self) -> None:
        import cv2
        capture = cv2.VideoCapture(str(self.path))
        self.fps = capture.get(cv2.CAP_PROP_FPS) or 60.0
        self.frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        self.frames_known.set()
        number = 0
        while self.running and capture.isOpened():
            ok, frame = capture.read()
            if not ok:
                if not number:
                    break                   # el archivo no se puede leer
                capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
                number = 0
                continue
            height = round(frame.shape[0] * self.width / frame.shape[1])
            small = cv2.resize(frame, (self.width, height), interpolation=cv2.INTER_AREA)
            image = QImage(small.data, small.shape[1], small.shape[0], small.strides[0], QImage.Format.Format_BGR888).copy()
            while self.running:
                try:
                    self.queue.put((number, image), timeout=0.1)
                    break
                except queue.Full:
                    pass
            number += 1
        capture.release()

    def _tick(self) -> None:
        if not self.frames_known.is_set() or not self.frames:
            return
        due = int(self.clock.elapsed() / 1000 * self.fps)
        target = due % self.frames
        loops = due // self.frames
        shown = None
        while True:
            item = self.pending
            self.pending = None
            if item is None:
                try:
                    item = self.queue.get_nowait()
                except queue.Empty:
                    break
            order = item[0] + (self._loop_of(item[0], loops, target)) * self.frames
            if order > due:
                self.pending = item         # todavía no le toca
                break
            shown = item
        if shown:
            self.number, self.image = shown
            self.frame_changed.emit()

    @staticmethod
    def _loop_of(number: int, loops: int, target: int) -> int:
        """A qué vuelta del clip pertenece un cuadro: uno muy adelantado respecto del actual es de la vuelta anterior."""
        return loops - 1 if number > target + BUFFER_FRAMES * 2 else loops

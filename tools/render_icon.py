"""Dibuja el ícono de la app y lo guarda como .ico de Windows (varios tamaños)."""

import os
import struct
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root))

from PySide6.QtCore import QBuffer, QIODevice, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from cs2stats.ui.theme import app_icon  # noqa: E402

app = QApplication([])
canvas = app_icon().pixmap(256, 256).toImage()
(root / "assets").mkdir(exist_ok=True)
canvas.save(str(root / "assets" / "cs2stats.png"))
payloads = []
for size in (16, 24, 32, 48, 64, 128, 256):
    scaled = canvas.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    scaled.save(buffer, "PNG")
    payloads.append((size, bytes(buffer.data())))
offset = 6 + 16 * len(payloads)
directory = []
for size, payload in payloads:
    directory.append(struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(payload), offset))
    offset += len(payload)
(root / "assets" / "cs2stats.ico").write_bytes(
    struct.pack("<HHH", 0, 1, len(payloads)) + b"".join(directory) + b"".join(data for _, data in payloads))
print("Icono creado")

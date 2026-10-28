"""Saca capturas de cada pantalla sin mostrar la ventana. Uso: python tools/capturas.py <carpeta>"""

import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from cs2stats.importer import import_demo, pending_demos  # noqa: E402
from cs2stats.store import PARSER_VERSION, Settings, Store  # noqa: E402
from cs2stats.ui.window import MainWindow  # noqa: E402

out = Path(sys.argv[1] if len(sys.argv) > 1 else "capturas")
out.mkdir(parents=True, exist_ok=True)

# Importa antes las demos de la PC, para que las capturas muestren datos reales.
store, settings = Store(), Settings()
if (settings["parser_version"] or 1) < PARSER_VERSION:
    store.forget_demo_matches()
    settings.set("parser_version", PARSER_VERSION)
for demo in pending_demos(store, settings):
    import_demo(store, demo, settings["steamid"])

app = QApplication(sys.argv)
window = MainWindow(start_hidden=True)
window.resize(1440, 960)
window.show()


def settle(seconds: float = 1.3) -> None:
    """Deja terminar las animaciones de entrada antes de sacar la captura."""
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.01)


def shoot() -> None:
    for key in window.pages:
        window.go(key)
        settle()
        window.grab().save(str(out / f"{key}.png"))
    if window.view["matches"]:
        window.open_match(window.view["matches"][-1]["id"])
        settle()
        window.grab().save(str(out / "partida.png"))
    window.quitting = True
    window.close()
    app.quit()


QTimer.singleShot(1500, shoot)
app.exec()

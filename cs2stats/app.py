"""Punto de entrada. Una sola copia abierta: si ya hay una, se la trae al frente."""

from __future__ import annotations

import sys

from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication

SOCKET_NAME = "cs2stats-unica"


def setup_log() -> None:
    """Errores inesperados a registro.log en la carpeta de datos, para poder revisarlos después."""
    import logging
    from .store import data_dir
    logging.basicConfig(filename=data_dir() / "registro.log", level=logging.INFO, encoding="utf-8",
                        format="%(asctime)s %(levelname)s %(message)s")

    def hook(kind, value, trace):
        logging.getLogger("cs2stats").error("Error inesperado", exc_info=(kind, value, trace))
    sys.excepthook = hook


def main() -> int:
    setup_log()
    app = QApplication(sys.argv)
    app.setApplicationName("CS2 Stats")
    app.setQuitOnLastWindowClosed(False)
    probe = QLocalSocket()
    probe.connectToServer(SOCKET_NAME)
    if probe.waitForConnected(300):
        probe.write(b"mostrar")
        probe.flush()
        probe.waitForBytesWritten(300)
        return 0
    QLocalServer.removeServer(SOCKET_NAME)
    server = QLocalServer()
    server.listen(SOCKET_NAME)

    # El idioma se fija antes de cargar las pantallas: sus textos se arman al importarlas.
    from .i18n import set_language
    from .store import Settings
    set_language(Settings()["language"])
    from .ui.window import MainWindow
    window = MainWindow(start_hidden="--bandeja" in sys.argv)

    def wake() -> None:
        connection = server.nextPendingConnection()
        if connection:
            connection.readyRead.connect(lambda: (connection.readAll(), window.bring_up()))
    server.newConnection.connect(wake)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())

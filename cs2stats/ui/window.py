"""Ventana principal: menú lateral, filtros y el controlador que une historial, Steam, demos locales y aviso de CS2."""

from __future__ import annotations

import logging
import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QEasingCurve, QEvent, QObject, QPropertyAnimation, QRect, QSize, Qt, QThread, QTimer, Signal
from PySide6.QtWidgets import (QApplication, QButtonGroup, QComboBox, QFileDialog, QFrame, QHBoxLayout, QMainWindow,
                               QMenu, QMessageBox, QPushButton, QStackedWidget, QSystemTrayIcon, QVBoxLayout, QWidget)

from .. import gsi
from ..benchmarks import compare, highlights, lobby_samples, tier_of
from ..finder import account_name, cs2_game_dir, steam_accounts, watched_folders
from ..helper import HelperError
from ..importer import import_demo, pending_demos
from ..insights import analyze
from ..metrics import SOURCE_NAMES, map_label, summarize
from ..steamapi import SteamError
from ..store import IMPORT_DATE_MARGIN, PARSER_VERSION, Settings, Store, data_dir
from ..i18n import LANGUAGES, language, t
from ..resumen import match_message
from ..sync import build_replay, reload_saved_history, send_summary, steam_ready, sync_history, sync_steam
from ..assets import (MAP_MUSIC, avatar_path, download_avatar, download_player_avatars, extract_game_assets,
                      extract_map_music, extract_overviews, map_music)
from ..demoview import DemoViewError, open_moment
from ..faceit import sync_faceit
from ..prematch import LobbyError, collect, detect_party
from ..nades import MapGrid
from ..nades import build_lineups
from ..recorder import RecorderError, cs2_running, ffmpeg_path, launch_practice, record_lineups
from .clips_page import ClipsPage
from .connect import ConnectPage, DemosPage, LoginDialog
from .match import MatchView
from .hud import CoachBot
from .motion import cascade, reveal
from .nades_page import NadesPage
from .pages import (AdvicePage, HelpPage, HistoryPage, MapsPage, MatchesPage, ProfilePage, RankPage, UtilityPage,
                    WeaponsPage)
from .prematch_page import PrematchPage
from .radio import MusicButton, MusicPanel
from .sessions_page import SessionsPage
from .social import AchievementsPage, FriendsPage
from .sound import MapMusic
from .theme import ACCENT, BAD, GOOD, MUTED, STYLE, app_icon, fmt_num, icon, label, panel
from .training_page import TrainingPage

RUN_KEY = t(r"Software\Microsoft\Windows\CurrentVersion\Run")
RUN_NAME = t("CS2 Stats")
log = logging.getLogger("cs2stats")
# Aviso al cambiar de idioma, en el idioma nuevo (la app sigue en el anterior hasta reabrirla).
EN_RESTART = "The language changes the next time you open the app."
ES_RESTART = "El idioma cambia la próxima vez que abras la app."


def launch_command() -> str:
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" --bandeja'
    return f'"{Path(sys.executable).with_name("pythonw.exe")}" -m cs2stats --bandeja'


def startup_enabled() -> bool:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, RUN_NAME)
            return True
    except OSError:
        return False


def set_startup(enabled: bool) -> None:
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, RUN_NAME, 0, winreg.REG_SZ, launch_command())
        else:
            try:
                winreg.DeleteValue(key, RUN_NAME)
            except OSError:
                pass


class ImportWorker(QObject):
    progress = Signal(int, int, str)
    item_done = Signal(str, str)
    finished = Signal(int)

    def __init__(self, store: Store, demos: list, steamid: int):
        super().__init__()
        self.store, self.demos, self.steamid = store, demos, steamid

    def run(self) -> None:
        imported = 0
        total = len(self.demos)
        for index, demo in enumerate(self.demos):
            self.progress.emit(index, total, t('Leyendo {0} ({1} de {2})').format(demo.path.name, index + 1, total))
            try:
                result = import_demo(self.store, demo, self.steamid)
            except BaseException as error:  # que una demo rara no frene las demás (incluye PanicException)
                if isinstance(error, (KeyboardInterrupt, SystemExit)):
                    raise
                log.exception("Falló la importación de %s", demo.path)
                self.item_done.emit("error", f"{demo.path.name}: {error}")
                continue
            log.info("%s: %s (%s)", demo.path.name, result.status, result.message)
            if result.status == "importada":
                imported += 1
            self.item_done.emit(result.status, result.message)
        self.progress.emit(total, total, t("Listo"))
        self.finished.emit(imported)


class TaskWorker(QObject):
    """Corre una tarea larga (sincronizar con Steam, leer el historial) fuera de la ventana."""
    message = Signal(str)
    finished = Signal(object, str)

    def __init__(self, task):
        super().__init__()
        self.task = task

    def run(self) -> None:
        try:
            result = self.task(self.message.emit)
            self.finished.emit(result, "")
        except (SteamError, HelperError, RecorderError, LobbyError, DemoViewError) as error:
            log.warning("Tarea: %s", error)
            self.finished.emit(None, str(error))
        except BaseException as error:
            if isinstance(error, (KeyboardInterrupt, SystemExit)):
                raise
            log.exception("Error en tarea de fondo")
            self.finished.emit(None, t('Error inesperado: {0}').format(error))


class TaskRunner(QObject):
    """Un carril para tareas largas. Vive en el hilo de la ventana, así "done" siempre llega a la interfaz
    (si se avisara desde el hilo de fondo, las pantallas redibujadas quedan en blanco)."""
    done = Signal(object, str)
    message = Signal(str)

    def __init__(self, name: str, parent=None):
        super().__init__(parent)
        self.name = name
        self.thread: QThread | None = None
        self.worker: TaskWorker | None = None

    @property
    def busy(self) -> bool:
        return self.thread is not None

    def start(self, task) -> bool:
        if self.busy:
            return False
        log.info("Tarea %s: empieza", self.name)
        self.thread = QThread()
        self.worker = TaskWorker(task)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.message.connect(self.message)
        self.worker.finished.connect(self._finished)
        self.thread.start()
        return True

    def _finished(self, result, error: str) -> None:
        self.thread.quit()
        self.thread.wait()
        self.thread = None
        self.worker = None
        log.info("Tarea %s: termina %s", self.name, f"con error: {error}" if error else "bien")
        self.done.emit(result, error)

    def stop(self) -> None:
        if self.thread is not None:
            self.thread.quit()
            self.thread.wait(3000)


class GsiBridge(QObject):
    """Pasa los avisos del servidor (otro hilo) al hilo de la ventana."""
    match_ended = Signal(dict)
    activity = Signal(str)


def real_date(match: dict) -> bool:
    """False si la fecha de la partida es en realidad la hora en que se importó."""
    try:
        gap = datetime.fromisoformat(match["played_at"]) - datetime.fromisoformat(match["imported_at"])
    except (KeyError, TypeError, ValueError):
        return True
    return abs(gap.total_seconds()) >= IMPORT_DATE_MARGIN


def unify_rows(demos: list[dict], history: list[dict]) -> list[dict]:
    """Una lista de partidas: las de demo con todo el detalle y las del historial de Steam que no tienen demo."""
    rows = []
    for m in demos:
        s = m["s"]
        premier = ""
        if m.get("rank_type") == 11 and m.get("rank_new"):
            premier = f"{fmt_num(m['rank_new'], 0)} ({(m.get('rank_change') or 0):+.0f})"
        rows.append({"id": m["id"], "played_at": m["played_at"], "date_ok": real_date(m), "mode": m["source"], "map": m["map"], "result": m["result"],
                     "us": m["score_us"], "them": m["score_them"], "k": s["kills"], "a": s["assists"], "d": s["deaths"],
                     "adr": s["adr"], "hs": (s["hs"] or 0) * 100 if s["hs"] is not None else None, "rating": s["rating"],
                     "premier": premier, "premier_value": m.get("rank_new") if m.get("rank_type") == 11 else None,
                     "premier_change": m.get("rank_change")})

    by_result: dict[tuple, list[datetime]] = {}
    for m in demos:
        try:
            when = datetime.fromisoformat(m["played_at"])
        except (TypeError, ValueError):
            continue
        by_result.setdefault((map_label(m["map"]).lower(), m["score_us"], m["score_them"]), []).append(when)

    def has_demo(h: dict) -> bool:
        try:
            when = datetime.fromisoformat(h["played_at"])
        except (TypeError, ValueError):
            return False
        limit = (48 if h["mode"] == "faceit" else 3) * 3600
        return any(abs((when - other).total_seconds()) <= limit
                   for other in by_result.get((h["map"].lower(), h["score_us"], h["score_them"]), []))

    for h in history:
        if has_demo(h):
            continue
        rows.append({"id": None, "played_at": h["played_at"], "mode": h["mode"], "map": h["map"], "result": h["result"],
                     "us": h["score_us"], "them": h["score_them"], "k": h["kills"], "a": h["assists"], "d": h["deaths"],
                     "adr": h.get("adr"), "hs": h["hsp"], "rating": None, "premier": ""})
    rows.sort(key=lambda r: r["played_at"] or "")
    return rows


class MainWindow(QMainWindow):
    NAV = [(t("ESTADÍSTICAS"), None, None), ("perfil", t("Perfil"), "profile"), ("partidas", t("Partidas"), "list"),
           ("jugadas", t("Jugadas"), "film"), ("rango", t("Tu rango"), "rank"), ("mapas", t("Mapas"), "map"), ("latas", t("Latas"), "grenade"),
           ("armas", t("Armas"), "target"),
           ("utilidad", t("Utilidad y plata"), "bolt"), ("consejos", t("Consejos"), "bulb"),
           ("sesiones", t("Sesiones"), "session"), ("entrenamiento", t("Entrenamiento"), "dumbbell"), ("amigos", t("Amigos"), "friends"),
           ("prepartida", t("Pre-partida"), "duel"),
           ("logros", t("Logros y metas"), "medal"), ("historial", t("Historial"), "history"),
           (t("CUENTA"), None, None), ("conectar", t("Conectar Steam"), "link"), ("demos", t("Demos y aviso"), "import"),
           ("ayuda", t("Cómo usar"), "help")]
    TITLES = {"perfil": t("Perfil"), "partidas": t("Partidas"), "rango": t("Comparación con tu rango"), "mapas": t("Mapas"),
              "latas": t("Latas"),
              "armas": t("Armas"), "utilidad": t("Utilidad y plata"), "consejos": t("Consejos para mejorar"),
              "jugadas": t("Tus jugadas"), "sesiones": t("Tus sesiones"), "entrenamiento": t("Entrenamiento"), "prepartida": t("Asistente pre-partida"),
              "historial": t("Historial completo"), "amigos": t("Vos y tus amigos"), "logros": t("Logros y metas"), "conectar": t("Conectar Steam"), "demos": t("Demos y aviso de fin de partida"),
              "ayuda": t("Cómo usar CS2 Stats")}

    def __init__(self, start_hidden: bool = False):
        super().__init__()
        self.store = Store()
        self.settings = Settings()
        self.view: dict | None = None
        self.pending: list = []
        self.thread: QThread | None = None
        self.worker: ImportWorker | None = None
        self.steam_runner = TaskRunner("partidas", self)
        self.history_runner = TaskRunner("historial", self)
        self.steam_runner.done.connect(self._steam_done)
        self.history_runner.done.connect(self._history_done)
        self.assets_runner = TaskRunner("recursos", self)
        self.assets_runner.done.connect(lambda _r, _e: self.refresh())
        self.clips_runner = TaskRunner("clips", self)
        self.clips_runner.done.connect(self._clips_done)
        self.replay_runner = TaskRunner("repeticion", self)
        self.replay_runner.done.connect(self._replay_done)
        self.replay_for: int | None = None
        self.faceit_runner = TaskRunner("faceit", self)
        self.faceit_runner.done.connect(self._faceit_done)
        self.lobby_runner = TaskRunner("pre-partida", self)
        self.lobby_runner.done.connect(self._lobby_done)
        self.lobby_task = ""
        self.replay_runner.message.connect(self._replay_message)
        self.demo_runner = TaskRunner("abrir en CS2", self)
        self.demo_runner.message.connect(self._demo_message)
        self.demo_runner.done.connect(self._demo_done)
        self.stop_recording = False
        self.quitting = False
        self.game_dir = cs2_game_dir()
        self.gsi_server: gsi.GsiServer | None = None
        self.gsi_status = ""
        self.force_import = False
        if (self.settings["parser_version"] or 1) < PARSER_VERSION:
            # Versión nueva del lector: se vuelven a leer las demos que siguen en la PC.
            self.store.forget_demo_matches()
            self.settings.set("parser_version", PARSER_VERSION)
            self.force_import = True
        try:
            reload_saved_history(self.store, self.settings)
        except (OSError, ValueError):
            log.exception("No se pudo releer el historial guardado")
        self.store.repair_played_at()

        self.setWindowTitle(t("CS2 Stats"))
        self.setWindowIcon(app_icon())
        self.resize(1400, 920)
        self.setMinimumSize(1150, 740)
        self.setStyleSheet(STYLE)
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        outer = QHBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._sidebar())
        content = QVBoxLayout()
        content.setContentsMargins(0, 18, 0, 0)
        content.setSpacing(8)
        self.header_bar = QWidget()  # se oculta en el detalle de partida, que trae su propia cabecera
        header = QHBoxLayout(self.header_bar)
        header.setContentsMargins(28, 0, 28, 0)
        self.title = label(t("Perfil"), "pageTitle")
        header.addWidget(self.title)
        header.addStretch(1)
        header.addWidget(self._now_playing())
        header.addSpacing(14)
        header.addWidget(label(t("Modo"), "smallMuted"))
        self.mode = QComboBox()
        self.mode.addItem(t("Todos los modos"), "")
        self.mode.setToolTip(t("Cada modo muestra sus números por separado: Premier por un lado, FACEIT por otro"))
        self.mode.currentIndexChanged.connect(self._mode_changed)
        header.addWidget(self.mode)
        header.addSpacing(10)
        header.addWidget(label(t("Comparar"), "smallMuted"))
        self.recent_n = QComboBox()
        for n in (5, 10, 20, 50):
            self.recent_n.addItem(t('Últimas {0}').format(n), n)
        self.recent_n.setCurrentIndex(max(0, self.recent_n.findData(self.settings["recent_n"])))
        self.recent_n.currentIndexChanged.connect(self._recent_changed)
        header.addWidget(self.recent_n)
        content.addWidget(self.header_bar)
        self.match_view: MatchView | None = None
        self.current_page = "perfil"
        self.stale: set[str] = set()
        self.music = MapMusic(self)
        self.music.set_volume(self.settings["music_volume"])
        self.music.changed.connect(self._music_changed)
        self.music.ended.connect(self._radio_next)
        self.stack = QStackedWidget()
        self.pages = {"perfil": ProfilePage(), "partidas": MatchesPage(), "rango": RankPage(), "mapas": MapsPage(),
                      "latas": NadesPage(), "armas": WeaponsPage(), "utilidad": UtilityPage(), "consejos": AdvicePage(),
                      "amigos": FriendsPage(), "logros": AchievementsPage(), "jugadas": ClipsPage(),
                      "sesiones": SessionsPage(), "entrenamiento": TrainingPage(), "prepartida": PrematchPage(),
                      "historial": HistoryPage(), "conectar": ConnectPage(), "demos": DemosPage(), "ayuda": HelpPage()}
        self.pages["logros"].set_goals(self.settings.values.get("goals", []))
        self.pages["logros"].goals_changed.connect(self._goals_changed)
        for page in self.pages.values():
            self.stack.addWidget(page)
            page.open_match.connect(self.open_match)
            page.go_to.connect(self.go)
        content.addWidget(self.stack, 1)
        outer.addLayout(content, 1)

        self.pages["jugadas"].open_in_game.connect(self.open_in_game)
        self.pages["perfil"].sync_requested.connect(self.sync_all)
        self.pages["partidas"].delete_requested.connect(self.delete_match)
        self.pages["partidas"].play_map.connect(self.toggle_music)
        self.pages["mapas"].play_map.connect(self.toggle_music)
        self.pages["jugadas"].store = self.store
        lobby: PrematchPage = self.pages["prepartida"]
        lobby.set_key(self.settings.secret("faceit_key"))
        lobby.detect_requested.connect(self.detect_lobby)
        lobby.analyze_requested.connect(self.analyze_lobby)
        self.lobby_runner.message.connect(lambda text: lobby.set_busy(True, text))
        nades: NadesPage = self.pages["latas"]
        nades.loader = lambda: build_lineups(self.store.nade_data())
        nades.record_requested.connect(self.start_recording)
        self.clips_runner.message.connect(lambda text: nades.record_button.setText(text[:60]))
        connect: ConnectPage = self.pages["conectar"]
        self.steam_runner.message.connect(connect.add_log)
        self.history_runner.message.connect(connect.add_log)
        connect.save_codes.connect(self.save_codes)
        connect.save_key.connect(lambda key: (self.settings.set("api_key", key), self.refresh_connect(), self.start_steam_sync()))
        connect.connect_gc.connect(self.login_gc)
        connect.disconnect_gc.connect(self.logout_gc)
        connect.connect_history.connect(self.login_history)
        connect.sync_now.connect(self.start_steam_sync)
        connect.save_faceit.connect(self.save_faceit_key)
        connect.sync_faceit.connect(self.start_faceit_sync)
        self.faceit_runner.message.connect(connect.set_faceit_status)
        connect.test_message.connect(self.test_message)
        connect.message_toggled.connect(lambda on: (self.settings.set("steam_message", on), self.refresh_connect()))
        connect.add_old_codes.connect(lambda codes: (self.store.add_sharecodes(codes), self.refresh_connect(), self.start_steam_sync()))
        demos: DemosPage = self.pages["demos"]
        demos.import_requested.connect(self.start_import)
        demos.scan_requested.connect(self.scan)
        demos.add_folder_requested.connect(self.add_folder)
        demos.setting_changed.connect(self.change_setting)
        demos.gsi_toggled.connect(self.toggle_gsi)
        demos.dismiss_gsi.connect(lambda i: (self.store.dismiss_gsi(i), self.refresh_demos()))

        self.tray = QSystemTrayIcon(app_icon(), self)
        self.tray.setToolTip(t("CS2 Stats"))
        menu = QMenu()
        menu.addAction(t("Abrir CS2 Stats"), self.bring_up)
        menu.addAction(t("Buscar partidas"), self.sync_all)
        menu.addSeparator()
        menu.addAction(t("Salir"), self.quit_app)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(lambda reason: self.bring_up() if reason == QSystemTrayIcon.ActivationReason.Trigger else None)
        self.tray.messageClicked.connect(self.bring_up)
        self.tray.show()

        self.bridge = GsiBridge()
        self.bridge.match_ended.connect(self.on_match_ended)
        self.bridge.activity.connect(self.on_gsi_activity)
        self.start_gsi()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.scan)
        self.timer.start(120_000)
        self.steam_timer = QTimer(self)
        self.steam_timer.timeout.connect(self.start_steam_sync)
        self.steam_timer.start(20 * 60_000)
        self.go("perfil")
        self.refresh()
        QTimer.singleShot(0, lambda: self._place_indicator(False))
        QTimer.singleShot(400, self.scan)
        QTimer.singleShot(800, self.load_assets)
        QTimer.singleShot(1500, self.start_steam_sync)
        QTimer.singleShot(2500, self.start_faceit_sync)
        self.steam_timer.timeout.connect(self.start_faceit_sync)
        if not start_hidden:
            self.show()

    # Estructura
    def _sidebar(self) -> QFrame:
        side = QFrame()
        side.setObjectName("sidebar")
        side.setFixedWidth(224)
        layout = QVBoxLayout(side)
        layout.setContentsMargins(12, 18, 12, 16)
        layout.setSpacing(2)
        brand = QHBoxLayout()
        logo = label("")
        logo.setPixmap(app_icon().pixmap(30, 30))
        brand.addWidget(logo)
        brand.addWidget(label(t("CS2 Stats"), "brand"), 1)
        layout.addLayout(brand)
        layout.addSpacing(12)
        # Placa que se desliza detrás del botón elegido (se crea antes que los botones para quedar debajo).
        self.nav_indicator = panel("navIndicator")
        self.nav_indicator.setParent(side)
        bar = panel("navIndicatorBar")
        bar.setParent(self.nav_indicator)
        bar.setGeometry(0, 9, 3, 20)
        self.nav_slide = QPropertyAnimation(self.nav_indicator, b"geometry", self)
        self.nav_slide.setDuration(340)
        self.nav_slide.setEasingCurve(QEasingCurve.Type.OutBack)
        side.installEventFilter(self)
        self.side = side
        self.nav_group = QButtonGroup(self)
        self.nav: dict[str, QPushButton] = {}
        for key, title, kind in self.NAV:
            if title is None:
                layout.addWidget(label(key, "navSection"))
                continue
            btn = QPushButton(title)
            btn.setObjectName("navButton")
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setIcon(icon(kind, MUTED, 18))
            btn.setIconSize(QSize(18, 18))
            btn.clicked.connect(lambda _=False, k=key: self.go(k))
            self.nav_group.addButton(btn)
            self.nav[key] = btn
            layout.addWidget(btn)
            if key == "consejos":
                # Globito rojo con la cantidad de puntos flojos, como en la referencia.
                inner = QHBoxLayout(btn)
                inner.setContentsMargins(0, 0, 12, 0)
                inner.addStretch(1)
                self.advice_badge = label("", "navBadge")
                self.advice_badge.hide()
                inner.addWidget(self.advice_badge)
        layout.addStretch(1)
        self.coach = panel("coachCard")
        coach_row = QHBoxLayout(self.coach)
        coach_row.setContentsMargins(10, 8, 10, 8)
        coach_row.setSpacing(8)
        coach_row.addWidget(CoachBot(42))
        coach_text = QVBoxLayout()
        coach_text.setSpacing(4)
        coach_text.addWidget(label(t("Tu entrenador"), "smallMuted"))
        coach_button = QPushButton(t("Ver consejos"))
        coach_button.setObjectName("coachButton")
        coach_button.setCursor(Qt.CursorShape.PointingHandCursor)
        coach_button.clicked.connect(lambda: self.go("consejos"))
        coach_text.addWidget(coach_button)
        coach_row.addLayout(coach_text, 1)
        layout.addWidget(self.coach)
        layout.addSpacing(8)
        status = QFrame()
        status.setObjectName("sideCard")
        self.status_card = status
        self.compact_nav = False
        status_layout = QVBoxLayout(status)
        status_layout.setContentsMargins(12, 10, 12, 10)
        status_layout.setSpacing(4)
        self.sync_dot = label("", "smallMuted", wrap=True)
        status_layout.addWidget(self.sync_dot)
        self.gsi_dot = label("", "smallMuted", wrap=True)
        status_layout.addWidget(self.gsi_dot)
        layout.addWidget(status)
        # Idioma: se aplica al volver a abrir la app (los textos se arman al iniciar).
        language_row = QHBoxLayout()
        language_row.addWidget(label(t("Idioma"), "smallMuted"))
        self.language_box = QComboBox()
        for code, name in LANGUAGES.items():
            self.language_box.addItem(name, code)
        self.language_box.setCurrentIndex(list(LANGUAGES).index(language()))
        self.language_box.currentIndexChanged.connect(self.change_language)
        language_row.addWidget(self.language_box, 1)
        layout.addLayout(language_row)
        return side

    def change_language(self, index: int) -> None:
        code = self.language_box.itemData(index)
        self.settings.set("language", code)
        QMessageBox.information(self, "CS2 Stats", t("El idioma cambia la próxima vez que abras la app.") if code == language()
                                else EN_RESTART if code == "en" else ES_RESTART)

    def _now_playing(self) -> QWidget:
        """Botón de música con su panel: radio de mapas, volumen y música en las partidas."""
        self.radio_on = False
        self.radio_queue: list[str] = []
        self.radio_index = 0
        self.music_button = MusicButton()
        self.music_panel = MusicPanel(self)
        self.music_button.clicked.connect(self._open_music_panel)
        self.music_panel.radio_toggled.connect(self.toggle_radio)
        self.music_panel.next_track.connect(self.radio_step)
        self.music_panel.volume_changed.connect(self._volume_changed)
        self.music_panel.auto_toggled.connect(lambda on: self.settings.set("map_music", on))
        return self.music_button

    def _open_music_panel(self) -> None:
        self._sync_music_panel()
        self.music_panel.open_below(self.music_button)

    def _sync_music_panel(self) -> None:
        self.music_panel.set_state(self.music.map_name if self.music.playing else "", self.radio_on,
                                   self.settings["music_volume"], self.settings["map_music"])

    def _volume_changed(self, value: int) -> None:
        self.music.set_volume(value)
        self.settings.set("music_volume", value)

    def toggle_radio(self) -> None:
        """Radio de mapas: pasa por la música de todos los mapas, en orden mezclado."""
        if self.radio_on:
            self.radio_on = False
            self.music.stop()
        else:
            import random
            self.radio_queue = [m for m in MAP_MUSIC if map_music(m) and map_music(m).stem == m]
            random.shuffle(self.radio_queue)
            self.radio_index = 0
            self.radio_on = bool(self.radio_queue)
            self._radio_play()
        self._sync_music_panel()

    def radio_step(self, step: int) -> None:
        if not self.radio_on or not self.radio_queue:
            return
        self.radio_index = (self.radio_index + step) % len(self.radio_queue)
        self._radio_play()

    def _radio_play(self) -> None:
        if self.radio_on and self.radio_queue:
            name = self.radio_queue[self.radio_index]
            self.music.play(name, map_music(name), loop=False)

    def _radio_next(self) -> None:
        if self.radio_on:
            self.radio_step(1)

    def _goals_changed(self, goals: list) -> None:
        self.settings.set("goals", goals)
        self.refresh()

    def eventFilter(self, obj, event):  # noqa: N802
        if obj is getattr(self, "side", None) and event.type() == QEvent.Type.Resize:
            # En ventanas bajas el robot y el estado se esconden y los botones se achican para que entre todo el menú.
            height = event.size().height()
            self.coach.setVisible(height >= 900)
            self.status_card.setVisible(height >= 800)
            compact = height < 900
            if compact != self.compact_nav:
                self.compact_nav = compact
                for btn in self.nav.values():
                    btn.setStyleSheet("QPushButton#navButton { padding: 4px 14px; }" if compact else "")
            QTimer.singleShot(0, lambda: self._place_indicator(False))
        return super().eventFilter(obj, event)

    def _place_indicator(self, animate: bool = True) -> None:
        btn = self.nav.get(self.current_page)
        if btn is None:
            return
        target = QRect(btn.geometry())
        if not animate or self.nav_indicator.geometry().isEmpty():
            self.nav_slide.stop()
            self.nav_indicator.setGeometry(target)
        else:
            self.nav_slide.stop()
            self.nav_slide.setStartValue(self.nav_indicator.geometry())
            self.nav_slide.setEndValue(target)
            self.nav_slide.start()
        self.nav_indicator.show()

    # Música del mapa
    def toggle_music(self, map_name: str) -> None:
        from ..metrics import map_label as _label
        self.radio_on = False
        if self.music.playing and _label(self.music.map_name).lower() == _label(map_name).lower():
            self.music.stop()
            return
        self.music.play(map_name, map_music(map_name))

    def _music_changed(self, map_name: str) -> None:
        self.music_button.set_playing(map_name)
        self._sync_music_panel()
        self.pages["mapas"].set_playing(map_name)
        if self.match_view is not None:
            self.match_view.set_music(bool(map_name))

    def go(self, key: str) -> None:
        for name, btn in self.nav.items():
            btn.setChecked(name == key)
            kind = next(k for n, _t, k in self.NAV if n == name)
            btn.setIcon(icon(kind, ACCENT if name == key else MUTED, 18))
        self.close_match()
        changed = key != self.current_page
        self.current_page = key
        self._place_indicator()
        if key not in ("partidas", "mapas") and not self.radio_on:
            self.music.stop()
        self._update_page(key)
        self.stack.setCurrentWidget(self.pages[key])
        self.title.setText(self.TITLES[key])
        if changed:
            reveal(self.title, duration=260)
            page = self.pages[key]
            if hasattr(page, "body"):
                cascade(page.body)
            else:
                reveal(page)
        if key == "demos":
            self.refresh_demos()
        if key == "conectar":
            self.refresh_connect()

    # Datos
    def _mode_changed(self) -> None:
        self.settings.set("mode_filter", self.mode.currentData() or "")
        self.refresh()

    def _recent_changed(self) -> None:
        self.settings.set("recent_n", self.recent_n.currentData())
        self.refresh()

    def refresh(self) -> None:
        steamid = self.settings["steamid"]
        all_matches = self.store.matches(steamid)
        for m in all_matches:
            if "s" not in m:
                m["s"] = summarize(m["rounds"])
        all_history = self.store.history(steamid)
        sources = sorted({m["source"] for m in all_matches} | {h["mode"] for h in all_history})
        current = self.settings["mode_filter"]
        self.mode.blockSignals(True)
        self.mode.clear()
        self.mode.addItem(t("Todos los modos"), "")
        for source in sources:
            self.mode.addItem(SOURCE_NAMES.get(source, source), source)
        if self.mode.findData(current) < 0 and current:
            self.mode.addItem(SOURCE_NAMES.get(current, current), current)   # el modo elegido aunque todavía no tenga partidas
        self.mode.setCurrentIndex(max(0, self.mode.findData(current)))
        self.mode.blockSignals(False)
        mode = self.mode.currentData()
        matches = [m for m in all_matches if not mode or m["source"] == mode]
        history = [h for h in all_history if not mode or h["mode"] == mode]
        n = self.recent_n.currentData() or 10
        recent = matches[-n:]
        name = next((m["my_name"] for m in reversed(all_matches) if m["my_name"]), "")
        if not name:
            name = dict(steam_accounts()).get(steamid, "")
        premier_match = next((m for m in reversed(all_matches) if m.get("rank_type") == 11 and m.get("rank_new")), None)
        premier = premier_match["rank_new"] if premier_match else None
        samples = lobby_samples(all_matches)
        total = summarize([r for m in matches for r in m["rounds"]])
        recent_total = summarize([r for m in recent for r in m["rounds"]])
        comparisons, reference, reference_n = compare(total, samples, premier)
        recent_comparisons, _ref, _n = compare(recent_total, samples, premier)
        if getattr(self, "_grids_for", None) != len(all_matches):
            raw: dict[str, list] = {}
            for map_name, cells in self.store.grids():
                raw.setdefault(map_name, []).extend(cells)
            self._grids = {name: MapGrid(cells) for name, cells in raw.items()}
            self._grids_for = len(all_matches)
        self.view = {
            "grids": self._grids,
            "all_matches": all_matches, "matches": matches, "recent": recent, "n": n, "total": total,
            "recent_total": recent_total, "insights": analyze(matches), "name": name, "data_dir": str(data_dir()),
            "history": history, "all_history": all_history, "premier": premier, "premier_tier": tier_of(premier),
            "comparisons": comparisons, "recent_comparisons": recent_comparisons, "reference": reference,
            "reference_n": reference_n, "highlights": highlights(comparisons), "rows": unify_rows(matches, history),
            "steam": steam_ready(self.settings), "mode": mode,
            "faceit": self.settings["faceit_profile"] or {}, "faceit_elo": self.store.faceit_elo(),
        }
        self.stale = set(self.pages)
        self._update_page(self.current_page)
        weak = sum(1 for i in self.view["insights"] if i.kind == "flojo")
        self.advice_badge.setText(str(weak))
        self.advice_badge.setVisible(bool(weak))
        self._update_dots()

    def _update_page(self, key: str) -> None:
        """Arma una pantalla con la vista actual si quedó vieja (refresh solo arma la que está a la vista)."""
        if self.view is not None and key in self.stale:
            self.stale.discard(key)
            self.pages[key].update_view(self.view)

    def _update_dots(self) -> None:
        ready = steam_ready(self.settings)
        if self.history_runner.busy:
            self.sync_dot.setText(t("●  Leyendo tu historial de Steam"))
            self.sync_dot.setStyleSheet(f"color: {MUTED};")
        elif self.steam_runner.busy:
            self.sync_dot.setText(t("●  Buscando partidas en Steam"))
            self.sync_dot.setStyleSheet(f"color: {MUTED};")
        elif ready["codes"] and ready["gc"]:
            error = self.settings["steam_error"]
            self.sync_dot.setText(t("●  Steam: ") + (t("revisar conexión") if error else t("conectado")))
            self.sync_dot.setStyleSheet(f"color: {BAD if error else GOOD};")
        else:
            self.sync_dot.setText(t("●  Steam sin conectar"))
            self.sync_dot.setStyleSheet(f"color: {MUTED};")

    def refresh_connect(self) -> None:
        self.pages["conectar"].set_state(self.settings, self.steam_runner.busy or self.history_runner.busy,
                                         self.store.sharecodes())
        self.pages["conectar"].set_faceit(self.settings, self.faceit_runner.busy,
                                          len(self.store.history_keys("faceit:")))
        self._update_dots()

    def refresh_demos(self) -> None:
        page: DemosPage = self.pages["demos"]
        folders = [str(f) for f in watched_folders(self.settings["extra_folders"])]
        page.set_settings(self.settings, steam_accounts(), folders, self.gsi_status, self.settings["gsi_enabled"],
                          self.settings.values.get("background", True), startup_enabled())
        page.set_pending(len(self.pending), self.thread is not None)
        page.set_gsi_pending(self.store.pending_gsi())

    # Steam
    def save_codes(self, auth: str, share: str) -> None:
        self.settings.set("auth_code", auth)
        self.settings.set("last_sharecode", share)
        self.store.add_sharecodes([share])
        self.refresh_connect()
        self.start_steam_sync()

    def login_gc(self) -> None:
        dialog = LoginDialog("client", t("Conectar la cuenta secundaria"),
                             t("Usá la cuenta nueva, no la principal. Escaneá el QR con la app de Steam del celular en la que "
                             "agregaste esa cuenta, o usá su usuario y contraseña."), True, self)
        if dialog.exec() and dialog.result_data:
            data = dialog.result_data
            if str(data.get("steamId")) == str(self.settings["steamid"]):
                QMessageBox.warning(self, t("CS2 Stats"), t("Esa es tu cuenta principal. Para bajar demos usá una cuenta secundaria, "
                                                       "así no se interrumpe tu juego."))
                return
            self.settings.set("gc_token", data["refreshToken"])
            self.settings.set("gc_account", data.get("accountName") or "")
            self.refresh_connect()
            self.start_steam_sync()

    def logout_gc(self) -> None:
        self.settings.set("gc_token", "")
        self.settings.set("gc_account", "")
        self.refresh_connect()

    def login_history(self) -> None:
        # Sesión tipo navegador: desde 2025 Steam solo da cookies web a ese tipo (y al de la app del celular).
        dialog = LoginDialog("web", t("Traer tu historial de Steam"),
                             t("Escaneá el QR con la app de Steam del celular de tu cuenta principal. La sesión se usa una sola vez "
                             "para leer \"Datos personales del juego\" y no se guarda."), False, self)
        accepted = dialog.exec()
        data = dialog.result_data
        if not (accepted and data):
            log.info("Historial: inicio de sesión cancelado o fallido (%s)", dialog.error or "sin error")
            if dialog.error:
                QMessageBox.warning(self, "CS2 Stats", t("Steam no completó el inicio de sesión: {0}").format(dialog.error))
            return
        if str(data.get("steamId")) != str(self.settings["steamid"]):
            log.info("Historial: se escaneó otra cuenta")
            QMessageBox.warning(self, t("CS2 Stats"), t('Esa no es la cuenta que se mide en la app ({0}). Escaneá con la app de Steam de tu cuenta principal.').format(account_name(self.settings['steamid'])))
            return
        cookies = data.get("cookies") or []
        log.info("Historial: sesión iniciada, %d cookies", len(cookies))
        self.pages["conectar"].add_log(t("Sesión iniciada. Leyendo tu historial de Steam (puede tardar unos minutos)"))
        self.go("conectar")
        # Corre aparte de la búsqueda de partidas: no tiene que esperar a que terminen las descargas de demos.
        if not self.history_runner.start(lambda say: sync_history(self.store, self.settings, cookies, say)):
            QMessageBox.information(self, t("CS2 Stats"), t("Ya se está leyendo tu historial. Esperá a que termine."))
        self.refresh_connect()

    def _history_done(self, result, error: str) -> None:
        if error:
            QMessageBox.warning(self, t("CS2 Stats"), t('No se pudo leer el historial: {0}').format(error))
        else:
            self.pages["conectar"].add_log(t('Historial actualizado ({0} partidas nuevas)').format(result))
            self.start_steam_sync()  # el historial puede traer demos todavía disponibles
        self.refresh()
        self.refresh_connect()

    def start_steam_sync(self) -> None:
        ready = steam_ready(self.settings)
        if not (ready["codes"] or ready["gc"] or ready["history"]):
            return
        if self.steam_runner.start(lambda say: sync_steam(self.store, self.settings, say)):
            self.refresh_connect()

    # FACEIT
    def save_faceit_key(self, key: str) -> None:
        self.settings.set("faceit_key", key)
        self.pages["prepartida"].set_key(key)
        self.start_faceit_sync()

    def start_faceit_sync(self) -> None:
        if self.settings.secret("faceit_key"):
            self.faceit_runner.start(lambda say: sync_faceit(self.store, self.settings, say))
            self.refresh_connect()

    def _faceit_done(self, added, error: str) -> None:
        if error:
            self.pages["conectar"].set_faceit_status(error, True)
        self.refresh()
        self.refresh_connect()

    def _steam_done(self, imported, error: str) -> None:
        if error:
            self.settings.set("steam_error", error)
            self.pages["conectar"].add_log(error)
        elif imported:
            if not self.isVisible():
                self.tray.showMessage(t("CS2 Stats"), t('Importé {0} {1} de Steam.').format(imported, t('partida') if imported == 1 else t('partidas')),
                                      app_icon(), 6000)
            self.load_assets()  # fotos de los jugadores de las partidas nuevas
        self.refresh()
        self.refresh_connect()


    def test_message(self) -> None:
        """Manda por Steam el resumen de tu última partida analizada, para ver cómo llega."""
        matches = self.store.matches(self.settings["steamid"])
        if not matches:
            QMessageBox.information(self, t("CS2 Stats"), t("Todavía no hay partidas analizadas para armar el resumen."))
            return
        text = match_message(matches[-1], matches[:-1])
        connect: ConnectPage = self.pages["conectar"]
        connect.add_log(t("Mandando un mensaje de prueba por Steam"))
        if not self.steam_runner.start(lambda say: send_summary(self.settings, text, say)):
            QMessageBox.information(self, t("CS2 Stats"), t("Ahora se están buscando partidas. Probá en un rato."))

    def sync_all(self) -> None:
        self.scan()
        self.start_steam_sync()
        self.go("conectar" if steam_ready(self.settings)["codes"] else "demos")

    # Fotos de mapas, íconos y foto de perfil
    def load_assets(self) -> None:
        avatar = avatar_path()
        old_avatar = not avatar.exists() or (datetime.now().timestamp() - avatar.stat().st_mtime) > 86400
        steamid, key = self.settings["steamid"], self.settings.secret("api_key")

        # Fotos de los demás jugadores de tus últimas partidas (las que falten o tengan más de una semana).
        others = {p["steamid"] for m in self.store.matches(steamid)[-40:] for p in m["scoreboard"] if not p.get("me")}

        def task(_say):
            extract_game_assets()
            extract_map_music()
            extract_overviews()
            if old_avatar:
                download_avatar(steamid, key)
            download_player_avatars(others, key)
            return True
        self.assets_runner.start(task)

    # Clips de latas
    def start_recording(self, map_name: str, lineups: list) -> None:
        page: NadesPage = self.pages["latas"]
        if self.clips_runner.busy:
            self.stop_recording = True
            page.record_button.setText(t("Deteniendo..."))
            return
        if not lineups:
            QMessageBox.information(self, t("CS2 Stats"), t("Todas las latas de esta lista ya tienen clip."))
            return
        if not ffmpeg_path():
            QMessageBox.warning(self, t("CS2 Stats"), t("Falta ffmpeg en la PC para grabar la pantalla."))
            return
        from ..recorder import NetCon
        probe = NetCon()
        already = probe.connect(1.0)
        probe.close()
        if not already and cs2_running():
            QMessageBox.information(self, t("CS2 Stats"), t("Cerrá CS2 y volvé a tocar el botón: la app lo abre en modo práctica."))
            return
        text = (t('Voy a grabar {0} {1} de {2}.\n\n• CS2 se abre en modo práctica (opción oficial -insecure: sin VAC solo en esa sesión, en un servidor tuyo; para volver a jugar online cerrás CS2 y lo abrís normal).\n• Mientras graba no toques el mouse ni el teclado. Se graba solo la ventana de CS2.\n• Tarda unos {3} minutos. Podés detenerlo con el mismo botón.').format(len(lineups), t('clip') if len(lineups) == 1 else t('clips'), map_label(map_name), max(1, len(lineups) * 18 // 60 + 1)))
        if QMessageBox.question(self, t("Grabar clips de latas"), text) != QMessageBox.StandardButton.Yes:
            return
        if not already:
            launch_practice()
        self.stop_recording = False
        page.record_button.setText(t("Detener grabación"))
        grid = page.data[1].get(map_name) if page.data else None
        self.clips_runner.start(lambda say: record_lineups(map_name, lineups, say, lambda: self.stop_recording, grid))

    def _clips_done(self, saved, error: str) -> None:
        page: NadesPage = self.pages["latas"]
        page.record_button.setText(t("Grabar clips de este mapa"))
        if error:
            QMessageBox.warning(self, t("CS2 Stats"), t('La grabación se cortó: {0}').format(error))
        else:
            self.bring_up()
            QMessageBox.information(self, t("CS2 Stats"), t('Listo: {0} clips grabados. Ya podés cerrar CS2.').format(saved or 0))
        page._draw()

    # Demos locales
    def scan(self) -> None:
        if self.thread is not None:
            return
        self.pending = pending_demos(self.store, self.settings)
        count = len(self.pending)
        log.info("Búsqueda: %d demos nuevas", count)
        self.nav["demos"].setText(t('Demos y aviso ({0})').format(count) if count else t("Demos y aviso"))
        self.pages["demos"].set_pending(count, False)
        if count and (self.settings["auto_import"] or self.force_import):
            self.start_import()
        self.force_import = False

    def start_import(self) -> None:
        if self.thread is not None or not self.pending:
            return
        self.thread = QThread(self)
        self.worker = ImportWorker(self.store, list(self.pending), self.settings["steamid"])
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        page: DemosPage = self.pages["demos"]
        self.worker.progress.connect(page.set_progress)
        self.worker.item_done.connect(self._log_result)
        self.worker.finished.connect(self._import_done)
        page.set_pending(len(self.pending), True)
        self.thread.start()

    def _log_result(self, status: str, message: str) -> None:
        text = {"importada": t('Importada: {0}').format(message), "duplicada": t('Repetida: {0}').format(message),
                "no_es_tuya": t('No es tuya: {0}').format(message), "error": t('No se pudo leer: {0}').format(message)}.get(status, message)
        color = {"importada": GOOD, "error": BAD}.get(status, MUTED)
        self.pages["demos"].add_log(text, color)

    def _import_done(self, imported: int) -> None:
        self.thread.quit()
        self.thread.wait()
        self.thread = None
        self.worker = None
        self.pending = []
        self.refresh()
        self.scan()
        self.refresh_demos()
        if imported and not self.isVisible():
            self.tray.showMessage(t("CS2 Stats"), t('Importé {0} {1}.').format(imported, t('partida') if imported == 1 else t('partidas')), app_icon(), 6000)

    def add_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, t("Elegí una carpeta con demos"))
        if folder and folder not in self.settings["extra_folders"]:
            self.settings.set("extra_folders", self.settings["extra_folders"] + [folder])
            self.refresh_demos()
            self.scan()

    def change_setting(self, key: str, value) -> None:
        if key == "startup":
            try:
                set_startup(bool(value))
            except OSError:
                QMessageBox.warning(self, t("CS2 Stats"), t("No se pudo cambiar el inicio con Windows."))
        elif key == "steamid":
            self.settings.set("steamid", int(value))
            if self.gsi_server:
                self.gsi_server.tracker.steamid = str(value)
            self.scan()
            self.refresh()
        else:
            self.settings.set(key, value)
            if key == "auto_import" and value:
                self.scan()
        self.refresh_demos()

    def delete_match(self, match_id: int) -> None:
        answer = QMessageBox.question(self, t("Borrar partida"), t("¿Borrar esta partida de tu historial? No se vuelve a importar sola."))
        if answer == QMessageBox.StandardButton.Yes:
            self.store.delete_match(match_id)
            self.refresh()

    def open_match(self, match_id: int) -> None:
        """El detalle se abre dentro de la misma ventana, en lugar de la página de donde viniste."""
        match = next((m for m in self.view["all_matches"] if m["id"] == match_id), None)
        if not match:
            return
        self.close_match()
        index = self.store.replay_index()
        view = MatchView(match, None, self.view["all_matches"], t("Volver a {0}").format(self.TITLES[self.current_page]),
                         replay_loader=lambda key: (self.store.replay(key), index.get(key, {}).get("status", "")),
                         grid=self.view.get("grids", {}).get(match["map"]))
        view.back.connect(lambda: self.go(self.current_page))
        view.replay_requested.connect(self.start_replay)
        view.replay_tab.open_in_game.connect(lambda number, at: self.open_in_game(match["id"], number, at))
        view.music_toggled.connect(self._match_music)
        self.stack.addWidget(view)
        self.match_view = view
        self.header_bar.hide()
        self.stack.setCurrentWidget(view)
        view.setFocus()
        view.animate_in()
        if self.settings["map_music"] and not self.radio_on:
            self.music.play(match["map"], map_music(match["map"]))
        view.set_music(self.music.playing)

    # Repetición 2D a pedido (partidas importadas antes de que se guardaran las posiciones)
    def start_replay(self, match_id: int) -> None:
        match = next((m for m in self.view["all_matches"] if m["id"] == match_id), None)
        if not match:
            return
        if not self.replay_runner.start(lambda say: build_replay(self.store, self.settings, match, say)):
            QMessageBox.information(self, t("CS2 Stats"), t("Ya se está armando otra repetición. Esperá a que termine."))
            return
        self.replay_for = match_id

    def _replay_message(self, text: str) -> None:
        if self.match_view is not None and self.match_view.match_id == self.replay_for:
            self.match_view.replay_tab.set_busy(text)

    def _replay_done(self, ready, error: str) -> None:
        match_id, self.replay_for = self.replay_for, None
        view = self.match_view
        if view is not None and view.match_id == match_id:
            if ready:
                view.replay_tab.reload()
            else:
                view.replay_tab.set_busy(error or t("No se pudo armar: la demo ya no está disponible."))
        if ready:
            self.refresh()

    # Abrir una jugada en CS2
    def open_in_game(self, match_id: int, round_number: int, seconds: float) -> None:
        match = next((m for m in self.view["all_matches"] if m["id"] == match_id), None)
        if not match:
            return
        if self.demo_runner.busy:
            QMessageBox.information(self, t("CS2 Stats"), t("CS2 todavía está abriendo la jugada anterior. Esperá a que termine."))
            return
        if not self.settings.values.get("demo_notice_seen") and not cs2_running():
            answer = QMessageBox.question(self, t("Abrir en CS2"), t(
                "CS2 se va a abrir en modo de repeticiones (-insecure). No afecta tu cuenta, pero en ese modo no podés "
                "jugar online: para volver a jugar, cerrá CS2 y abrilo normal desde Steam.\n\n¿Abrirlo?"))
            if answer != QMessageBox.StandardButton.Yes:
                return
            self.settings.set("demo_notice_seen", True)
        self.demo_runner.start(lambda say: open_moment(self.store, match, round_number, seconds, say))
        self._demo_message(t("Preparando la jugada"))

    def _demo_message(self, text: str) -> None:
        self.tray.showMessage(t("Abrir en CS2"), text, QSystemTrayIcon.MessageIcon.NoIcon, 2500)

    def _demo_done(self, result, error: str) -> None:
        if error or result is None:
            QMessageBox.warning(self, t("Abrir en CS2"), error or t("No se pudo abrir la jugada en CS2."))
        elif result.commands:
            QApplication.clipboard().setText(result.commands[0])
            box = QMessageBox(QMessageBox.Icon.Information, t("Abrir en CS2"), t(
                "CS2 ya está abierto, así que la app no lo toca para no cortarte una partida. Abrí la consola de CS2 y "
                "pegá el primer comando (ya está copiado). Cuando cargue la demo, escribí el segundo:\n\n{0}\n{1}").format(*result.commands), QMessageBox.StandardButton.Ok, self)
            box.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            box.exec()

    # Pre-partida
    def detect_lobby(self) -> None:
        page: PrematchPage = self.pages["prepartida"]
        key, me = self.settings.secret("api_key"), self.settings["steamid"]
        self.lobby_task = "detect"
        if self.lobby_runner.start(lambda _say: detect_party(key, me)):
            page.set_busy(True, t("Buscando tu grupo en Steam"))

    def analyze_lobby(self, mates: str, rivals: str, room: str, faceit_key: str) -> None:
        page: PrematchPage = self.pages["prepartida"]
        if faceit_key != self.settings.secret("faceit_key"):
            self.settings.set("faceit_key", faceit_key)
        key, me, matches = self.settings.secret("api_key"), self.settings["steamid"], self.view["all_matches"]
        self.lobby_task = "analyze"
        if self.lobby_runner.start(lambda say: collect(key, faceit_key, me, mates, rivals, room, matches, say)):
            page.set_busy(True, t("Analizando el lobby"))

    def _lobby_done(self, result, error: str) -> None:
        page: PrematchPage = self.pages["prepartida"]
        if error:
            page.show_error(error)
        elif self.lobby_task == "detect":
            page.set_mates([f"https://steamcommunity.com/profiles/{p.steamid}" for p in result])
            page.set_busy(False, t("Encontré {0} amigos en tu lobby.").format(len(result)) if result
                          else t("No hay amigos tuyos en tu lobby ahora."))
        else:
            page.show_collected(result)

    def _match_music(self, on: bool) -> None:
        self.settings.set("map_music", on)
        self.radio_on = False
        if on and self.match_view is not None:
            self.music.play(self.match_view.map_name, map_music(self.match_view.map_name))
        elif not on:
            self.music.stop()

    def close_match(self) -> None:
        if self.match_view is not None:
            self.stack.removeWidget(self.match_view)
            self.match_view.deleteLater()
            self.match_view = None
        self.header_bar.show()

    # Aviso de fin de partida (GSI)
    def start_gsi(self) -> None:
        if self.gsi_server:
            self.gsi_server.stop()
            self.gsi_server = None
        port, token = self.settings["gsi_port"], self.settings["gsi_token"]
        if not self.settings["gsi_enabled"]:
            self.gsi_status = t("Desactivado. Las partidas se importan igual; solo no vas a recibir el aviso al terminar.")
            self.gsi_dot.setText(t("●  Aviso de fin de partida apagado"))
            return
        if not self.game_dir:
            self.gsi_status = t("No encontré CS2 instalado en esta PC, así que no se puede activar el aviso.")
            self.gsi_dot.setText(t("●  CS2 no encontrado"))
            return
        fresh = not gsi.is_installed(self.game_dir, port, token)
        if fresh:
            try:
                gsi.install(self.game_dir, port, token)
            except OSError:
                self.gsi_status = t("No pude crear el archivo en la carpeta de CS2.")
                self.gsi_dot.setText(t("●  Aviso sin activar"))
                return
        tracker = gsi.MatchTracker(self.settings["steamid"], self.bridge.match_ended.emit, self.bridge.activity.emit)
        self.gsi_server = gsi.GsiServer(port, token, tracker)
        if not self.gsi_server.start():
            self.gsi_server = None
            self.gsi_status = t("Otra copia de CS2 Stats ya está escuchando el aviso.")
            self.gsi_dot.setText(t("●  Aviso en otra ventana"))
            return
        restart = t(" Si CS2 estaba abierto, cerralo y abrilo una vez para que lo tome.") if fresh else ""
        self.gsi_status = t("Activo. Cuando termine una partida tuya, la app busca la demo sola.") + restart
        self.gsi_dot.setText(t("●  Escuchando el fin de partida"))
        self.gsi_dot.setStyleSheet(f"color: {GOOD};")

    def toggle_gsi(self, enabled: bool) -> None:
        self.settings.set("gsi_enabled", bool(enabled))
        if not enabled:
            if self.gsi_server:
                self.gsi_server.stop()
                self.gsi_server = None
            if self.game_dir:
                gsi.uninstall(self.game_dir)
            self.gsi_dot.setStyleSheet("")
        self.start_gsi()
        self.refresh_demos()

    def on_gsi_activity(self, phase: str) -> None:
        if phase in ("live", "warmup", "intermission"):
            self.gsi_dot.setText(t("●  Partida en curso"))

    def on_match_ended(self, data: dict) -> None:
        self.store.add_gsi_match(data)
        self.gsi_dot.setText(t("●  Escuchando el fin de partida"))
        ready = steam_ready(self.settings)
        if ready["codes"] and ready["gc"]:
            text = (t('Terminaste {0} {1} a {2}. En unos minutos la demo se baja y se analiza sola.').format(map_label(data['map']), data['score_us'], data['score_them']))
        else:
            text = (t('Terminaste {0} {1} a {2} ({3}/{4}/{5}). Bajá la demo y la importo.').format(map_label(data['map']), data['score_us'], data['score_them'], data['kills'], data['deaths'], data['assists']))
        self.tray.showMessage(t("Partida terminada"), text, app_icon(), 10000)
        self.refresh_demos()
        if ready["gc"] and self.settings["steam_message"]:
            self.settings.set("message_pending", data)   # sale por Steam cuando se analice la demo
        # Valve tarda unos minutos en publicar el código y la demo. A los 31 minutos sale el mensaje aunque no haya demo.
        for minutes in (3, 8, 20, 31):
            QTimer.singleShot(minutes * 60_000, self.start_steam_sync)
        QTimer.singleShot(90_000, self.scan)

    # Ventana y bandeja
    def bring_up(self) -> None:
        self.show()
        self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized)
        self.raise_()
        self.activateWindow()

    def quit_app(self) -> None:
        self.quitting = True
        self.close()

    def closeEvent(self, event):  # noqa: N802
        if not self.quitting and self.settings.values.get("background", True) and self.gsi_server:
            event.ignore()
            self.hide()
            if not self.settings.values.get("tray_hint_shown"):
                self.settings.set("tray_hint_shown", True)
                self.tray.showMessage(t("CS2 Stats sigue abierta"), t("Quedó en la bandeja para avisarte cuando termine tu partida. "
                                      "Clic derecho en el ícono para salir."), app_icon(), 8000)
            return
        if self.thread is not None:
            self.thread.quit()
            self.thread.wait(3000)
        self.steam_runner.stop()
        self.history_runner.stop()
        self.stop_recording = True
        self.clips_runner.stop()
        self.assets_runner.stop()
        self.replay_runner.stop()
        self.lobby_runner.stop()
        self.faceit_runner.stop()
        if self.gsi_server:
            self.gsi_server.stop()
        self.music.shutdown()
        self.tray.hide()
        QApplication.quit()
        event.accept()

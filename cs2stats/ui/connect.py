"""Conectar Steam (paso a paso), login con QR y la pantalla de demos locales y aviso de fin de partida."""

from __future__ import annotations

import logging
import re

from PySide6.QtCore import QObject, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit,
                               QProgressBar, QPushButton, QVBoxLayout, QWidget)

from ..helper import Helper, HelperError
from ..i18n import t
from ..metrics import map_label
from ..steamapi import AUTHCODE_RE, clean_sharecode
from .pages import Page, card, chip, clear, short_date
from .theme import BAD, MUTED, STYLE, button, icon, label, panel

AUTH_PAGE = "https://help.steampowered.com/es/wizard/HelpWithGameIssue/?appid=730&issueid=128"
KEY_PAGE = "https://steamcommunity.com/dev/apikey"
JOIN_PAGE = "https://store.steampowered.com/join/"
log = logging.getLogger("cs2stats")


def open_url(url: str) -> None:
    QDesktopServices.openUrl(QUrl(url))


class _Bridge(QObject):
    event = Signal(dict)


def qr_pixmap(text: str, size: int = 260) -> QPixmap:
    import io
    import segno
    buffer = io.BytesIO()
    segno.make(text, error="m").save(buffer, kind="png", scale=8, border=2, dark="#0f1014", light="#ffffff")
    pixmap = QPixmap()
    pixmap.loadFromData(buffer.getvalue(), t("PNG"))
    return pixmap.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)


class LoginDialog(QDialog):
    """Inicio de sesión en Steam con QR (o usuario y contraseña escritos por vos). La app nunca ve la contraseña guardada."""

    def __init__(self, platform: str, title: str, lead: str, allow_password: bool, parent=None, want_cookies: bool = False):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setStyleSheet(STYLE)
        self.setMinimumWidth(460)
        self.platform = platform
        self.want_cookies = want_cookies
        self.error = ""
        self.result_data: dict | None = None
        self.helper: Helper | None = None
        self.bridge = _Bridge()
        self.bridge.event.connect(self._on_event)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(12)
        layout.addWidget(label(title, "sectionTitle"))
        layout.addWidget(label(lead, "body", wrap=True))
        self.qr = QLabel()
        self.qr.setFixedSize(270, 270)
        self.qr.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.qr.setStyleSheet("background: #ffffff; border-radius: 10px;")
        layout.addWidget(self.qr, 0, Qt.AlignmentFlag.AlignCenter)
        self.status = label(t("Pidiendo el código a Steam"), "muted", wrap=True)
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.status)
        self.form = QWidget()
        form = QVBoxLayout(self.form)
        form.setContentsMargins(0, 0, 0, 0)
        self.user = QLineEdit()
        self.user.setPlaceholderText(t("Nombre de cuenta de Steam"))
        self.password = QLineEdit()
        self.password.setPlaceholderText(t("Contraseña"))
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.code = QLineEdit()
        self.code.setPlaceholderText(t("Código de Steam Guard"))
        self.code.hide()
        form.addWidget(self.user)
        form.addWidget(self.password)
        form.addWidget(self.code)
        form.addWidget(label(t("La contraseña va directo a Steam. La app solo guarda el permiso de sesión que devuelve Steam."),
                             "smallMuted", wrap=True))
        self.form_button = button(t("Iniciar sesión"), primary=True)
        self.form_button.clicked.connect(self._submit)
        form.addWidget(self.form_button)
        self.form.hide()
        layout.addWidget(self.form)
        row = QHBoxLayout()
        self.switch = QPushButton(t("Usar usuario y contraseña"))
        self.switch.setObjectName("linkButton")
        self.switch.setCursor(Qt.CursorShape.PointingHandCursor)
        self.switch.clicked.connect(self._use_password)
        self.switch.setVisible(allow_password)
        row.addWidget(self.switch)
        row.addStretch(1)
        cancel = button(t("Cancelar"))
        cancel.clicked.connect(self.reject)
        row.addWidget(cancel)
        layout.addLayout(row)
        self._start()

    def _start(self) -> None:
        try:
            self.helper = Helper(self.bridge.event.emit)
        except HelperError as error:
            self.status.setText(str(error))

    def _on_event(self, message: dict) -> None:
        kind = message.get("event")
        log.info("Inicio de sesión (%s): %s %s", self.platform, kind, message.get("message", "") if kind == "error" else "")
        if kind == "ready" and self.form.isHidden():
            self.helper.send("qr_login", platform=self.platform, cookies=self.want_cookies)
        elif kind == "qr":
            self.qr.setPixmap(qr_pixmap(message["url"]))
            self.status.setText(t("Abrí la app de Steam en el celular, tocá el escudo de Steam Guard y después el ícono de "
                                "escanear QR. Apuntá a este código."))
        elif kind == "scanned":
            self.status.setText(t("Listo, ahora confirmá el inicio de sesión en el celular."))
        elif kind == "guard":
            guard = message.get("kind")
            if guard == "confirm":
                self.status.setText(t("Confirmá el inicio de sesión en la app de Steam del celular."))
            else:
                self.code.show()
                self.code.setFocus()
                self.form_button.setText(t("Enviar código"))
                self.status.setText(t("Steam te mandó un código por mail.") if guard == "email"
                                    else t("Escribí el código de Steam Guard de la app del celular."))
        elif kind == "authenticated":
            self.result_data = message
            self.accept()
        elif kind == "error":
            self.error = message.get("message", "error")
            self.status.setText(t('Steam respondió: {0}. Cerrá esta ventana y probá de nuevo.').format(message.get('message', 'error')))
            self.status.setStyleSheet(f"color: {BAD};")

    def _use_password(self) -> None:
        self.qr.hide()
        self.switch.hide()
        self.form.show()
        self.status.setText(t("Escribí los datos de la cuenta secundaria."))
        if self.helper:
            self.helper.close()
        self._start()

    def _submit(self) -> None:
        if not self.helper:
            return
        if self.code.isVisible():
            self.helper.send("guard_code", code=self.code.text().strip())
            self.status.setText(t("Verificando el código"))
            return
        if not self.user.text().strip() or not self.password.text():
            self.status.setText(t("Completá usuario y contraseña."))
            return
        self.helper.send("cred_login", platform=self.platform, cookies=self.want_cookies,
                         accountName=self.user.text().strip(), password=self.password.text())
        self.password.clear()
        self.status.setText(t("Conectando con Steam"))

    def done(self, result: int) -> None:  # noqa: D401 - cierra el ayudante siempre
        if self.helper:
            self.helper.close()
            self.helper = None
        super().done(result)


class Step(QFrame):
    def __init__(self, number: int, title: str, lead: str, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        outer = QHBoxLayout(self)
        outer.setContentsMargins(18, 16, 18, 16)
        outer.setSpacing(14)
        self.badge = label(str(number), "stepNumber")
        self.number = number
        outer.addWidget(self.badge, 0, Qt.AlignmentFlag.AlignTop)
        self.content = QVBoxLayout()
        self.content.setSpacing(8)
        top = QHBoxLayout()
        top.addWidget(label(title, "insightTitle"))
        top.addStretch(1)
        self.state = chip(t("Falta"), "chipWarn")
        top.addWidget(self.state)
        self.content.addLayout(top)
        self.content.addWidget(label(lead, "muted", wrap=True))
        outer.addLayout(self.content, 1)

    def set_done(self, done: bool, text: str = "") -> None:
        self.badge.setText("✓" if done else str(self.number))
        self.badge.setObjectName("stepDone" if done else "stepNumber")
        self.badge.style().unpolish(self.badge); self.badge.style().polish(self.badge)
        self.state.setText(text or (t("Listo") if done else t("Falta")))
        self.state.setObjectName("chipGood" if done else "chipWarn")
        self.state.style().unpolish(self.state); self.state.style().polish(self.state)


class ConnectPage(Page):
    save_codes = Signal(str, str)
    save_key = Signal(str)
    connect_gc = Signal()
    disconnect_gc = Signal()
    connect_history = Signal()
    sync_now = Signal()
    add_old_codes = Signal(list)
    test_message = Signal()
    message_toggled = Signal(bool)
    save_faceit = Signal(str)
    sync_faceit = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        body = self.body
        body.addWidget(label(t("Esto es lo que hace Leetify con tu cuenta, pero en tu PC: Steam avisa cuando jugás una partida "
                             "nueva, la app pide la demo al Game Coordinator y la analiza sola."), "pageLead", wrap=True))

        self.step1 = Step(1, t("Código de autenticación y último código de partida"),
                          t("Valve los muestra en una página de ayuda de Steam. Tocá el botón, iniciá sesión si te lo pide, "
                          "y copiá los dos códigos que aparecen (el de autenticación tiene la forma AAAA-AAAAA-AAAA y el de "
                          "partida empieza con CSGO-)."))
        row = QHBoxLayout()
        open_auth = button(t("Abrir la página de Valve"), "external")
        open_auth.clicked.connect(lambda: open_url(AUTH_PAGE))
        row.addWidget(open_auth)
        row.addStretch(1)
        self.step1.content.addLayout(row)
        self.auth = QLineEdit()
        self.auth.setPlaceholderText(t("Código de autenticación (AAAA-AAAAA-AAAA)"))
        self.share = QLineEdit()
        self.share.setPlaceholderText(t("Último código de partida (CSGO-xxxxx-xxxxx-xxxxx-xxxxx-xxxxx)"))
        self.step1.content.addWidget(self.auth)
        self.step1.content.addWidget(self.share)
        self.step1_msg = label("", "smallMuted", wrap=True)
        self.step1.content.addWidget(self.step1_msg)
        save = button(t("Guardar códigos"), primary=True)
        save.clicked.connect(self._save_codes)
        self.step1.content.addWidget(save, 0, Qt.AlignmentFlag.AlignLeft)
        body.addWidget(self.step1)

        self.step2 = Step(2, t("Clave de Web API de Steam"),
                          t("Steam la pide para consultar la Match History API. Tocá el botón, en \"Dominio\" escribí localhost, "
                          "aceptá y copiá la clave. Necesita Steam Guard del celular activo en tu cuenta principal."))
        row = QHBoxLayout()
        open_key = button(t("Abrir la página de la clave"), "external")
        open_key.clicked.connect(lambda: open_url(KEY_PAGE))
        row.addWidget(open_key)
        row.addStretch(1)
        self.step2.content.addLayout(row)
        self.key = QLineEdit()
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        self.key.setPlaceholderText(t("Clave de Web API (32 letras y números)"))
        self.step2.content.addWidget(self.key)
        self.step2_msg = label("", "smallMuted", wrap=True)
        self.step2.content.addWidget(self.step2_msg)
        save = button(t("Guardar clave"), primary=True)
        save.clicked.connect(self._save_key)
        self.step2.content.addWidget(save, 0, Qt.AlignmentFlag.AlignLeft)
        body.addWidget(self.step2)

        self.step3 = Step(3, t("Cuenta secundaria para bajar las demos"),
                          t("Creá una cuenta de Steam nueva y gratis (no hace falta comprar nada; la app le agrega CS2 sola). "
                          "Para conectarla con QR, sumala a la app de Steam del celular; si no, podés usar su usuario y "
                          "contraseña. Esta cuenta no juega: solo le pide las demos al Game Coordinator."))
        row = QHBoxLayout()
        join = button(t("Crear cuenta en Steam"), "external")
        join.clicked.connect(lambda: open_url(JOIN_PAGE))
        row.addWidget(join)
        self.gc_button = button(t("Conectar cuenta secundaria"), "link", primary=True)
        self.gc_button.clicked.connect(self.connect_gc)
        row.addWidget(self.gc_button)
        self.gc_off = button(t("Desconectar"))
        self.gc_off.clicked.connect(self.disconnect_gc)
        row.addWidget(self.gc_off)
        row.addStretch(1)
        self.step3.content.addLayout(row)
        body.addWidget(self.step3)

        self.step4 = Step(4, t("Todo tu historial de CS2"),
                          t("Iniciás sesión una vez con QR con tu cuenta principal y la app lee la página oficial \"Datos personales "
                          "del juego\": todas tus partidas de Premier y Competitivo desde que salió CS2. La sesión se usa solo para "
                          "leer esa página y no se guarda."))
        row = QHBoxLayout()
        self.history_button = button(t("Traer mi historial con QR"), "history", primary=True)
        self.history_button.clicked.connect(self.connect_history)
        row.addWidget(self.history_button)
        row.addStretch(1)
        self.step4.content.addLayout(row)
        body.addWidget(self.step4)

        box, layout = card(t("Mensaje al terminar cada partida"),
                           t("La cuenta secundaria te escribe por el chat de Steam, como un amigo, con lo mejor de tu "
                             "partida. Tienen que ser amigos en Steam: la primera vez te manda la solicitud (o agregala "
                             "vos desde tu cuenta)."))
        self.message_check = QCheckBox(t("Mandarme el resumen por Steam"))
        self.message_check.toggled.connect(self.message_toggled)
        layout.addWidget(self.message_check)
        row = QHBoxLayout()
        self.message_state = label("", "smallMuted", wrap=True)
        row.addWidget(self.message_state, 1)
        self.message_test = button(t("Mandarme uno de prueba"), "send")
        self.message_test.clicked.connect(self.test_message)
        row.addWidget(self.message_test)
        layout.addLayout(row)
        body.addWidget(box)

        box, layout = card(t("Partidas anteriores (opcional)"),
                           t("Los códigos solo traen partidas nuevas. Para sumar tus últimas 8 de Premier (si tienen menos de 30 días), "
                           "copiá su código desde CS2 y pegalos acá, uno por línea."))
        self.old_codes = QPlainTextEdit()
        self.old_codes.setPlaceholderText(t("CSGO-xxxxx-xxxxx-xxxxx-xxxxx-xxxxx"))
        self.old_codes.setFixedHeight(90)
        self.old_codes.setStyleSheet("QPlainTextEdit { background: #0f1014; border: 1px solid #30343c; border-radius: 8px; padding: 6px; }")
        layout.addWidget(self.old_codes)
        add = button(t("Agregar códigos"))
        add.clicked.connect(self._add_old)
        layout.addWidget(add, 0, Qt.AlignmentFlag.AlignLeft)
        body.addWidget(box)

        box, layout = card(t("FACEIT (opcional)"),
                           t("Con una clave gratis de la API de datos de FACEIT, la app trae tu nivel, tu ELO y tus partidas "
                             "de FACEIT con sus números, separadas de Premier."))
        row = QHBoxLayout()
        row.setSpacing(8)
        self.faceit_key = QLineEdit()
        self.faceit_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.faceit_key.setPlaceholderText(t("Clave de la API de datos de FACEIT (Server side)"))
        row.addWidget(self.faceit_key, 1)
        save_faceit = button(t("Guardar y traer mis partidas"), "check", primary=True)
        save_faceit.clicked.connect(self._save_faceit)
        row.addWidget(save_faceit)
        self.faceit_sync_button = button(t("Actualizar"), "scan")
        self.faceit_sync_button.clicked.connect(self.sync_faceit)
        row.addWidget(self.faceit_sync_button)
        layout.addLayout(row)
        how = QPushButton(t("Cómo conseguir la clave: developers.faceit.com › App Studio › creá una app › API keys › Server side"))
        how.setObjectName("linkButton")
        how.setCursor(Qt.CursorShape.PointingHandCursor)
        how.clicked.connect(lambda: open_url("https://developers.faceit.com/"))
        layout.addWidget(how, 0, Qt.AlignmentFlag.AlignLeft)
        self.faceit_state = label("", "smallMuted", wrap=True)
        layout.addWidget(self.faceit_state)
        body.addWidget(box)

        box, layout = card(t("Sincronización"))
        row = QHBoxLayout()
        self.sync_state = label("", "body", wrap=True)
        row.addWidget(self.sync_state, 1)
        self.sync_button = button(t("Buscar partidas ahora"), "scan", primary=True)
        self.sync_button.clicked.connect(self.sync_now)
        row.addWidget(self.sync_button)
        layout.addLayout(row)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.hide()
        layout.addWidget(self.progress)
        self.log = QVBoxLayout()
        self.log.setSpacing(3)
        layout.addLayout(self.log)
        self.codes_box = QVBoxLayout()
        layout.addLayout(self.codes_box)
        body.addWidget(box)
        body.addStretch(1)

    def _save_codes(self) -> None:
        auth = self.auth.text().strip()
        share = clean_sharecode(self.share.text())
        if not AUTHCODE_RE.match(auth):
            self.step1_msg.setText(t("El código de autenticación tiene que tener la forma AAAA-AAAAA-AAAA."))
            self.step1_msg.setStyleSheet(f"color: {BAD};")
            return
        if not share:
            self.step1_msg.setText(t("El código de partida tiene que empezar con CSGO- y tener 5 grupos."))
            self.step1_msg.setStyleSheet(f"color: {BAD};")
            return
        self.step1_msg.setStyleSheet("")
        self.save_codes.emit(auth, share)
        self.auth.clear()
        self.share.clear()

    def _save_key(self) -> None:
        key = self.key.text().strip()
        if not re.fullmatch(r"[A-Fa-f0-9]{32}", key):
            self.step2_msg.setText(t("La clave tiene 32 caracteres (números y letras de la A a la F)."))
            self.step2_msg.setStyleSheet(f"color: {BAD};")
            return
        self.step2_msg.setStyleSheet("")
        self.save_key.emit(key)
        self.key.clear()

    def _save_faceit(self) -> None:
        key = self.faceit_key.text().strip()
        if len(key) < 30:
            self.set_faceit_status(t("La clave de FACEIT es larga (unos 36 caracteres con guiones). Copiala entera."), True)
            return
        self.save_faceit.emit(key)
        self.faceit_key.clear()

    def set_faceit_status(self, text: str, error: bool = False) -> None:
        self.faceit_state.setText(text)
        self.faceit_state.setStyleSheet(f"color: {BAD};" if error else "")

    def set_faceit(self, settings, busy: bool, count: int) -> None:
        has_key = bool(settings.secret("faceit_key"))
        me = settings["faceit_profile"] or {}
        self.faceit_sync_button.setEnabled(has_key and not busy)
        if busy:
            return
        if not has_key:
            self.set_faceit_status(t("Sin clave: tus partidas de FACEIT solo entran si bajás la demo desde la sala."))
        elif me.get("nickname"):
            synced = settings["faceit_synced_at"]
            self.set_faceit_status(t("Conectado como {0} · nivel {1} · {2} ELO · {3} partidas guardadas · última vez {4}").format(
                me["nickname"], me.get("level") or "—", me.get("elo") or "—", count, short_date(synced) if synced else "—"))

    def _add_old(self) -> None:
        codes = [clean_sharecode(line) for line in self.old_codes.toPlainText().splitlines()]
        codes = [c for c in codes if c]
        if codes:
            self.add_old_codes.emit(codes)
            self.old_codes.clear()

    def set_state(self, settings, busy: bool, codes: list[dict]) -> None:
        has_codes = bool(settings.secret("auth_code") and settings["last_sharecode"])
        self.step1.set_done(has_codes, t("Guardados") if has_codes else t("Falta"))
        if has_codes:
            self.step1_msg.setText(t('Último código conocido: {0}. Si querés cambiarlos, pegá nuevos y guardá.').format(settings['last_sharecode']))
        has_key = bool(settings.secret("api_key"))
        self.step2.set_done(has_key, t("Guardada") if has_key else t("Falta"))
        if has_key:
            self.step2_msg.setText(t("Clave guardada cifrada en tu PC."))
        has_gc = bool(settings.secret("gc_token"))
        self.step3.set_done(has_gc, t('Conectada: {0}').format(settings['gc_account']) if has_gc else t("Falta"))
        self.gc_off.setVisible(has_gc)
        self.gc_button.setText(t("Volver a conectar") if has_gc else t("Conectar cuenta secundaria"))
        self.message_check.blockSignals(True)
        self.message_check.setChecked(bool(settings["steam_message"]))
        self.message_check.blockSignals(False)
        self.message_check.setEnabled(has_gc)
        self.message_test.setEnabled(has_gc and not busy)
        states = {"sent": t("El último mensaje llegó bien."),
                  "request_sent": t("Te llegó una solicitud de amistad de la cuenta secundaria: aceptala en Steam."),
                  "not_friends": t("Falta que aceptes la solicitud de amistad de la cuenta secundaria en Steam."),
                  "limited": t("La cuenta secundaria es limitada y no puede mandar solicitudes: agregala vos desde tu cuenta.")}
        self.message_state.setText(states.get(settings["message_status"], "") if has_gc
                                   else t("Primero conectá la cuenta secundaria (paso 3)."))
        synced = settings["history_synced_at"]
        self.step4.set_done(bool(synced), t('Leído el {0}').format(short_date(synced)) if synced else t("Falta"))
        self.history_button.setText(t("Actualizar historial con QR") if synced else t("Traer mi historial con QR"))
        error = settings["steam_error"]
        last = settings["steam_synced_at"]
        if busy:
            self.sync_state.setText(t("Buscando partidas en Steam"))
        elif error:
            self.sync_state.setText(t('Último intento: {0}').format(error))
            self.sync_state.setStyleSheet(f"color: {BAD};")
        else:
            self.sync_state.setStyleSheet("")
            self.sync_state.setText(t('Última búsqueda: {0}. Se repite sola cada 20 minutos con la app abierta.').format(short_date(last))
                                    if last else t("Cuando completes los pasos 1 a 3, la app busca tus partidas sola."))
        self.sync_button.setEnabled(not busy)
        self.progress.setVisible(busy)
        clear(self.codes_box)
        names = {"nueva": t("Esperando"), "reintentar": t("Reintentando"), "con_url": t("Por bajar"), "importada": t("Importada"),
                 "vencida": t("Demo vencida"), "sin_datos": t("Sin datos"), "no_es_tuya": t("No es tuya"), "error": t("Error")}
        recent = [c for c in codes if not c["code"].startswith("historial:")][-8:]
        if recent:
            self.codes_box.addWidget(label(t("ÚLTIMOS CÓDIGOS"), "cardTitle"))
        for item in reversed(recent):
            row = QHBoxLayout()
            row.addWidget(label(item["code"], "smallMuted"))
            status = names.get(item["status"], item["status"])
            row.addWidget(chip(status, "chipGood" if item["status"] == "importada" else "chipBad"
                               if item["status"] in ("vencida", "sin_datos", "error") else "chip", item.get("message") or ""))
            row.addStretch(1)
            self.codes_box.addLayout(row)

    def add_log(self, text: str) -> None:
        line = label(text, "smallMuted", wrap=True)
        self.log.insertWidget(0, line)
        while self.log.count() > 6:
            item = self.log.takeAt(self.log.count() - 1)
            if item.widget():
                item.widget().deleteLater()

    def update_view(self, view: dict) -> None:
        pass


class DemosPage(Page):
    """Demos locales (FACEIT o descargadas a mano) y aviso de fin de partida."""

    import_requested = Signal()
    scan_requested = Signal()
    add_folder_requested = Signal()
    setting_changed = Signal(str, object)
    gsi_toggled = Signal(bool)
    dismiss_gsi = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.banner, layout = card()
        row = QHBoxLayout()
        text = QVBoxLayout()
        self.banner_title = label("", "insightTitle")
        self.banner_note = label("", "muted", wrap=True)
        text.addWidget(self.banner_title)
        text.addWidget(self.banner_note)
        row.addLayout(text, 1)
        self.import_button = button(t("Importar ahora"), "import", primary=True)
        self.import_button.clicked.connect(self.import_requested)
        row.addWidget(self.import_button)
        rescan = button(t("Buscar de nuevo"), "scan")
        rescan.clicked.connect(self.scan_requested)
        row.addWidget(rescan)
        layout.addLayout(row)
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        layout.addWidget(self.progress)
        self.progress_note = label("", "smallMuted")
        layout.addWidget(self.progress_note)
        self.body.addWidget(self.banner)

        self.gsi_box = QVBoxLayout()
        self.gsi_box.setSpacing(10)
        self.body.addLayout(self.gsi_box)

        status, layout = card(t("Aviso de fin de partida"))
        self.gsi_state = label("", "body", wrap=True)
        layout.addWidget(self.gsi_state)
        self.gsi_check = QCheckBox(t("Activar el aviso (archivo oficial de Valve en la carpeta cfg de CS2)"))
        self.gsi_check.toggled.connect(self.gsi_toggled)
        layout.addWidget(self.gsi_check)
        self.background_check = QCheckBox(t("Al cerrar la ventana, seguir en la bandeja para escuchar el fin de partida"))
        self.background_check.toggled.connect(lambda v: self.setting_changed.emit("background", v))
        layout.addWidget(self.background_check)
        self.startup_check = QCheckBox(t("Abrir CS2 Stats al prender la PC (minimizado en la bandeja)"))
        self.startup_check.toggled.connect(lambda v: self.setting_changed.emit("startup", v))
        layout.addWidget(self.startup_check)
        self.auto_check = QCheckBox(t("Importar solas las demos locales nuevas, sin tocar el botón"))
        self.auto_check.toggled.connect(lambda v: self.setting_changed.emit("auto_import", v))
        layout.addWidget(self.auto_check)
        self.body.addWidget(status)

        folders, layout = card(t("Dónde busca demos locales"), t("Para FACEIT: bajá la demo desde la sala del partido y queda en Descargas"))
        self.folder_list = QVBoxLayout()
        layout.addLayout(self.folder_list)
        add = button(t("Agregar otra carpeta"), "folder")
        add.clicked.connect(self.add_folder_requested)
        layout.addWidget(add, 0, Qt.AlignmentFlag.AlignLeft)
        account_row = QHBoxLayout()
        account_row.addWidget(label(t("Cuenta que se mide:"), "body"))
        self.account = QComboBox()
        self.account.currentIndexChanged.connect(self._account_changed)
        account_row.addWidget(self.account)
        account_row.addStretch(1)
        layout.addLayout(account_row)
        self.body.addWidget(folders)

        log, layout = card(t("Últimas importaciones"))
        self.log = QVBoxLayout()
        self.log.setSpacing(3)
        layout.addLayout(self.log)
        self.body.addWidget(log)
        self.body.addStretch(1)
        self._accounts: list[int] = []

    def _account_changed(self, index: int) -> None:
        if 0 <= index < len(self._accounts) and not self.account.signalsBlocked():
            self.setting_changed.emit("steamid", self._accounts[index])

    def set_pending(self, count: int, busy: bool) -> None:
        if busy:
            self.banner_title.setText(t("Importando demos"))
            self.banner_note.setText(t("Cada demo tarda unos segundos. Podés seguir usando la app."))
        elif count:
            self.banner_title.setText(t('Encontré {0} {1} en la PC').format(count, t('demo nueva') if count == 1 else t('demos nuevas')))
            self.banner_note.setText(t("Tocá Importar y en unos segundos tenés tus números."))
        else:
            self.banner_title.setText(t("No hay demos locales nuevas"))
            self.banner_note.setText(t("La app vuelve a mirar cada 2 minutos mientras está abierta."))
        self.import_button.setEnabled(bool(count) and not busy)
        self.progress.setVisible(busy)

    def set_progress(self, done: int, total: int, text: str) -> None:
        self.progress.setMaximum(max(1, total))
        self.progress.setValue(done)
        self.progress_note.setText(text)

    def set_settings(self, settings, accounts, folders, gsi_state, gsi_on, background, startup) -> None:
        for widget, value in ((self.gsi_check, gsi_on), (self.background_check, background),
                              (self.startup_check, startup), (self.auto_check, settings["auto_import"])):
            widget.blockSignals(True)
            widget.setChecked(bool(value))
            widget.blockSignals(False)
        self.gsi_state.setText(gsi_state)
        clear(self.folder_list)
        for folder in folders:
            row = QHBoxLayout()
            glyph = QLabel()
            glyph.setPixmap(icon("folder", MUTED, 16).pixmap(16, 16))
            row.addWidget(glyph)
            row.addWidget(label(folder, "body"), 1)
            self.folder_list.addLayout(row)
        self.account.blockSignals(True)
        self.account.clear()
        current = settings["steamid"]
        known = dict(accounts)
        known.setdefault(current, str(current))
        self._accounts = list(known)
        for name in known.values():
            self.account.addItem(name)
        self.account.setCurrentIndex(self._accounts.index(current))
        self.account.blockSignals(False)

    def set_gsi_pending(self, items: list[dict]) -> None:
        clear(self.gsi_box)
        for item in items[:3]:
            frame = panel("notice")
            layout = QHBoxLayout(frame)
            layout.setContentsMargins(16, 10, 14, 10)
            text = QVBoxLayout()
            text.addWidget(label(t('Terminaste {0} {1} a {2} ({3})').format(map_label(item['map']), item['score_us'], item['score_them'], short_date(item['ended_at'])), "insightTitle"))
            text.addWidget(label(t('{0} kills, {1} muertes y {2} asistencias. Si es Premier y Steam está conectado, la demo llega sola en unos minutos. Si es FACEIT, bajala desde la sala del partido.').format(item['kills'], item['deaths'], item['assists']), "muted", wrap=True))
            layout.addLayout(text, 1)
            dismiss = button(t("Ya está"))
            dismiss.clicked.connect(lambda _=False, i=item["id"]: self.dismiss_gsi.emit(i))
            layout.addWidget(dismiss)
            self.gsi_box.addWidget(frame)

    def add_log(self, text: str, color: str = MUTED) -> None:
        line = label(text, "body", wrap=True)
        line.setStyleSheet(f"color: {color};")
        self.log.insertWidget(0, line)
        while self.log.count() > 12:
            item = self.log.takeAt(self.log.count() - 1)
            if item.widget():
                item.widget().deleteLater()

    def update_view(self, view: dict) -> None:
        pass

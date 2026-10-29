"""Control de la música en la cabecera: botón con ecualizador y un panel con la radio de mapas y el volumen."""

from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPoint, QSize, Qt, QVariantAnimation, Signal
from PySide6.QtWidgets import QCheckBox, QFrame, QHBoxLayout, QLabel, QPushButton, QSlider, QVBoxLayout

from ..i18n import t
from ..metrics import map_label
from .hud import Equalizer, map_emblem
from .theme import ACCENT, TEXT, icon, label


def track_name(map_name: str) -> str:
    return map_label(map_name) if map_name.startswith("de_") else map_name


class MusicPanel(QFrame):
    """Panel flotante: qué suena, radio de mapas (anterior, play/stop, siguiente), volumen y música en las partidas."""

    radio_toggled = Signal()
    next_track = Signal(int)          # +1 siguiente, -1 anterior
    volume_changed = Signal(int)
    auto_toggled = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent, Qt.WindowType.Popup)
        self.setObjectName("musicPanel")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedWidth(300)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)
        layout.addWidget(label(t("MÚSICA DE LOS MAPAS"), "cardTitle"))
        now = QHBoxLayout()
        now.setSpacing(10)
        self.emblem = QLabel()
        self.emblem.setFixedSize(28, 28)
        now.addWidget(self.emblem)
        text = QVBoxLayout()
        text.setSpacing(0)
        self.title = label(t("Nada sonando"), "insightTitle")
        text.addWidget(self.title)
        self.subtitle = label(t("Tocá play para escuchar la radio de mapas"), "smallMuted")
        text.addWidget(self.subtitle)
        now.addLayout(text, 1)
        self.equalizer = Equalizer(ACCENT)
        now.addWidget(self.equalizer)
        layout.addLayout(now)
        controls = QHBoxLayout()
        controls.setSpacing(8)
        controls.addStretch(1)
        self.previous = self._round_button("prev", 34, t("Mapa anterior"))
        self.previous.clicked.connect(lambda: self.next_track.emit(-1))
        self.play = self._round_button("play", 44, t("Radio de mapas: pasa por todos los mapas"))
        self.play.setObjectName("playButton")
        self.play.clicked.connect(self.radio_toggled)
        self.following = self._round_button("next", 34, t("Mapa siguiente"))
        self.following.clicked.connect(lambda: self.next_track.emit(1))
        for widget in (self.previous, self.play, self.following):
            controls.addWidget(widget)
        controls.addStretch(1)
        layout.addLayout(controls)
        volume = QHBoxLayout()
        volume.setSpacing(10)
        speaker = QLabel()
        speaker.setPixmap(icon("volume", TEXT, 18).pixmap(QSize(18, 18)))
        volume.addWidget(speaker)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 100)
        self.slider.valueChanged.connect(self._volume)
        volume.addWidget(self.slider, 1)
        self.volume_text = label("", "smallMuted")
        self.volume_text.setFixedWidth(36)
        volume.addWidget(self.volume_text)
        layout.addLayout(volume)
        self.auto = QCheckBox(t("Música al abrir una partida"))
        self.auto.toggled.connect(self.auto_toggled)
        layout.addWidget(self.auto)

    @staticmethod
    def _round_button(kind: str, size: int, tip: str) -> QPushButton:
        button = QPushButton()
        button.setObjectName("roundButton")
        button.setFixedSize(size, size)
        button.setIcon(icon(kind, TEXT, size // 2))
        button.setIconSize(QSize(size // 2, size // 2))
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setToolTip(tip)
        return button

    def _volume(self, value: int) -> None:
        self.volume_text.setText(f"{value} %")
        self.volume_changed.emit(value)

    def set_state(self, map_name: str, radio: bool, volume: int, auto: bool) -> None:
        self.slider.blockSignals(True)
        self.slider.setValue(volume)
        self.slider.blockSignals(False)
        self.volume_text.setText(f"{volume} %")
        self.auto.blockSignals(True)
        self.auto.setChecked(auto)
        self.auto.blockSignals(False)
        self.equalizer.set_active(bool(map_name))
        self.emblem.setPixmap(map_emblem(map_name, 28) if map_name.startswith("de_") else icon("music", ACCENT, 24).pixmap(24, 24))
        if map_name:
            self.title.setText(track_name(map_name))
            self.subtitle.setText(t("Radio de mapas") if radio else t("Música del mapa"))
        else:
            self.title.setText(t("Nada sonando"))
            self.subtitle.setText(t("Tocá play para escuchar la radio de mapas"))
        playing = radio and bool(map_name)
        self.play.setIcon(icon("stop" if playing else "play", "#04140f", 22))
        self.previous.setEnabled(radio)
        self.following.setEnabled(radio)

    def open_below(self, anchor) -> None:
        corner = anchor.mapToGlobal(QPoint(anchor.width() - self.width(), anchor.height() + 6))
        self.move(corner)
        self.setWindowOpacity(0.0)
        self.show()
        fade = QVariantAnimation(self)
        fade.setStartValue(0.0)
        fade.setEndValue(1.0)
        fade.setDuration(200)
        fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        fade.valueChanged.connect(self.setWindowOpacity)
        fade.start()


class MusicButton(QPushButton):
    """Botón de la cabecera: nota musical (o ecualizador y el mapa que suena)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("musicButton")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(t("Música de los mapas: radio y volumen"))
        self.setFixedHeight(32)
        row = QHBoxLayout(self)
        row.setContentsMargins(10, 0, 12, 0)
        row.setSpacing(8)
        self.note = QLabel()
        self.note.setPixmap(icon("music", "#dfe2e7", 16).pixmap(QSize(16, 16)))
        row.addWidget(self.note)
        self.equalizer = Equalizer(ACCENT)
        self.equalizer.hide()
        row.addWidget(self.equalizer)
        self.text = label(t("Radio"), "smallMuted")
        self.text.setStyleSheet("color: #dfe5ea; font-size: 12px; font-weight: 700;")
        row.addWidget(self.text)
        self.setMinimumWidth(90)

    def set_playing(self, map_name: str) -> None:
        self.note.setVisible(not map_name)
        self.equalizer.setVisible(bool(map_name))
        self.equalizer.set_active(bool(map_name))
        self.setProperty("playing", bool(map_name))
        self.style().unpolish(self)
        self.style().polish(self)
        self.text.setText(t("Sonando: {0}").format(track_name(map_name)) if map_name else t("Radio"))
        self.setMinimumWidth(self.layout().sizeHint().width())

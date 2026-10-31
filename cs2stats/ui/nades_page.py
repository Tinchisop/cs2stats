"""Pantalla de latas: los lineups conocidos de cada mapa, con clip grabado en CS2, pasos y comando de práctica."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QButtonGroup, QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea,
                               QSizePolicy, QVBoxLayout, QWidget)

from ..i18n import t
from ..assets import map_image, weapon_icon
from ..metrics import map_label
from ..nades import TYPE_COLORS, Lineup, MapGrid
from ..parser import GRID
from ..recorder import clip_meta, clip_path
from .clip_player import ClipPlayer
from .pages import card, chip, clear
from .theme import ACCENT, MUTED, TEXT, button, fmt_num, label
from .visual import svg_pixmap

NADE_ICONS = {"smoke": "smokegrenade", "flash": "flashbang", "molotov": "molotov", "he": "hegrenade"}


class MapChip(QWidget):
    clicked = Signal(str)

    def __init__(self, map_name: str, count: int, parent=None):
        super().__init__(parent)
        self.map_name, self.count, self.selected = map_name, count, False
        path = map_image(map_name)
        self.image = QPixmap(str(path)) if path else QPixmap()
        self.setFixedSize(150, 74)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, _event):  # noqa: N802
        self.clicked.emit(self.map_name)

    def paintEvent(self, _event):  # noqa: N802
        from PySide6.QtGui import QPainterPath
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        path = QPainterPath()
        path.addRoundedRect(rect, 10, 10)
        painter.setClipPath(path)
        painter.fillRect(rect, QColor("#151920"))
        if not self.image.isNull():
            scaled = self.image.scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
            painter.drawPixmap(int((self.width() - scaled.width()) / 2), int((self.height() - scaled.height()) / 2), scaled)
        painter.fillRect(rect, QColor(10, 14, 22, 120 if self.selected else 175))
        painter.setClipping(False)
        painter.setPen(QPen(QColor(ACCENT) if self.selected else QColor(255, 255, 255, 30), 2 if self.selected else 1))
        painter.drawRoundedRect(rect, 10, 10)
        painter.setPen(QColor(TEXT))
        painter.setFont(QFont("Segoe UI Variable Display", 12, QFont.Weight.Bold))
        painter.drawText(rect.adjusted(10, 6, -6, -24), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, map_label(self.map_name))
        painter.setPen(QColor("#c9ced6"))
        painter.setFont(QFont("Segoe UI", 8))
        painter.drawText(rect.adjusted(10, 0, -6, -8), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom, t("{0} latas").format(self.count))


class LineupRow(QFrame):
    clicked = Signal(str)

    def __init__(self, lineup: Lineup, selected: bool, parent=None):
        super().__init__(parent)
        self.lineup_id = lineup.id
        self.setObjectName("card")
        self.set_selected(selected)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        row = QHBoxLayout(self)
        row.setContentsMargins(12, 8, 12, 8)
        row.setSpacing(12)
        icon = QLabel()
        icon.setPixmap(svg_pixmap(weapon_icon(NADE_ICONS[lineup.type]), TYPE_COLORS[lineup.type], QSize(26, 26)))
        icon.setFixedSize(30, 30)
        row.addWidget(icon)
        text = QVBoxLayout()
        text.setSpacing(1)
        text.addWidget(label(lineup.title, "insightTitle"))
        text.addWidget(label(lineup.subtitle, "smallMuted"))
        row.addLayout(text, 1)
        if lineup.count:
            uses = (t("1 vez") if lineup.count == 1 else t("{0} veces").format(lineup.count))
            row.addWidget(chip(uses, "chip", t("Cuántas veces se tiró en tus partidas (tuyas y de los demás jugadores)")))
        if lineup.mine:
            row.addWidget(chip(t("Vos {0}").format(lineup.mine), "chipGood"))
        if clip_path(lineup.id).exists():
            row.addWidget(chip(t("Clip"), "chipWarn"))
        for child in self.findChildren(QLabel):
            child.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def set_selected(self, selected: bool) -> None:
        self.setStyleSheet(f"QFrame#card {{ border: 1px solid {ACCENT}; }}" if selected else "")

    def mousePressEvent(self, _event):  # noqa: N802
        self.clicked.emit(self.lineup_id)


class RadarView(QWidget):
    """Mapa armado con las posiciones de los jugadores en tus demos, con el tiro y la caída de la lata."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.grid: MapGrid | None = None
        self.lineup: Lineup | None = None
        self.setMinimumHeight(300)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_data(self, grid: MapGrid | None, lineup: Lineup | None) -> None:
        self.grid, self.lineup = grid, lineup
        self.update()

    def paintEvent(self, _event):  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#0f1216"))
        if not self.grid or not self.grid.cells:
            painter.setPen(QColor(MUTED))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, t("Sin datos de este mapa"))
            return
        x0, y0, x1, y1 = self.grid.bounds()
        pad = 14
        scale = min((self.width() - 2 * pad) / max(1, x1 - x0), (self.height() - 2 * pad) / max(1, y1 - y0))
        ox = (self.width() - (x1 - x0) * scale) / 2
        oy = (self.height() - (y1 - y0) * scale) / 2

        def to_screen(x: float, y: float) -> QPointF:
            return QPointF(ox + (x - x0) * scale, oy + (y1 - y) * scale)  # en el juego la Y crece hacia arriba

        zs = [c[0] for c in self.grid.cells.values()]
        z_low, z_high = min(zs), max(max(zs), min(zs) + 1)
        size = max(2.0, GRID * scale)
        painter.setPen(Qt.PenStyle.NoPen)
        for (gx, gy), (z, _place, _n) in self.grid.cells.items():
            shade = int(52 + 70 * (z - z_low) / (z_high - z_low))
            painter.setBrush(QColor(shade, shade + 6, shade + 12))
            p = to_screen(gx * GRID, (gy + 1) * GRID)
            painter.drawRect(QRectF(p.x(), p.y(), size + 0.6, size + 0.6))
        if not self.lineup:
            return
        color = QColor(TYPE_COLORS[self.lineup.type])
        for throw in self.lineup.throws:
            if not throw.get("land"):
                continue
            a, b = to_screen(*throw["pos"][:2]), to_screen(*throw["land"][:2])
            faint = QColor(color); faint.setAlpha(60)
            painter.setPen(QPen(faint, 1.2))
            painter.drawLine(a, b)
        main = self.lineup.main
        a, b = to_screen(*main["pos"][:2]), to_screen(*main["land"][:2])
        painter.setPen(QPen(color, 2.4, Qt.PenStyle.DashLine))
        painter.drawLine(a, b)
        painter.setPen(QPen(QColor("#0f1216"), 2))
        painter.setBrush(QColor(ACCENT))
        painter.drawEllipse(a, 7, 7)
        painter.setBrush(color)
        painter.drawEllipse(b, 9, 9)
        painter.setPen(QColor(TEXT))
        painter.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        painter.drawText(QRectF(a.x() + 10, a.y() - 9, 160, 18), Qt.AlignmentFlag.AlignVCenter, t("Desde acá"))
        painter.drawText(QRectF(b.x() + 12, b.y() - 9, 160, 18), Qt.AlignmentFlag.AlignVCenter, t("Cae acá"))


PHASES = {"position": ("1", t("Dónde pararte"), t("Parate acá")), "around": ("1", t("Dónde pararte"), ""),
          "aim": ("2", t("Adónde apuntar"), t("Apuntá acá")), "throw": ("3", t("Tirá"), t("Tirá desde acá")),
          "land": ("4", t("Cómo cae"), "")}
CAPTIONS = {"around": t("Así se ve el lugar donde te parás")}


def clip_phase(number: int, meta: dict) -> str:
    """En qué tramo del clip va: el .json del clip dice en qué segundos pasa cada cosa."""
    if number < 0:
        return ""
    seconds = number / meta.get("fps", 60)
    for phase in ("position", "aim", "throw"):
        span = meta.get(phase)
        if span and span[0] <= seconds < span[1]:
            # Sin lugar para caminar, el clip muestra el lugar girando desde ahí mismo.
            return "around" if phase == "position" and meta.get("position_mode") == "around" else phase
    return "land" if meta.get("throw") and seconds >= meta["throw"][1] else ""


def paint_clip_overlay(painter: QPainter, rect: QRectF, phase: str, scale: float = 1.0, technique: str = "") -> None:
    """Marca el punto (centro de la pantalla = mira), el paso del clip en la esquina y, al tirar, la técnica."""
    if not phase:
        return
    number, title, marker = PHASES[phase]
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    font = QFont("Segoe UI", max(8, int(9 * scale)), QFont.Weight.Bold)
    painter.setFont(font)
    metrics = painter.fontMetrics()
    pad = 10 * scale
    banner = f"{number}   {title}"
    box = QRectF(rect.left() + pad, rect.top() + pad, metrics.horizontalAdvance(banner) + 22 * scale, 26 * scale)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(10, 12, 16, 215))
    painter.drawRoundedRect(box, 8 * scale, 8 * scale)
    painter.setPen(QColor(ACCENT))
    painter.drawText(box.adjusted(11 * scale, 0, 0, 0), Qt.AlignmentFlag.AlignVCenter, number)
    painter.setPen(QColor(TEXT))
    painter.drawText(box.adjusted(11 * scale + metrics.horizontalAdvance(f"{number}   "), 0, 0, 0),
                     Qt.AlignmentFlag.AlignVCenter, title)
    caption = technique.capitalize() if phase == "throw" else CAPTIONS.get(phase)
    if caption:
        width = metrics.horizontalAdvance(caption) + 24 * scale
        pill = QRectF(rect.center().x() - width / 2, rect.bottom() - 48 * scale, width, 28 * scale)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(10, 12, 16, 215))
        painter.drawRoundedRect(pill, 9 * scale, 9 * scale)
        painter.setPen(QColor(TEXT))
        painter.drawText(pill, Qt.AlignmentFlag.AlignCenter, caption)
    if not marker:
        return
    center = rect.center()
    radius = 15 * scale
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(QPen(QColor(0, 0, 0, 160), 4 * scale))
    painter.drawEllipse(center, radius, radius)
    painter.setPen(QPen(QColor(ACCENT), 2.5 * scale))
    painter.drawEllipse(center, radius, radius)
    painter.setPen(QPen(QColor(0, 0, 0, 180), 1.5))
    painter.setBrush(QColor(ACCENT))
    painter.drawEllipse(center, 3.5 * scale, 3.5 * scale)
    label_box = QRectF(center.x() + radius + 7 * scale, center.y() - 12 * scale,
                       metrics.horizontalAdvance(marker) + 16 * scale, 24 * scale)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(10, 12, 16, 215))
    painter.drawRoundedRect(label_box, 8 * scale, 8 * scale)
    painter.setPen(QColor(TEXT))
    painter.drawText(label_box, Qt.AlignmentFlag.AlignCenter, marker)


class ClipDialog(QDialog):
    """El clip en pantalla completa. Se cierra con Esc o con un clic."""

    def __init__(self, lineup: Lineup, parent=None):
        super().__init__(parent)
        self.setWindowTitle(lineup.title)
        self.setStyleSheet("background: #000;")
        self.meta = clip_meta(lineup.id)
        self.technique = lineup.technique_label
        screen = QGuiApplication.primaryScreen()
        width = int(screen.size().width() * screen.devicePixelRatio()) if screen else 1920
        self.player = ClipPlayer(clip_path(lineup.id), min(width, 1920), self)
        self.player.frame_changed.connect(self.update)
        self.player.start()
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def paintEvent(self, _event):  # noqa: N802
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#000"))
        frame = self.player.image
        if frame is None:
            return
        size = frame.size().scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio)
        target = QRectF((self.width() - size.width()) / 2, (self.height() - size.height()) / 2, size.width(), size.height())
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawImage(target, frame)
        paint_clip_overlay(painter, target, clip_phase(self.player.number, self.meta), max(1.0, target.width() / 900), self.technique)
        painter.setPen(QColor(255, 255, 255, 140))
        painter.setFont(QFont("Segoe UI", 10))
        painter.drawText(self.rect().adjusted(0, 0, -18, -12), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom,
                         t("Esc o clic para salir"))

    def mousePressEvent(self, _event):  # noqa: N802
        self.close()

    def closeEvent(self, event):  # noqa: N802
        self.player.stop()
        super().closeEvent(event)


class ClipView(QLabel):
    """Reproduce el clip grabado, en loop, marcando dónde pararse, adónde apuntar y cómo tirar.
    Con un clic se ve en pantalla completa. Si no hay clip, muestra la foto del mapa."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.player: ClipPlayer | None = None
        self.meta: dict = {}
        self.lineup: Lineup | None = None
        self.setMinimumHeight(300)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet("background: #0b0d10; border-radius: 12px; color: #8b919d;")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def show_lineup(self, lineup: Lineup | None) -> bool:
        if self.player:
            self.player.stop()
            self.player.deleteLater()
            self.player = None
        self.lineup = lineup
        self.setCursor(Qt.CursorShape.ArrowCursor)
        if lineup and clip_path(lineup.id).exists():
            self.meta = clip_meta(lineup.id)
            self.clear()
            width = self.width() - 8
            self.player = ClipPlayer(clip_path(lineup.id), int(width * self.devicePixelRatioF()), self)
            self.setFixedHeight(int(width * 9 / 16) + 8)
            self.player.frame_changed.connect(self.update)
            self.player.start()
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            self.setToolTip(t("Clic para verlo en pantalla completa"))
            return True
        self.setFixedHeight(260)
        path = map_image(lineup.map) if lineup else None
        if path:
            pix = QPixmap(str(path)).scaled(self.width(), 260, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                            Qt.TransformationMode.SmoothTransformation)
            painter = QPainter(pix)
            painter.fillRect(pix.rect(), QColor(8, 10, 14, 185))
            painter.setPen(QColor(TEXT))
            painter.setFont(QFont("Segoe UI Variable Display", 13, QFont.Weight.Bold))
            painter.drawText(pix.rect(), Qt.AlignmentFlag.AlignCenter,
                             t("Este clip todavía no está grabado\nTocá \"Grabar clips de este mapa\""))
            painter.end()
            self.setPixmap(pix)
        else:
            self.setText(t("Elegí una lata de la lista"))
        return False

    def paintEvent(self, event):  # noqa: N802
        super().paintEvent(event)
        if not self.player:
            return
        painter = QPainter(self)
        inner = QRectF(self.rect()).adjusted(4, 4, -4, -4)
        if self.player.image is not None:
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            painter.drawImage(inner, self.player.image)
        paint_clip_overlay(painter, inner, clip_phase(self.player.number, self.meta), 1.0, self.lineup.technique_label)
        text = t("Pantalla completa")
        painter.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        width = painter.fontMetrics().horizontalAdvance(text) + 18
        box = QRectF(inner.right() - width - 10, inner.bottom() - 32, width, 22)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(10, 12, 16, 190))
        painter.drawRoundedRect(box, 7, 7)
        painter.setPen(QColor(TEXT))
        painter.drawText(box, Qt.AlignmentFlag.AlignCenter, text)

    def mousePressEvent(self, _event):  # noqa: N802
        if self.player and self.lineup:
            self.player.timer.stop()
            dialog = ClipDialog(self.lineup, self.window())
            dialog.showFullScreen()
            dialog.exec()
            self.player.clock.restart()
            self.player.timer.start()


class NadesPage(QWidget):
    open_match = Signal(int)
    go_to = Signal(str)
    record_requested = Signal(str, list)   # mapa, lineups

    def __init__(self, parent=None):
        super().__init__(parent)
        self.loader = None
        self.data: tuple[dict, dict] | None = None
        self.data_key = None
        self.map_name = ""
        self.kind = ""
        self.side = ""
        self.selected: str = ""
        self.rows: dict[str, LineupRow] = {}
        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 6, 28, 20)
        outer.setSpacing(12)
        self.maps_row = QHBoxLayout()
        self.maps_row.setSpacing(10)
        outer.addLayout(self.maps_row)
        filters = QHBoxLayout()
        self.kind_group = QButtonGroup(self)
        for key, text in (("", t("Todas")), ("smoke", t("Smokes")), ("flash", t("Flashes")), ("molotov", t("Molotovs")), ("he", t("HE"))):
            filters.addWidget(self._segment(text, key == "", lambda _=False, k=key: self._set("kind", k), self.kind_group))
        filters.addSpacing(16)
        self.side_group = QButtonGroup(self)
        for key, text in (("", t("Ambos lados")), ("T", "T"), (t("CT"), t("CT"))):
            filters.addWidget(self._segment(text, key == "", lambda _=False, k=key: self._set("side", k), self.side_group))
        filters.addStretch(1)
        self.record_button = button(t("Grabar clips de este mapa"), "target", primary=True)
        self.record_button.clicked.connect(self._record)
        filters.addWidget(self.record_button)
        outer.addLayout(filters)
        body = QHBoxLayout()
        body.setSpacing(14)
        self.list_area = QScrollArea()
        self.list_area.setWidgetResizable(True)
        self.list_area.setFrameShape(QFrame.Shape.NoFrame)
        holder = QWidget()
        holder.setObjectName("canvas")
        self.list_layout = QVBoxLayout(holder)
        # Sin esto, al cargar muchas latas de golpe la lista no crece y las filas quedan aplastadas.
        self.list_layout.setSizeConstraint(QVBoxLayout.SizeConstraint.SetMinimumSize)
        self.list_layout.setContentsMargins(0, 0, 6, 0)
        self.list_layout.setSpacing(8)
        self.list_area.setWidget(holder)
        body.addWidget(self.list_area, 5)
        detail_area = QScrollArea()
        detail_area.setWidgetResizable(True)
        detail_area.setFrameShape(QFrame.Shape.NoFrame)
        detail_holder = QWidget()
        detail_holder.setObjectName("canvas")
        detail = QVBoxLayout(detail_holder)
        detail.setSizeConstraint(QVBoxLayout.SizeConstraint.SetMinimumSize)
        detail.setContentsMargins(0, 0, 6, 0)
        detail.setSpacing(12)
        box, layout = card()
        self.detail_title = label("", "sectionTitle")
        self.detail_sub = label("", "muted", wrap=True)
        layout.addWidget(self.detail_title)
        layout.addWidget(self.detail_sub)
        self.clip = ClipView()
        layout.addWidget(self.clip)
        self.steps = label("", "", wrap=True)
        self.steps.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(self.steps)
        self.info = QHBoxLayout()
        layout.addLayout(self.info)
        command_row = QHBoxLayout()
        self.command = label("", "smallMuted")
        self.command.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        command_row.addWidget(self.command, 1)
        copy = button(t("Copiar comando de práctica"))
        copy.clicked.connect(lambda: QGuiApplication.clipboard().setText(self.command.text()))
        command_row.addWidget(copy)
        layout.addLayout(command_row)
        layout.addWidget(label(t("Para practicarla: en un servidor propio con sv_cheats 1, pegá el comando en la consola y "
                               "tirá con la técnica indicada."), "smallMuted", wrap=True))
        detail.addWidget(box)
        box, layout = card(t("En el mapa"), t("Las líneas finas son las veces que se tiró en tus partidas"))
        self.radar = RadarView()
        layout.addWidget(self.radar)
        detail.addWidget(box)
        detail.addStretch(1)
        detail_area.setWidget(detail_holder)
        body.addWidget(detail_area, 6)
        outer.addLayout(body, 1)

    def _segment(self, text, checked, slot, group) -> QPushButton:
        seg = QPushButton(text)
        seg.setObjectName("segment")
        seg.setCheckable(True)
        seg.setChecked(checked)
        seg.setCursor(Qt.CursorShape.PointingHandCursor)
        seg.clicked.connect(slot)
        group.addButton(seg)
        return seg

    def _set(self, attr: str, value) -> None:
        setattr(self, attr, value)
        self.selected = ""
        self._draw()

    def update_view(self, view: dict) -> None:
        key = len(view["all_matches"])
        if self.data is None or key != self.data_key:
            self.data = None
            self.data_key = key
        if self.isVisible():
            self.ensure_loaded()

    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        self.ensure_loaded()

    def ensure_loaded(self) -> None:
        if self.data is None and self.loader:
            self.data = self.loader()
            lineups = self.data[0]
            if lineups and self.map_name not in lineups:
                self.map_name = self._maps_by_use()[0]
            self._draw_maps()
            self._draw()

    def _maps_by_use(self) -> list[str]:
        """Primero los mapas donde más se usaron estas latas en tus partidas."""
        lineups = self.data[0] if self.data else {}
        return sorted(lineups, key=lambda m: (-sum(l.count for l in lineups[m]), m))

    def _draw_maps(self) -> None:
        clear(self.maps_row)
        lineups = self.data[0] if self.data else {}
        for name in self._maps_by_use():
            chip_widget = MapChip(name, len(lineups[name]))
            chip_widget.selected = name == self.map_name
            chip_widget.clicked.connect(self._pick_map)
            self.maps_row.addWidget(chip_widget)
        self.maps_row.addStretch(1)

    def _pick_map(self, name: str) -> None:
        self.map_name = name
        self.selected = ""
        self._draw_maps()
        self._draw()

    def visible_lineups(self) -> list[Lineup]:
        if not self.data:
            return []
        items = self.data[0].get(self.map_name, [])
        return [l for l in items if (not self.kind or l.type == self.kind) and (not self.side or l.side == self.side)]

    def _draw(self) -> None:
        clear(self.list_layout)
        items = self.visible_lineups()
        if not self.data or not self.data[0]:
            self.list_layout.addWidget(label(t("No se encontró la lista de latas."), "muted", wrap=True))
        elif not items:
            self.list_layout.addWidget(label(t("No hay latas con este filtro."), "muted"))
        if items and not any(l.id == self.selected for l in items):
            self.selected = items[0].id
        self.rows = {}
        for lineup in items[:150]:
            row = LineupRow(lineup, lineup.id == self.selected)
            row.clicked.connect(self._select)
            self.list_layout.addWidget(row)
            self.rows[lineup.id] = row
        self.list_layout.addStretch(1)
        self.record_button.setEnabled(bool(items))
        self._show_detail(next((l for l in items if l.id == self.selected), None))

    def _select(self, lineup_id: str) -> None:
        """Solo cambia el resaltado y el detalle: rearmar toda la lista en cada clic se notaba."""
        if lineup_id == self.selected:
            return
        if self.selected in self.rows:
            self.rows[self.selected].set_selected(False)
        self.selected = lineup_id
        self.rows[lineup_id].set_selected(True)
        self._show_detail(next((l for l in self.visible_lineups() if l.id == lineup_id), None))

    def _show_detail(self, lineup: Lineup | None) -> None:
        grid = self.data[1].get(self.map_name) if self.data else None
        self.radar.set_data(grid, lineup)
        clear(self.info)
        if not lineup:
            self.detail_title.setText(t("Elegí una lata"))
            self.detail_sub.setText("")
            self.steps.setText("")
            self.command.setText("")
            self.clip.show_lineup(None)
            return
        self.detail_title.setText(f"{lineup.title} · {map_label(lineup.map)}")
        self.detail_sub.setText(lineup.subtitle)
        self.clip.show_lineup(lineup)
        self.steps.setText("".join(
            f"<p style='margin:4px 0'><span style='color:{ACCENT}; font-weight:700'>{n}.</span>&nbsp; {step}</p>"
            for n, step in enumerate(lineup.step_list, start=1)))
        for title, value in ((t("TÉCNICA"), lineup.technique_label.capitalize()), (t("LADO"), lineup.side or t("Ambos")),
                             (t("EN TUS PARTIDAS"), (t("1 vez") if lineup.count == 1 else t("{0} veces").format(lineup.count))),
                             (t("TUYAS"), str(lineup.mine)),
                             (t("TARDA EN CAER"), f"{fmt_num(lineup.flight, 1)} s" if lineup.flight else "—")):
            col = QVBoxLayout()
            col.setSpacing(0)
            col.addWidget(label(title, "cardTitle"))
            col.addWidget(label(value, "midValue"))
            self.info.addLayout(col)
        self.command.setText(lineup.practice_command)

    def _record(self) -> None:
        items = self.visible_lineups()
        if items:
            self.clip.show_lineup(None)   # suelta el archivo: un clip abierto no se puede reemplazar
            self.record_requested.emit(self.map_name, [l for l in items if not clip_path(l.id).exists()][:40])

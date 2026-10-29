"""Animaciones: entrada de páginas y tarjetas (aparecen subiendo un poco), números que cuentan hasta su valor,
brillo al pasar el mouse y gráficos que se dibujan solos.

Duraciones cortas y con frenado al final (OutCubic): la animación acompaña, no hace esperar."""

from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QEvent, QObject, QTimer, QVariantAnimation
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QGraphicsDropShadowEffect, QGraphicsEffect, QLabel, QWidget

ENTER_MS = 320        # páginas y tarjetas
CHART_MS = 850        # gráficos que crecen
COUNT_MS = 900        # números que cuentan
HOVER_MS = 180        # brillo al pasar el mouse
STAGGER_MS = 45       # diferencia entre una tarjeta y la siguiente
RISE = 18             # píxeles que sube al aparecer


class Reveal(QGraphicsEffect):
    """Dibuja el widget con transparencia, un poco más abajo y apenas más chico según el avance
    (0 = oculto, 1 = en su lugar)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.progress = 0.0

    def set_progress(self, value: float) -> None:
        self.progress = value
        self.update()

    def draw(self, painter: QPainter) -> None:  # noqa: D401
        painter.save()
        painter.setOpacity(painter.opacity() * min(1.0, self.progress * 1.4))
        rect = self.sourceBoundingRect()
        scale = 0.97 + 0.03 * self.progress
        center = rect.center()
        painter.translate(center.x(), center.y() + (1 - self.progress) * RISE)
        painter.scale(scale, scale)
        painter.translate(-center.x(), -center.y())
        self.drawSource(painter)
        painter.restore()


def reveal(widget: QWidget, delay: int = 0, duration: int = ENTER_MS, then=None) -> None:
    """Hace aparecer un widget. Al terminar le saca el efecto y llama a then (o a widget.after_reveal),
    por ejemplo para devolverle su brillo."""
    effect = Reveal(widget)
    effect.set_progress(0.0)
    widget.setGraphicsEffect(effect)
    animation = QVariantAnimation(effect)
    animation.setStartValue(0.0)
    animation.setEndValue(1.0)
    animation.setDuration(duration)
    animation.setEasingCurve(QEasingCurve.Type.OutCubic)
    animation.valueChanged.connect(effect.set_progress)

    def finish() -> None:
        if widget.graphicsEffect() is effect:
            widget.setGraphicsEffect(None)
            after = then or getattr(widget, "after_reveal", None)
            if after:
                after(widget)
    animation.finished.connect(finish)
    if delay:
        QTimer.singleShot(delay, animation.start)
    else:
        animation.start()


def reveal_children(widgets: list[QWidget], then=None, stagger: int = STAGGER_MS) -> None:
    """Tarjetas que aparecen una detrás de otra."""
    for index, widget in enumerate(widgets):
        reveal(widget, index * stagger, then=then)


def cascade(layout, limit: int = 16) -> None:
    """Hace entrar en cascada lo que hay en una página: tarjetas sueltas y las que están dentro de filas o grillas."""
    widgets: list[QWidget] = []

    def collect(lay, depth: int) -> None:
        for index in range(lay.count()):
            item = lay.itemAt(index)
            widget = item.widget()
            if widget is not None:
                if not widget.isHidden():
                    widgets.append(widget)
            elif item.layout() is not None and depth < 2:
                collect(item.layout(), depth + 1)
    collect(layout, 0)
    reveal_children(widgets[:limit])
    for widget in widgets[limit:]:
        reveal(widget, limit * STAGGER_MS)


def glow_effect(widget: QWidget, color: str, blur: float, alpha: int) -> QGraphicsDropShadowEffect:
    effect = QGraphicsDropShadowEffect(widget)
    shade = QColor(color)
    shade.setAlpha(alpha)
    effect.setColor(shade)
    effect.setBlurRadius(blur)
    effect.setOffset(0, 0)
    return effect


class HoverGlow(QObject):
    """Al pasar el mouse, la tarjeta se ilumina con un halo del color dado (y se apaga al salir)."""

    def __init__(self, widget: QWidget, color: str, blur: int = 30, alpha: int = 120):
        super().__init__(widget)
        self.widget, self.color, self.blur, self.alpha = widget, color, blur, alpha
        self.effect: QGraphicsDropShadowEffect | None = None
        self.animation = QVariantAnimation(self)
        self.animation.setDuration(HOVER_MS)
        self.animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.animation.valueChanged.connect(self._step)
        self.animation.finished.connect(self._done)
        self.value = 0.0
        widget.installEventFilter(self)

    def eventFilter(self, obj, event):  # noqa: N802
        if event.type() == QEvent.Type.Enter:
            self._go(1.0)
        elif event.type() == QEvent.Type.Leave:
            self._go(0.0)
        return False

    def _go(self, target: float) -> None:
        current = self.widget.graphicsEffect()
        if current is not None and current is not self.effect:
            return   # está entrando (Reveal) o tiene su propio brillo fijo
        if self.effect is None or current is None:
            self.effect = glow_effect(self.widget, self.color, 0, 0)
            self.widget.setGraphicsEffect(self.effect)
        self.animation.stop()
        self.animation.setStartValue(self.value)
        self.animation.setEndValue(target)
        self.animation.start()

    def _step(self, value: float) -> None:
        self.value = value
        if self.effect is not None and self.widget.graphicsEffect() is self.effect:
            shade = QColor(self.color)
            shade.setAlpha(int(self.alpha * value))
            self.effect.setColor(shade)
            self.effect.setBlurRadius(self.blur * value)

    def _done(self) -> None:
        if self.value <= 0.01 and self.widget.graphicsEffect() is self.effect:
            self.widget.setGraphicsEffect(None)
            self.effect = None


def hover_glow(widget: QWidget, color: str, blur: int = 30, alpha: int = 120) -> QWidget:
    HoverGlow(widget, color, blur, alpha)
    return widget


class CountUp(QLabel):
    """Número que cuenta desde cero hasta su valor cada vez que aparece en pantalla."""

    def __init__(self, value: float | None, fmt, name: str = "", parent=None):
        super().__init__(parent)
        self.value, self.fmt = value, fmt
        if name:
            self.setObjectName(name)
        self.animation = QVariantAnimation(self)
        self.animation.setDuration(COUNT_MS)
        self.animation.setEasingCurve(QEasingCurve.Type.OutExpo)
        self.animation.valueChanged.connect(lambda v: self.setText(self.fmt(v)))
        self.setText(fmt(value))

    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        if self.value is None or not isinstance(self.value, (int, float)):
            return
        self.animation.stop()
        self.animation.setStartValue(0.0)
        self.animation.setEndValue(float(self.value))
        self.animation.start()


class Growing:
    """Mezcla para gráficos pintados a mano: self.grow va de 0 a 1 cada vez que el gráfico se muestra."""

    grow = 1.0
    grow_ms = CHART_MS
    grow_delay = 0

    def start_grow(self) -> None:
        animation = getattr(self, "_grow_animation", None)
        if animation is None:
            animation = QVariantAnimation(self)
            animation.setStartValue(0.0)
            animation.setEndValue(1.0)
            animation.setEasingCurve(QEasingCurve.Type.OutCubic)
            animation.valueChanged.connect(self._grow_step)
            self._grow_animation = animation
        animation.stop()
        animation.setDuration(self.grow_ms)
        self.grow = 0.0
        self.update()
        if self.grow_delay:
            QTimer.singleShot(self.grow_delay, animation.start)
        else:
            animation.start()

    def _grow_step(self, value: float) -> None:
        self.grow = value
        self.update()

    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        self.start_grow()


class Hovering:
    """Mezcla para piezas pintadas a mano con varias partes: self.hover[i] va de 0 a 1 en la parte bajo el mouse."""

    def init_hover(self) -> None:
        self.hover: dict[int, float] = {}
        self.hover_target: int | None = None
        self._hover_timer = QTimer(self)
        self._hover_timer.setInterval(16)
        self._hover_timer.timeout.connect(self._hover_tick)

    def set_hover(self, index: int | None) -> None:
        if index != self.hover_target:
            self.hover_target = index
            self._hover_timer.start()

    def _hover_tick(self) -> None:
        busy = False
        keys = set(self.hover) | ({self.hover_target} if self.hover_target is not None else set())
        for key in keys:
            target = 1.0 if key == self.hover_target else 0.0
            value = self.hover.get(key, 0.0)
            value += (target - value) * 0.28
            if abs(target - value) < 0.01:
                value = target
            else:
                busy = True
            if value == 0.0:
                self.hover.pop(key, None)
            else:
                self.hover[key] = value
        self.update()
        if not busy:
            self._hover_timer.stop()


def ease(value: float) -> float:
    """Frenado suave (OutCubic) para avances que se calculan a mano."""
    value = min(1.0, max(0.0, value))
    return 1 - (1 - value) ** 3


def stagger(progress: float, index: int, count: int, spread: float = 0.5) -> float:
    """Avance de la parte index de count cuando el total va en progress: cada una arranca un poco después."""
    start = spread * index / max(1, count)
    return ease((progress - start) / max(0.01, 1 - spread))

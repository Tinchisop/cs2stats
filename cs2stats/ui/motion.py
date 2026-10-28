"""Animaciones: entrada de páginas y tarjetas (aparecen subiendo un poco) y gráficos que se dibujan solos.

Duraciones cortas y con frenado al final (OutCubic): la animación acompaña, no hace esperar."""

from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPointF, QTimer, QVariantAnimation
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QGraphicsEffect, QWidget

ENTER_MS = 260        # páginas y tarjetas
CHART_MS = 750        # gráficos que crecen
STAGGER_MS = 55       # diferencia entre una tarjeta y la siguiente
RISE = 14             # píxeles que sube al aparecer


class Reveal(QGraphicsEffect):
    """Dibuja el widget con transparencia y un poco más abajo según el avance (0 = oculto, 1 = en su lugar)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.progress = 0.0

    def set_progress(self, value: float) -> None:
        self.progress = value
        self.update()

    def draw(self, painter: QPainter) -> None:  # noqa: D401
        painter.save()
        painter.setOpacity(painter.opacity() * self.progress)
        painter.translate(QPointF(0, (1 - self.progress) * RISE))
        self.drawSource(painter)
        painter.restore()


def reveal(widget: QWidget, delay: int = 0, duration: int = ENTER_MS, then=None) -> None:
    """Hace aparecer un widget. Al terminar le saca el efecto (y llama a then, por ejemplo para devolverle su brillo)."""
    effect = Reveal(widget)
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
            if then:
                then(widget)
    animation.finished.connect(finish)
    if delay:
        QTimer.singleShot(delay, animation.start)
    else:
        animation.start()


def reveal_children(widgets: list[QWidget], then=None) -> None:
    """Tarjetas que aparecen una detrás de otra."""
    for index, widget in enumerate(widgets):
        reveal(widget, index * STAGGER_MS, then=then)


class Growing:
    """Mezcla para gráficos pintados a mano: self.grow va de 0 a 1 cada vez que el gráfico se muestra."""

    grow = 1.0
    grow_ms = CHART_MS

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
        animation.start()

    def _grow_step(self, value: float) -> None:
        self.grow = value
        self.update()

    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        self.start_grow()

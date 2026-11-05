"""Piezas que se acomodan al ancho de la ventana: grillas que pasan de 4 a 2 columnas y filas que se apilan.

En pantallas chicas (o con Windows al 125 o 150 %) la ventana puede quedar más angosta que el contenido; con estas
piezas el contenido se reacomoda en vez de cortarse a la derecha. Cada una informa como mínimo el ancho de su forma
más angosta, así la página puede achicarse y recién ahí se reacomoda."""

from __future__ import annotations

from PySide6.QtCore import QSize
from PySide6.QtWidgets import QBoxLayout, QGridLayout, QLayout, QWidget


class FlowGrid(QWidget):
    """Grilla de tarjetas del mismo tipo: tantas columnas como entren (hasta `columns`), el resto baja a otra fila."""

    is_container = True   # al entrar una página, se animan sus tarjetas (no la grilla entera)

    def __init__(self, columns: int, spacing: int = 12, parent=None):
        super().__init__(parent)
        self.max_columns = max(1, columns)
        self.columns = self.max_columns
        self.items: list[QWidget] = []
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(spacing)

    def add(self, widget: QWidget) -> None:
        self.items.append(widget)
        self._place()

    def clear(self) -> None:
        for widget in self.items:
            self.grid.removeWidget(widget)
            widget.deleteLater()
        self.items = []

    def _item_width(self) -> int:
        return max([w.minimumSizeHint().width() for w in self.items] + [w.minimumWidth() for w in self.items] + [1])

    def _fit(self, width: int) -> int:
        """Cuántas columnas usar en este ancho: las que entran, pero sin dejar una tarjeta sola abajo
        (4 tarjetas van 4 o 2 por fila, nunca 3 y 1)."""
        gap = self.grid.horizontalSpacing()
        count = len(self.items) or 1
        widths = [max(w.minimumSizeHint().width(), w.minimumWidth()) for w in self.items] or [1]
        for columns in range(min(self.max_columns, count), 0, -1):
            # Lo mismo que mide la grilla: cada columna necesita lo de su tarjeta más ancha.
            needed = sum(max(widths[col::columns]) for col in range(columns)) + gap * (columns - 1)
            rest = count % columns
            if needed <= width and (rest == 0 or rest >= columns - 1):
                return columns
        return 1

    def _place(self) -> None:
        for widget in self.items:
            self.grid.removeWidget(widget)
        for index, widget in enumerate(self.items):
            self.grid.addWidget(widget, index // self.columns, index % self.columns)
        for col in range(self.max_columns):
            self.grid.setColumnStretch(col, 1 if col < self.columns else 0)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(self._item_width(), super().minimumSizeHint().height())

    def resizeEvent(self, event):  # noqa: N802
        columns = self._fit(event.size().width())
        if columns != self.columns:
            self.columns = columns
            self._place()
        super().resizeEvent(event)


class StackRow(QWidget):
    """Fila con dos o tres partes: una al lado de la otra si entran, una debajo de la otra si no."""

    is_container = True

    def __init__(self, spacing: int = 16, parent=None):
        super().__init__(parent)
        self.box = QBoxLayout(QBoxLayout.Direction.LeftToRight, self)
        self.box.setContentsMargins(0, 0, 0, 0)
        self.box.setSpacing(spacing)

    def addWidget(self, widget: QWidget, stretch: int = 0, alignment=None) -> None:  # noqa: N802
        if alignment is None:
            self.box.addWidget(widget, stretch)
        else:
            self.box.addWidget(widget, stretch, alignment)

    def addLayout(self, layout: QLayout, stretch: int = 0) -> None:  # noqa: N802
        self.box.addLayout(layout, stretch)

    def _widths(self) -> list[int]:
        return [self.box.itemAt(i).minimumSize().width() for i in range(self.box.count())]

    def side_by_side_width(self) -> int:
        widths = self._widths()
        return sum(widths) + self.box.spacing() * max(0, len(widths) - 1)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(max(self._widths() + [0]), super().minimumSizeHint().height())

    def resizeEvent(self, event):  # noqa: N802
        wide = event.size().width() >= self.side_by_side_width()
        direction = QBoxLayout.Direction.LeftToRight if wide else QBoxLayout.Direction.TopToBottom
        if self.box.direction() != direction:
            self.box.setDirection(direction)
        super().resizeEvent(event)

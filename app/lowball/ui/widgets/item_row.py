"""A row in the trade pane.

Carries a 2px rarity-coloured left edge, which is the fastest thing on screen
to read: the user already decodes SkyBlock rarity colours without thinking.

Selection is a brass left edge and a raised background, never a border. A
border would add a shape to a layout that is otherwise made of hairlines.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ...money import format_coins, format_coins_exact
from ...parsing.signature import ItemSignature
from ..theme import (
    ACCENT,
    GRID,
    INK_DIM,
    SIZE_BODY,
    SIZE_MICRO,
    SURFACE_HIGH,
    WEIGHT_EMPHASIS,
    numeric_font,
    rarity_colour,
    ui_font,
)
from .primitives import ElidedLabel

EDGE_WIDTH = 2


class TradeItemRow(QWidget):
    """One item the customer is offering."""

    clicked = Signal(object)

    def __init__(
        self, sig: ItemSignature, *, duplicates: int = 1, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.sig = sig
        self.duplicates = duplicates
        self._selected = False
        self._hovered = False
        self._value: int | None = None
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(GRID * 3, GRID * 2, GRID * 3, GRID * 2)
        outer.setSpacing(GRID * 2)

        text = QVBoxLayout()
        text.setContentsMargins(0, 0, 0, 0)
        text.setSpacing(2)

        name = sig.display_name or sig.tag.replace("_", " ").title()
        if duplicates > 1:
            name = f"{name} x{duplicates}"
        # Assigned before the label exists: a resize can arrive during
        # construction, and an exception inside a Qt event handler takes the
        # whole process down without a traceback.
        self._full_name = name

        self.name_label = ElidedLabel(name)
        self.name_label.setFont(ui_font(SIZE_BODY, WEIGHT_EMPHASIS))
        self.name_label.setStyleSheet(f"color: {rarity_colour(sig.rarity)};")

        self.value_label = QLabel("Valuing")
        self.value_label.setFont(numeric_font(SIZE_BODY))
        self.value_label.setStyleSheet(f"color: {INK_DIM};")

        text.addWidget(self.name_label)
        text.addWidget(self.value_label)
        outer.addLayout(text, 1)

        chips = sig.summary()
        if chips:
            self.chips_label = QLabel(chips[0] if len(chips) == 1 else f"{len(chips)} mods")
            self.chips_label.setFont(ui_font(SIZE_MICRO))
            self.chips_label.setStyleSheet(f"color: {INK_DIM};")
            self.chips_label.setToolTip("\n".join(chips))
            outer.addWidget(self.chips_label, 0, Qt.AlignmentFlag.AlignTop)

    def set_value(self, coins: int | None, *, pending: bool = False) -> None:
        self._value = coins
        if pending:
            self.value_label.setText("Valuing")
            self.value_label.setToolTip("")
            return
        if coins is None:
            self.value_label.setText("No price")
            return
        total = coins * max(1, self.duplicates)
        self.value_label.setText(format_coins(total))
        self.value_label.setToolTip(format_coins_exact(total))

    def set_selected(self, selected: bool) -> None:
        if self._selected == selected:
            return
        self._selected = selected
        self.update()

    @property
    def is_selected(self) -> bool:
        return self._selected

    def enterEvent(self, event) -> None:  # noqa: N802 - Qt naming
        self._hovered = True
        self.update()

    def leaveEvent(self, event) -> None:  # noqa: N802 - Qt naming
        self._hovered = False
        self.update()

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt naming
        painter = QPainter(self)
        if self._selected:
            painter.fillRect(self.rect(), QColor(SURFACE_HIGH))
        elif self._hovered:
            # The only hover effect anywhere: one step of background value.
            painter.fillRect(self.rect(), QColor(SURFACE_HIGH).darker(108))
        edge = QColor(ACCENT) if self._selected else QColor(rarity_colour(self.sig.rarity))
        painter.fillRect(0, 0, EDGE_WIDTH, self.height(), edge)
        painter.end()

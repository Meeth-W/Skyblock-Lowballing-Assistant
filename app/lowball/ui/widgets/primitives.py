"""Small building blocks.

Everything structural in this app is a hairline, a background value shift, or
4px of space.  These are those three things, so no view has to reinvent them.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..theme import (
    ACCENT,
    GRID,
    INK_DIM,
    SIZE_MICRO,
    SIZE_SECTION,
    WEIGHT_EMPHASIS,
    numeric_font,
    ui_font,
)


class ElidedLabel(QLabel):
    """A label that shortens its text instead of overflowing.

    Eliding happens at paint time on purpose. Doing it in ``resizeEvent`` by
    calling ``setText`` re-triggers layout, which resizes the label, which
    fires ``resizeEvent`` again -- an unbounded recursion that takes the
    process down with no traceback, because it happens inside a Qt event
    handler.
    """

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self._text = text
        self.setMinimumWidth(0)
        self.setToolTip(text)

    def setText(self, text: str) -> None:  # noqa: N802 - Qt naming
        self._text = text
        self.setToolTip(text)
        super().setText(text)

    def fullText(self) -> str:  # noqa: N802 - Qt naming
        return self._text

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt naming
        painter = QPainter(self)
        metrics = painter.fontMetrics()
        elided = metrics.elidedText(self._text, Qt.TextElideMode.ElideRight, self.width())
        painter.setPen(self.palette().color(self.foregroundRole()))
        painter.drawText(self.rect(), int(self.alignment()), elided)
        painter.end()


class Hairline(QFrame):
    """The only separator device in the app."""

    def __init__(self, horizontal: bool = True, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("hairline" if horizontal else "vhairline")
        if horizontal:
            self.setFixedHeight(1)
            self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        else:
            self.setFixedWidth(1)
            self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)


class Panel(QFrame):
    """A background value shift with a vertical layout.  Not a card."""

    def __init__(self, parent: QWidget | None = None, *, padding: int = GRID * 4) -> None:
        super().__init__(parent)
        self.setObjectName("panel")
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(padding, padding, padding, padding)
        self.body.setSpacing(GRID * 2)

    def add(self, widget: QWidget, stretch: int = 0) -> QWidget:
        self.body.addWidget(widget, stretch)
        return widget

    def add_hairline(self) -> Hairline:
        line = Hairline()
        self.body.addWidget(line)
        return line

    def add_stretch(self) -> None:
        self.body.addStretch(1)


class SectionLabel(QLabel):
    """A quiet label above a group.  Sentence case, never tracked-out caps."""

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setObjectName("sectionLabel")
        self.setFont(ui_font(SIZE_MICRO, WEIGHT_EMPHASIS))


class Heading(QLabel):
    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setFont(ui_font(SIZE_SECTION, WEIGHT_EMPHASIS))


class DimLabel(QLabel):
    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setObjectName("dim")


class NumericLabel(QLabel):
    """Digits that have to line up with the digits above and below them."""

    def __init__(
        self, text: str = "", size: int = 13, parent: QWidget | None = None
    ) -> None:
        super().__init__(text, parent)
        self.setObjectName("numeric")
        self.setFont(numeric_font(size))
        self.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)


class KeyValueRow(QWidget):
    """A label on the left, a figure on the right, aligned across rows."""

    def __init__(
        self,
        label: str,
        value: str = "",
        *,
        numeric: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(GRID * 2)
        self.label = QLabel(label)
        self.label.setObjectName("dim")
        self.value = NumericLabel(value) if numeric else QLabel(value)
        if not numeric:
            self.value.setAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
        row.addWidget(self.label)
        row.addStretch(1)
        row.addWidget(self.value)

    def set_value(self, text: str, *, tooltip: str | None = None) -> None:
        self.value.setText(text)
        if tooltip:
            self.value.setToolTip(tooltip)

    def set_note(self, text: str) -> None:
        """A quiet trailing note, such as a comparable count."""
        self.label.setText(f"{self.label.text()}")
        self.value.setToolTip(text)


def coloured(widget: QLabel, colour: str) -> QLabel:
    widget.setStyleSheet(f"color: {colour};")
    return widget


def accent(widget: QLabel) -> QLabel:
    return coloured(widget, ACCENT)


def dim(widget: QLabel) -> QLabel:
    return coloured(widget, INK_DIM)

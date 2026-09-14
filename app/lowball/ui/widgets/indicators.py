"""Confidence dots and rule badges.

Both exist so a number can never appear without the reason for it appearing
beside it.  The dots say how much of the estimate is observation; the badge
says which rule moved it.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QLabel, QSizePolicy, QWidget

from ..theme import ACCENT, GRID, HAIRLINE, INK_DIM, RADIUS, SIZE_MICRO, ui_font

DOT_DIAMETER = 6
DOT_GAP = 4
DOT_COUNT = 4


class ConfidenceDots(QWidget):
    """Four dots, filled in brass.

    Always shown, never hidden.  A confidently wrong number on a 500M item is
    how a lowballer goes broke, so low confidence has to be unmistakable at a
    glance rather than something the user has to go looking for.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._filled = 0
        self._reasons: tuple[str, ...] = ()
        self.setFixedSize(
            DOT_COUNT * DOT_DIAMETER + (DOT_COUNT - 1) * DOT_GAP, DOT_DIAMETER + 2
        )
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def set_confidence(self, filled: int, reasons: tuple[str, ...] = ()) -> None:
        self._filled = max(0, min(DOT_COUNT, int(filled)))
        self._reasons = reasons
        self.setToolTip("\n".join(reasons) if reasons else "Confidence in this estimate")
        self.update()

    @property
    def filled(self) -> int:
        return self._filled

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt naming
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        for index in range(DOT_COUNT):
            x = index * (DOT_DIAMETER + DOT_GAP)
            rect = QRectF(x, 1, DOT_DIAMETER, DOT_DIAMETER)
            if index < self._filled:
                painter.setBrush(QColor(ACCENT))
                painter.setPen(Qt.PenStyle.NoPen)
            else:
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(QPen(QColor(HAIRLINE), 1))
            painter.drawEllipse(rect)
        painter.end()


class RuleBadge(QLabel):
    """A small brass-outlined pill naming the rule that moved a number.

    Sits inline beside the figure it affected.  Hovering says what it changed.
    A silent override is worse than no rule, so this is not optional chrome.
    """

    def __init__(self, name: str, detail: str = "", parent: QWidget | None = None) -> None:
        super().__init__(name, parent)
        self.setFont(ui_font(SIZE_MICRO))
        self.setToolTip(detail or name)
        self.setStyleSheet(
            f"color: {ACCENT};"
            f" border: 1px solid {ACCENT};"
            f" border-radius: {RADIUS}px;"
            f" padding: 1px {GRID}px;"
            " background: transparent;"
        )
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)


class StaleBadge(QLabel):
    """Marks a price that came from cache after the network failed."""

    def __init__(self, text: str = "Stale", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setFont(ui_font(SIZE_MICRO))
        self.setToolTip("Shown from cache; the last refresh did not reach Coflnet")
        self.setStyleSheet(
            f"color: {INK_DIM};"
            f" border: 1px solid {HAIRLINE};"
            f" border-radius: {RADIUS}px;"
            f" padding: 1px {GRID}px;"
        )
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)


class ExplorationBadge(QLabel):
    """Marks an offer chosen at random rather than by the model."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Exploring", parent)
        self.setFont(ui_font(SIZE_MICRO))
        self.setToolTip(
            "A randomised percentage, so the acceptance model keeps learning\n"
            "instead of calcifying around whatever was tried first"
        )
        self.setStyleSheet(
            f"color: {ACCENT};"
            f" border: 1px dashed {ACCENT};"
            f" border-radius: {RADIUS}px;"
            f" padding: 1px {GRID}px;"
        )
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

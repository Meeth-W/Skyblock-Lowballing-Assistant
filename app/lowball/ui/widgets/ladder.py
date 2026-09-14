"""The offer ladder.

Clicking a rung expands it in place into the three controls from Part 8.1.
The row grows downward and nothing else moves: no modal, no dialog, nothing
that takes the numbers off screen while the customer is still talking.

    OFFER_PENDING
      [Confirm sale]   -> confirmed at the offered price
      [Rejected]       -> logged as rejected, back to idle
      [Bought at ___]  -> confirmed at a price the user types

Clicking a different rung while one is pending logs the pending one as
rejected on the way past. That is how a negotiation chain records itself
without anyone having to remember to record it.
"""

from __future__ import annotations

from PySide6.QtCore import (
    QEasingCurve,
    QPropertyAnimation,
    Qt,
    Signal,
)
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...money import format_coins, format_coins_exact, format_signed, parse_coins
from ...pricing.offer import OfferLadder, Rung
from ..theme import (
    ACCENT,
    GRID,
    INK_DIM,
    LOSS,
    MOTION_MS,
    SIZE_BODY,
    SIZE_EMPHASIS,
    SIZE_MICRO,
    SURFACE_HIGH,
    WEIGHT_BODY,
    WEIGHT_EMPHASIS,
    numeric_font,
    ui_font,
)
from .indicators import ExplorationBadge, RuleBadge
from .primitives import Hairline

COLLAPSED_HEIGHT = 26
CONTROL_HEIGHT = 38


class LadderRow(QWidget):
    """One rung, collapsed or expanded."""

    activated = Signal(object)
    confirmed = Signal(object, int)
    rejected = Signal(object)
    countered = Signal(object, int)

    def __init__(self, rung: Rung, *, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.rung = rung
        self._expanded = False
        self._hovered = False
        self._recommended = False
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.header = QWidget()
        header = QHBoxLayout(self.header)
        header.setContentsMargins(GRID * 3, GRID, GRID * 3, GRID)
        header.setSpacing(GRID * 2)

        self.pct_label = QLabel(rung.pct_label)
        self.pct_label.setFont(numeric_font(SIZE_BODY))
        self.pct_label.setFixedWidth(58)
        self.pct_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )

        self.coins_label = QLabel(format_coins(rung.coins))
        self.coins_label.setFont(numeric_font(SIZE_BODY))
        self.coins_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self.coins_label.setToolTip(format_coins_exact(rung.coins))

        header.addWidget(self.pct_label)
        header.addStretch(1)
        if rung.rule_name:
            header.addWidget(RuleBadge(rung.rule_name, f"Set this rung to {rung.pct_label}"))
        header.addWidget(self.coins_label)
        root.addWidget(self.header)

        self.controls = self._build_controls()
        self.controls.setMaximumHeight(0)
        self.controls.setVisible(False)
        root.addWidget(self.controls)

        self._animation = QPropertyAnimation(self.controls, b"maximumHeight", self)
        self._animation.setDuration(MOTION_MS)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)

        if not rung.meets_floor:
            self.coins_label.setStyleSheet(f"color: {INK_DIM};")
            self.setToolTip(
                f"Expected profit {format_signed(rung.expected_profit)};"
                " below the discount that covers holding costs"
            )
        else:
            self.setToolTip(f"Expected profit {format_signed(rung.expected_profit)}")

    def _build_controls(self) -> QWidget:
        holder = QWidget()
        row = QHBoxLayout(holder)
        row.setContentsMargins(GRID * 3, 0, GRID * 3, GRID * 2)
        row.setSpacing(GRID * 2)

        confirm = QPushButton("Confirm sale")
        confirm.setObjectName("primary")
        confirm.clicked.connect(lambda: self.confirmed.emit(self.rung, self.rung.coins))

        reject = QPushButton("Rejected")
        reject.clicked.connect(lambda: self.rejected.emit(self.rung))

        self.custom_price = QLineEdit()
        self.custom_price.setObjectName("numericInput")
        self.custom_price.setPlaceholderText("Bought at")
        self.custom_price.setFixedWidth(96)
        self.custom_price.returnPressed.connect(self._confirm_custom)

        bought = QPushButton("Log")
        bought.setToolTip("Confirm at the price typed on the left")
        bought.clicked.connect(self._confirm_custom)

        row.addWidget(confirm)
        row.addWidget(reject)
        row.addStretch(1)
        row.addWidget(self.custom_price)
        row.addWidget(bought)
        return holder

    def _confirm_custom(self) -> None:
        text = self.custom_price.text().strip()
        if not text:
            return
        try:
            price = parse_coins(text)
        except ValueError:
            # Say what happened and what to do, rather than silently ignoring.
            self.custom_price.setToolTip("Type an amount such as 762.5m or 762,500,000")
            self.custom_price.setStyleSheet(f"border-color: {LOSS};")
            return
        self.custom_price.setStyleSheet("")
        self.confirmed.emit(self.rung, price)

    def set_expanded(self, expanded: bool) -> None:
        if self._expanded == expanded:
            return
        self._expanded = expanded
        self._animation.stop()
        if expanded:
            self.controls.setVisible(True)
            self._animation.setStartValue(self.controls.maximumHeight())
            self._animation.setEndValue(CONTROL_HEIGHT)
            self.custom_price.clear()
            self.custom_price.setStyleSheet("")
        else:
            self._animation.setStartValue(self.controls.maximumHeight())
            self._animation.setEndValue(0)
        self._animation.start()
        self.update()

    @property
    def is_expanded(self) -> bool:
        return self._expanded

    def set_recommended(self, recommended: bool) -> None:
        self._recommended = recommended
        weight = WEIGHT_EMPHASIS if recommended else WEIGHT_BODY
        for label in (self.pct_label, self.coins_label):
            label.setFont(numeric_font(SIZE_BODY, weight))
        self.pct_label.setStyleSheet(f"color: {ACCENT};" if recommended else "")
        self.update()

    def enterEvent(self, event) -> None:  # noqa: N802 - Qt naming
        self._hovered = True
        self.update()

    def leaveEvent(self, event) -> None:  # noqa: N802 - Qt naming
        self._hovered = False
        self.update()

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if event.button() == Qt.MouseButton.LeftButton and event.position().y() <= COLLAPSED_HEIGHT:
            self.activated.emit(self.rung)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt naming
        painter = QPainter(self)
        if self._expanded:
            painter.fillRect(self.rect(), QColor(SURFACE_HIGH))
            painter.fillRect(0, 0, 2, self.height(), QColor(ACCENT))
        elif self._hovered:
            painter.fillRect(
                0, 0, self.width(), COLLAPSED_HEIGHT, QColor(SURFACE_HIGH).darker(108)
            )
        if self._recommended and not self._expanded:
            painter.fillRect(0, 0, self.width(), COLLAPSED_HEIGHT, QColor(SURFACE_HIGH))
            painter.fillRect(0, 0, 2, COLLAPSED_HEIGHT, QColor(ACCENT))
        painter.end()


class OfferLadderWidget(QWidget):
    """The whole ladder, plus the recommendation underneath it."""

    offer_made = Signal(object)
    sale_confirmed = Signal(object, int)
    offer_rejected = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._rows: list[LadderRow] = []
        self._pending: LadderRow | None = None

        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(0, 0, 0, 0)
        self.root.setSpacing(0)

        self.summary = QVBoxLayout()
        self.summary.setContentsMargins(GRID * 3, GRID * 2, GRID * 3, GRID * 2)
        self.summary.setSpacing(2)
        self.root.addLayout(self.summary)
        self.root.addWidget(Hairline())

        self.rows_holder = QVBoxLayout()
        self.rows_holder.setContentsMargins(0, GRID, 0, GRID)
        self.rows_holder.setSpacing(0)
        self.root.addLayout(self.rows_holder)

        self.root.addWidget(Hairline())
        self.footer = QVBoxLayout()
        self.footer.setContentsMargins(GRID * 3, GRID * 2, GRID * 3, GRID * 2)
        self.footer.setSpacing(2)
        self.root.addLayout(self.footer)
        self.root.addStretch(1)

    def clear(self) -> None:
        self._pending = None
        self._rows.clear()
        for layout in (self.summary, self.rows_holder, self.footer):
            while layout.count():
                item = layout.takeAt(0)
                widget = item.widget()
                if widget is not None:
                    widget.setParent(None)

    def set_ladder(self, ladder: OfferLadder) -> None:
        self.clear()
        self._build_summary(ladder)
        for rung in ladder.steps:
            row = LadderRow(rung)
            row.activated.connect(self._on_activated)
            row.confirmed.connect(self._on_confirmed)
            row.rejected.connect(self._on_rejected)
            if ladder.recommended is not None and abs(rung.pct - ladder.recommended.pct) < 1e-9:
                row.set_recommended(True)
            self.rows_holder.addWidget(row)
            self._rows.append(row)
        self._build_footer(ladder)

    def _build_summary(self, ladder: OfferLadder) -> None:
        for rung in ladder.rungs:
            if rung.kind not in {"ESTIMATE", "NET_OF_TAX"}:
                continue
            line = QHBoxLayout()
            line.setContentsMargins(0, 0, 0, 0)
            label = QLabel(rung.label)
            label.setObjectName("dim")
            value = QLabel(format_coins(rung.coins))
            value.setFont(numeric_font(SIZE_EMPHASIS if rung.kind == "ESTIMATE" else SIZE_BODY))
            value.setToolTip(format_coins_exact(rung.coins))
            if rung.kind == "NET_OF_TAX":
                value.setStyleSheet(f"color: {INK_DIM};")
            line.addWidget(label)
            line.addStretch(1)
            line.addWidget(value)
            holder = QWidget()
            holder.setLayout(line)
            self.summary.addWidget(holder)

    def _build_footer(self, ladder: OfferLadder) -> None:
        title = QLabel("Recommended")
        title.setObjectName("sectionLabel")
        title.setFont(ui_font(SIZE_MICRO, WEIGHT_EMPHASIS))
        self.footer.addWidget(title)

        if ladder.recommended is not None:
            headline = QHBoxLayout()
            headline.setContentsMargins(0, 0, 0, 0)
            pct = QLabel(ladder.recommended.pct_label)
            pct.setFont(numeric_font(SIZE_EMPHASIS, WEIGHT_EMPHASIS))
            pct.setStyleSheet(f"color: {ACCENT};")
            coins = QLabel(format_coins(ladder.recommended.coins))
            coins.setFont(numeric_font(SIZE_EMPHASIS))
            headline.addWidget(pct)
            if ladder.recommended.is_exploration:
                headline.addWidget(ExplorationBadge())
            headline.addStretch(1)
            headline.addWidget(coins)
            holder = QWidget()
            holder.setLayout(headline)
            self.footer.addWidget(holder)

        for line in ladder.reasoning + ladder.evidence:
            label = QLabel(line)
            label.setObjectName("faint")
            label.setFont(ui_font(SIZE_MICRO))
            label.setWordWrap(True)
            self.footer.addWidget(label)

        for warning in ladder.warnings:
            label = QLabel(warning)
            label.setFont(ui_font(SIZE_MICRO))
            label.setStyleSheet(f"color: {LOSS};")
            label.setWordWrap(True)
            self.footer.addWidget(label)

        floor = QLabel(f"Costs covered from {ladder.floor_pct * 100:.0f}%")
        floor.setObjectName("faint")
        floor.setFont(ui_font(SIZE_MICRO))
        floor.setToolTip(
            "\n".join(f"{name}: {value * 100:.2f}%" for name, value in ladder.floor.as_rows())
        )
        self.footer.addWidget(floor)

    # ---- interaction ----------------------------------------------------

    def _on_activated(self, rung: Rung) -> None:
        row = self._row_for(rung)
        if row is None:
            return
        if row is self._pending:
            row.set_expanded(False)
            self._pending = None
            return
        if self._pending is not None:
            # Moving to a different rung means the customer said no to this
            # one. Log it on the way past rather than asking the user to.
            self.offer_rejected.emit(self._pending.rung)
            self._pending.set_expanded(False)
        row.set_expanded(True)
        self._pending = row
        self.offer_made.emit(rung)

    def _on_confirmed(self, rung: Rung, price: int) -> None:
        self.sale_confirmed.emit(rung, price)
        self.collapse()

    def _on_rejected(self, rung: Rung) -> None:
        self.offer_rejected.emit(rung)
        self.collapse()

    def collapse(self) -> None:
        if self._pending is not None:
            self._pending.set_expanded(False)
            self._pending = None

    def _row_for(self, rung: Rung) -> LadderRow | None:
        for row in self._rows:
            if abs(row.rung.pct - rung.pct) < 1e-9:
                return row
        return None

    @property
    def pending_rung(self) -> Rung | None:
        return self._pending.rung if self._pending else None

    def prefill_settled_price(self, coins: int) -> bool:
        """Put the price a trade actually settled at into the open rung.

        Only ever fills a rung that is already pending. Expanding one here
        would log an offer the user never made, which would poison the
        acceptance model with a percentage nobody ever said out loud.
        """
        if self._pending is None:
            return False
        self._pending.custom_price.setText(format_coins_exact(coins))
        self._pending.custom_price.setStyleSheet(f"border-color: {ACCENT};")
        self._pending.custom_price.setFocus()
        self._pending.custom_price.selectAll()
        return True

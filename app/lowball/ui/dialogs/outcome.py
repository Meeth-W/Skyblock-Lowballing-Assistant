"""What happened to an item after it was bought.

This replaced auction house tracking. Scraping a coop member's auctions to
discover that something sold was a great deal of machinery for a fact the user
already knows the moment it happens -- and it could never see a private trade
at all. One button and a price is both simpler and more complete.

Three outcomes, and they are not symmetric:

* **Sold** is the normal one. The price is the gross figure; the claim tax is
  taken off it when the sale went through the auction house, which is why
  there is a switch for that rather than an assumption.
* **Kept** is a withdrawal at market value, not a sale. Booked apart so a
  personal-use Hyperion does not read as an unsold loss forever.
* **Back into stock** undoes an outcome recorded in error.

Re-opening this on an item that already has an outcome is how a price is
corrected: the dialog opens on what was recorded, and saving replaces it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from ...money import format_coins, format_coins_exact, format_signed, parse_coins
from ...tax import DEFAULT_TAX, TaxConfig, claim_tax
from ..theme import (
    GAIN,
    GRID,
    LOSS,
    SIZE_MICRO,
    SIZE_SECTION,
    WEIGHT_EMPHASIS,
    rarity_colour,
    stylesheet,
    ui_font,
)
from ..widgets.primitives import Hairline

SOLD = "SOLD"
KEPT = "KEPT"
HELD = "HELD"


@dataclass(frozen=True)
class OutcomeChoice:
    """What the user decided.  ``route`` is SOLD, KEPT or HELD."""

    route: str
    price: int = 0
    taxed: bool = True
    note: str | None = None

    @property
    def is_unwind(self) -> bool:
        return self.route == HELD


class OutcomeDialog(QDialog):
    """Mark one item sold, kept, or back into stock."""

    def __init__(
        self,
        row: Any,
        *,
        tax: TaxConfig = DEFAULT_TAX,
        exit_row: Any = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.row = row
        self.tax = tax
        self.choice: OutcomeChoice | None = None
        self.setWindowTitle("Record an outcome")
        self.setStyleSheet(stylesheet())
        self.setMinimumWidth(420)

        cost = int(row["cost_basis"] or 0)
        state = (row["state"] or HELD).upper()
        # Opening on an item that already has an outcome should show that
        # outcome, not a blank form: the common reason to reopen this is that
        # the price was wrong by a few million.
        recorded = int(exit_row["gross"]) if exit_row is not None else 0
        suggested = recorded or int(row["est_value_now"] or 0) or cost

        root = QVBoxLayout(self)
        root.setContentsMargins(GRID * 6, GRID * 5, GRID * 6, GRID * 5)
        root.setSpacing(GRID * 2)

        name = row["display_name"] or (row["tag"] or "").replace("_", " ").title()
        heading = QLabel(name)
        heading.setFont(ui_font(SIZE_SECTION, WEIGHT_EMPHASIS))
        heading.setStyleSheet(f"color: {rarity_colour(row['rarity'])};")
        root.addWidget(heading)

        paid = QLabel(f"Bought for {format_coins(cost)}")
        paid.setObjectName("dim")
        paid.setFont(ui_font(SIZE_MICRO))
        root.addWidget(paid)
        root.addWidget(Hairline())

        self.group = QButtonGroup(self)
        self.sold = QRadioButton("Sold")
        self.kept = QRadioButton("Kept for personal use")
        self.back = QRadioButton("Put back into stock")
        self.back.setToolTip("Undo an outcome recorded in error")
        for index, button in enumerate((self.sold, self.kept, self.back)):
            self.group.addButton(button, index)
            root.addWidget(button)
        self.back.setVisible(state != HELD)

        price_row = QHBoxLayout()
        price_row.setContentsMargins(GRID * 5, 0, 0, 0)
        price_row.setSpacing(GRID * 2)
        self.price_label = QLabel("Price")
        self.price_label.setObjectName("dim")
        self.price = QLineEdit(format_coins_exact(suggested) if suggested else "")
        self.price.setObjectName("numericInput")
        self.price.setPlaceholderText("e.g. 847.2m")
        self.price.textChanged.connect(self._update_outcome_line)
        price_row.addWidget(self.price_label)
        price_row.addWidget(self.price, 1)
        holder = QWidget()
        holder.setLayout(price_row)
        root.addWidget(holder)

        self.taxed = QCheckBox("Sold on the auction house, so claim tax applies")
        self.taxed.setChecked(
            bool(exit_row["taxed"]) if exit_row is not None and exit_row["route"] == SOLD
            else True
        )
        self.taxed.stateChanged.connect(self._update_outcome_line)
        taxed_holder = QWidget()
        taxed_layout = QHBoxLayout(taxed_holder)
        taxed_layout.setContentsMargins(GRID * 5, 0, 0, 0)
        taxed_layout.addWidget(self.taxed)
        root.addWidget(taxed_holder)

        self.outcome_line = QLabel("")
        self.outcome_line.setFont(ui_font(SIZE_MICRO))
        self.outcome_line.setWordWrap(True)
        self.outcome_line.setContentsMargins(GRID * 5, 0, 0, 0)
        root.addWidget(self.outcome_line)

        note_row = QHBoxLayout()
        note_row.setContentsMargins(GRID * 5, GRID, 0, 0)
        note_row.setSpacing(GRID * 2)
        note_label = QLabel("Note")
        note_label.setObjectName("dim")
        self.note = QLineEdit(
            str(exit_row["note"]) if exit_row is not None and exit_row["note"] else ""
        )
        self.note.setPlaceholderText("optional")
        note_row.addWidget(note_label)
        note_row.addWidget(self.note, 1)
        note_holder = QWidget()
        note_holder.setLayout(note_row)
        root.addWidget(note_holder)

        root.addWidget(Hairline())
        buttons = QHBoxLayout()
        buttons.setSpacing(GRID * 2)
        buttons.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        self.save = QPushButton("Save")
        self.save.setObjectName("primary")
        self.save.setDefault(True)
        self.save.clicked.connect(self._on_save)
        buttons.addWidget(cancel)
        buttons.addWidget(self.save)
        button_holder = QWidget()
        button_holder.setLayout(buttons)
        root.addWidget(button_holder)

        self.group.idToggled.connect(lambda _id, _on: self._update_mode())
        if exit_row is not None and exit_row["route"] == KEPT:
            self.kept.setChecked(True)
        else:
            self.sold.setChecked(True)
        self._update_mode()
        self.price.setFocus()
        self.price.selectAll()

    # ---- state ---------------------------------------------------------

    @property
    def route(self) -> str:
        if self.kept.isChecked():
            return KEPT
        if self.back.isChecked():
            return HELD
        return SOLD

    def _update_mode(self) -> None:
        route = self.route
        wants_price = route in {SOLD, KEPT}
        self.price.setEnabled(wants_price)
        self.price_label.setEnabled(wants_price)
        self.price_label.setText("Price" if route == SOLD else "Market value")
        self.taxed.setVisible(route == SOLD)
        self.note.setEnabled(route != HELD)
        self._update_outcome_line()

    def _typed_price(self) -> int | None:
        text = self.price.text().strip()
        if not text:
            return None
        try:
            return parse_coins(text)
        except ValueError:
            return None

    def _update_outcome_line(self) -> None:
        route = self.route
        if route == HELD:
            self.outcome_line.setText("The recorded outcome is removed.")
            self.outcome_line.setStyleSheet("")
            return

        price = self._typed_price()
        if price is None:
            self.outcome_line.setText("Type an amount such as 847.2m or 847,200,000")
            self.outcome_line.setStyleSheet(f"color: {LOSS};")
            return

        cost = int(self.row["cost_basis"] or 0)
        tax = claim_tax(price, self.tax) if (route == SOLD and self.taxed.isChecked()) else 0
        profit = price - tax - cost
        # Say the profit before the click, not after: the whole point of the
        # tax switch is that it moves this number.
        parts = [f"{format_coins(price)} gross"]
        if tax:
            parts.append(f"less {format_coins(tax)} claim tax")
        parts.append(f"{format_signed(profit)} against the {format_coins(cost)} paid")
        self.outcome_line.setText(", ".join(parts))
        self.outcome_line.setStyleSheet(
            f"color: {GAIN if profit > 0 else (LOSS if profit < 0 else '')};"
        )

    def _on_save(self) -> None:
        route = self.route
        note = self.note.text().strip() or None
        if route == HELD:
            self.choice = OutcomeChoice(HELD, note=note)
            self.accept()
            return
        price = self._typed_price()
        if price is None or price < 0:
            self.price.setStyleSheet(f"border-color: {LOSS};")
            self.price.setFocus()
            return
        self.choice = OutcomeChoice(
            route=route, price=price, taxed=self.taxed.isChecked(), note=note
        )
        self.accept()

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt naming
        # Return in the price field should save, not just leave the field.
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._on_save()
            return
        super().keyPressEvent(event)

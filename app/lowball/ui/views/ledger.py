"""The ledger view: everything bought, and what happened to it.

The table answers three questions and nothing else: what it is, what it cost,
and where it ended up. Time held used to be a column; it is now the colour of
the acquisition date, because a number nobody reads is worse than a tint that
cannot be ignored.

Every row carries its own outcome control. Recording a sale is one click and a
price, which is what made auction house tracking redundant: the user knows the
moment something sells, and a scraper could never see a private trade at all.

Clicking the item name opens what the item actually is, read back from the
signature stored when it changed hands.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...ledger import Ledger
from ...money import format_coins, format_coins_exact, format_signed
from ...parsing.signature import ItemSignature
from ...timeutil import age_days, format_duration
from ..dialogs.attributes import ItemAttributesDialog, ledger_facts
from ..dialogs.outcome import HELD, KEPT, SOLD, OutcomeDialog
from ..theme import (
    GAIN,
    GRID,
    INK_DIM,
    LOSS,
    SIZE_MICRO,
    numeric_font,
    rarity_colour,
    ui_font,
)
from ..widgets.primitives import Hairline, SectionLabel

#: Outcome is a button, so it is last: the eye reads the figures first and the
#: only clickable thing on the row sits where the hand expects it.
COLUMNS = ("Item", "Acquired", "Paid", "Worth now", "Out at", "Net", "P&L", "Outcome")

COL_ITEM, COL_ACQUIRED, COL_PAID, COL_NOW, COL_EXIT, COL_NET, COL_PNL, COL_ACTION = range(8)

NUMERIC_COLUMNS = frozenset({COL_PAID, COL_NOW, COL_EXIT, COL_NET, COL_PNL})

FILTERS: dict[str, tuple[str, ...] | None] = {
    "Everything": None,
    "In stock": (HELD,),
    "Sold": (SOLD,),
    "Kept": (KEPT,),
}

#: Held longer than this and the capital is doing nothing.
DEAD_DAYS = 7.0


class LedgerView(QWidget):
    """The table, its filter, and the two destructive-ish buttons."""

    #: Something was written, so the statistics tab is now stale.
    changed = Signal()
    status = Signal(str)
    #: Confirmed by the user. The controller does the erasing, because it also
    #: has to drop the negotiation sessions pointing at the old events.
    clear_confirmed = Signal()

    def __init__(self, ledger: Ledger, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.ledger = ledger
        self._rows: list = []

        root = QVBoxLayout(self)
        root.setContentsMargins(GRID * 4, GRID * 4, GRID * 4, GRID * 4)
        root.setSpacing(GRID * 2)

        header = QHBoxLayout()
        header.setSpacing(GRID * 2)
        header.addWidget(SectionLabel("Ledger"))
        header.addStretch(1)

        self.summary = QLabel("")
        self.summary.setObjectName("faint")
        self.summary.setFont(ui_font(SIZE_MICRO))
        header.addWidget(self.summary)

        self.filter = QComboBox()
        self.filter.addItems(list(FILTERS))
        self.filter.currentTextChanged.connect(lambda _: self.refresh())
        header.addWidget(self.filter)

        clear = QPushButton("Clear history")
        clear.setObjectName("danger")
        clear.setToolTip("Erase every trade ever recorded. Cannot be undone.")
        clear.clicked.connect(self._confirm_clear)
        header.addWidget(clear)

        holder = QWidget()
        holder.setLayout(header)
        root.addWidget(holder)
        root.addWidget(Hairline())

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setShowGrid(False)
        self.table.horizontalHeader().setSectionResizeMode(
            COL_ITEM, QHeaderView.ResizeMode.Stretch
        )
        self.table.cellClicked.connect(self._on_cell_clicked)
        root.addWidget(self.table, 1)

        self.empty = QLabel("No items yet. Open a trade in Minecraft to start.")
        self.empty.setObjectName("dim")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self.empty)

        self.refresh()

    # ---- reading -------------------------------------------------------

    def refresh(self) -> None:
        states = FILTERS.get(self.filter.currentText())
        sql = (
            "SELECT i.*, e.route AS route, e.gross AS exit_gross, e.net AS exit_net,"
            " e.profit AS profit, e.taxed AS taxed, e.note AS exit_note,"
            " e.hold_seconds AS hold_seconds"
            " FROM items i LEFT JOIN exits e ON e.item_id = i.item_id"
        )
        params: tuple = ()
        if states:
            placeholders = ",".join("?" for _ in states)
            sql += f" WHERE i.state IN ({placeholders})"
            params = states
        sql += " ORDER BY i.acquired_ts DESC"
        self._rows = self.ledger.query(sql, params)

        self.empty.setVisible(not self._rows)
        self.table.setVisible(bool(self._rows))
        self.table.setRowCount(len(self._rows))
        for index, row in enumerate(self._rows):
            self._fill_row(index, row)
        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setSectionResizeMode(
            COL_ITEM, QHeaderView.ResizeMode.Stretch
        )
        self._update_summary()

    def _update_summary(self) -> None:
        held = sum(1 for r in self._rows if (r["state"] or HELD) == HELD)
        deployed = sum(
            int(r["cost_basis"] or 0) for r in self._rows if (r["state"] or HELD) == HELD
        )
        realised = sum(int(r["profit"] or 0) for r in self._rows if r["route"] == SOLD)
        parts = [f"{len(self._rows)} item(s)"]
        if held:
            parts.append(f"{held} in stock, {format_coins(deployed)} deployed")
        if realised:
            parts.append(f"{format_signed(realised)} realised")
        self.summary.setText("   ".join(parts))

    def _fill_row(self, index: int, row) -> None:
        name = row["display_name"] or (row["tag"] or "").replace("_", " ").title()
        state = (row["state"] or HELD).upper()
        cost = int(row["cost_basis"] or 0)
        now = int(row["est_value_now"] or 0)
        held_days = age_days(row["acquired_ts"]) if row["acquired_ts"] else 0.0
        is_dead = state == HELD and held_days >= DEAD_DAYS

        cells: list[tuple[str, str | None, str | None]] = [
            (name, "Click to see what this item is", rarity_colour(row["rarity"])),
            (
                _short_date(row["acquired_ts"]),
                f"Held {format_duration(held_days * 86400)}"
                if state == HELD
                else f"Held {format_duration(int(row['hold_seconds'] or 0))}",
                LOSS if is_dead else None,
            ),
            (format_coins(cost), format_coins_exact(cost), None),
            (
                format_coins(now) if now and state == HELD else "—",
                format_coins_exact(now) if now else None,
                None,
            ),
            (
                format_coins(row["exit_gross"]) if row["exit_gross"] is not None else "—",
                _exit_tooltip(row),
                None,
            ),
            (
                format_coins(row["exit_net"]) if row["exit_net"] is not None else "—",
                format_coins_exact(row["exit_net"]) if row["exit_net"] is not None else None,
                None,
            ),
            (
                format_signed(row["profit"]) if row["profit"] is not None else "—",
                None,
                _pnl_colour(row["profit"]),
            ),
        ]

        for column, (text, tooltip, colour) in enumerate(cells):
            cell = QTableWidgetItem(text)
            cell.setData(Qt.ItemDataRole.UserRole, row["item_id"])
            if column in NUMERIC_COLUMNS:
                cell.setFont(numeric_font(SIZE_MICRO + 2))
                cell.setTextAlignment(
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                )
            else:
                cell.setFont(ui_font(SIZE_MICRO + 2))
            if tooltip:
                cell.setToolTip(tooltip)
            if colour is not None:
                cell.setForeground(_brush(colour))
            self.table.setItem(index, column, cell)

        if is_dead:
            self.table.item(index, COL_ACQUIRED).setToolTip(
                "Held over a week; this capital is doing nothing"
            )
        self.table.setCellWidget(index, COL_ACTION, self._outcome_button(row))

    def _outcome_button(self, row) -> QWidget:
        """One button per row, labelled with what is currently recorded."""
        state = (row["state"] or HELD).upper()
        label = {
            HELD: "Mark sold…",
            SOLD: f"Sold {format_coins(row['exit_gross'])}",
            KEPT: "Kept",
        }.get(state, state.title())

        button = QPushButton(label)
        button.setObjectName("primary" if state == HELD else "ghost")
        button.setToolTip(
            "Record what happened to this item"
            if state == HELD
            else "Change the price, keep it instead, or put it back into stock"
        )
        button.clicked.connect(lambda _=False, r=row: self._open_outcome(r))

        holder = QWidget()
        layout = QHBoxLayout(holder)
        layout.setContentsMargins(GRID, 2, GRID, 2)
        layout.addWidget(button)
        return holder

    # ---- interaction ---------------------------------------------------

    def _row_at(self, index: int):
        return self._rows[index] if 0 <= index < len(self._rows) else None

    def _on_cell_clicked(self, index: int, column: int) -> None:
        if column != COL_ITEM:
            return
        row = self._row_at(index)
        if row is not None:
            self._open_attributes(row)

    def _open_attributes(self, row) -> None:
        signature = row["signature"]
        if not signature:
            QMessageBox.information(
                self,
                "Nothing recorded",
                "This item was logged without a signature, so there is nothing"
                " to show beyond what the row already says.",
            )
            return
        try:
            sig = _signature_of(signature)
        except Exception as exc:  # noqa: BLE001 - a stored signature may predate a change
            QMessageBox.warning(
                self, "Could not read the item", f"{type(exc).__name__}: {exc}"
            )
            return
        ItemAttributesDialog(sig, facts=ledger_facts(row), parent=self).exec()

    def _open_outcome(self, row) -> None:
        exit_row = self.ledger.exit_for(row["item_id"])
        dialog = OutcomeDialog(row, tax=self.ledger.tax, exit_row=exit_row, parent=self)
        if not dialog.exec() or dialog.choice is None:
            return
        choice = dialog.choice
        name = row["display_name"] or row["tag"]

        if choice.route == HELD:
            self.ledger.unwind_exit(row["item_id"], note=choice.note)
            self.status.emit(f"{name} is back in stock")
        elif choice.route == KEPT:
            self.ledger.keep_item(
                item_id=row["item_id"], market_value=choice.price, note=choice.note
            )
            self.status.emit(f"{name} kept at {format_coins(choice.price)}")
        else:
            self.ledger.sell_item(
                item_id=row["item_id"],
                price=choice.price,
                taxed=choice.taxed,
                note=choice.note,
            )
            profit = self.ledger.exit_for(row["item_id"])["profit"]
            self.status.emit(
                f"{name} sold for {format_coins(choice.price)},"
                f" {format_signed(profit)}"
            )
        self.refresh()
        self.changed.emit()

    def _confirm_clear(self) -> None:
        total = self.ledger.log.count()
        if not total:
            self.status.emit("There is no history to clear")
            return
        items = self.ledger.query("SELECT COUNT(*) AS n FROM items")[0]["n"]
        box = QMessageBox(self)
        box.setWindowTitle("Clear the whole history?")
        box.setIcon(QMessageBox.Icon.Warning)
        box.setText(
            f"This erases {total} recorded event(s), covering {items} item(s)"
            " and every offer ever made."
        )
        box.setInformativeText(
            "The acceptance model learns from that history, so it starts again"
            " from nothing. Settings, rules and pricing are untouched.\n\n"
            "This cannot be undone."
        )
        box.setStandardButtons(
            QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes
        )
        box.setDefaultButton(QMessageBox.StandardButton.Cancel)
        box.button(QMessageBox.StandardButton.Yes).setText("Erase everything")
        if box.exec() != QMessageBox.StandardButton.Yes:
            return
        self.clear_confirmed.emit()

    def filter_to_items(self, item_ids: list[str]) -> None:
        """Used when a chart is clicked through to the rows behind it."""
        wanted = set(item_ids)
        for row in range(self.table.rowCount()):
            cell = self.table.item(row, COL_ITEM)
            visible = cell is not None and cell.data(Qt.ItemDataRole.UserRole) in wanted
            self.table.setRowHidden(row, not visible)


def _signature_of(blob) -> ItemSignature:
    import json

    data = json.loads(blob) if isinstance(blob, str) else blob
    return ItemSignature.from_dict(data)


def _brush(colour: str):
    from PySide6.QtGui import QBrush, QColor

    return QBrush(QColor(colour))


def _pnl_colour(profit) -> str | None:
    if profit is None:
        return None
    if int(profit) > 0:
        return GAIN
    if int(profit) < 0:
        return LOSS
    return INK_DIM


def _exit_tooltip(row) -> str | None:
    if row["exit_gross"] is None:
        return None
    parts = [format_coins_exact(row["exit_gross"])]
    if row["route"] == KEPT:
        parts.append("kept at market value, not a sale")
    elif row["taxed"]:
        parts.append("auction house claim tax taken off")
    else:
        parts.append("untaxed, so a direct trade")
    if row["exit_note"]:
        parts.append(str(row["exit_note"]))
    return "\n".join(parts)


def _short_date(iso_ts: str | None) -> str:
    if not iso_ts:
        return ""
    return iso_ts[:10]

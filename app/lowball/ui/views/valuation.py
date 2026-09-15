"""The main valuation view: three panes, separated by hairlines.

    TRADE          | selected item              | OFFER
    what is on the | what it is worth and why   | what to say
    table

Nothing here is a card and nothing animates on load. The only movement is a
ladder row expanding under the cursor.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ...money import format_coins, format_coins_exact
from ...parsing.signature import ItemSignature
from ...pricing.offer import OfferLadder, Rung
from ...pricing.valuation import Valuation
from ..theme import GRID, SIZE_BODY, SIZE_EMPHASIS, numeric_font, ui_font
from ..widgets.item_row import TradeItemRow
from ..widgets.ladder import OfferLadderWidget
from ..widgets.primitives import Hairline, SectionLabel


class TradePane(QWidget):
    """Left pane: what the customer has put on the table."""

    item_selected = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._rows: list[TradeItemRow] = []
        self._selected = -1

        root = QVBoxLayout(self)
        root.setContentsMargins(0, GRID * 4, 0, GRID * 3)
        root.setSpacing(GRID)

        header = SectionLabel("Trade")
        header.setContentsMargins(GRID * 3, 0, GRID * 3, 0)
        root.addWidget(header)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.rows_holder = QWidget()
        self.rows_layout = QVBoxLayout(self.rows_holder)
        self.rows_layout.setContentsMargins(0, 0, 0, 0)
        self.rows_layout.setSpacing(0)
        self.rows_layout.addStretch(1)
        self.scroll.setWidget(self.rows_holder)
        root.addWidget(self.scroll, 1)

        root.addWidget(Hairline())
        totals = QVBoxLayout()
        totals.setContentsMargins(GRID * 3, GRID * 2, GRID * 3, 0)
        totals.setSpacing(GRID)
        self.total_row = self._total_line("Total", totals)
        self.offer_row = self._total_line("Offer", totals)
        holder = QWidget()
        holder.setLayout(totals)
        root.addWidget(holder)

        self.empty_label = QLabel("No items yet.\nOpen a trade in Minecraft to start.")
        self.empty_label.setObjectName("dim")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setWordWrap(True)
        self.rows_layout.insertWidget(0, self.empty_label)

    def _total_line(self, label: str, layout: QVBoxLayout) -> QLabel:
        block = QVBoxLayout()
        block.setContentsMargins(0, 0, 0, 0)
        block.setSpacing(0)
        caption = QLabel(label)
        caption.setObjectName("dim")
        caption.setFont(ui_font(SIZE_BODY))
        value = QLabel("\u2014")
        value.setFont(numeric_font(SIZE_EMPHASIS))
        block.addWidget(caption)
        block.addWidget(value)
        holder = QWidget()
        holder.setLayout(block)
        layout.addWidget(holder)
        return value

    def set_items(self, items: list[tuple[ItemSignature, int]]) -> None:
        for row in self._rows:
            row.setParent(None)
        self._rows.clear()
        self._selected = -1
        self.empty_label.setVisible(not items)

        for index, (sig, duplicates) in enumerate(items):
            row = TradeItemRow(sig, duplicates=duplicates)
            row.clicked.connect(lambda r=row, i=index: self._select(i))
            self.rows_layout.insertWidget(index + 1, row)
            self._rows.append(row)
        if items:
            self._select(0)
        else:
            self.set_totals(None, None)

    def select_index(self, index: int) -> None:
        """Select from outside, e.g. when a completed trade names an item."""
        self._select(index)

    def _select(self, index: int) -> None:
        if index == self._selected:
            return
        for position, row in enumerate(self._rows):
            row.set_selected(position == index)
        self._selected = index
        self.item_selected.emit(index)

    def set_item_value(self, index: int, coins: int | None, *, pending: bool = False) -> None:
        if 0 <= index < len(self._rows):
            self._rows[index].set_value(coins, pending=pending)

    def set_totals(self, total: int | None, offer: int | None) -> None:
        self.total_row.setText(format_coins(total))
        self.total_row.setToolTip(format_coins_exact(total) if total else "")
        self.offer_row.setText(format_coins(offer))
        self.offer_row.setToolTip(format_coins_exact(offer) if offer else "")

    @property
    def selected_index(self) -> int:
        return self._selected


class ValuationView(QWidget):
    """The three panes together."""

    item_selected = Signal(int)
    offer_made = Signal(int, object)
    sale_confirmed = Signal(int, object, int)
    offer_rejected = Signal(int, object)
    #: (index, coins or None) -- the user set the value by hand, or undid it.
    estimate_overridden = Signal(int, object)
    #: (action, auction) -- a market figure was clicked. See widgets.links.
    auction_action = Signal(str, object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        from .detail import ItemDetailPane

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setHandleWidth(1)
        self.splitter.setChildrenCollapsible(False)

        self.trade = TradePane()
        self.detail = ItemDetailPane()
        # Kept so the breakdown can be opened without asking the controller
        # to hand the valuation back across a signal.
        self._valuations: dict[int, Valuation] = {}

        offer_holder = QWidget()
        offer_layout = QVBoxLayout(offer_holder)
        offer_layout.setContentsMargins(0, GRID * 4, 0, 0)
        offer_layout.setSpacing(GRID)
        offer_header = SectionLabel("Offer")
        offer_header.setContentsMargins(GRID * 3, 0, GRID * 3, 0)
        offer_layout.addWidget(offer_header)
        self.ladder = OfferLadderWidget()
        offer_layout.addWidget(self.ladder, 1)

        detail_scroll = QScrollArea()
        detail_scroll.setWidgetResizable(True)
        detail_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        detail_scroll.setWidget(self.detail)

        for widget in (self.trade, detail_scroll, offer_holder):
            self.splitter.addWidget(widget)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setStretchFactor(2, 0)
        self.splitter.setSizes([220, 520, 260])
        root.addWidget(self.splitter)

        self.trade.item_selected.connect(self._on_item_selected)
        self.detail.breakdown_requested.connect(self._show_breakdown)
        self.detail.auction_action.connect(self.auction_action.emit)
        self.ladder.offer_made.connect(
            lambda rung: self.offer_made.emit(self.trade.selected_index, rung)
        )
        self.ladder.sale_confirmed.connect(
            lambda rung, price: self.sale_confirmed.emit(
                self.trade.selected_index, rung, price
            )
        )
        self.ladder.offer_rejected.connect(
            lambda rung: self.offer_rejected.emit(self.trade.selected_index, rung)
        )

    def _show_breakdown(self) -> None:
        """Open the derivation of the number the user just clicked."""
        from ..dialogs.breakdown import ValuationBreakdownDialog

        valuation = self._valuations.get(self.trade.selected_index)
        if valuation is None:
            return
        index = self.trade.selected_index
        dialog = ValuationBreakdownDialog(valuation, parent=self)
        dialog.override_requested.connect(
            lambda coins, i=index: self.estimate_overridden.emit(i, coins)
        )
        dialog.auction_action.connect(self.auction_action.emit)
        dialog.exec()

    def _on_item_selected(self, index: int) -> None:
        # Changing item abandons whatever rung was open: a pending offer
        # belongs to the item it was made on.
        self.ladder.collapse()
        self.item_selected.emit(index)

    def set_items(self, items: list[tuple[ItemSignature, int]]) -> None:
        self._valuations.clear()
        self.trade.set_items(items)
        if not items:
            self.ladder.clear()
            self.detail._show_empty()

    def show_pending(self, index: int, sig: ItemSignature) -> None:
        self.trade.set_item_value(index, None, pending=True)
        if index == self.trade.selected_index:
            self.detail.show_pending(
                sig.display_name or sig.tag.replace("_", " ").title(), sig.rarity
            )

    def show_valuation(self, index: int, valuation: Valuation, ladder: OfferLadder) -> None:
        self._valuations[index] = valuation
        self.trade.set_item_value(index, valuation.estimate)
        if index != self.trade.selected_index:
            return
        self.detail.show_valuation(valuation)
        self.ladder.set_ladder(ladder)

    def set_totals(self, total: int | None, offer: int | None) -> None:
        self.trade.set_totals(total, offer)

    def pending_rung(self) -> Rung | None:
        return self.ladder.pending_rung

    def prefill_confirmation(self, index: int, coins: int) -> bool:
        """Show the item a completed trade settled, with the real price filled in."""
        self.trade.select_index(index)
        return self.ladder.prefill_settled_price(coins)

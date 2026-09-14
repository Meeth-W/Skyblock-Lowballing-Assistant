"""The middle pane: everything known about the selected item.

Reads top to bottom in the order the user needs it: what the item is, what it
is worth and how sure we are, what the market looks like right now, and then
the evidence underneath. The estimate is the only figure at display size,
because it is the only one being read out loud.

The estimate is also the only thing here that is clickable. Clicking it opens
the whole derivation, and the control to overrule it: a lowballer looking at
the item can know things the comparables cannot.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ...money import format_coins, format_coins_exact
from ...pricing.valuation import Valuation
from ...timeutil import age_seconds, format_duration
from ..theme import (
    ACCENT,
    GRID,
    INK_DIM,
    LOSS,
    SIZE_BODY,
    SIZE_MICRO,
    SIZE_SECTION,
    WEIGHT_EMPHASIS,
    numeric_font,
    rarity_colour,
    ui_font,
)
from ..widgets.indicators import ConfidenceDots, RuleBadge
from ..widgets.primitives import Hairline, KeyValueRow, SectionLabel


class ClickableFigure(QLabel):
    """The estimate.  Clicking it opens the breakdown.

    A label rather than a button on purpose: this is a number being read out
    loud to a customer, and dressing it as a control would put chrome around
    the one thing on screen that has to stay legible at a glance.
    """

    clicked = Signal()

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
            return
        super().mousePressEvent(event)


class ItemDetailPane(QWidget):
    #: The user clicked the estimate and wants to see where it came from.
    breakdown_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(GRID * 7, GRID * 6, GRID * 7, GRID * 6)
        self.root.setSpacing(GRID * 3)
        self._show_empty()

    def _clear(self) -> None:
        while self.root.count():
            item = self.root.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)

    def _show_empty(self) -> None:
        self._clear()
        # Empty states direct rather than decorate.
        message = QLabel("No item selected. Open a trade in Minecraft to start.")
        message.setObjectName("dim")
        message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.root.addStretch(1)
        self.root.addWidget(message)
        self.root.addStretch(1)

    def show_pending(self, name: str, rarity: str | None) -> None:
        self._clear()
        heading = QLabel(name)
        heading.setFont(ui_font(SIZE_SECTION, WEIGHT_EMPHASIS))
        heading.setStyleSheet(f"color: {rarity_colour(rarity)};")
        self.root.addWidget(heading)
        pending = QLabel("Valuing")
        pending.setObjectName("dim")
        self.root.addWidget(pending)
        self.root.addStretch(1)

    def show_valuation(self, valuation: Valuation) -> None:
        self._clear()
        sig = valuation.sig

        heading = QLabel(sig.display_name or sig.tag.replace("_", " ").title())
        heading.setFont(ui_font(SIZE_SECTION, WEIGHT_EMPHASIS))
        heading.setStyleSheet(f"color: {rarity_colour(sig.rarity)};")
        self.root.addWidget(heading)

        chips = sig.summary()
        if chips:
            chip_label = QLabel("   ".join(f"\u25c6 {c}" for c in chips[:6]))
            chip_label.setObjectName("dim")
            chip_label.setFont(ui_font(SIZE_MICRO))
            chip_label.setWordWrap(True)
            if len(chips) > 6:
                chip_label.setToolTip("\n".join(chips))
            self.root.addWidget(chip_label)

        self.root.addWidget(Hairline())
        self.root.addWidget(self._estimate_block(valuation))
        self.root.addWidget(self._market_block(valuation))

        if valuation.notes:
            for note in valuation.notes:
                label = QLabel(note)
                label.setObjectName("faint")
                label.setFont(ui_font(SIZE_MICRO))
                label.setWordWrap(True)
                self.root.addWidget(label)

        # Side by side: recent sales and what is listed answer the same
        # question from two directions, and stacking them left half the pane
        # empty on any reasonable window.
        evidence = QWidget()
        columns = QHBoxLayout(evidence)
        columns.setContentsMargins(0, 0, 0, 0)
        columns.setSpacing(GRID * 8)
        columns.addWidget(self._sales_block(valuation), 1)
        columns.addWidget(self._listings_block(valuation), 1)
        self.root.addWidget(evidence)
        self.root.addStretch(1)
        self.root.addWidget(self._attribution(valuation))

    def _estimate_block(self, valuation: Valuation) -> QWidget:
        holder = QWidget()
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(0, GRID, 0, GRID)
        layout.setSpacing(GRID)

        line = QHBoxLayout()
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(GRID * 2)

        figure = ClickableFigure(format_coins(valuation.estimate))
        # One or two dots also tints the figure toward ink-dim: low confidence
        # should feel visibly less solid, not just carry a smaller indicator.
        figure.setObjectName(
            "figureLowConfidence" if valuation.confidence.is_low else "figure"
        )
        figure.setToolTip(
            f"{format_coins_exact(valuation.estimate)}\nClick for the breakdown"
        )
        figure.clicked.connect(self.breakdown_requested.emit)
        if valuation.is_manual:
            # A hand-set figure has to look different from a measured one, or
            # the next glance at it reads as market evidence.
            figure.setStyleSheet(f"color: {ACCENT};")

        dots = ConfidenceDots()
        dots.set_confidence(valuation.confidence.dots, valuation.confidence.reasons)

        fraction = QLabel(valuation.confidence.modifier_fraction)
        fraction.setObjectName("faint")
        fraction.setFont(ui_font(SIZE_MICRO))
        fraction.setToolTip(
            f"{valuation.confidence.kept} of "
            f"{valuation.confidence.kept + valuation.confidence.dropped} modifiers matched"
            " in the comparable search; the rest were priced separately"
        )

        line.addWidget(figure)
        line.addStretch(1)
        line.addWidget(dots)
        line.addWidget(fraction)
        wrapper = QWidget()
        wrapper.setLayout(line)
        layout.addWidget(wrapper)

        if valuation.rules_fired:
            badges = QHBoxLayout()
            badges.setContentsMargins(0, 0, 0, 0)
            badges.setSpacing(GRID)
            for firing in valuation.rules_fired:
                name = getattr(firing, "name", str(firing))
                detail = getattr(firing, "detail", "")
                badges.addWidget(RuleBadge(name, detail))
            badges.addStretch(1)
            badge_holder = QWidget()
            badge_holder.setLayout(badges)
            layout.addWidget(badge_holder)

        if valuation.is_manual:
            manual = QLabel(
                f"Set by hand · the market said"
                f" {format_coins(valuation.market_estimate)}"
            )
            manual.setFont(ui_font(SIZE_MICRO))
            manual.setStyleSheet(f"color: {ACCENT};")
            layout.addWidget(manual)

        if valuation.addback:
            split = QLabel(
                f"{format_coins(valuation.comparable_base)} from comparables"
                f" + {format_coins(valuation.addback)} priced separately"
            )
            split.setObjectName("faint")
            split.setFont(ui_font(SIZE_MICRO))
            split.setToolTip(
                "\n".join(
                    f"{a.label}: {format_coins(a.applied)} ({a.source.lower()})"
                    for a in valuation.add_backs
                )
            )
            layout.addWidget(split)
        return holder

    def _market_block(self, valuation: Valuation) -> QWidget:
        holder = QWidget()
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        lbin = KeyValueRow("Lowest BIN", format_coins(valuation.lbin_price))
        if valuation.lbin.rejected_count:
            lbin.set_value(
                format_coins(valuation.lbin_price),
                tooltip=(
                    f"{valuation.lbin.rejected_count} cheaper listing(s) ignored as"
                    " implausible against the sales median"
                ),
            )
        layout.addWidget(lbin)

        median_row = KeyValueRow("Median", format_coins(valuation.median))
        median_row.set_value(
            format_coins(valuation.median),
            tooltip=f"n={valuation.search.sales_count} matching sales",
        )
        layout.addWidget(median_row)

        sell = valuation.sell_time
        label = f"~{format_duration(sell.seconds)}"
        sell_row = KeyValueRow("Sells in", label)
        sell_row.set_value(
            label,
            tooltip={
                "PERSONAL": f"From your own sales, n={sell.n}",
                "BLENDED": f"Your sales blended with Coflnet, n={sell.n}",
                "PUBLIC": "Coflnet median for this item",
                "FALLBACK": "No data; assuming one auction duration",
            }.get(sell.source, sell.source),
        )
        layout.addWidget(sell_row)

        if valuation.volatility:
            layout.addWidget(
                KeyValueRow("Volatility", f"{valuation.volatility * 100:.0f}%")
            )
        return holder

    def _sales_block(self, valuation: Valuation) -> QWidget:
        holder = QWidget()
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(0, GRID, 0, 0)
        layout.setSpacing(2)
        layout.addWidget(SectionLabel("Recent sales"))
        layout.addWidget(Hairline())

        sales = sorted(
            valuation.recent_sales,
            key=lambda a: a.end or "",
            reverse=True,
        )[:4]
        if not sales:
            empty = QLabel("No matching sales in the window")
            empty.setObjectName("faint")
            empty.setFont(ui_font(SIZE_MICRO))
            layout.addWidget(empty)
            return holder

        for sale in sales:
            row = QHBoxLayout()
            row.setContentsMargins(0, 1, 0, 1)
            price = QLabel(format_coins(sale.unit_price))
            price.setFont(numeric_font(SIZE_BODY))
            price.setToolTip(format_coins_exact(sale.unit_price))
            when = QLabel(_ago(sale.end))
            when.setObjectName("faint")
            when.setFont(ui_font(SIZE_MICRO))
            row.addWidget(price)
            row.addStretch(1)
            row.addWidget(when)
            wrapper = QWidget()
            wrapper.setLayout(row)
            layout.addWidget(wrapper)
        return holder

    def _listings_block(self, valuation: Valuation) -> QWidget:
        holder = QWidget()
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(0, GRID, 0, 0)
        layout.setSpacing(2)
        layout.addWidget(SectionLabel("Cheapest active"))
        layout.addWidget(Hairline())

        median = valuation.median or 0
        # The three cheapest, so the user can eyeball them: a rejected listing
        # is worth seeing, not just counting.
        shown = list(valuation.cheapest_active)
        rejected = list(valuation.lbin.rejected)
        entries = [(a, True) for a in rejected] + [(a, False) for a in shown]
        if not entries:
            empty = QLabel("Nothing listed right now")
            empty.setObjectName("faint")
            empty.setFont(ui_font(SIZE_MICRO))
            layout.addWidget(empty)
            return holder

        for auction, was_rejected in entries[:4]:
            row = QHBoxLayout()
            row.setContentsMargins(0, 1, 0, 1)
            price = QLabel(format_coins(auction.unit_price))
            price.setFont(numeric_font(SIZE_BODY))
            price.setToolTip(format_coins_exact(auction.unit_price))
            row.addWidget(price)
            row.addStretch(1)
            if was_rejected and median:
                gap = (median - auction.unit_price) / median * 100
                warn = QLabel(f"\u26a0 {gap:.1f}% below median")
                warn.setFont(ui_font(SIZE_MICRO))
                warn.setStyleSheet(f"color: {LOSS};")
                warn.setToolTip("Ignored when picking the lowest BIN")
                price.setStyleSheet(f"color: {INK_DIM};")
                row.addWidget(warn)
            wrapper = QWidget()
            wrapper.setLayout(row)
            layout.addWidget(wrapper)
        return holder

    def _attribution(self, valuation: Valuation) -> QWidget:
        # Coflnet require a visible link wherever their data is displayed.
        link = QLabel(
            f'<a style="color:{INK_DIM}; text-decoration:none;"'
            f' href="{valuation.attribution}">Prices from SkyCofl</a>'
        )
        link.setObjectName("faint")
        link.setFont(ui_font(SIZE_MICRO))
        link.setOpenExternalLinks(True)
        link.setToolTip(valuation.attribution)
        return link


def _ago(iso_ts: str | None) -> str:
    if not iso_ts:
        return ""
    try:
        return f"{format_duration(age_seconds(iso_ts))} ago"
    except (ValueError, TypeError):
        return ""

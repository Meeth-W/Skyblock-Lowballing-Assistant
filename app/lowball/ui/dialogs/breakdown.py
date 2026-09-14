"""Where the estimate came from, and how to overrule it.

The detail pane shows the number. This shows the arithmetic behind it: the
comparables it rested on, each modifier that was matched or priced separately,
the rules that fired, and every reason the confidence is what it is.

It also lets the user replace the number. That is not a failure of the model
-- the user can see the item and knows things the comparables do not, like a
skin that is about to be reissued. Their figure is stored beside ours rather
than over it, so the override can be undone and the breakdown still shows what
the market said.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ...money import format_coins, format_coins_exact, format_pct, parse_coins
from ...pricing.valuation import Valuation
from ...timeutil import format_duration
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
    stylesheet,
    ui_font,
)
from ..widgets.indicators import ConfidenceDots
from ..widgets.primitives import Hairline, KeyValueRow, SectionLabel


class ValuationBreakdownDialog(QDialog):
    """The whole derivation, plus the override control."""

    #: Coins, or None to go back to the market estimate.
    override_requested = Signal(object)

    def __init__(self, valuation: Valuation, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.valuation = valuation
        sig = valuation.sig
        self.setWindowTitle("How this was valued")
        self.setStyleSheet(stylesheet())
        self.setMinimumWidth(480)
        self.resize(520, 660)

        root = QVBoxLayout(self)
        root.setContentsMargins(GRID * 6, GRID * 5, GRID * 6, GRID * 5)
        root.setSpacing(GRID * 2)

        heading = QLabel(sig.display_name or sig.tag.replace("_", " ").title())
        heading.setFont(ui_font(SIZE_SECTION, WEIGHT_EMPHASIS))
        heading.setStyleSheet(f"color: {rarity_colour(sig.rarity)};")
        root.addWidget(heading)

        total = QHBoxLayout()
        total.setContentsMargins(0, 0, 0, 0)
        figure = QLabel(format_coins(valuation.estimate))
        figure.setFont(numeric_font(SIZE_SECTION + 6, WEIGHT_EMPHASIS))
        figure.setToolTip(format_coins_exact(valuation.estimate))
        dots = ConfidenceDots()
        dots.set_confidence(valuation.confidence.dots, valuation.confidence.reasons)
        total.addWidget(figure)
        total.addStretch(1)
        total.addWidget(dots)
        total_holder = QWidget()
        total_holder.setLayout(total)
        root.addWidget(total_holder)

        if valuation.is_manual:
            manual = QLabel(
                f"Set by hand. The market said {format_coins(valuation.market_estimate)}."
            )
            manual.setFont(ui_font(SIZE_MICRO))
            manual.setStyleSheet(f"color: {ACCENT};")
            root.addWidget(manual)

        root.addWidget(Hairline())

        body = QWidget()
        self.body = QVBoxLayout(body)
        self.body.setContentsMargins(0, GRID, 0, 0)
        self.body.setSpacing(GRID * 3)
        self._build(valuation)
        self.body.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(body)
        root.addWidget(scroll, 1)

        root.addWidget(Hairline())
        root.addWidget(self._override_block(valuation))

    # ---- sections ------------------------------------------------------

    def _section(self, title: str) -> QVBoxLayout:
        block = QWidget()
        layout = QVBoxLayout(block)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        layout.addWidget(SectionLabel(title))
        layout.addWidget(Hairline())
        self.body.addWidget(block)
        return layout

    def _line(self, layout: QVBoxLayout, text: str, *, colour: str | None = None) -> None:
        label = QLabel(text)
        label.setObjectName("faint" if colour is None else "")
        label.setFont(ui_font(SIZE_MICRO))
        label.setWordWrap(True)
        if colour:
            label.setStyleSheet(f"color: {colour};")
        layout.addWidget(label)

    def _build(self, v: Valuation) -> None:
        arithmetic = self._section("The sum")
        arithmetic.addWidget(
            KeyValueRow("From comparables", format_coins(v.comparable_base))
        )
        arithmetic.addWidget(
            KeyValueRow("Modifiers priced separately", format_coins(v.addback))
        )
        market = KeyValueRow("Market estimate", format_coins(v.market_estimate))
        market.value.setFont(numeric_font(SIZE_BODY, WEIGHT_EMPHASIS))
        arithmetic.addWidget(market)
        if v.is_manual:
            manual_row = KeyValueRow("Your figure", format_coins(v.manual_estimate))
            manual_row.value.setStyleSheet(f"color: {ACCENT};")
            arithmetic.addWidget(manual_row)
        if v.fallback_used:
            self._line(
                arithmetic,
                "Nothing matched at any filter set; this is the unfiltered market"
                " median for the tag.",
                colour=LOSS,
            )

        evidence = self._section("What it was priced against")
        evidence.addWidget(
            KeyValueRow("Matching sales", str(v.search.sales_count))
        )
        evidence.addWidget(KeyValueRow("Median of those", format_coins(v.median)))
        evidence.addWidget(KeyValueRow("Lowest BIN", format_coins(v.lbin_price)))
        if v.lbin.rejected_count:
            self._line(
                evidence,
                f"{v.lbin.rejected_count} cheaper listing(s) ignored as implausible"
                " against the sales median",
            )
        evidence.addWidget(
            KeyValueRow("Sales considered", str(v.search.sample_size))
        )
        if v.volatility:
            evidence.addWidget(
                KeyValueRow("Volatility", format_pct(v.volatility, decimals=0))
            )
        evidence.addWidget(
            KeyValueRow("Expected to sell in", f"~{format_duration(v.sell_time.seconds)}")
        )

        if v.search.kept:
            matched = self._section(f"Matched on ({len(v.search.kept)})")
            for mod in v.search.kept:
                matched.addWidget(
                    KeyValueRow(str(mod), format_coins(int(mod.rank)), numeric=True)
                )

        if v.add_backs:
            priced = self._section(f"Priced separately ({len(v.add_backs)})")
            for add in v.add_backs:
                row = KeyValueRow(add.label, format_coins(add.applied))
                source = {
                    "MARKET": f"lowest BIN {format_coins(add.market_price)}",
                    "HEURISTIC": "from the pricing table",
                    "NONE": "not priced",
                }.get(add.source, add.source)
                row.value.setToolTip(source)
                row.label.setToolTip(source)
                if add.applied < 0:
                    row.value.setStyleSheet(f"color: {LOSS};")
                priced.addWidget(row)
            self._line(
                priced,
                "Each is shaved by its recovery rate and the discount in the"
                " pricing table: a book already applied is worth less than the"
                " book itself.",
            )

        if v.rules_fired:
            rules = self._section("Rules that fired")
            for firing in v.rules_fired:
                name = getattr(firing, "name", str(firing))
                detail = getattr(firing, "detail", "")
                row = KeyValueRow(name, detail, numeric=False)
                row.value.setFont(ui_font(SIZE_MICRO))
                row.value.setStyleSheet(f"color: {INK_DIM};")
                rules.addWidget(row)

        confidence = self._section(
            f"Confidence: {v.confidence.dots} of 4"
        )
        for reason in v.confidence.reasons:
            self._line(confidence, reason)
        for note in v.notes:
            self._line(confidence, note)

    # ---- the override --------------------------------------------------

    def _override_block(self, v: Valuation) -> QWidget:
        holder = QWidget()
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(0, GRID, 0, 0)
        layout.setSpacing(GRID)

        blurb = QLabel(
            "Set your own value. Every offer percentage moves with it."
        )
        blurb.setObjectName("faint")
        blurb.setFont(ui_font(SIZE_MICRO))
        layout.addWidget(blurb)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(GRID * 2)
        self.field = QLineEdit(format_coins_exact(v.estimate))
        self.field.setObjectName("numericInput")
        self.field.setPlaceholderText("e.g. 847.2m")
        self.field.returnPressed.connect(self._apply)
        apply_button = QPushButton("Apply")
        apply_button.setObjectName("primary")
        apply_button.clicked.connect(self._apply)
        reset = QPushButton("Use the market estimate")
        reset.setObjectName("ghost")
        reset.setEnabled(v.is_manual)
        reset.clicked.connect(self._reset)
        row.addWidget(self.field, 1)
        row.addWidget(apply_button)
        row.addWidget(reset)
        inner = QWidget()
        inner.setLayout(row)
        layout.addWidget(inner)

        self.error = QLabel("")
        self.error.setFont(ui_font(SIZE_MICRO))
        self.error.setStyleSheet(f"color: {LOSS};")
        layout.addWidget(self.error)
        return holder

    def _apply(self) -> None:
        try:
            coins = parse_coins(self.field.text())
        except ValueError:
            self.error.setText("Type an amount such as 847.2m or 847,200,000")
            return
        if coins < 0:
            self.error.setText("A value cannot be negative")
            return
        self.override_requested.emit(int(coins))
        self.accept()

    def _reset(self) -> None:
        self.override_requested.emit(None)
        self.accept()

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if event.key() == Qt.Key.Key_Escape:
            self.reject()
            return
        super().keyPressEvent(event)

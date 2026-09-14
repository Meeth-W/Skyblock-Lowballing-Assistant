"""The statistics view: six figures and two charts.

There used to be eight figures and five charts, and most of them answered
questions nobody was asking -- exit route composition and a sell-time
histogram are interesting once and never again. What is left answers the two
questions a lowballer actually has: am I making money, and how much of my
capital is stuck?

Kept items are reported on their own line rather than folded into the trading
P&L. Left in, a personal-use Hyperion reads as an unsold loss forever.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QGridLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ...ledger import Ledger
from ...money import format_coins, format_pct, format_signed
from ...stats import queries
from ..charts import AgeingChart, BarChart, ProfitChart
from ..theme import (
    GAIN,
    GRID,
    LOSS,
    SIZE_EMPHASIS,
    SIZE_MICRO,
    numeric_font,
    ui_font,
)
from ..widgets.primitives import Hairline, SectionLabel


class Figure(QWidget):
    """One headline number with its caption underneath."""

    def __init__(self, caption: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.value = QLabel("—")
        self.value.setFont(numeric_font(SIZE_EMPHASIS + 4))
        self.caption = QLabel(caption)
        self.caption.setObjectName("dim")
        self.caption.setFont(ui_font(SIZE_MICRO))
        layout.addWidget(self.value)
        layout.addWidget(self.caption)

    def set(self, text: str, *, colour: str | None = None, tooltip: str = "") -> None:
        self.value.setText(text)
        self.value.setStyleSheet(f"color: {colour};" if colour else "")
        if tooltip:
            self.setToolTip(tooltip)


class StatisticsView(QWidget):
    #: An age band on the ageing chart was clicked.
    bucket_clicked = Signal(object)

    def __init__(self, ledger: Ledger, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.ledger = ledger

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        body = QWidget()
        scroll.setWidget(body)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

        root = QVBoxLayout(body)
        root.setContentsMargins(GRID * 4, GRID * 4, GRID * 4, GRID * 4)
        root.setSpacing(GRID * 4)

        figures = QGridLayout()
        figures.setHorizontalSpacing(GRID * 8)
        figures.setVerticalSpacing(GRID * 3)
        self.f_profit = Figure("Realised profit, after tax")
        self.f_roi = Figure("Return on capital")
        self.f_deployed = Figure("Capital deployed")
        self.f_unrealised = Figure("Unrealised, marked to market")
        self.f_dead = Figure("Dead capital, held over a week")
        self.f_kept = Figure("Kept for personal use")
        for position, figure in enumerate(
            (
                self.f_profit, self.f_roi, self.f_deployed,
                self.f_unrealised, self.f_dead, self.f_kept,
            )
        ):
            figures.addWidget(figure, position // 3, position % 3)
        holder = QWidget()
        holder.setLayout(figures)
        root.addWidget(holder)
        root.addWidget(Hairline())

        self.charts: dict[str, QWidget] = {}
        root.addWidget(
            self._chart_block("Cumulative realised profit", ProfitChart(), "profit")
        )
        root.addWidget(
            self._chart_block("Capital by how long it has sat", AgeingChart(), "ageing")
        )
        root.addWidget(self._chart_block("Return by category", BarChart(), "roi"))
        root.addStretch(1)

        self.charts["ageing"].point_clicked.connect(self.bucket_clicked.emit)
        self.refresh()

    def _chart_block(self, title: str, chart: QWidget, key: str) -> QWidget:
        holder = QWidget()
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(GRID)
        layout.addWidget(SectionLabel(title))
        chart.setMinimumHeight(200)
        layout.addWidget(chart)
        self.charts[key] = chart
        return holder

    def refresh(self) -> None:
        conn = self.ledger.conn
        position = queries.position(conn)
        realised = queries.realised(conn)
        kept_count, kept_value = queries.kept_summary(conn)

        self.f_profit.set(
            format_signed(realised.profit),
            colour=GAIN if realised.profit > 0 else (LOSS if realised.profit < 0 else None),
            tooltip=(
                f"{format_coins(realised.gross)} gross,"
                f" {format_coins(realised.fees)} in claim tax,"
                f" across {realised.exits} sales"
            ),
        )
        self.f_roi.set(
            format_pct(realised.roi, signed=True) if realised.roi is not None else "—",
            colour=GAIN if (realised.roi or 0) > 0 else (
                LOSS if (realised.roi or 0) < 0 else None
            ),
            tooltip=f"Against {format_coins(realised.cost_basis)} of cost basis",
        )
        self.f_deployed.set(
            format_coins(position.cost_basis),
            tooltip=f"{position.items} items in stock",
        )
        self.f_unrealised.set(
            format_signed(position.unrealised),
            colour=GAIN if position.unrealised > 0 else (
                LOSS if position.unrealised < 0 else None
            ),
            tooltip=f"Marked at {format_coins(position.market_value)}",
        )
        self.f_dead.set(
            format_coins(position.dead_capital),
            colour=LOSS if position.dead_capital else None,
            tooltip=f"{position.dead_items} items held over seven days",
        )
        # A separate line, never inside the trading P&L.
        self.f_kept.set(
            f"{kept_count}",
            tooltip=f"{format_coins(kept_value)} at withdrawal",
        )

        exits = [
            dict(row)
            for row in conn.execute(
                "SELECT ts, profit, item_id FROM exits WHERE route != 'KEPT' ORDER BY ts"
            )
        ]
        self.charts["profit"].render(exits)
        self.charts["ageing"].render(queries.dead_capital_buckets(conn))
        self.charts["roi"].render(
            queries.roi_by_category(conn),
            annotate=lambda row: (
                f"  n={row['n']}, {format_coins(row['deployed'])} deployed"
            ),
        )

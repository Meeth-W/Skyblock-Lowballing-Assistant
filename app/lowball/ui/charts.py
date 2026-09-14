"""Charts, themed to the same tokens as everything else.

Surface background, hairline gridlines at 1px, ink-dim axis labels, no chart
borders, and no legend where direct labelling works instead.

Every chart is click-through to the rows behind it.  A number the user cannot
interrogate is a number they will not trust, and on a chart that is the
difference between a recommendation being believed and being ignored.
"""

from __future__ import annotations

from collections.abc import Callable

import pyqtgraph as pg
from PySide6.QtCore import Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import QVBoxLayout, QWidget

from ..money import format_coins
from .theme import (
    ACCENT,
    GAIN,
    GRID,
    HAIRLINE,
    INK,
    INK_DIM,
    LOSS,
    SIZE_MICRO,
    SURFACE,
    load_fonts,
)

pg.setConfigOption("background", SURFACE)
pg.setConfigOption("foreground", INK_DIM)
pg.setConfigOption("antialias", True)


def _axis_font() -> QFont:
    font = QFont(load_fonts()["num"], SIZE_MICRO)
    return font


class ChartBase(QWidget):
    """A themed plot with a title and a click-through signal."""

    point_clicked = Signal(object)

    def __init__(self, title: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(GRID)

        self.plot = pg.PlotWidget()
        self.plot.setBackground(SURFACE)
        self.plot.showGrid(x=True, y=True, alpha=0.18)
        self.plot.getPlotItem().getViewBox().setDefaultPadding(0.05)
        for side in ("left", "bottom"):
            axis = self.plot.getAxis(side)
            axis.setPen(pg.mkPen(HAIRLINE, width=1))
            axis.setTextPen(pg.mkPen(INK_DIM))
            axis.setStyle(tickFont=_axis_font(), tickTextOffset=6)
        for side in ("top", "right"):
            self.plot.getPlotItem().hideAxis(side)
        if title:
            self.plot.setTitle(title, color=INK, size=f"{SIZE_MICRO}pt")
        layout.addWidget(self.plot)

    def clear(self) -> None:
        self.plot.clear()

    def set_labels(self, x: str = "", y: str = "") -> None:
        style = {"color": INK_DIM, "font-size": f"{SIZE_MICRO}px"}
        if x:
            self.plot.setLabel("bottom", x, **style)
        if y:
            self.plot.setLabel("left", y, **style)

    def show_empty(self, message: str) -> None:
        self.clear()
        text = pg.TextItem(message, color=INK_DIM, anchor=(0.5, 0.5))
        text.setFont(QFont(load_fonts()["ui"], SIZE_MICRO))
        self.plot.addItem(text)
        text.setPos(0.5, 0.5)
        self.plot.setXRange(0, 1, padding=0)
        self.plot.setYRange(0, 1, padding=0)


class CoinAxis(pg.AxisItem):
    """Y axis in 847.2M form rather than raw digits."""

    def tickStrings(self, values, scale, spacing):  # noqa: N802 - pyqtgraph naming
        return [format_coins(v) if abs(v) >= 1000 else f"{v:.0f}" for v in values]


class PercentAxis(pg.AxisItem):
    def tickStrings(self, values, scale, spacing):  # noqa: N802 - pyqtgraph naming
        return [f"{v * 100:.0f}%" for v in values]


class ProfitChart(ChartBase):
    """Cumulative realised profit over time, with the routes banded apart."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("", parent)
        self.plot.setAxisItems({"left": CoinAxis(orientation="left")})
        self.set_labels("", "Cumulative profit")

    def render(self, exits: list[dict]) -> None:
        self.clear()
        if not exits:
            self.show_empty("No completed sales yet")
            return

        ordered = sorted(exits, key=lambda e: e["ts"] or "")
        running = 0
        xs, ys = [], []
        outliers_x, outliers_y, outlier_labels = [], [], []
        threshold = max(abs(e["profit"]) for e in ordered) * 0.4 if ordered else 0

        for index, row in enumerate(ordered):
            running += int(row["profit"] or 0)
            xs.append(index)
            ys.append(running)
            if threshold and abs(int(row["profit"] or 0)) >= threshold:
                outliers_x.append(index)
                outliers_y.append(running)
                outlier_labels.append(row)

        self.plot.plot(xs, ys, pen=pg.mkPen(ACCENT, width=2))
        self.plot.addItem(
            pg.InfiniteLine(pos=0, angle=0, pen=pg.mkPen(HAIRLINE, width=1))
        )
        if outliers_x:
            # Big single wins and losses are marked so they stay traceable to
            # the item that caused them.
            self.plot.addItem(
                pg.ScatterPlotItem(
                    x=outliers_x,
                    y=outliers_y,
                    size=9,
                    pen=pg.mkPen(INK, width=1),
                    brush=pg.mkBrush(QColor(GAIN if ys[-1] >= 0 else LOSS)),
                )
            )
        self.set_labels("Sales, oldest first", "Cumulative profit")


class BarChart(ChartBase):
    """Horizontal bars with direct labels instead of a legend."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("", parent)
        self.plot.setAxisItems({"bottom": CoinAxis(orientation="bottom")})
        self._rows: list[dict] = []
        self.plot.scene().sigMouseClicked.connect(self._on_click)

    def render(
        self,
        rows: list[dict],
        *,
        value_key: str = "profit",
        label_key: str = "category",
        annotate: Callable[[dict], str] | None = None,
    ) -> None:
        self.clear()
        self._rows = rows
        if not rows:
            self.show_empty("Nothing to show yet")
            return

        labels = [str(r[label_key]) for r in rows]
        values = [int(r[value_key] or 0) for r in rows]
        positions = list(range(len(rows)))

        self.plot.addItem(
            pg.BarGraphItem(
                x0=[min(0, v) for v in values],
                y=positions,
                height=0.55,
                width=[abs(v) for v in values],
                brushes=[pg.mkBrush(QColor(GAIN if v >= 0 else LOSS)) for v in values],
                pen=pg.mkPen(None),
            )
        )

        axis = self.plot.getAxis("left")
        axis.setTicks([[(i, labels[i]) for i in positions]])
        axis.setStyle(tickFont=QFont(load_fonts()["ui"], SIZE_MICRO))

        if annotate is not None:
            # The count and the capital deployed sit on the bar: a 40% return
            # on two items is noise, and the chart should say so in place.
            for index, row in enumerate(rows):
                text = pg.TextItem(annotate(row), color=INK_DIM, anchor=(0, 0.5))
                text.setFont(QFont(load_fonts()["ui"], SIZE_MICRO))
                text.setPos(max(values[index], 0), index)
                self.plot.addItem(text)

        self.plot.invertY(True)

    def _on_click(self, event) -> None:
        position = self.plot.getPlotItem().vb.mapSceneToView(event.scenePos())
        index = int(round(position.y()))
        if 0 <= index < len(self._rows):
            self.point_clicked.emit(self._rows[index])


class AgeingChart(ChartBase):
    """Coins tied up by age band.

    This chart exists to make dead capital impossible to ignore, so the two
    oldest bands are drawn in the loss colour whatever they contain.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("", parent)
        self.plot.setAxisItems({"left": CoinAxis(orientation="left")})
        self._buckets: list[tuple[str, int, int]] = []
        self.plot.scene().sigMouseClicked.connect(self._on_click)

    def render(self, buckets: list[tuple[str, int, int]]) -> None:
        self.clear()
        self._buckets = buckets
        if not buckets or all(coins == 0 for _, _, coins in buckets):
            self.show_empty("Nothing held")
            return

        positions = list(range(len(buckets)))
        values = [coins for _, _, coins in buckets]
        colours = [
            QColor(LOSS if label in {"7-14d", "14d+"} else ACCENT) for label, _, _ in buckets
        ]
        self.plot.addItem(
            pg.BarGraphItem(
                x=positions,
                height=values,
                width=0.6,
                brushes=[pg.mkBrush(c) for c in colours],
                pen=pg.mkPen(None),
            )
        )
        axis = self.plot.getAxis("bottom")
        axis.setTicks([[(i, buckets[i][0]) for i in positions]])
        axis.setStyle(tickFont=QFont(load_fonts()["ui"], SIZE_MICRO))
        self.set_labels("Days held", "Capital")

    def _on_click(self, event) -> None:
        position = self.plot.getPlotItem().vb.mapSceneToView(event.scenePos())
        index = int(round(position.x()))
        if 0 <= index < len(self._buckets):
            self.point_clicked.emit(self._buckets[index])

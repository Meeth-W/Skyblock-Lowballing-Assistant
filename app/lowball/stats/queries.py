"""Aggregations over the ledger.

Every figure in the reports and statistics tabs comes from here, and every one
of them is a query against projected state rather than a number kept anywhere.
That is what makes a correction event able to change history: nothing is
cached, so nothing has to be invalidated.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from ..timeutil import age_days

#: Held longer than this and the capital is doing nothing.  This is where
#: lowballers quietly bleed, so it gets its own figure and its own chart.
DEAD_CAPITAL_DAYS = 7.0


@dataclass(frozen=True)
class Position:
    """What is currently held, marked to the last recorded valuation."""

    items: int = 0
    cost_basis: int = 0
    market_value: int = 0
    dead_items: int = 0
    dead_capital: int = 0

    @property
    def unrealised(self) -> int:
        return self.market_value - self.cost_basis

    @property
    def dead_share(self) -> float:
        return self.dead_capital / self.cost_basis if self.cost_basis else 0.0


@dataclass(frozen=True)
class Realised:
    """Profit actually banked, after every tax and every sunk fee."""

    gross: int = 0
    fees: int = 0
    net: int = 0
    cost_basis: int = 0
    profit: int = 0
    exits: int = 0

    @property
    def roi(self) -> float | None:
        return self.profit / self.cost_basis if self.cost_basis else None


def position(conn: sqlite3.Connection) -> Position:
    rows = conn.execute(
        "SELECT cost_basis, est_value_now, acquired_ts FROM items WHERE state = 'HELD'"
    ).fetchall()
    cost = value = dead_items = dead_capital = 0
    for row in rows:
        basis = int(row["cost_basis"] or 0)
        cost += basis
        # Unvalued items are marked at cost rather than at zero; a missing
        # valuation is not the same as a worthless item.
        value += int(row["est_value_now"] or basis)
        if row["acquired_ts"] and age_days(row["acquired_ts"]) >= DEAD_CAPITAL_DAYS:
            dead_items += 1
            dead_capital += basis
    return Position(len(rows), cost, value, dead_items, dead_capital)


def realised(conn: sqlite3.Connection, *, route: str | None = None) -> Realised:
    """Realised P&L.  Kept items are excluded: they are a withdrawal, not a sale."""
    sql = (
        "SELECT COALESCE(SUM(gross),0) g, COALESCE(SUM(fees_total),0) f,"
        " COALESCE(SUM(net),0) n, COALESCE(SUM(cost_basis),0) c,"
        " COALESCE(SUM(profit),0) p, COUNT(*) k FROM exits WHERE route != 'KEPT'"
    )
    params: tuple = ()
    if route is not None:
        sql += " AND route = ?"
        params = (route,)
    row = conn.execute(sql, params).fetchone()
    return Realised(
        gross=int(row["g"]),
        fees=int(row["f"]),
        net=int(row["n"]),
        cost_basis=int(row["c"]),
        profit=int(row["p"]),
        exits=int(row["k"]),
    )


def kept_summary(conn: sqlite3.Connection) -> tuple[int, int]:
    """Kept items reported on their own line: (count, value at withdrawal).

    Leaving them in the trading P&L would make a personal-use Hyperion read as
    an unsold loss forever.
    """
    row = conn.execute(
        "SELECT COUNT(*) k, COALESCE(SUM(gross),0) g FROM exits WHERE route = 'KEPT'"
    ).fetchone()
    return int(row["k"]), int(row["g"])


def roi_by_category(conn: sqlite3.Connection) -> list[dict]:
    """Return by category, with the item count alongside.

    The count matters: a 40% return on two items is noise, and a chart that
    shows the bar without the n invites exactly the wrong conclusion.
    """
    rows = conn.execute(
        "SELECT COALESCE(i.category, 'Other') AS category,"
        " COUNT(*) AS n,"
        " COALESCE(SUM(e.cost_basis), 0) AS deployed,"
        " COALESCE(SUM(e.profit), 0) AS profit"
        " FROM exits AS e JOIN items AS i ON i.item_id = e.item_id"
        " WHERE e.route != 'KEPT'"
        " GROUP BY COALESCE(i.category, 'Other')"
        " ORDER BY profit DESC"
    ).fetchall()
    return [
        {
            "category": row["category"],
            "n": int(row["n"]),
            "deployed": int(row["deployed"]),
            "profit": int(row["profit"]),
            "roi": (int(row["profit"]) / int(row["deployed"])) if row["deployed"] else None,
        }
        for row in rows
    ]


#: Age bands for held capital, in days.
AGE_BANDS: tuple[tuple[str, float, float], ...] = (
    ("0-1d", 0.0, 1.0),
    ("1-3d", 1.0, 3.0),
    ("3-7d", 3.0, 7.0),
    ("7-14d", 7.0, 14.0),
    ("14d+", 14.0, float("inf")),
)


def dead_capital_buckets(conn: sqlite3.Connection) -> list[tuple[str, int, int]]:
    """Coins tied up by age band: (label, item count, coins)."""
    totals = {label: [0, 0] for label, _, _ in AGE_BANDS}
    for row in conn.execute(
        "SELECT cost_basis, acquired_ts FROM items WHERE state = 'HELD'"
    ):
        if not row["acquired_ts"]:
            continue
        age = age_days(row["acquired_ts"])
        for label, low, high in AGE_BANDS:
            if low <= age < high:
                totals[label][0] += 1
                totals[label][1] += int(row["cost_basis"] or 0)
                break
    return [(label, totals[label][0], totals[label][1]) for label, _, _ in AGE_BANDS]


def items_in_age_band(conn: sqlite3.Connection, label: str) -> list[str]:
    """Which held items sit in one band, so a chart click can filter the ledger."""
    band = next((b for b in AGE_BANDS if b[0] == label), None)
    if band is None:
        return []
    _, low, high = band
    out: list[str] = []
    for row in conn.execute(
        "SELECT item_id, acquired_ts FROM items WHERE state = 'HELD'"
    ):
        if not row["acquired_ts"]:
            continue
        if low <= age_days(row["acquired_ts"]) < high:
            out.append(str(row["item_id"]))
    return out

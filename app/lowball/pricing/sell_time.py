"""How long an item will take to sell.

Two sources.  Coflnet publishes a median sell time per tag, which covers the
whole market.  The ledger knows how long *this user's* stock actually took to
move, which is better -- it reflects their own pricing and their own patience
-- but sparse.  The two are blended with the shrinkage in :mod:`shrinkage`.

Personal sell time is measured from **acquisition** to the sale rather than
from a listing, because acquisition is when the capital started being tied up
and the offer floor is charging for exactly that.  An item that sat in the
inventory for three days before anyone listed it took three days.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from ..api.models import PriceAnalysis
from ..parsing.categories import shrinkage_key
from ..parsing.signature import ItemSignature
from .shrinkage import DEFAULT_K, shrink_geometric

#: Used when nothing at all is known.  Two days is one auction duration, which
#: is the point at which a relist fee starts to bite.
FALLBACK_SELL_SECONDS = 48 * 3600.0

_SOLD_ITEMS_SQL = """
SELECT
    i.tag           AS tag,
    i.category      AS category,
    e.hold_seconds  AS hold_seconds
FROM exits AS e
JOIN items AS i ON i.item_id = e.item_id
WHERE e.route = 'SOLD' AND e.hold_seconds IS NOT NULL AND e.hold_seconds > 0
"""


@dataclass(frozen=True)
class SellTimeEstimate:
    seconds: float
    source: str          # PERSONAL | BLENDED | PUBLIC | FALLBACK
    n: int
    personal_weight: float
    public_seconds: float | None = None

    @property
    def hours(self) -> float:
        return self.seconds / 3600.0

    @property
    def days(self) -> float:
        return self.seconds / 86_400.0

    @property
    def is_guess(self) -> bool:
        return self.source == "FALLBACK"


def personal_sell_times(
    conn: sqlite3.Connection, *, tag: str | None = None, category: str | None = None
) -> list[float]:
    """Observed hold time on items that sold, filtered to a tag or category."""
    rows = conn.execute(_SOLD_ITEMS_SQL).fetchall()
    out: list[float] = []
    for row in rows:
        if tag is not None and row["tag"] != tag:
            continue
        if category is not None and row["category"] != category:
            continue
        out.append(float(row["hold_seconds"]))
    return out


def estimate_sell_time(
    conn: sqlite3.Connection | None,
    sig: ItemSignature,
    analysis: PriceAnalysis | None = None,
    *,
    k: float = DEFAULT_K,
) -> SellTimeEstimate:
    """Blend personal history with Coflnet's median for this tag."""
    public = analysis.median_sell_seconds if analysis else None

    if conn is None:
        seconds = public or FALLBACK_SELL_SECONDS
        return SellTimeEstimate(
            seconds=seconds,
            source="PUBLIC" if public else "FALLBACK",
            n=0,
            personal_weight=0.0,
            public_seconds=public,
        )

    category = shrinkage_key(sig)
    levels = [
        ("tag", personal_sell_times(conn, tag=sig.tag)),
        ("category", personal_sell_times(conn, category=category)),
        ("global", personal_sell_times(conn)),
    ]
    result = shrink_geometric(levels, public, k=k)

    if result.level == "none":
        return SellTimeEstimate(
            FALLBACK_SELL_SECONDS, "FALLBACK", 0, 0.0, public
        )
    if result.personal_weight <= 0.0:
        source = "PUBLIC"
    elif result.personal_weight >= 0.85:
        source = "PERSONAL"
    else:
        source = "BLENDED"
    return SellTimeEstimate(
        seconds=max(60.0, result.value),
        source=source,
        n=result.n,
        personal_weight=result.personal_weight,
        public_seconds=public,
    )

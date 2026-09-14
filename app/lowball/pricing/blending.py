"""Turning comparables into one number.

Two inputs, each wrong in its own way.

The lowest BIN is a ceiling -- to sell quickly you have to undercut it -- but
raw lowest BIN is regularly a typo, a manipulation, or a scam listing, so it is
sanitised against the recent-sales median before being trusted.

The median of matching recent sales is what items like this actually fetch, but
it lags and it says nothing about what is on the market right now.

Fast movers weight toward the BIN, because the market is deep enough that the
cheapest listing is the real price.  Slow movers weight toward the median,
because on a thin market the cheapest listing is often one optimistic seller.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field

from ..api.models import Auction, PriceAnalysis

#: A listing below this fraction of the median is not a price, it is a mistake.
LBIN_TOLERANCE = 0.35

#: How far down the listing book sanitisation is willing to walk.
MAX_LBIN_SKIP = 4

#: What has to be given up to actually move an item rather than sit behind the
#: cheapest listing.  The estimate is a realisable price, not a shelf price.
UNDERCUT_ALLOWANCE = 0.02

#: Sales per day at which a market counts as fully liquid for weighting.
LIQUID_SALES_PER_DAY = 24.0

MIN_LBIN_WEIGHT = 0.15
MAX_LBIN_WEIGHT = 0.65


@dataclass(frozen=True)
class LbinResult:
    """The sanitised lowest BIN, and what was thrown out to get there."""

    price: int | None
    listing: Auction | None = None
    rejected: tuple[Auction, ...] = ()
    reason: str = "OK"
    validated: bool = True

    @property
    def rejected_count(self) -> int:
        return len(self.rejected)


def sanitise_lbin(
    active: list[Auction] | tuple[Auction, ...],
    median: int | None,
    *,
    tolerance: float = LBIN_TOLERANCE,
    max_skip: int = MAX_LBIN_SKIP,
) -> LbinResult:
    """The cheapest listing that is plausibly a real price.

    Walks up from the bottom of the book until a listing sits within tolerance
    of the median.  Everything skipped is kept so the UI can show what was
    ignored -- the user should be able to see a rejected 3M Hyperion and judge
    for themselves.
    """
    listings = sorted(
        (a for a in active if a.unit_price > 0), key=lambda a: a.unit_price
    )
    if not listings:
        return LbinResult(None, None, (), "NO_LISTINGS", validated=False)
    if not median:
        # Nothing to validate against.  Take the lowest, flag it as unchecked.
        return LbinResult(
            listings[0].unit_price, listings[0], (), "NO_MEDIAN", validated=False
        )

    floor = int(median * (1.0 - tolerance))
    rejected: list[Auction] = []
    for listing in listings[: max_skip + 1]:
        if listing.unit_price >= floor:
            return LbinResult(
                listing.unit_price,
                listing,
                tuple(rejected),
                "OK" if not rejected else "SKIPPED_OUTLIERS",
            )
        rejected.append(listing)

    # Every listing near the bottom looks wrong.  That is itself information:
    # either the market has crashed or the book is being manipulated.
    remaining = listings[max_skip + 1 :]
    if remaining:
        return LbinResult(
            remaining[0].unit_price, remaining[0], tuple(rejected), "ALL_BELOW_BAND", False
        )
    return LbinResult(median, None, tuple(rejected), "ALL_BELOW_BAND", validated=False)


@dataclass(frozen=True)
class Blend:
    """The blended estimate, with every input kept for display."""

    estimate: int
    lbin: int | None
    median: int | None
    lbin_weight: float
    undercut: float
    spread: float = 0.0
    sample: int = 0
    inputs: dict[str, int] = field(default_factory=dict)

    @property
    def has_market(self) -> bool:
        return self.lbin is not None or self.median is not None


def liquidity_score(analysis: PriceAnalysis | None, sample: int) -> float:
    """0.0 for a dead market, 1.0 for one deep enough to price off the book."""
    if analysis is None:
        # No market data at all; lean on whatever comparables came back.
        return min(1.0, sample / 20.0) * 0.5
    by_volume = min(1.0, analysis.sales_per_day / LIQUID_SALES_PER_DAY)
    if analysis.median_sell_seconds:
        # Under an hour to sell is a fast mover; a day or more is not.
        by_speed = min(1.0, 3600.0 / max(60.0, analysis.median_sell_seconds))
    else:
        by_speed = by_volume
    return max(0.0, min(1.0, 0.5 * by_volume + 0.5 * by_speed))


def price_spread(prices: list[int]) -> float:
    """Coefficient of variation of the comparables: how much they disagree."""
    usable = [p for p in prices if p > 0]
    if len(usable) < 2:
        return 0.0
    mean = statistics.fmean(usable)
    if mean <= 0:
        return 0.0
    return statistics.pstdev(usable) / mean


def blend(
    *,
    lbin: int | None,
    median: int | None,
    analysis: PriceAnalysis | None = None,
    sold_prices: list[int] | None = None,
    undercut: float = UNDERCUT_ALLOWANCE,
) -> Blend:
    """Combine the cheapest listing and the recent-sales median into one price."""
    sold_prices = sold_prices or []
    sample = len(sold_prices)
    spread = price_spread(sold_prices)

    if lbin is None and median is None:
        return Blend(0, None, None, 0.0, undercut, spread, sample)
    if lbin is None:
        base = float(median or 0)
        weight = 0.0
    elif median is None:
        base = float(lbin)
        weight = 1.0
    else:
        score = liquidity_score(analysis, sample)
        weight = MIN_LBIN_WEIGHT + (MAX_LBIN_WEIGHT - MIN_LBIN_WEIGHT) * score
        base = weight * lbin + (1.0 - weight) * median

    # The estimate is what the item can be sold for, which means listing under
    # the cheapest competitor rather than alongside it.
    estimate = int(base * (1.0 - undercut))
    return Blend(
        estimate=max(0, estimate),
        lbin=lbin,
        median=median,
        lbin_weight=weight,
        undercut=undercut,
        spread=spread,
        sample=sample,
        inputs={"base": int(base)},
    )


def median_of(prices: list[int]) -> int | None:
    usable = [p for p in prices if p > 0]
    if not usable:
        return None
    return int(statistics.median(usable))

"""How much to trust the number.

A confidently wrong estimate on a 500M item is how a lowballer goes broke, so
this is never hidden and never rounded up.  Three things drag it down:

* **too few comparables** -- one matching sale is an anecdote;
* **a wide spread** -- if matching sales range over 40%, there is no single
  price, and the midpoint is a fiction;
* **modifiers priced separately** -- every modifier stripped out of the query
  and added back from its own market is a second estimate stacked on the first.

The third is weighted by *value*, not by count.  Dropping Scavenger V off a
Hyperion costs nothing; dropping a Chimera V means most of the price is now an
add-back rather than an observation.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

#: Comparable count at which sample size stops being the limiting factor.
FULL_SAMPLE = 20

#: Spread at which the comparables have stopped agreeing on a price at all.
MAX_USEFUL_SPREAD = 0.5

#: Share of the estimate that can come from add-backs before it dominates.
MAX_ADDBACK_SHARE = 0.5

#: How much of the score the spread and add-back terms can move, once
#: there are enough comparables for them to mean anything.
WEIGHT_SAMPLE = 0.45
WEIGHT_SPREAD = 0.30
WEIGHT_ADDBACK = 0.25


@dataclass(frozen=True)
class Confidence:
    score: float
    dots: int
    sample: int
    spread: float
    dropped: int
    kept: int
    addback_share: float
    reasons: tuple[str, ...] = ()

    @property
    def is_low(self) -> bool:
        """Two dots or fewer should look visibly less solid in the UI."""
        return self.dots <= 2

    @property
    def modifier_fraction(self) -> str:
        total = self.kept + self.dropped
        return f"{self.kept}/{total}" if total else "0/0"


def _sample_score(n: int) -> float:
    if n <= 0:
        return 0.0
    # Diminishing returns: the step from 1 to 5 comparables matters far more
    # than the step from 15 to 20.
    return min(1.0, math.log1p(n) / math.log1p(FULL_SAMPLE))


def _spread_score(spread: float) -> float:
    return max(0.0, 1.0 - (max(0.0, spread) / MAX_USEFUL_SPREAD))


def _addback_score(share: float) -> float:
    return max(0.0, 1.0 - (max(0.0, share) / MAX_ADDBACK_SHARE))


def score(
    *,
    sample: int,
    spread: float,
    kept: int = 0,
    dropped: int = 0,
    addback_total: int = 0,
    estimate: int = 0,
) -> Confidence:
    share = 0.0
    if estimate > 0 and addback_total > 0:
        share = min(1.0, addback_total / estimate)

    # Sample size multiplies rather than averages.  Averaging lets a query
    # that found nothing score two dots on the strength of having no spread
    # and no add-backs, which is precisely the confident-wrong-number failure
    # this score exists to prevent.
    quality = (
        WEIGHT_SPREAD * _spread_score(spread) + WEIGHT_ADDBACK * _addback_score(share)
    ) / (WEIGHT_SPREAD + WEIGHT_ADDBACK)
    total = _sample_score(sample) * (1.0 - WEIGHT_SAMPLE + WEIGHT_SAMPLE * quality)

    reasons: list[str] = []
    if sample == 0:
        reasons.append("No matching sales found")
    elif sample < 3:
        reasons.append(f"Only {sample} matching sale{'s' if sample != 1 else ''}")
    elif sample < 10:
        reasons.append(f"{sample} matching sales")
    if spread > 0.25:
        reasons.append(f"Matching sales range over {spread * 100:.0f}%")
    if share > 0.2:
        reasons.append(f"{share * 100:.0f}% of the estimate is priced from add-backs")
    if dropped and not reasons:
        reasons.append(f"{dropped} modifier{'s' if dropped != 1 else ''} priced separately")

    return Confidence(
        score=round(total, 4),
        dots=_dots(total),
        sample=sample,
        spread=round(spread, 4),
        dropped=dropped,
        kept=kept,
        addback_share=round(share, 4),
        reasons=tuple(reasons),
    )


def _dots(value: float) -> int:
    for threshold, dots in ((0.80, 4), (0.60, 3), (0.40, 2), (0.20, 1)):
        if value >= threshold:
            return dots
    return 0

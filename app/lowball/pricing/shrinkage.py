"""Hierarchical shrinkage.

Personal data is better than public data -- it reflects how *this* user relists
and undercuts, and which offers *their* customers accept -- but there is never
much of it.  Shrinkage is how both get used: start from the broad estimate and
pull it toward the specific one in proportion to how much specific data exists.

The ladder runs item tag, then category, then value bucket, then global, then
whatever public prior is available.  With two observations on a tag the answer
is mostly the category; with forty it is mostly the tag.

``k`` is the pseudo-count: the number of observations at which a level carries
equal weight with everything broader.  Five is deliberately conservative.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

#: Observations at which a level is trusted as much as the level above it.
DEFAULT_K = 5.0

#: Below this many observations at every level, report raw counts instead of a
#: modelled number.  The brief is explicit: never render a model-backed
#: prediction on thin data.
MIN_FOR_MODEL = 5


@dataclass(frozen=True)
class ShrunkEstimate:
    value: float
    #: Observations at the most specific level that had any.
    n: int
    #: Which rung of the ladder supplied most of the weight.
    level: str
    #: How much of the final number came from personal data rather than prior.
    personal_weight: float
    has_enough_data: bool

    @property
    def is_prior_only(self) -> bool:
        return self.n == 0


def shrink_mean(
    levels: list[tuple[str, list[float]]],
    prior: float | None = None,
    *,
    k: float = DEFAULT_K,
) -> ShrunkEstimate:
    """Fold observations inward, most general first.

    ``levels`` is ordered most specific first, which is how callers naturally
    build it; the fold runs in reverse so each level pulls the running estimate
    toward itself.
    """
    estimate = prior
    total_n = 0
    chosen = "prior"
    personal_weight = 0.0

    for name, values in reversed(levels):
        usable = [v for v in values if v is not None]
        n = len(usable)
        if not n:
            continue
        mean = sum(usable) / n
        if estimate is None:
            estimate = mean
            personal_weight = 1.0
        else:
            weight = n / (n + k)
            estimate = weight * mean + (1.0 - weight) * estimate
            personal_weight = weight + (1.0 - weight) * personal_weight
        total_n = n
        chosen = name

    if estimate is None:
        return ShrunkEstimate(0.0, 0, "none", 0.0, False)
    most_specific_n = len(levels[0][1]) if levels else 0
    return ShrunkEstimate(
        value=estimate,
        n=total_n,
        level=chosen,
        personal_weight=round(personal_weight, 4),
        has_enough_data=(most_specific_n >= MIN_FOR_MODEL or total_n >= MIN_FOR_MODEL),
    )


def shrink_geometric(
    levels: list[tuple[str, list[float]]],
    prior: float | None = None,
    *,
    k: float = DEFAULT_K,
) -> ShrunkEstimate:
    """Shrink in log space, for quantities with a long right tail.

    Sell times are the case that matters: a handful of items that sat for a
    week would drag an arithmetic mean somewhere no item actually sells.
    """
    log_levels = [
        (name, [math.log(max(1e-9, v)) for v in values if v and v > 0])
        for name, values in levels
    ]
    log_prior = math.log(prior) if prior and prior > 0 else None
    result = shrink_mean(log_levels, log_prior, k=k)
    return ShrunkEstimate(
        value=math.exp(result.value) if result.level != "none" else 0.0,
        n=result.n,
        level=result.level,
        personal_weight=result.personal_weight,
        has_enough_data=result.has_enough_data,
    )


def shrink_rate(
    levels: list[tuple[str, tuple[int, int]]],
    prior_rate: float = 0.5,
    *,
    k: float = DEFAULT_K,
) -> ShrunkEstimate:
    """Shrink a success rate, given (successes, trials) per level.

    Used for P(accept).  A single accepted offer out of one is not a 100%
    acceptance rate, and this is what stops the app claiming it is.
    """
    estimate = prior_rate
    total_n = 0
    chosen = "prior"
    personal_weight = 0.0

    for name, (successes, trials) in reversed(levels):
        if trials <= 0:
            continue
        rate = successes / trials
        weight = trials / (trials + k)
        estimate = weight * rate + (1.0 - weight) * estimate
        personal_weight = weight + (1.0 - weight) * personal_weight
        total_n = trials
        chosen = name

    most_specific = levels[0][1][1] if levels else 0
    return ShrunkEstimate(
        value=max(0.0, min(1.0, estimate)),
        n=total_n,
        level=chosen,
        personal_weight=round(personal_weight, 4),
        has_enough_data=(most_specific >= MIN_FOR_MODEL or total_n >= MIN_FOR_MODEL),
    )

"""P(accept | offer percentage), and the offer that maximises expected value.

Fitted from the user's own logged offers.  Rejections are the valuable half of
that data: logging only accepted offers makes every observed acceptance rate
100% and the model worthless, which is why the session state machine records a
rejection before it opens the next offer.

**Outcome handling.**  A confirmed offer is an accept.  A rejection or a
counter is not -- a counter means the customer declined *that* number, even
though they stayed at the table.  A walk-away is excluded entirely: the
customer never answered, so it says nothing about whether the price was
acceptable, and folding it in as a rejection would bias every curve downward.

**Cold start.**  With no history the fit returns a prior curve rather than
nothing, so the chart and the recommendation have something to show on day one.
The prior is deliberately bland: about three quarters of customers accept a 7%
lowball, about a fifth accept 25%.  Real observations override it quickly.
"""

from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass, field

from ..money import value_bucket
from .shrinkage import MIN_FOR_MODEL

#: Logit of the cold-start curve: 75% acceptance at -7%, 20% at -25%.
PRIOR_INTERCEPT = 2.065
PRIOR_SLOPE = -13.805

#: Weight of the prior, in pseudo-observations.  Low enough that a dozen real
#: offers dominate it, high enough to keep an early fit from swinging wildly.
PRIOR_WEIGHT = 6.0

#: How much each rung of the hierarchy counts toward the fit.
LEVEL_WEIGHTS: dict[str, float] = {
    "tag": 1.0,
    "category": 0.45,
    "bucket": 0.25,
    "global": 0.12,
}


@dataclass(frozen=True)
class Observation:
    pct: float
    accepted: bool
    level: str = "tag"
    is_exploration: bool = False

    @property
    def weight(self) -> float:
        return LEVEL_WEIGHTS.get(self.level, 0.1)


@dataclass
class AcceptanceCurve:
    """A fitted logistic, plus enough context to say how much to trust it."""

    intercept: float
    slope: float
    n_tag: int = 0
    n_total: int = 0
    observations: list[Observation] = field(default_factory=list)

    def probability(self, pct: float) -> float:
        z = self.intercept + self.slope * pct
        # Guard the exponential so an extreme fit cannot overflow.
        if z < -60:
            return 0.0
        if z > 60:
            return 1.0
        return 1.0 / (1.0 + math.exp(-z))

    @property
    def has_enough_data(self) -> bool:
        """Below this, the UI shows raw counts instead of a prediction."""
        return self.n_tag >= MIN_FOR_MODEL

    @property
    def is_prior_only(self) -> bool:
        return self.n_total == 0


def fit_logistic(
    observations: list[Observation],
    *,
    prior_weight: float = PRIOR_WEIGHT,
    iterations: int = 60,
) -> tuple[float, float]:
    """Weighted logistic fit by gradient ascent, anchored on the prior.

    The prior enters as pseudo-observations spread along the ladder rather than
    as a penalty term, which keeps the fit well behaved when every real
    observation happens to share an outcome -- five rejections in a row would
    otherwise drive the slope to infinity.
    """
    points: list[tuple[float, float, float]] = []  # (pct, outcome, weight)
    for obs in observations:
        points.append((obs.pct, 1.0 if obs.accepted else 0.0, obs.weight))
    if prior_weight > 0:
        per_point = prior_weight / 5.0
        for pct in (0.05, 0.10, 0.15, 0.20, 0.25):
            target = 1.0 / (1.0 + math.exp(-(PRIOR_INTERCEPT + PRIOR_SLOPE * pct)))
            points.append((pct, target, per_point))
    if not points:
        return PRIOR_INTERCEPT, PRIOR_SLOPE

    a, b = PRIOR_INTERCEPT, PRIOR_SLOPE
    total_weight = sum(w for _, _, w in points) or 1.0
    rate = 2.0
    for _ in range(iterations):
        grad_a = grad_b = 0.0
        for pct, target, weight in points:
            z = a + b * pct
            z = max(-60.0, min(60.0, z))
            predicted = 1.0 / (1.0 + math.exp(-z))
            error = target - predicted
            grad_a += weight * error
            grad_b += weight * error * pct
        a += rate * grad_a / total_weight
        b += rate * grad_b / total_weight
    return a, b


_OFFER_SQL = """
SELECT o.offer_pct        AS pct,
       o.outcome          AS outcome,
       o.tag              AS tag,
       o.est_value        AS est_value,
       o.is_exploration   AS is_exploration,
       i.category         AS category
FROM offers AS o
LEFT JOIN items AS i ON i.session_id = o.session_id
WHERE o.outcome IN ('CONFIRMED', 'REJECTED', 'COUNTERED')
  AND o.offer_pct IS NOT NULL
"""


def load_observations(
    conn: sqlite3.Connection,
    *,
    tag: str | None = None,
    category: str | None = None,
    bucket: str | None = None,
) -> list[Observation]:
    """Every usable offer, labelled by which rung of the hierarchy it matches."""
    rows = conn.execute(_OFFER_SQL).fetchall()
    out: list[Observation] = []
    for row in rows:
        accepted = row["outcome"] == "CONFIRMED"
        row_bucket = value_bucket(int(row["est_value"] or 0))
        if tag is not None and row["tag"] == tag:
            level = "tag"
        elif category is not None and row["category"] == category:
            level = "category"
        elif bucket is not None and row_bucket == bucket:
            level = "bucket"
        else:
            level = "global"
        out.append(
            Observation(
                pct=float(row["pct"]),
                accepted=accepted,
                level=level,
                is_exploration=bool(row["is_exploration"]),
            )
        )
    return out


def fit_curve(
    conn: sqlite3.Connection | None,
    *,
    tag: str | None = None,
    category: str | None = None,
    bucket: str | None = None,
) -> AcceptanceCurve:
    if conn is None:
        return AcceptanceCurve(PRIOR_INTERCEPT, PRIOR_SLOPE)
    observations = load_observations(conn, tag=tag, category=category, bucket=bucket)
    intercept, slope = fit_logistic(observations)
    return AcceptanceCurve(
        intercept=intercept,
        slope=slope,
        n_tag=sum(1 for o in observations if o.level == "tag"),
        n_total=len(observations),
        observations=observations,
    )

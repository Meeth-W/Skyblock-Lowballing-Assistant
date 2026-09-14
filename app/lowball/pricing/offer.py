"""What to offer.

Three layers, in increasing order of how much they know.

The **floor** is arithmetic: below a certain discount the trade cannot make
money, whatever the customer would accept.  It covers the claim tax, every
listing fee the expected hold will incur, the risk that a volatile item moves
against you while you hold it, the return that capital should have earned
elsewhere, and the margin the business runs on.

The **ladder** is the fixed set of rungs the user actually clicks: the
estimate, the estimate net of tax, and every step from -7% to -15%.

The **recommendation** is empirical, and only appears once there is personal
history to support it.  Below that it says what it knows in raw counts rather
than dressing thin data as a prediction.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from ..money import format_coins, format_pct
from ..tax import DEFAULT_TAX, TaxConfig, claim_tax_rate, expected_listing_cost
from .acceptance import AcceptanceCurve
from .shrinkage import MIN_FOR_MODEL

#: Rungs the ladder always shows, as fractions below the estimate.
LADDER_MIN = 0.07
LADDER_MAX = 0.15
LADDER_STEP = 0.01


@dataclass(frozen=True)
class OfferConfig:
    """The user's own trading parameters."""

    #: Profit wanted on top of every cost, as a fraction of the item price.
    target_margin: float = 0.05
    #: Coins that the capital in **one item** should earn per hour it is
    #: tied up.  This is a per-item figure, not a target for the whole
    #: operation: a lowballer holding ten items at once wants ten times
    #: this per hour in total.
    target_hourly_return: int = 2_000_000
    #: Roughly one offer in this many uses a randomised percentage, to keep the
    #: acceptance model from calcifying around whatever was tried first.
    exploration_every: int = 15
    ladder_min: float = LADDER_MIN
    ladder_max: float = LADDER_MAX
    ladder_step: float = LADDER_STEP
    tax: TaxConfig = DEFAULT_TAX

    def ladder_percentages(self) -> list[float]:
        steps = int(round((self.ladder_max - self.ladder_min) / self.ladder_step))
        return [round(self.ladder_min + i * self.ladder_step, 4) for i in range(steps + 1)]


DEFAULT_OFFER_CONFIG = OfferConfig()


@dataclass(frozen=True)
class FloorBreakdown:
    """Every term of the required discount, kept separate so it can be shown."""

    claim_tax: float
    listing_fees: float
    volatility: float
    capital: float
    margin: float

    @property
    def total(self) -> float:
        return (
            self.claim_tax + self.listing_fees + self.volatility + self.capital + self.margin
        )

    def as_rows(self) -> list[tuple[str, float]]:
        return [
            ("Claim tax", self.claim_tax),
            ("Listing fees", self.listing_fees),
            ("Volatility risk", self.volatility),
            ("Cost of capital", self.capital),
            ("Target margin", self.margin),
        ]


def required_discount(
    price: int,
    *,
    hold_hours: float,
    volatility: float = 0.0,
    volatility_window_days: float = 7.0,
    config: OfferConfig = DEFAULT_OFFER_CONFIG,
) -> FloorBreakdown:
    """The discount below which the trade stops being worth doing.

    Every term is a fraction of ``price``, so they add directly.

    ``volatility`` is Coflnet's ``priceCoeffVariation``, which is the spread of
    sale prices across the whole analysis window -- not a daily figure.  Used
    raw it would charge a few hours of holding for a week of dispersion and
    put the floor above every rung on the ladder.  Dividing by the square root
    of the window converts it to a per-day figure first, which is what the
    square-root-of-time scaling below expects.
    """
    price = max(1, int(price))
    hold_hours = max(0.0, float(hold_hours))
    hold_days = hold_hours / 24.0

    tax = claim_tax_rate(price, config.tax)
    fees = expected_listing_cost(price, hold_hours, config.tax) / price
    # Price risk grows with the square root of time held, as a random walk does.
    window = max(0.5, float(volatility_window_days))
    risk = max(0.0, volatility) * math.sqrt(hold_days / window)
    capital = (config.target_hourly_return * hold_hours) / price
    return FloorBreakdown(
        claim_tax=tax,
        listing_fees=fees,
        volatility=risk,
        capital=capital,
        margin=config.target_margin,
    )


@dataclass(frozen=True)
class Rung:
    """One clickable row of the ladder."""

    kind: str            # ESTIMATE | NET_OF_TAX | STEP | RULE | RECOMMENDED
    label: str
    pct: float           # fraction below the estimate
    coins: int
    #: Profit if it resells at the estimate, after tax and expected fees.
    expected_profit: int = 0
    meets_floor: bool = True
    rule_name: str | None = None
    is_exploration: bool = False

    @property
    def pct_label(self) -> str:
        if self.kind in {"ESTIMATE", "NET_OF_TAX"}:
            return self.label
        return format_pct(-self.pct, decimals=0, signed=False)

    @property
    def coins_label(self) -> str:
        return format_coins(self.coins)


@dataclass
class OfferLadder:
    estimate: int
    rungs: list[Rung]
    floor: FloorBreakdown
    floor_pct: float
    recommended: Rung | None = None
    #: Why the recommendation is what it is, shown beside it.
    reasoning: list[str] = field(default_factory=list)
    #: Raw counts, shown instead of a prediction when history is thin.
    evidence: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def rung_at(self, pct: float) -> Rung | None:
        for rung in self.rungs:
            if abs(rung.pct - pct) < 1e-9:
                return rung
        return None

    @property
    def steps(self) -> list[Rung]:
        return [r for r in self.rungs if r.kind in {"STEP", "RULE"}]


def _profit_at(price: int, estimate: int, hold_hours: float, config: OfferConfig) -> int:
    """What is left after tax and expected listing fees if it resells at estimate."""
    tax = int(estimate * claim_tax_rate(estimate, config.tax))
    fees = expected_listing_cost(estimate, hold_hours, config.tax)
    return estimate - tax - fees - price


def build_ladder(
    estimate: int,
    *,
    hold_hours: float,
    volatility: float = 0.0,
    volatility_window_days: float = 7.0,
    config: OfferConfig = DEFAULT_OFFER_CONFIG,
    rule_pct: float | None = None,
    rule_name: str | None = None,
) -> OfferLadder:
    """The full ladder: estimate, estimate net of tax, then every step."""
    estimate = max(0, int(estimate))
    floor = required_discount(
        estimate,
        hold_hours=hold_hours,
        volatility=volatility,
        volatility_window_days=volatility_window_days,
        config=config,
    )
    tax_rate = claim_tax_rate(estimate, config.tax)

    rungs: list[Rung] = [
        Rung("ESTIMATE", "Estimate", 0.0, estimate,
             _profit_at(estimate, estimate, hold_hours, config)),
        Rung("NET_OF_TAX", "Less AH tax", tax_rate, int(estimate * (1 - tax_rate)),
             _profit_at(int(estimate * (1 - tax_rate)), estimate, hold_hours, config)),
    ]

    percentages = list(config.ladder_percentages())
    if rule_pct is not None and not any(abs(rule_pct - p) < 1e-9 for p in percentages):
        percentages.append(round(rule_pct, 4))
    percentages.sort()

    for pct in percentages:
        coins = int(estimate * (1.0 - pct))
        is_rule = rule_pct is not None and abs(pct - rule_pct) < 1e-9
        rungs.append(
            Rung(
                kind="RULE" if is_rule else "STEP",
                label=format_pct(-pct, decimals=0),
                pct=pct,
                coins=coins,
                expected_profit=_profit_at(coins, estimate, hold_hours, config),
                meets_floor=pct >= floor.total,
                rule_name=rule_name if is_rule else None,
            )
        )

    return OfferLadder(
        estimate=estimate, rungs=rungs, floor=floor, floor_pct=floor.total
    )


def _raw_evidence(curve: AcceptanceCurve) -> list[str]:
    """What is known, stated as counts.

    Shown instead of a prediction when the data is too thin to fit anything.
    Two rejections and one acceptance is a fact; a curve drawn through them is
    a fiction.
    """
    tag_obs = [o for o in curve.observations if o.level == "tag"]
    if not tag_obs:
        return ["No offers logged for this item yet"]
    accepted = sorted(o.pct for o in tag_obs if o.accepted)
    rejected = sorted((o.pct for o in tag_obs if not o.accepted), reverse=True)
    lines: list[str] = []
    if rejected:
        lines.append(
            f"{len(rejected)} rejected at {format_pct(rejected[-1], decimals=0)} or more"
        )
    if accepted:
        best = format_pct(max(accepted), decimals=0)
        lines.append(f"{len(accepted)} accepted, best at {best}")
    return lines


def _underperformance_warning(curve: AcceptanceCurve, pct: float, tag: str) -> str | None:
    """Flag a rung this item has historically never been bought at."""
    accepted = [o.pct for o in curve.observations if o.level == "tag" and o.accepted]
    tried = [o.pct for o in curve.observations if o.level == "tag"]
    if len(tried) < MIN_FOR_MODEL or not accepted:
        return None
    best = max(accepted)
    if pct > best + 0.005:
        return (
            f"{tag}: only successfully lowballed at "
            f"{format_pct(best, decimals=0)} or less, n={len(tried)}"
        )
    return None


def recommend(
    ladder: OfferLadder,
    curve: AcceptanceCurve,
    *,
    tag: str = "",
    config: OfferConfig = DEFAULT_OFFER_CONFIG,
    rng: random.Random | None = None,
    allow_exploration: bool = True,
) -> OfferLadder:
    """Pick the rung with the highest expected value, and explain the pick.

    Expected value is ``P(accept) x profit``: offering less earns more when it
    lands but lands less often, and the peak of that product is the number
    worth saying out loud.
    """
    steps = ladder.steps
    if not steps:
        return ladder

    scored = [(curve.probability(r.pct) * r.expected_profit, r) for r in steps]
    best_value, best_rung = max(scored, key=lambda pair: pair[0])

    ladder.evidence = _raw_evidence(curve)

    if not curve.has_enough_data:
        # Thin data: still point at a rung, but the reasoning says the number
        # comes from the floor and the prior, not from this item's history.
        floor_rungs = [r for r in steps if r.meets_floor]
        chosen = floor_rungs[0] if floor_rungs else steps[-1]
        ladder.recommended = Rung(
            kind="RECOMMENDED",
            label=chosen.label,
            pct=chosen.pct,
            coins=chosen.coins,
            expected_profit=chosen.expected_profit,
            meets_floor=chosen.meets_floor,
        )
        ladder.reasoning = [
            "Not enough history for this item",
            f"Covers costs from {format_pct(ladder.floor_pct, decimals=0)}",
        ]
        if not floor_rungs:
            ladder.warnings.append(
                "No rung on the ladder covers the expected cost of holding this"
            )
        return ladder

    chosen = best_rung
    is_exploration = False
    if allow_exploration and config.exploration_every > 0:
        roll = (rng or random).randrange(config.exploration_every)
        if roll == 0:
            # Without this the model calcifies around whatever was tried first:
            # percentages that are never offered never gather evidence.
            chosen = (rng or random).choice(steps)
            is_exploration = chosen.pct != best_rung.pct

    ladder.recommended = Rung(
        kind="RECOMMENDED",
        label=chosen.label,
        pct=chosen.pct,
        coins=chosen.coins,
        expected_profit=chosen.expected_profit,
        meets_floor=chosen.meets_floor,
        is_exploration=is_exploration,
    )
    probability = curve.probability(chosen.pct)
    ladder.reasoning = [
        f"{format_pct(probability, decimals=0)} accepted at this step, n={curve.n_tag}",
        f"Expected value {format_coins(int(probability * chosen.expected_profit))}",
    ]
    if is_exploration:
        ladder.reasoning.insert(
            0, f"Exploring: best by the model is {format_pct(-best_rung.pct, decimals=0)}"
        )
    if not chosen.meets_floor:
        ladder.warnings.append(
            f"Below the {format_pct(ladder.floor_pct, decimals=0)} that covers costs"
        )
    warning = _underperformance_warning(curve, chosen.pct, tag)
    if warning:
        ladder.warnings.append(warning)
    return ladder

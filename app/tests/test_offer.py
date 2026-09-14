"""Offer floor, ladder and acceptance model.

The acceptance test that matters is the last one: generate offers from a known
logistic, fit the model back, and assert it recovers the optimum. Without that,
a subtly broken fit would still produce plausible-looking numbers.
"""

from __future__ import annotations

import math
import random

import pytest

from lowball.pricing.acceptance import (
    PRIOR_INTERCEPT,
    PRIOR_SLOPE,
    AcceptanceCurve,
    Observation,
    fit_logistic,
)
from lowball.pricing.offer import (
    DEFAULT_OFFER_CONFIG,
    OfferConfig,
    build_ladder,
    recommend,
    required_discount,
)
from lowball.tax import TaxConfig

ESTIMATE = 847_200_000


def test_the_floor_adds_up_to_its_parts() -> None:
    floor = required_discount(ESTIMATE, hold_hours=4.3, volatility=0.374)
    assert floor.total == pytest.approx(sum(v for _, v in floor.as_rows()))
    assert floor.claim_tax == pytest.approx(0.025)
    assert floor.margin == pytest.approx(DEFAULT_OFFER_CONFIG.target_margin)


def test_a_longer_hold_demands_a_deeper_discount() -> None:
    quick = required_discount(ESTIMATE, hold_hours=4, volatility=0.3)
    slow = required_discount(ESTIMATE, hold_hours=96, volatility=0.3)
    assert slow.total > quick.total
    # A four-day hold spans more than one auction duration, so it is relisted.
    assert slow.listing_fees > quick.listing_fees
    assert slow.capital > quick.capital


def test_volatility_is_scaled_by_the_window_it_was_measured_over() -> None:
    """Raw priceCoeffVariation is a week of dispersion, not a day of it."""
    scaled = required_discount(ESTIMATE, hold_hours=4.3, volatility=0.374)
    # Used unscaled, a few hours of holding would be charged 15%+ of risk and
    # the floor would sit above every rung on the ladder.
    assert scaled.volatility < 0.10
    assert scaled.total < 0.25


def test_derpy_raises_the_floor() -> None:
    plain = required_discount(ESTIMATE, hold_hours=4, volatility=0.2)
    derpy = required_discount(
        ESTIMATE,
        hold_hours=4,
        volatility=0.2,
        config=OfferConfig(tax=TaxConfig(derpy=True)),
    )
    assert derpy.total > plain.total
    assert derpy.claim_tax == pytest.approx(0.05)


def test_the_ladder_covers_every_step_from_7_to_15() -> None:
    ladder = build_ladder(ESTIMATE, hold_hours=4.3, volatility=0.374)
    percentages = [round(r.pct, 2) for r in ladder.steps]
    assert percentages == [0.07, 0.08, 0.09, 0.10, 0.11, 0.12, 0.13, 0.14, 0.15]
    assert ladder.rungs[0].kind == "ESTIMATE"
    assert ladder.rungs[0].coins == ESTIMATE
    assert ladder.rungs[1].kind == "NET_OF_TAX"
    assert ladder.rungs[1].coins == int(ESTIMATE * 0.975)


def test_a_rule_percentage_is_added_to_the_ladder_and_badged() -> None:
    ladder = build_ladder(
        ESTIMATE, hold_hours=4.3, rule_pct=0.25, rule_name="Skins are illiquid"
    )
    rung = ladder.rung_at(0.25)
    assert rung is not None
    assert rung.kind == "RULE"
    assert rung.rule_name == "Skins are illiquid"
    assert rung.coins == int(ESTIMATE * 0.75)


def test_buying_at_the_estimate_loses_money() -> None:
    ladder = build_ladder(ESTIMATE, hold_hours=4.3)
    # Tax on the way out and a listing fee on the way in; there is no version
    # of this trade that works without a discount.
    assert ladder.rungs[0].expected_profit < 0


def test_deeper_offers_are_worth_more_when_they_land() -> None:
    ladder = build_ladder(ESTIMATE, hold_hours=4.3)
    profits = [r.expected_profit for r in ladder.steps]
    assert profits == sorted(profits)


def test_the_prior_curve_is_used_when_nothing_is_known() -> None:
    curve = AcceptanceCurve(*fit_logistic([]))
    assert curve.probability(0.07) == pytest.approx(0.75, abs=0.02)
    assert curve.probability(0.25) == pytest.approx(0.20, abs=0.02)
    assert curve.probability(0.15) > curve.probability(0.20)


def test_the_curve_is_monotonic_in_the_offer_percentage() -> None:
    curve = AcceptanceCurve(PRIOR_INTERCEPT, PRIOR_SLOPE)
    probabilities = [curve.probability(p / 100) for p in range(5, 30)]
    assert probabilities == sorted(probabilities, reverse=True)


def test_a_single_acceptance_is_not_a_100_percent_acceptance_rate() -> None:
    curve = AcceptanceCurve(*fit_logistic([Observation(0.15, True)]))
    assert curve.probability(0.15) < 0.75


def test_real_observations_pull_the_curve_away_from_the_prior() -> None:
    rejections = [Observation(0.15, False) for _ in range(12)]
    curve = AcceptanceCurve(*fit_logistic(rejections))
    prior = AcceptanceCurve(PRIOR_INTERCEPT, PRIOR_SLOPE)
    assert curve.probability(0.15) < prior.probability(0.15)


def test_broader_levels_count_for_less_than_the_item_itself() -> None:
    tag_level = [Observation(0.12, True, level="tag") for _ in range(4)]
    global_level = [Observation(0.12, False, level="global") for _ in range(4)]
    mixed = AcceptanceCurve(*fit_logistic(tag_level + global_level))
    only_global = AcceptanceCurve(*fit_logistic(global_level))
    assert mixed.probability(0.12) > only_global.probability(0.12)


def synthetic_offers(
    intercept: float, slope: float, n: int = 600, seed: int = 7
) -> list[Observation]:
    """Offers drawn from a known ground-truth acceptance curve."""
    rng = random.Random(seed)
    out: list[Observation] = []
    for _ in range(n):
        pct = rng.choice([0.07, 0.08, 0.09, 0.10, 0.11, 0.12, 0.13, 0.14, 0.15])
        probability = 1.0 / (1.0 + math.exp(-(intercept + slope * pct)))
        out.append(Observation(pct, rng.random() < probability))
    return out


def test_the_fit_recovers_a_known_curve() -> None:
    truth_a, truth_b = 3.2, -20.0
    fitted = AcceptanceCurve(*fit_logistic(synthetic_offers(truth_a, truth_b)))
    for pct in (0.08, 0.11, 0.14):
        expected = 1.0 / (1.0 + math.exp(-(truth_a + truth_b * pct)))
        assert fitted.probability(pct) == pytest.approx(expected, abs=0.08)


def test_the_recommendation_recovers_the_known_optimum() -> None:
    """The assertion that makes the recommendation trustworthy.

    Generate offers from a ground-truth curve, work out by hand which rung
    maximises P(accept) x profit under that curve, then check the fitted model
    lands on the same rung.
    """
    truth_a, truth_b = 3.2, -20.0
    observations = synthetic_offers(truth_a, truth_b)
    ladder = build_ladder(ESTIMATE, hold_hours=4.3, volatility=0.2)

    def truth(pct: float) -> float:
        return 1.0 / (1.0 + math.exp(-(truth_a + truth_b * pct)))

    true_best = max(ladder.steps, key=lambda r: truth(r.pct) * r.expected_profit)

    curve = AcceptanceCurve(
        *fit_logistic(observations), n_tag=len(observations), n_total=len(observations),
        observations=observations,
    )
    recommend(ladder, curve, tag="HYPERION", allow_exploration=False)
    assert ladder.recommended is not None
    assert ladder.recommended.pct == pytest.approx(true_best.pct, abs=0.011)


def test_thin_data_shows_counts_rather_than_a_prediction() -> None:
    observations = [Observation(0.15, False), Observation(0.08, True)]
    curve = AcceptanceCurve(
        *fit_logistic(observations), n_tag=2, n_total=2, observations=observations
    )
    ladder = recommend(
        build_ladder(ESTIMATE, hold_hours=4.3), curve, tag="HYPERION",
        allow_exploration=False,
    )
    assert "Not enough history for this item" in ladder.reasoning
    assert any("rejected" in line for line in ladder.evidence)
    assert any("accepted" in line for line in ladder.evidence)
    # No modelled acceptance probability is quoted on two observations.
    assert not any("accepted at this step" in line for line in ladder.reasoning)


def test_an_item_never_bought_above_8_percent_is_flagged() -> None:
    observations = [Observation(0.14, False) for _ in range(13)] + [
        Observation(0.08, True)
    ]
    curve = AcceptanceCurve(
        *fit_logistic(observations), n_tag=14, n_total=14, observations=observations
    )
    ladder = recommend(
        build_ladder(ESTIMATE, hold_hours=4.3), curve, tag="NECRON_HANDLE",
        allow_exploration=False,
    )
    assert any("only successfully lowballed at 8%" in w for w in ladder.warnings)


def test_exploration_fires_at_the_configured_rate_and_is_marked() -> None:
    observations = synthetic_offers(3.2, -20.0, n=100)
    curve = AcceptanceCurve(
        *fit_logistic(observations), n_tag=100, n_total=100, observations=observations
    )
    explored = 0
    for seed in range(150):
        ladder = recommend(
            build_ladder(ESTIMATE, hold_hours=4.3),
            curve,
            tag="HYPERION",
            rng=random.Random(seed),
        )
        if ladder.recommended.is_exploration:
            explored += 1
    # Roughly one in fifteen, allowing for the roll sometimes landing on the
    # rung the model would have chosen anyway.
    assert 2 <= explored <= 20


def test_exploration_can_be_turned_off() -> None:
    observations = synthetic_offers(3.2, -20.0, n=100)
    curve = AcceptanceCurve(
        *fit_logistic(observations), n_tag=100, n_total=100, observations=observations
    )
    for seed in range(30):
        ladder = recommend(
            build_ladder(ESTIMATE, hold_hours=4.3),
            curve,
            tag="HYPERION",
            rng=random.Random(seed),
            allow_exploration=False,
        )
        assert not ladder.recommended.is_exploration

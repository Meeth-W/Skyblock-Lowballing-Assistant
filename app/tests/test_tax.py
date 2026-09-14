"""Tax arithmetic, boundary by boundary (Part 16)."""

from __future__ import annotations

import pytest

from lowball.tax import (
    TaxConfig,
    claim_tax,
    expected_listing_cost,
    listing_fee,
    net_after_claim,
    relist_count,
)


@pytest.mark.parametrize(
    ("price", "expected"),
    [
        (0, 0),
        (1_000_000, 10_000),          # 1%
        (9_999_999, 99_999),          # still the bottom tier
        (10_000_000, 200_000),        # 2% starts exactly at 10M
        (50_000_000, 1_000_000),
        (100_000_000, 2_000_000),     # 100M is still the middle tier
        (100_000_001, 2_500_000),     # one coin over tips into 2.5%
        (847_200_000, 21_180_000),
    ],
)
def test_claim_tax_tiers(price: int, expected: int) -> None:
    assert claim_tax(price) == expected


def test_tier_boundary_is_not_a_cliff_in_net_proceeds() -> None:
    """Crossing 100M must not leave the seller with less than just under it."""
    assert net_after_claim(100_000_000) == 98_000_000
    assert net_after_claim(100_000_001) == 97_500_001
    # The jump is real and worth knowing about; assert its size so a change to
    # the tier table cannot pass unnoticed.
    assert net_after_claim(100_000_000) - net_after_claim(100_000_001) == 499_999


def test_derpy_doubles_the_rate() -> None:
    plain = claim_tax(500_000_000)
    derpy = claim_tax(500_000_000, TaxConfig(derpy=True))
    assert plain == 12_500_000
    assert derpy == 25_000_000


def test_derpy_applies_to_listing_fees_too() -> None:
    assert listing_fee(20_000_000) == 400_000
    assert listing_fee(20_000_000, TaxConfig(derpy=True)) == 800_000


def test_negative_and_zero_prices_cost_nothing() -> None:
    assert claim_tax(-5) == 0
    assert listing_fee(-5) == 0


def test_relists_are_counted_by_auction_duration() -> None:
    assert relist_count(1) == 1
    assert relist_count(48) == 1
    assert relist_count(48.1) == 2
    assert relist_count(200) == 5


def test_expected_listing_cost_multiplies_by_relists() -> None:
    # A 200M item held five days is listed three times, not once.
    one_fee = listing_fee(200_000_000)
    assert one_fee == 5_000_000
    assert expected_listing_cost(200_000_000, hold_hours=120) == one_fee * 3

"""Refreshing the pricing table from the bazaar.

The table is the tunable half of every valuation, and its numbers move weekly.
These tests hold the two things that make the refresh safe to press: it fills
in what the bazaar trades, and it leaves alone what the bazaar does not --
zeroing a skin because it has no product would quietly wreck every add-back.
"""

from __future__ import annotations

from lowball.api.bazaar import BazaarRefresh, refresh_values
from lowball.pricing.values import ValueTable


def _prices(**extra: int) -> dict[str, int]:
    prices = {
        "RECOMBOBULATOR_3000": 9_500_000,
        "THE_ART_OF_WAR": 4_100_000,
        "HOT_POTATO_BOOK": 120_000,
        "FUMING_POTATO_BOOK": 1_400_000,
        "FIRST_MASTER_STAR": 28_000_000,
        "SECOND_MASTER_STAR": 55_000_000,
        "THIRD_MASTER_STAR": 110_000_000,
        "FOURTH_MASTER_STAR": 240_000_000,
        "FIFTH_MASTER_STAR": 480_000_000,
        "PERFECT_JASPER_GEM": 9_000_000,
        "PERFECT_RUBY_GEM": 7_000_000,
        "ENCHANTMENT_ULTIMATE_WISE_5": 2_400_000,
        "ENCHANTMENT_SHARPNESS_7": 61_000_000,
    }
    prices.update(extra)
    return prices


def test_a_refresh_writes_what_the_bazaar_trades() -> None:
    table = ValueTable()
    result = refresh_values(table, _prices())

    assert isinstance(result, BazaarRefresh)
    assert table.recomb == 9_500_000
    assert table.hot_potato == 120_000
    assert table.master_stars[0] == 28_000_000
    assert table.ultimate_enchants["ultimate_wise"] == 2_400_000
    assert table.top_tier_enchants["sharpness"] == 61_000_000


def test_a_gemstone_quality_is_the_median_across_kinds() -> None:
    """One arbitrary stone is not the price of a quality: jasper and ruby
    trade at very different numbers."""
    table = ValueTable()
    refresh_values(table, _prices())
    assert table.gems["PERFECT"] == 8_000_000  # median of 9M and 7M


def test_the_top_level_the_bazaar_trades_becomes_the_reference() -> None:
    """Enchantments cap at different levels, and the bazaar is the authority.

    Reading a Looting V price as though it were two levels short of a notional
    VII multiplied it by thirty-six, which is how a Looting book ended up
    valued in the billions.
    """
    table = ValueTable()
    prices = _prices()
    prices["ENCHANTMENT_LOOTING_5"] = 132_000_000

    refresh_values(table, prices)

    assert table.top_tier_enchants["looting"] == 132_000_000
    assert table.reference_level("looting") == 5
    assert table.enchant_value("looting", 5) == 132_000_000


def test_the_decay_between_levels_is_measured_rather_than_assumed() -> None:
    """Two Sharpness VI make a VII, so a VII is worth far more than six VIs."""
    table = ValueTable()
    prices = _prices()
    prices["ENCHANTMENT_SHARPNESS_7"] = 120_000_000
    prices["ENCHANTMENT_SHARPNESS_6"] = 400_000

    refresh_values(table, prices)

    assert table.decay_for("sharpness") == 300.0
    assert table.enchant_value("sharpness", 7) == 120_000_000
    assert table.enchant_value("sharpness", 6) == 400_000


def test_a_decay_is_only_measured_between_adjacent_levels() -> None:
    """A gap in the book says nothing about the step between levels."""
    table = ValueTable()
    prices = _prices()
    prices["ENCHANTMENT_SHARPNESS_7"] = 120_000_000
    prices["ENCHANTMENT_SHARPNESS_4"] = 1_000

    refresh_values(table, prices)

    assert "sharpness" not in table.top_tier_decay
    assert table.decay_for("sharpness") == 6.0


def test_an_ultimate_that_only_trades_at_level_one_is_scaled_up() -> None:
    table = ValueTable()
    prices = _prices()
    del prices["ENCHANTMENT_ULTIMATE_WISE_5"]
    prices["ENCHANTMENT_ULTIMATE_WISE_1"] = 4_000_000
    refresh_values(table, prices)

    assert table.ultimate_enchants["ultimate_wise"] == 100_000_000
    assert table.enchant_value("ultimate_wise", 1) == 4_000_000


def test_what_the_bazaar_does_not_trade_is_left_exactly_as_it_was() -> None:
    table = ValueTable()
    table.skin = 77_000_000
    table.dye = 300_000_000
    table.ability_scroll = 88_000_000
    refresh_values(table, _prices())

    assert table.skin == 77_000_000
    assert table.dye == 300_000_000
    assert table.ability_scroll == 88_000_000


def test_an_empty_response_changes_nothing() -> None:
    """A bad response must not be mistaken for a market where everything is
    free."""
    table = ValueTable()
    before = table.as_dict()
    result = refresh_values(table, {})
    assert table.as_dict() == before
    assert result.count == 0


def test_the_discount_shaves_every_modifier_price() -> None:
    table = ValueTable(modifier_discount_pct=40)
    assert table.modifier_multiplier == 0.6
    assert ValueTable().modifier_multiplier == 1.0

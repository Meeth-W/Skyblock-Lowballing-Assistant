"""Pet exp-to-level conversion.

The anchors below are the published totals to reach level 100 at each rarity.
They are the check that keeps the shared cost table and the rarity offsets
honest: get either wrong and every pet in the app is mispriced.
"""

from __future__ import annotations

import pytest

from lowball.parsing.pets import (
    PET_LEVEL_COSTS,
    PET_RARITY_OFFSET,
    exp_for_level,
    level_for_exp,
    parse_pet_info,
)

LEVEL_100_EXP = {
    "COMMON": 5_624_785,
    "UNCOMMON": 8_644_220,
    "RARE": 12_626_665,
    "EPIC": 18_608_500,
    "LEGENDARY": 25_353_230,
    "MYTHIC": 25_353_230,
}


def test_the_table_is_long_enough_for_the_highest_offset() -> None:
    # 99 level-ups starting from the legendary offset must stay in range.
    assert len(PET_LEVEL_COSTS) >= max(PET_RARITY_OFFSET.values()) + 99


@pytest.mark.parametrize(("rarity", "total"), sorted(LEVEL_100_EXP.items()))
def test_exp_to_reach_level_100(rarity: str, total: int) -> None:
    assert exp_for_level(100, rarity) == total


@pytest.mark.parametrize(("rarity", "total"), sorted(LEVEL_100_EXP.items()))
def test_level_100_is_reached_exactly_at_that_total(rarity: str, total: int) -> None:
    assert level_for_exp(total - 1, rarity) == (99, True)
    assert level_for_exp(total, rarity) == (100, True)


def test_a_higher_rarity_needs_more_exp_for_the_same_level() -> None:
    assert exp_for_level(50, "LEGENDARY") > exp_for_level(50, "COMMON")


def test_zero_exp_is_level_one() -> None:
    assert level_for_exp(0, "LEGENDARY") == (1, True)
    assert level_for_exp(-500, "COMMON") == (1, True)


def test_a_dragon_above_100_reports_a_floor_not_a_guess() -> None:
    level, exact = level_for_exp(150_000_000, "LEGENDARY", pet_type="GOLDEN_DRAGON")
    assert (level, exact) == (100, False)
    # The same exp on an ordinary legendary pet is simply capped at 100.
    assert level_for_exp(150_000_000, "LEGENDARY") == (100, True)


def test_pet_info_json_is_parsed_from_the_nested_string() -> None:
    info = parse_pet_info(
        '{"type":"BLUE_WHALE","exp":1500000.0,"tier":"LEGENDARY","candyUsed":2,'
        '"heldItem":"MINOS_RELIC","skin":"BLUE_WHALE_ORCA"}'
    )
    assert info.type == "BLUE_WHALE"
    assert info.tier == "LEGENDARY"
    assert info.candy_used == 2
    assert info.held_item == "MINOS_RELIC"
    assert info.skin == "BLUE_WHALE_ORCA"
    assert info.level_is_exact


def test_malformed_pet_info_is_ignored_rather_than_raised() -> None:
    assert parse_pet_info("not json") is None
    assert parse_pet_info(None) is None
    assert parse_pet_info('{"exp":100}') is None

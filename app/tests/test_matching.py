"""Matching a sold auction against an item, and the value table that gates it.

These two decide what counts as a comparable, which is the number the whole
app rests on. Coflnet's sold endpoint ignores filter parameters entirely, so
this is the only thing narrowing the comparables at all.
"""

from __future__ import annotations

from lowball.api.models import Auction
from lowball.parsing.signature import ItemSignature
from lowball.pricing.matching import SoldItem, matches_all, select
from lowball.pricing.modifiers import rank_by_value_contribution
from lowball.pricing.values import ValueTable, dump_values, load_values


def sold(price=1_000_000_000, name="Heroic Hyperion", tier="MYTHIC", enchants=None, **flat):
    return SoldItem.from_auction(
        Auction.parse(
            {
                "uuid": "x",
                "tag": "HYPERION",
                "itemName": name,
                "startingBid": price,
                "highestBidAmount": price,
                "count": 1,
                "tier": tier,
                "enchantments": [
                    {"type": k, "level": v} for k, v in (enchants or {}).items()
                ],
                "flattenedNbt": {k: str(v) for k, v in flat.items()},
            },
            sold=True,
        )
    )


def mods_for(**kwargs):
    return rank_by_value_contribution(ItemSignature(tag="HYPERION", **kwargs))


def test_flattened_nbt_is_read_into_the_fields_that_matter() -> None:
    item = sold(
        upgrade_level=10,
        rarity_upgrades=1,
        hpc=15,
        art_of_war_count=1,
        ability_scroll="IMPLOSION_SCROLL SHADOW_WARP_SCROLL",
        COMBAT_0="PERFECT",
        SAPPHIRE_0="PERFECT",
    )
    assert item.stars == 10
    assert item.recombobulated
    assert item.hot_potato == 15
    assert item.art_of_war
    assert item.gem_count("PERFECT") == 2
    assert "IMPLOSION_SCROLL" in item.ability_scrolls


def test_the_reforge_is_read_from_the_name() -> None:
    # It is the one modifier the sale feed does not report as data.
    assert sold(name="Fabled Hyperion").has_reforge("fabled")
    assert not sold(name="Heroic Hyperion").has_reforge("fabled")


def test_a_gem_slot_is_not_counted_twice() -> None:
    item = sold(COMBAT_0="PERFECT", COMBAT_0_gem="SAPPHIRE", unlocked_slots="COMBAT_0")
    assert item.gem_count("PERFECT") == 1


def test_stars_must_match_exactly() -> None:
    star = next(m for m in mods_for(stars=10) if m.kind == "star")
    assert matches_all(sold(upgrade_level=10), [star], None)
    assert not matches_all(sold(upgrade_level=5), [star], None)


def test_rarity_narrows_the_field() -> None:
    assert matches_all(sold(tier="MYTHIC"), [], "MYTHIC")
    assert not matches_all(sold(tier="LEGENDARY"), [], "MYTHIC")


def test_a_modifier_the_feed_cannot_report_does_not_disqualify() -> None:
    """A skin is unknowable from a sale, so it must not exclude every sale."""
    skin = next(m for m in mods_for(skin="HYPERION_SKIN") if m.kind == "skin")
    assert matches_all(sold(), [skin], None)


def test_select_narrows_a_real_looking_feed() -> None:
    feed = [sold(1_000_000_000, upgrade_level=5) for _ in range(20)]
    feed += [
        sold(2_200_000_000, upgrade_level=10, enchants={"ultimate_chimera": 5})
        for _ in range(6)
    ]
    wanted = mods_for(stars=10, enchantments=(("ultimate_chimera", 5),))
    matched = select(feed, [m for m in wanted if m.use_for_matching], None)
    assert len(matched) == 6
    assert min(i.unit_price for i in matched) == 2_200_000_000


# ---- the value table --------------------------------------------------------


def test_only_expensive_enchantments_are_matched_on() -> None:
    table = ValueTable()
    # An item carries twenty enchantments; insisting a comparable share all of
    # them would leave nothing to compare against.
    assert table.is_filter_worthy("ultimate_chimera", 5)
    assert table.is_filter_worthy("sharpness", 7)
    assert not table.is_filter_worthy("sharpness", 6)
    assert not table.is_filter_worthy("looting", 5)


def test_value_falls_away_below_the_top_level() -> None:
    table = ValueTable()
    assert table.enchant_value("sharpness", 7) > table.enchant_value("sharpness", 6) * 5
    assert table.enchant_value("ultimate_chimera", 5) > table.enchant_value(
        "ultimate_chimera", 3
    )


def test_the_threshold_is_what_decides_and_it_is_editable() -> None:
    cheap = ValueTable(min_enchant_filter_value=1_000_000)
    assert cheap.is_filter_worthy("sharpness", 6)
    strict = ValueTable(min_enchant_filter_value=500_000_000)
    assert not strict.is_filter_worthy("ultimate_chimera", 5)


def test_the_ranking_follows_the_table() -> None:
    table = ValueTable(top_tier_enchants={"cleave": 900_000_000})
    ranked = rank_by_value_contribution(
        ItemSignature(tag="HYPERION", enchantments=(("cleave", 7), ("sharpness", 7))),
        table,
    )
    assert str(ranked[0]) == "Cleave 7"


def test_the_table_round_trips_through_yaml(tmp_path) -> None:
    table = ValueTable(min_enchant_filter_value=25_000_000)
    table.top_tier_enchants["cleave"] = 77_000_000
    path = tmp_path / "values.yaml"
    path.write_text(dump_values(table), encoding="utf-8")
    back = load_values(path)
    assert back.min_enchant_filter_value == 25_000_000
    assert back.top_tier_enchants["cleave"] == 77_000_000


def test_an_unreadable_table_falls_back_to_defaults(tmp_path) -> None:
    path = tmp_path / "values.yaml"
    path.write_text("this: [is not: valid", encoding="utf-8")
    # Starting on default prices is recoverable; refusing to start is not.
    assert load_values(path).min_enchant_filter_value == ValueTable().min_enchant_filter_value


def test_pet_levels_match_within_a_band() -> None:
    from lowball.pricing.matching import pet_level_tolerance

    # A level 160 pet compared only against exactly 160 would find nothing.
    assert pet_level_tolerance(160) >= 12
    assert pet_level_tolerance(10) == 5

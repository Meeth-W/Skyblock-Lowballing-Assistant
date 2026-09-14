"""A real item, captured from a live trade.

``real_hyperion_fabled.component.b64`` is not modelled. It came off a running
client through the mod, out of the app's own diagnostic dump, and it is the
item that exposed the bug the synthetic corpus could not: on a modern client
Hypixel writes the SkyBlock attributes straight into ``minecraft:custom_data``
with no ``ExtraAttributes`` wrapper. Every hand-built fixture had the wrapper,
because the wrapper is what the old 1.8 format used, so both sides of the app
agreed with each other and disagreed with the game.

It is a 10-star Fabled Hyperion with Chimera V, which makes it a useful
stress case for the modifier ranking as well.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lowball.parsing.categories import category_of
from lowball.parsing.nbt import decode_b64, extra_attributes, looks_like_skyblock
from lowball.parsing.parser import signature_from_b64
from lowball.pricing.modifiers import rank_by_value_contribution, to_filters

FIXTURE = Path(__file__).parent / "fixtures" / "real_hyperion_fabled.component.b64"
PAYLOAD = FIXTURE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def sig():
    parsed = signature_from_b64(PAYLOAD)
    assert parsed is not None, "the real capture must parse"
    return parsed


def test_attributes_sit_directly_in_custom_data() -> None:
    """The shape that broke the first build."""
    root = decode_b64(PAYLOAD)
    custom = root["components"]["minecraft:custom_data"]
    assert "ExtraAttributes" not in custom
    assert custom["id"] == "HYPERION"
    assert looks_like_skyblock(custom)
    # The parser has to find it anyway.
    assert extra_attributes(root)["id"] == "HYPERION"


def test_the_whole_signature_is_recovered(sig) -> None:
    assert sig.tag == "HYPERION"
    assert sig.rarity == "MYTHIC"
    assert sig.base_rarity == "LEGENDARY"     # recombobulated, so comparables use this
    assert sig.category == "SWORD"
    assert category_of(sig) == "Weapon"
    assert sig.reforge == "fabled"
    assert sig.stars == 10
    assert sig.recombobulated is True
    assert sig.art_of_war is True
    assert sig.hot_potato == 15


def test_the_join_key_is_derived_from_the_item_uuid(sig) -> None:
    # There is no uId field on a real item; it is the last 12 characters of
    # the uuid, and it is what later matches a purchase to a listing.
    assert sig.uid == "f5ad8c56e548"
    assert not sig.is_stackable


def test_enchantments_gems_and_scrolls_survive(sig) -> None:
    assert sig.enchant_level("ultimate_chimera") == 5
    assert sig.enchant_level("champion") == 10
    assert len(sig.enchantments) == 21
    assert [(g.slot, g.quality, g.kind) for g in sig.gems] == [
        ("COMBAT_0", "PERFECT", "ONYX"),
        ("SAPPHIRE_0", "PERFECT", None),
    ]
    assert sig.ability_scroll == (
        "IMPLOSION_SCROLL",
        "SHADOW_WARP_SCROLL",
        "WITHER_SHIELD_SCROLL",
    )


def test_the_shiny_rarity_line_does_not_leak_into_the_category(sig) -> None:
    """A shiny item's rarity line reads 'a SHINY MYTHIC DUNGEON SWORD a'.

    The stray letters are what is left of an obfuscated glyph once formatting
    is stripped, and they are not part of the category.
    """
    assert sig.category == "SWORD"


def test_the_most_valuable_modifiers_are_given_up_last(sig) -> None:
    ranked = rank_by_value_contribution(sig)
    assert [m.kind for m in ranked[:2]] == ["star", "enchantment"]
    assert str(ranked[0]) == "10 stars"
    assert str(ranked[1]) == "Chimera 5"


def test_the_filters_match_what_the_auction_house_shows(sig) -> None:
    filters, _ = to_filters(rank_by_value_contribution(sig), sig)
    # The API rejects "fabled" with a 500; it wants "Fabled".
    assert filters["Reforge"] == "Fabled"
    # The listed rarity, not the pre-recombobulation one. Filtering on
    # LEGENDARY here matched no recombobulated listing at all, which is
    # everything worth lowballing.
    assert filters["Rarity"] == "MYTHIC"
    assert filters["Stars"] == 10

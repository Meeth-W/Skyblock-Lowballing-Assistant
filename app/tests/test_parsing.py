"""Parser regression tests against the fixture corpus (Part 16).

Every fixture exists in both the legacy ``tag`` layout and the 1.20.5+
component layout, and both must produce the same signature.  That equivalence
is the test that actually matters: it is what keeps a content drop from
silently breaking valuation.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lowball.parsing.parser import signature_from_b64, signatures_from_inventory
from lowball.parsing.signature import ItemSignature

FIXTURES = Path(__file__).parent / "fixtures"

ITEM_KEYS = [
    "hyperion_wither_impact",
    "crimson_chestplate_attributes",
    "golden_dragon_pet",
    "low_level_wolf_pet",
    "skinned_dyed_helmet",
    "stackable_enchanted_book",
    "runed_terminator",
    "vanilla_cobblestone",
]


def load(key: str, layout: str) -> ItemSignature | None:
    return signature_from_b64((FIXTURES / f"{key}.{layout}.b64").read_text(encoding="utf-8"))


@pytest.fixture(params=["legacy", "component"])
def layout(request: pytest.FixtureRequest) -> str:
    return request.param


@pytest.mark.parametrize("key", ITEM_KEYS)
def test_both_layouts_produce_the_same_signature(key: str) -> None:
    legacy = load(key, "legacy")
    component = load(key, "component")
    if legacy is None:
        assert component is None
        return
    # display_name differs only in how the two layouts encode the text; the
    # price-relevant part of the signature must be identical.
    assert legacy.cache_key() == component.cache_key()
    assert legacy.tag == component.tag
    assert legacy.uid == component.uid


def test_a_loaded_hyperion_parses_every_modifier(layout: str) -> None:
    sig = load("hyperion_wither_impact", layout)
    assert sig is not None
    assert sig.tag == "HYPERION"
    assert sig.rarity == "MYTHIC"
    assert sig.category == "SWORD"
    assert sig.reforge == "heroic"
    assert sig.stars == 5
    assert sig.recombobulated is True
    assert sig.art_of_war is True
    assert sig.hot_potato == 15
    assert sig.enchant_level("ultimate_wise") == 5
    assert sig.enchant_level("sharpness") == 7
    assert sig.uid == "a1b2c3d4e5f6"
    assert [(g.slot, g.quality, g.kind) for g in sig.gems] == [
        ("COMBAT_0", "PERFECT", "SAPPHIRE"),
        ("UNIVERSAL_0", "PERFECT", "JASPER"),
    ]


def test_recombobulated_items_report_their_base_rarity(layout: str) -> None:
    sig = load("hyperion_wither_impact", layout)
    # Comparables are keyed on the rarity before the recomb was applied.
    assert sig.rarity == "MYTHIC"
    assert sig.base_rarity == "LEGENDARY"


def test_attribute_shards_are_parsed(layout: str) -> None:
    sig = load("crimson_chestplate_attributes", layout)
    assert sig.attribute_level("lifeline") == 5
    assert sig.attribute_level("mana_pool") == 4
    assert sig.category == "CHESTPLATE"


def test_a_dragon_level_comes_from_the_name(layout: str) -> None:
    """Above 100 the exp table runs out, but the game prints the level."""
    sig = load("golden_dragon_pet", layout)
    assert sig.is_pet
    assert sig.pet.type == "GOLDEN_DRAGON"
    assert sig.pet.held_item == "PET_ITEM_TIER_BOOST"
    # "[Lvl 160] Golden Dragon". Reading it is what lets a maxed dragon be
    # compared against other maxed dragons rather than against level 1 eggs.
    assert sig.pet.level == 160
    assert sig.pet.level_is_exact is True
    assert sig.rarity == "LEGENDARY"


def test_a_pet_is_tagged_by_species_not_by_the_word_pet(layout: str) -> None:
    # Every pet carries the id "PET"; the auction house lists them by species.
    assert load("golden_dragon_pet", layout).tag == "PET_GOLDEN_DRAGON"
    assert load("low_level_wolf_pet", layout).tag == "PET_WOLF"


def test_a_low_pet_gets_an_exact_level(layout: str) -> None:
    sig = load("low_level_wolf_pet", layout)
    assert sig.pet.level_is_exact is True
    assert 1 < sig.pet.level < 100
    assert sig.pet.candy_used == 3


def test_skins_and_dyes_are_flagged(layout: str) -> None:
    sig = load("skinned_dyed_helmet", layout)
    assert sig.has_skin
    assert sig.skin == "NECRON_HELMET_TIED"
    assert sig.dye == "DYE_NECRON"
    assert sig.stars == 10


def test_stackables_have_no_join_key(layout: str) -> None:
    sig = load("stackable_enchanted_book", layout)
    assert sig.is_stackable
    assert sig.uid is None
    assert sig.count == 16
    assert sig.enchant_level("ultimate_wise") == 5


def test_runes_and_ability_scrolls(layout: str) -> None:
    sig = load("runed_terminator", layout)
    assert sig.rune == ("BARK_TUNES", 3)
    assert sig.ability_scroll == ("IMPLOSION_SCROLL", "WITHER_SHIELD_SCROLL")


def test_vanilla_items_are_not_skyblock_items(layout: str) -> None:
    assert load("vanilla_cobblestone", layout) is None


def test_an_inventory_keeps_slot_indices(): 
    payload = (FIXTURES / "inventory.legacy.b64").read_text(encoding="utf-8")
    sigs = signatures_from_inventory(payload)
    assert len(sigs) == 9
    assert sigs[0].tag == "HYPERION"
    assert sigs[2] is None  # the deliberately empty slot
    assert sigs[3].tag == "PET_GOLDEN_DRAGON"


def test_identical_items_share_a_cache_key_but_differ_by_modifier() -> None:
    hyperion = load("hyperion_wither_impact", "legacy")
    terminator = load("runed_terminator", "legacy")
    assert hyperion.cache_key() != terminator.cache_key()
    # Identity does not affect the cache key: two of the same item ask the
    # same question and must not cost two API calls.
    twin = ItemSignature.from_dict({**hyperion.as_dict(), "uid": "ffffffffffff"})
    assert twin.cache_key() == hyperion.cache_key()

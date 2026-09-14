"""Modifiers: ranking them, filtering on them, and pricing them on their own.

Two jobs.

First, decide the order in which modifiers are given up during the relaxation
search.  The ranking only has to be directionally right: it decides which
question is asked next, and the money it gives up is then priced from that
modifier's own market, so an ordering mistake costs a little accuracy rather
than a lot.

Second, translate a modifier into Coflnet query parameters.  Not everything can
be expressed as a filter -- the API accepts at most two enchantments per query
-- and anything that cannot be filtered on is treated as dropped, because a
filter that is silently ignored would leave the comparables unconstrained while
the code believed otherwise.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..parsing.signature import ItemSignature
from .values import DEFAULT_VALUES, ValueTable

#: Coflnet accepts one primary and one secondary enchantment filter.
MAX_ENCHANT_FILTERS = 2

# ---- rough value contributions, in coins -----------------------------------
# Hand-written starting point, per the brief.  Refine from observed data once
# the ledger has enough acquisitions to regress against.

ULTIMATE_ENCHANT_VALUE: dict[str, int] = {
    "ultimate_chimera": 120_000_000,
    "ultimate_one_for_all": 15_000_000,
    "ultimate_soul_eater": 3_000_000,
    "ultimate_legion": 8_000_000,
    "ultimate_wise": 2_000_000,
    "ultimate_swarm": 6_000_000,
    "ultimate_fatal_tempo": 40_000_000,
    "ultimate_duplex": 20_000_000,
    "ultimate_inferno": 12_000_000,
    "ultimate_rend": 2_000_000,
    "ultimate_last_stand": 4_000_000,
    "ultimate_no_pain_no_gain": 5_000_000,
    "ultimate_combo": 3_000_000,
    "ultimate_bank": 2_000_000,
    "ultimate_flash": 1_500_000,
    "ultimate_habanero_tactics": 1_500_000,
    "ultimate_the_one": 10_000_000,
    "ultimate_jerry": 500_000,
}
DEFAULT_ULTIMATE_VALUE = 3_000_000

#: Dungeon stars 1-5 come from essence; 6-10 need master stars, which are items.
MASTER_STAR_VALUE: tuple[int, ...] = (
    30_000_000, 60_000_000, 120_000_000, 250_000_000, 500_000_000,
)
MASTER_STAR_TAGS: tuple[str, ...] = (
    "FIRST_MASTER_STAR",
    "SECOND_MASTER_STAR",
    "THIRD_MASTER_STAR",
    "FOURTH_MASTER_STAR",
    "FIFTH_MASTER_STAR",
)
ESSENCE_STAR_VALUE = 2_000_000

GEM_VALUE: dict[str, int] = {
    "PERFECT": 8_000_000,
    "FLAWLESS": 1_500_000,
    "FINE": 200_000,
    "FLAWED": 30_000,
    "ROUGH": 5_000,
}

RECOMB_VALUE = 12_000_000
ART_OF_WAR_VALUE = 5_000_000
REFORGE_VALUE = 3_000_000
RUNE_VALUE = 2_000_000
SKIN_VALUE = 50_000_000
DYE_VALUE = 200_000_000
HPB_VALUE = 100_000
FUMING_VALUE = 1_200_000
PET_HELD_ITEM_VALUE = 10_000_000
COMMON_ENCHANT_VALUE = 400_000

#: An attribute shard roughly doubles in price per level.
ATTRIBUTE_BASE_VALUE = 250_000

#: How much of a modifier's standalone price actually carries into the item.
#: Applying a book costs coins and time, and a used item never fetches the full
#: sum of its parts, so an add-back at 100% would systematically overvalue.
DEFAULT_RECOVERY = 0.75
RECOVERY: dict[str, float] = {
    "enchantment": 0.75,
    "attribute": 0.90,
    "star": 0.85,
    "gem": 0.70,
    "recomb": 0.80,
    "reforge": 0.60,
    "hot_potato": 0.70,
    "art_of_war": 0.80,
    "rune": 0.50,
    "skin": 0.85,
    "dye": 0.90,
    "pet_held_item": 0.85,
    "ability_scroll": 0.85,
}


@dataclass(frozen=True)
class Modifier:
    """One price-moving property of an item."""

    kind: str
    key: str
    level: int = 0
    label: str = ""
    #: Rough coin contribution.  Used only to order the relaxation search.
    rank: float = 0.0
    #: Coflnet parameters this modifier contributes, if any.
    filters: dict[str, Any] = field(default_factory=dict)
    #: Which filter family it occupies, so competing modifiers can be counted.
    filter_slot: str | None = None
    #: How to price it on its own once it has been dropped.
    price_tag: str | None = None
    price_filters: dict[str, Any] = field(default_factory=dict)
    #: Multiplier on that standalone price when adding it back.
    recovery: float = DEFAULT_RECOVERY
    #: Whether comparables must share this. An item carries twenty
    #: enchantments and most are worth nothing; insisting a comparable match
    #: every one of them leaves nothing to compare against.
    use_for_matching: bool = True

    @property
    def filterable(self) -> bool:
        return bool(self.filters)

    @property
    def priceable(self) -> bool:
        return self.price_tag is not None

    def __str__(self) -> str:
        return self.label or f"{self.key} {self.level}".strip()


def _enchant_modifier(name: str, level: int, values: ValueTable) -> Modifier:
    rank = values.enchant_value(name, level)
    worthy = rank >= values.min_enchant_filter_value
    pretty = name.replace("ultimate_", "").replace("_", " ").title()
    return Modifier(
        kind="enchantment",
        key=name,
        level=level,
        label=f"{pretty} {level}",
        rank=rank,
        # Only the expensive ones narrow the comparables. The rest are given
        # up and priced back from the book market instead.
        filters={"Enchantment": name, "EnchantLvl": level} if worthy else {},
        filter_slot="enchantment",
        price_tag="ENCHANTED_BOOK",
        price_filters={"Enchantment": name, "EnchantLvl": level},
        recovery=RECOVERY["enchantment"],
        use_for_matching=worthy,
    )


def _attribute_modifier(name: str, level: int) -> Modifier:
    pretty = name.replace("_", " ").title()
    return Modifier(
        kind="attribute",
        key=name,
        level=level,
        label=f"{pretty} {level}",
        rank=ATTRIBUTE_BASE_VALUE * (2 ** max(0, level - 1)),
        # Attributes are not a Coflnet filter of their own; they come along
        # with the item, so they can only be kept by luck or dropped.
        filters={},
        filter_slot="attribute",
        price_tag="ATTRIBUTE_SHARD",
        price_filters={"Enchantment": name, "EnchantLvl": level},
        recovery=RECOVERY["attribute"],
    )


def _star_modifier(stars: int) -> Modifier:
    master = max(0, stars - 5)
    rank = ESSENCE_STAR_VALUE * min(stars, 5) + sum(MASTER_STAR_VALUE[:master])
    return Modifier(
        kind="star",
        key="stars",
        level=stars,
        label=f"{stars} star" if stars == 1 else f"{stars} stars",
        rank=rank,
        filters={"Stars": stars},
        filter_slot="stars",
        price_tag=MASTER_STAR_TAGS[master - 1] if master else None,
        recovery=RECOVERY["star"],
    )


def _gem_modifiers(sig: ItemSignature) -> list[Modifier]:
    """Gems are filtered by count at a quality, not slot by slot."""
    by_quality: dict[str, int] = {}
    for gem in sig.gems:
        by_quality[gem.quality] = by_quality.get(gem.quality, 0) + 1
    out: list[Modifier] = []
    for quality, count in sorted(by_quality.items()):
        unit = GEM_VALUE.get(quality, 50_000)
        filters: dict[str, Any] = {}
        if quality == "PERFECT":
            filters = {"PerfectGemsCount": count}
        elif quality == "FLAWLESS":
            filters = {"FlawlessGemsCount": count}
        kinds = [g.kind for g in sig.gems if g.quality == quality and g.kind]
        tag = f"{quality}_{kinds[0]}_GEM" if kinds else None
        out.append(
            Modifier(
                kind="gem",
                key=quality.lower(),
                level=count,
                label=f"{count}x {quality.title()}",
                rank=unit * count,
                filters=filters,
                filter_slot=f"gem:{quality}",
                price_tag=tag,
                recovery=RECOVERY["gem"],
            )
        )
    return out


def _pet_modifiers(sig: ItemSignature) -> list[Modifier]:
    pet = sig.pet
    if pet is None:
        return []
    out: list[Modifier] = []
    # A dragon past level 100 is deliberately not filtered on level: Coflnet
    # reads PetLevel 100 as "100 or more exp", which matches almost everything.
    if pet.level_is_exact:
        out.append(
            Modifier(
                kind="pet_level",
                key="level",
                level=pet.level,
                label=f"Level {pet.level}",
                rank=float(pet.level) * 200_000,
                filters={"PetLevel": pet.level},
                filter_slot="pet_level",
            )
        )
    if pet.held_item:
        out.append(
            Modifier(
                kind="pet_held_item",
                key=pet.held_item,
                label=pet.held_item.replace("PET_ITEM_", "").replace("_", " ").title(),
                rank=PET_HELD_ITEM_VALUE,
                filters={"PetItem": pet.held_item},
                filter_slot="pet_item",
                price_tag=pet.held_item,
                recovery=RECOVERY["pet_held_item"],
            )
        )
    if pet.skin:
        out.append(
            Modifier(
                kind="pet_skin",
                key=pet.skin,
                label="Pet skin",
                rank=SKIN_VALUE / 2,
                filters={"PetSkin": pet.skin},
                filter_slot="pet_skin",
                price_tag=pet.skin,
                recovery=RECOVERY["skin"],
            )
        )
    if pet.candy_used:
        # Candy is the one modifier that takes value away.  It ranks last so
        # it is given up first, and its add-back is negative.
        out.append(
            Modifier(
                kind="pet_candy",
                key="candy",
                level=pet.candy_used,
                label=f"{pet.candy_used}x candy",
                rank=-1.0,
                filter_slot="pet_candy",
            )
        )
    return out


def rank_by_value_contribution(
    sig: ItemSignature, values: ValueTable = DEFAULT_VALUES
) -> list[Modifier]:
    """Every modifier on an item, most valuable first.

    This is the order the relaxation search gives things up in: the least
    valuable modifier is dropped first, because losing it from the filter set
    costs the least accuracy when it is priced back in separately.
    """
    mods: list[Modifier] = []

    for name, level in sig.enchantments:
        mods.append(_enchant_modifier(name, level, values))
    for name, level in sig.attributes:
        mods.append(_attribute_modifier(name, level))
    if sig.stars:
        mods.append(_star_modifier(sig.stars))
    mods.extend(_gem_modifiers(sig))
    mods.extend(_pet_modifiers(sig))

    if sig.recombobulated:
        mods.append(
            Modifier(
                kind="recomb",
                key="recombobulated",
                label="Recombobulated",
                rank=RECOMB_VALUE,
                filters={"Recombobulated": "true"},
                filter_slot="recomb",
                price_tag="RECOMBOBULATOR_3000",
                recovery=RECOVERY["recomb"],
            )
        )
    if sig.reforge:
        mods.append(
            Modifier(
                kind="reforge",
                key=sig.reforge,
                label=sig.reforge.title(),
                rank=REFORGE_VALUE,
                # Title case: the API rejects "fabled" outright, and rejects
                # some reforge names in any casing at all, which is why the
                # search treats this filter as droppable rather than trusted.
                filters={"Reforge": sig.reforge.title()},
                filter_slot="reforge",
                recovery=RECOVERY["reforge"],
            )
        )
    if sig.hot_potato:
        # Past ten, the extras are fuming potato books and worth far more.
        fuming = max(0, sig.hot_potato - 10)
        plain = min(10, sig.hot_potato)
        mods.append(
            Modifier(
                kind="hot_potato",
                key="hot_potato",
                level=sig.hot_potato,
                label=f"{sig.hot_potato}x potato",
                rank=plain * HPB_VALUE + fuming * FUMING_VALUE,
                filters={"HotPotatoCount": sig.hot_potato},
                filter_slot="hot_potato",
                price_tag="FUMING_POTATO_BOOK" if fuming else "HOT_POTATO_BOOK",
                recovery=RECOVERY["hot_potato"],
            )
        )
    if sig.art_of_war:
        mods.append(
            Modifier(
                kind="art_of_war",
                key="art_of_war",
                label="Art of War",
                rank=ART_OF_WAR_VALUE,
                filters={"ArtOfTheWar": "true"},
                filter_slot="art_of_war",
                price_tag="THE_ART_OF_WAR",
                recovery=RECOVERY["art_of_war"],
            )
        )
    if sig.skin:
        mods.append(
            Modifier(
                kind="skin",
                key=sig.skin,
                label="Skin",
                rank=SKIN_VALUE,
                filters={"Skin": sig.skin},
                filter_slot="skin",
                price_tag=sig.skin,
                recovery=RECOVERY["skin"],
            )
        )
    if sig.dye:
        mods.append(
            Modifier(
                kind="dye",
                key=sig.dye,
                label="Dyed",
                rank=DYE_VALUE,
                filters={"DyeItem": sig.dye},
                filter_slot="dye",
                price_tag=sig.dye,
                recovery=RECOVERY["dye"],
            )
        )
    if sig.rune:
        name, level = sig.rune
        mods.append(
            Modifier(
                kind="rune",
                key=name,
                level=level,
                label=f"{name.replace('_', ' ').title()} {level}",
                rank=RUNE_VALUE * level,
                price_tag=f"{name}_RUNE",
                recovery=RECOVERY["rune"],
            )
        )
    for scroll in sig.ability_scroll:
        mods.append(
            Modifier(
                kind="ability_scroll",
                key=scroll,
                label=scroll.replace("_SCROLL", "").replace("_", " ").title(),
                rank=80_000_000,
                price_tag=scroll,
                recovery=RECOVERY["ability_scroll"],
            )
        )

    mods.sort(key=lambda m: (-m.rank, m.kind, m.key))
    return mods


def to_filters(
    modifiers: list[Modifier], sig: ItemSignature | None = None
) -> tuple[dict[str, Any], list[Modifier]]:
    """Build a Coflnet query from a set of kept modifiers.

    Returns the parameters plus the modifiers that could **not** be expressed.
    Those are handed back so the caller can treat them as dropped and price
    them separately.  Silently including a modifier the API cannot filter on
    would leave the comparables unconstrained while the code believed they
    matched, which is the one failure mode that produces a confident wrong
    number.
    """
    filters: dict[str, Any] = {}
    unrepresentable: list[Modifier] = []
    enchant_slots = 0

    if sig is not None and sig.rarity:
        # The rarity the auction house shows, which for a recombobulated item
        # is the upgraded one. Filtering on the pre-recomb rarity instead
        # excluded every recombobulated listing -- and anything worth
        # lowballing is recombobulated -- so a fully specified item matched
        # nothing at all. Recombobulation is carried separately below.
        filters["Rarity"] = sig.rarity

    for mod in modifiers:
        if not mod.filterable:
            unrepresentable.append(mod)
            continue
        if mod.kind == "enchantment":
            if enchant_slots == 0:
                filters["Enchantment"] = mod.key
                filters["EnchantLvl"] = mod.level
            elif enchant_slots == 1:
                filters["SecondEnchantment"] = mod.key
                filters["SecondEnchantLvl"] = mod.level
            else:
                # The API takes two enchantments; the rest have to be dropped.
                unrepresentable.append(mod)
                continue
            enchant_slots += 1
            continue
        clash = any(key in filters for key in mod.filters)
        if clash:
            unrepresentable.append(mod)
            continue
        filters.update(mod.filters)

    return filters, unrepresentable


def describe(modifiers: list[Modifier]) -> list[str]:
    return [str(m) for m in modifiers]

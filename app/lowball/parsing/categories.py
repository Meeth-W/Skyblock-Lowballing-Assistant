"""Item categories.

Used for two things: grouping in the reports view, and as the middle rung of
the shrinkage ladder in the offer model (item tag, then category, then value
bucket, then global).  The groups are coarse on purpose -- they exist so a tag
with three observations can borrow from something related, not to slice the
data further.
"""

from __future__ import annotations

from .signature import ItemSignature

WEAPON = "Weapon"
ARMOR = "Armor"
EQUIPMENT = "Equipment"
ACCESSORY = "Accessory"
PET = "Pet"
TOOL = "Tool"
CONSUMABLE = "Consumable"
BOOK = "Book"
COSMETIC = "Cosmetic"
MATERIAL = "Material"
OTHER = "Other"

#: SkyBlock's own category words, as they appear on the rarity line.
_BY_LORE_CATEGORY: dict[str, str] = {
    "SWORD": WEAPON,
    "BOW": WEAPON,
    "LONGSWORD": WEAPON,
    "GAUNTLET": WEAPON,
    "WAND": WEAPON,
    "FISHING WEAPON": WEAPON,
    "HELMET": ARMOR,
    "CHESTPLATE": ARMOR,
    "LEGGINGS": ARMOR,
    "BOOTS": ARMOR,
    "NECKLACE": EQUIPMENT,
    "CLOAK": EQUIPMENT,
    "BELT": EQUIPMENT,
    "GLOVES": EQUIPMENT,
    "BRACELET": EQUIPMENT,
    "ACCESSORY": ACCESSORY,
    "HATCESSORY": ACCESSORY,
    "PET": PET,
    "PET ITEM": PET,
    "AXE": TOOL,
    "PICKAXE": TOOL,
    "DRILL": TOOL,
    "SHOVEL": TOOL,
    "HOE": TOOL,
    "FISHING ROD": TOOL,
    "SHEARS": TOOL,
    "TRAVEL SCROLL": CONSUMABLE,
    "ARROW POISON": CONSUMABLE,
    "REFORGE STONE": MATERIAL,
    "COSMETIC": COSMETIC,
    "DEPLOYABLE": EQUIPMENT,
}

#: Fallbacks keyed on how the item tag reads, for items whose lore is missing.
_BY_TAG_SUFFIX: tuple[tuple[str, str], ...] = (
    ("_HELMET", ARMOR),
    ("_CHESTPLATE", ARMOR),
    ("_LEGGINGS", ARMOR),
    ("_BOOTS", ARMOR),
    ("_SWORD", WEAPON),
    ("_BOW", WEAPON),
    ("_AXE", TOOL),
    ("_PICKAXE", TOOL),
    ("_DRILL", TOOL),
    ("_NECKLACE", EQUIPMENT),
    ("_CLOAK", EQUIPMENT),
    ("_BELT", EQUIPMENT),
    ("_GLOVES", EQUIPMENT),
    ("_TALISMAN", ACCESSORY),
    ("_RING", ACCESSORY),
    ("_ARTIFACT", ACCESSORY),
    ("_RELIC", ACCESSORY),
    ("_SKIN", COSMETIC),
)

_BY_TAG_EXACT: dict[str, str] = {
    "PET": PET,
    "ENCHANTED_BOOK": BOOK,
    "ATTRIBUTE_SHARD": MATERIAL,
    "RUNE": COSMETIC,
}


def category_of(sig: ItemSignature) -> str:
    """Best available category for an item, never None."""
    if sig.is_pet:
        return PET
    tag = (sig.tag or "").upper()
    if tag in _BY_TAG_EXACT:
        return _BY_TAG_EXACT[tag]
    lore_category = (sig.category or "").upper().strip()
    if lore_category in _BY_LORE_CATEGORY:
        return _BY_LORE_CATEGORY[lore_category]
    for suffix, group in _BY_TAG_SUFFIX:
        if tag.endswith(suffix):
            return group
    # A lore category we do not have a group for is still better than nothing.
    if lore_category:
        return lore_category.title()
    return OTHER


def pet_family(sig: ItemSignature) -> str | None:
    """``PET:GOLDEN_DRAGON``, so pets group by species rather than all together."""
    if not sig.is_pet or sig.pet is None:
        return None
    return f"PET:{sig.pet.type}"


def shrinkage_key(sig: ItemSignature) -> str:
    """The category rung of the shrinkage ladder.

    Pets use their species, because a Golden Dragon and a Rock share nothing
    that would make pooling them informative.
    """
    return pet_family(sig) or category_of(sig)

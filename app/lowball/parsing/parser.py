"""NBT to ItemSignature.

Tolerant by design.  SkyBlock has changed how it stores gems, stars and pet
data more than once, and an item this parser cannot read is an item the user
cannot price while a customer stands in front of them.  Unknown shapes are
skipped, never raised on.
"""

from __future__ import annotations

import re
from typing import Any

from ..ids import uid_of
from .nbt import (
    decode_inventory,
    decode_item,
    display_name,
    extra_attributes,
    lore_lines,
    stack_count,
)
from .pets import parse_pet_info
from .signature import RARITIES, Gem, ItemSignature

_FORMAT_CODE = re.compile("[\u00a7&][0-9a-fk-orA-FK-OR]")

#: Words that appear on the rarity line but are not part of the category.
_RARITY_LINE_NOISE = frozenset({"DUNGEON", "SHINY", "ACCESSORY!"})

#: Keys inside the gems compound that are not themselves a filled slot.
_GEM_META_KEYS = frozenset({"unlocked_slots"})


def strip_formatting(text: str) -> str:
    return _FORMAT_CODE.sub("", text or "").strip()


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def parse_rarity_line(lore: list[str]) -> tuple[str | None, str | None]:
    """Pull rarity and category from the rarity line at the foot of the lore.

    The line reads like ``MYTHIC DUNGEON SWORD``; the rarity is the first token
    that names one, and whatever follows is the category.
    """
    for raw in reversed(lore):
        line = strip_formatting(raw).upper().strip()
        if not line:
            continue
        cleaned = re.sub("[^A-Z ]", " ", line)
        tokens = [t for t in cleaned.split() if t]
        if not tokens:
            continue
        # "VERY SPECIAL" is two words; check it before single tokens.
        rarity: str | None = None
        start = 0
        if len(tokens) >= 2 and f"{tokens[0]} {tokens[1]}" == "VERY SPECIAL":
            rarity, start = "VERY SPECIAL", 2
        else:
            for index, token in enumerate(tokens):
                if token in RARITIES:
                    rarity, start = token, index + 1
                    break
        if rarity is None:
            continue
        # Single letters are what is left of an obfuscated glyph once the
        # formatting codes are stripped -- a shiny item's rarity line reads
        # "a SHINY MYTHIC DUNGEON SWORD a" -- so they are not category words.
        rest = [
            token
            for token in tokens[start:]
            if token not in _RARITY_LINE_NOISE and len(token) > 1
        ]
        return rarity, " ".join(rest) or None
    return None, None


def parse_gems(raw: Any) -> tuple[Gem, ...]:
    """Read the gems compound in either the old or the current layout."""
    if not isinstance(raw, dict):
        return ()
    gems: list[Gem] = []
    for slot, value in raw.items():
        if slot in _GEM_META_KEYS or slot.endswith("_gem"):
            continue
        if isinstance(value, dict):
            quality = value.get("quality")
        elif isinstance(value, str):
            quality = value
        else:
            continue
        if not quality:
            continue
        kind = raw.get(f"{slot}_gem")
        gems.append(Gem(str(slot), str(quality).upper(), str(kind).upper() if kind else None))
    return tuple(sorted(gems))


def _parse_rune(raw: Any) -> tuple[str, int] | None:
    if not isinstance(raw, dict) or not raw:
        return None
    name, level = next(iter(raw.items()))
    return str(name).upper(), _as_int(level, 1)


def _parse_ability_scroll(raw: Any) -> tuple[str, ...]:
    if isinstance(raw, list):
        return tuple(sorted(str(s).upper() for s in raw))
    if isinstance(raw, str):
        return (raw.upper(),)
    return ()


#: ExtraAttributes keys already represented by a dedicated signature field.
_CLAIMED_KEYS = frozenset(
    {
        "id", "uuid", "uId", "modifier", "enchantments", "upgrade_level",
        "dungeon_item_level", "gems", "attributes", "hot_potato_count",
        "rarity_upgrades", "art_of_war_count", "skin", "dye_item", "runes",
        "petInfo", "ability_scroll", "timestamp", "originTag", "donated_museum",
        "uuid_hash", "compact_blocks", "boss_tier", "item_tier",
    }
)


def signature_from_item(item: dict[str, Any]) -> ItemSignature | None:
    """Build a signature from one decoded item stack.

    Returns None for an empty slot or for anything without a SkyBlock id,
    which is how vanilla items and air are filtered out.
    """
    ea = extra_attributes(item)
    tag = ea.get("id")
    if not tag:
        return None
    tag = str(tag).upper()

    lore = lore_lines(item)
    rarity, category = parse_rarity_line(lore)
    shown_name = strip_formatting(display_name(item))
    pet = parse_pet_info(ea.get("petInfo"), display_name=shown_name)
    if pet is not None:
        # The lore rarity of a pet is its tier; petInfo is the source of truth.
        rarity = pet.tier
        category = category or "PET"
        # Every pet carries the id "PET"; the auction house lists them under
        # the species. Without this the market lookup asks about a tag that
        # matches nothing, which is why pets priced at zero.
        tag = f"PET_{pet.type}"

    item_uuid = ea.get("uuid")
    item_uuid = str(item_uuid) if item_uuid else None
    uid = ea.get("uId")
    uid = str(uid) if uid else uid_of(item_uuid)

    enchantments = {
        str(k).lower(): _as_int(v)
        for k, v in (ea.get("enchantments") or {}).items()
        if _as_int(v) > 0
    }
    attributes = {
        str(k).lower(): _as_int(v)
        for k, v in (ea.get("attributes") or {}).items()
        if _as_int(v) > 0
    }
    stars = _as_int(ea.get("upgrade_level"), 0) or _as_int(ea.get("dungeon_item_level"), 0)

    extras = {
        str(k): str(v)
        for k, v in ea.items()
        if k not in _CLAIMED_KEYS and isinstance(v, (str, int, float))
    }

    return ItemSignature(
        tag=tag,
        display_name=shown_name,
        rarity=rarity,
        category=category,
        count=stack_count(item),
        item_uuid=item_uuid,
        uid=uid,
        reforge=str(ea["modifier"]).lower() if ea.get("modifier") else None,
        enchantments=tuple(sorted(enchantments.items())),
        stars=stars,
        gems=parse_gems(ea.get("gems")),
        attributes=tuple(sorted(attributes.items())),
        hot_potato=_as_int(ea.get("hot_potato_count"), 0),
        recombobulated=_as_int(ea.get("rarity_upgrades"), 0) > 0,
        art_of_war=_as_int(ea.get("art_of_war_count"), 0) > 0,
        skin=str(ea["skin"]).upper() if ea.get("skin") else None,
        dye=str(ea["dye_item"]).upper() if ea.get("dye_item") else None,
        rune=_parse_rune(ea.get("runes")),
        pet=pet,
        ability_scroll=_parse_ability_scroll(ea.get("ability_scroll")),
        extras=tuple(sorted(extras.items())),
    )


def signature_from_b64(payload: str) -> ItemSignature | None:
    """Decode one base64 item blob straight to a signature."""
    return signature_from_item(decode_item(payload))


def signatures_from_inventory(payload: str) -> list[ItemSignature | None]:
    """Decode a whole inventory, keeping empty slots as None so indices hold."""
    return [signature_from_item(entry) for entry in decode_inventory(payload)]

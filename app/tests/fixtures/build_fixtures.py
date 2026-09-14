"""Regenerate the parser fixture corpus.

These blobs go through the real gzip + NBT + base64 path, so the fixtures
exercise decoding end to end rather than handing the parser a dict.

They are modelled on the documented shape of SkyBlock item data, not captured
from a live trade.  Real captures are strictly better and should be dropped in
here as they are collected -- see fixtures/README.md.

Run:  python build_fixtures.py
"""

from __future__ import annotations

import base64
import gzip
import io
import json
from pathlib import Path
from typing import Any

import nbtlib
from nbtlib import Byte, Compound, Int, List, String

HERE = Path(__file__).parent

SECTION = "\u00a7"


def _tag(value: Any) -> Any:
    if isinstance(value, bool):
        return Byte(int(value))
    if isinstance(value, int):
        return Int(value)
    if isinstance(value, str):
        return String(value)
    if isinstance(value, dict):
        return Compound({k: _tag(v) for k, v in value.items()})
    if isinstance(value, list):
        if not value:
            return List[String]([])
        tagged = [_tag(v) for v in value]
        return List[type(tagged[0])](tagged)
    raise TypeError(f"cannot tag {value!r}")


def encode(root: dict[str, Any]) -> str:
    """dict -> NBT -> gzip -> base64, the way the mod and the API both send it."""
    buf = io.BytesIO()
    nbtlib.File(_tag(root)).write(buf)
    return base64.b64encode(gzip.compress(buf.getvalue())).decode("ascii")


def legacy_item(
    *, mc_id: str, name: str, lore: list[str], extra: dict[str, Any], count: int = 1
) -> dict[str, Any]:
    """The pre-1.20.5 layout, still what the Hypixel API returns."""
    return {
        "id": mc_id,
        "Count": count,
        "Damage": 0,
        "tag": {
            "display": {"Name": name, "Lore": lore},
            "ExtraAttributes": extra,
        },
    }


def component_item(
    *, mc_id: str, name: str, lore: list[str], extra: dict[str, Any], count: int = 1
) -> dict[str, Any]:
    """The 1.20.5+ layout the mod sees, with ExtraAttributes under custom_data."""
    return {
        "id": mc_id,
        "count": count,
        "components": {
            "minecraft:custom_name": json.dumps({"text": name}),
            "minecraft:lore": [json.dumps({"text": line}) for line in lore],
            "minecraft:custom_data": {"ExtraAttributes": extra},
        },
    }


S = SECTION

ITEMS: dict[str, dict[str, Any]] = {
    # A fully loaded end-game sword: the hard case for relaxation search.
    "hyperion_wither_impact": {
        "mc_id": "minecraft:diamond_sword",
        "name": f"{S}dHeroic Hyperion {S}6\u272a{S}6\u272a{S}6\u272a{S}6\u272a{S}6\u272a",
        "lore": [f"{S}d{S}lMYTHIC DUNGEON SWORD"],
        "extra": {
            "id": "HYPERION",
            "uuid": "6e1b0a3c-9f2d-4a11-b7e8-a1b2c3d4e5f6",
            "uId": "a1b2c3d4e5f6",
            "modifier": "heroic",
            "enchantments": {
                "ultimate_wise": 5,
                "sharpness": 7,
                "critical": 7,
                "looting": 5,
                "scavenger": 5,
            },
            "upgrade_level": 5,
            "rarity_upgrades": 1,
            "hot_potato_count": 15,
            "art_of_war_count": 1,
            "gems": {
                "COMBAT_0": "PERFECT",
                "COMBAT_0_gem": "SAPPHIRE",
                "UNIVERSAL_0": "PERFECT",
                "UNIVERSAL_0_gem": "JASPER",
                "unlocked_slots": ["COMBAT_0", "UNIVERSAL_0"],
            },
            "timestamp": 1694600000,
        },
    },
    # Attribute shards on a chestplate: the other multi-modifier shape.
    "crimson_chestplate_attributes": {
        "mc_id": "minecraft:leather_chestplate",
        "name": f"{S}6Ancient Crimson Chestplate",
        "lore": [f"{S}6{S}lLEGENDARY CHESTPLATE"],
        "extra": {
            "id": "CRIMSON_CHESTPLATE",
            "uuid": "11112222-3333-4444-5555-666677778888",
            "uId": "666677778888",
            "modifier": "ancient",
            "enchantments": {"growth": 6, "protection": 6},
            "attributes": {"lifeline": 5, "mana_pool": 4},
            "hot_potato_count": 10,
        },
    },
    # A pet: level comes from exp and tier, never from the lore.
    "golden_dragon_pet": {
        "mc_id": "minecraft:player_head",
        "name": f"{S}6[Lvl 160] Golden Dragon",
        "lore": [f"{S}6{S}lLEGENDARY PET"],
        "extra": {
            "id": "PET",
            "uuid": "aaaa1111-bbbb-2222-cccc-3333dddd4444",
            "petInfo": json.dumps(
                {
                    "type": "GOLDEN_DRAGON",
                    "active": False,
                    "exp": 96_000_000.0,
                    "tier": "LEGENDARY",
                    "hideInfo": False,
                    "candyUsed": 0,
                    "heldItem": "PET_ITEM_TIER_BOOST",
                    "uuid": "aaaa1111-bbbb-2222-cccc-3333dddd4444",
                }
            ),
        },
    },
    # A low-level pet, which the rules engine normalises to level 1.
    "low_level_wolf_pet": {
        "mc_id": "minecraft:player_head",
        "name": f"{S}5[Lvl 42] Wolf",
        "lore": [f"{S}5{S}lEPIC PET"],
        "extra": {
            "id": "PET",
            "uuid": "beef1111-2222-3333-4444-555566667777",
            "petInfo": json.dumps(
                {"type": "WOLF", "exp": 120000.0, "tier": "EPIC", "candyUsed": 3}
            ),
        },
    },
}

ITEMS.update(
    {
        # A skin plus a dye: the illiquid combination the rules engine discounts.
        "skinned_dyed_helmet": {
            "mc_id": "minecraft:leather_helmet",
            "name": f"{S}6Necron's Helmet",
            "lore": [f"{S}6{S}lLEGENDARY DUNGEON HELMET"],
            "extra": {
                "id": "POWER_WITHER_HELMET",
                "uuid": "cafe0001-0002-0003-0004-000500060007",
                "uId": "000500060007",
                "modifier": "renowned",
                "skin": "NECRON_HELMET_TIED",
                "dye_item": "DYE_NECRON",
                "upgrade_level": 10,
                "rarity_upgrades": 1,
            },
        },
        # Stackable: no uuid, so no join key for auction house tracking.
        "stackable_enchanted_book": {
            "mc_id": "minecraft:enchanted_book",
            "count": 16,
            "name": f"{S}aEnchanted Book",
            "lore": [f"{S}9Ultimate Wise V", f"{S}6{S}lLEGENDARY"],
            "extra": {
                "id": "ENCHANTED_BOOK",
                "enchantments": {"ultimate_wise": 5},
            },
        },
        # A rune and an ability scroll on a bow.
        "runed_terminator": {
            "mc_id": "minecraft:bow",
            "name": f"{S}dTerminator",
            "lore": [f"{S}d{S}lMYTHIC BOW"],
            "extra": {
                "id": "TERMINATOR",
                "uuid": "dead0001-0002-0003-0004-000500060008",
                "uId": "000500060008",
                "modifier": "withered",
                "enchantments": {"ultimate_soul_eater": 5, "power": 7},
                "runes": {"BARK_TUNES": 3},
                "ability_scroll": ["IMPLOSION_SCROLL", "WITHER_SHIELD_SCROLL"],
                "rarity_upgrades": 1,
            },
        },
        # A plain vanilla item, which must parse to nothing at all.
        "vanilla_cobblestone": {
            "mc_id": "minecraft:cobblestone",
            "count": 64,
            "name": "Cobblestone",
            "lore": [],
            "extra": {},
        },
    }
)


def main() -> None:
    manifest: dict[str, Any] = {}
    for key, spec in ITEMS.items():
        count = spec.get("count", 1)
        legacy = legacy_item(
            mc_id=spec["mc_id"],
            name=spec["name"],
            lore=spec["lore"],
            extra=spec["extra"],
            count=count,
        )
        modern = component_item(
            mc_id=spec["mc_id"],
            name=spec["name"],
            lore=spec["lore"],
            extra=spec["extra"],
            count=count,
        )
        (HERE / f"{key}.legacy.b64").write_text(encode({"i": [legacy]}), encoding="utf-8")
        (HERE / f"{key}.component.b64").write_text(encode(modern), encoding="utf-8")
        manifest[key] = {"tag": spec["extra"].get("id"), "count": count}

    # One multi-slot inventory blob, the shape the Hypixel API returns.
    inventory = [
        legacy_item(
            mc_id=spec["mc_id"],
            name=spec["name"],
            lore=spec["lore"],
            extra=spec["extra"],
            count=spec.get("count", 1),
        )
        for spec in ITEMS.values()
    ]
    inventory.insert(2, {})  # an empty slot in the middle
    (HERE / "inventory.legacy.b64").write_text(encode({"i": inventory}), encoding="utf-8")
    manifest["_inventory_slots"] = len(inventory)

    (HERE / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"wrote {len(ITEMS)} items in two layouts, plus a {len(inventory)}-slot inventory")


if __name__ == "__main__":
    main()

"""The canonical form of an item.

An ItemSignature is what the rest of the app passes around instead of raw NBT:
frozen, hashable, ordered deterministically, and cheap to serialise.  It is the
cache key, the input to the comparable search, and what gets stored on an offer
so a price can later be explained.

Ordering matters.  Two items with the same modifiers in a different NBT order
must produce the same signature, or the cache misses and the rate limit pays
for it.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from .pets import PetInfo

RARITIES = (
    "COMMON",
    "UNCOMMON",
    "RARE",
    "EPIC",
    "LEGENDARY",
    "MYTHIC",
    "DIVINE",
    "SPECIAL",
    "VERY SPECIAL",
    "ULTIMATE",
    "ADMIN",
)

#: Gemstone qualities, weakest first.
GEM_QUALITIES = ("ROUGH", "FLAWED", "FINE", "FLAWLESS", "PERFECT")


@dataclass(frozen=True, order=True)
class Gem:
    """One filled gemstone slot.

    ``slot`` is the slot name from NBT (``COMBAT_0``).  ``kind`` is the stone
    itself, which for a universal slot is stored separately in NBT and for a
    typed slot is implied by the slot name.
    """

    slot: str
    quality: str
    kind: str | None = None

    @property
    def slot_type(self) -> str:
        return self.slot.rsplit("_", 1)[0]

    def label(self) -> str:
        return f"{self.quality} {self.kind or self.slot_type}".title()

    def as_dict(self) -> dict[str, Any]:
        return {"slot": self.slot, "quality": self.quality, "kind": self.kind}


@dataclass(frozen=True)
class ItemSignature:
    """Everything about an item that moves its price."""

    tag: str
    display_name: str = ""
    rarity: str | None = None
    category: str | None = None
    count: int = 1
    item_uuid: str | None = None
    uid: str | None = None
    reforge: str | None = None
    enchantments: tuple[tuple[str, int], ...] = ()
    stars: int = 0
    gems: tuple[Gem, ...] = ()
    attributes: tuple[tuple[str, int], ...] = ()
    hot_potato: int = 0
    recombobulated: bool = False
    art_of_war: bool = False
    skin: str | None = None
    dye: str | None = None
    rune: tuple[str, int] | None = None
    pet: PetInfo | None = None
    ability_scroll: tuple[str, ...] = ()
    #: Extra ExtraAttributes keys kept for display and for rule predicates.
    extras: tuple[tuple[str, str], ...] = field(default=(), repr=False)

    # ---- convenience predicates used by rules and the relaxation search ----

    @property
    def is_pet(self) -> bool:
        return self.pet is not None

    @property
    def is_stackable(self) -> bool:
        """No item uuid means no identity, so it cannot be tracked to a listing."""
        return self.item_uuid is None

    @property
    def has_skin(self) -> bool:
        return self.skin is not None

    @property
    def pet_level(self) -> int | None:
        return self.pet.level if self.pet else None

    @property
    def enchant_map(self) -> dict[str, int]:
        return dict(self.enchantments)

    @property
    def attribute_map(self) -> dict[str, int]:
        return dict(self.attributes)

    def enchant_level(self, name: str) -> int:
        return self.enchant_map.get(name.lower(), 0)

    def attribute_level(self, name: str) -> int:
        return self.attribute_map.get(name.lower(), 0)

    @property
    def gem_qualities(self) -> tuple[str, ...]:
        return tuple(g.quality for g in self.gems)

    def rarity_index(self) -> int:
        try:
            return RARITIES.index((self.rarity or "").upper())
        except ValueError:
            return -1

    @property
    def base_rarity(self) -> str | None:
        """Rarity before recombobulation, which is what comparables are keyed on."""
        if not self.recombobulated or self.rarity is None:
            return self.rarity
        index = self.rarity_index()
        return RARITIES[index - 1] if index > 0 else self.rarity

    # ---- serialisation -------------------------------------------------

    def as_dict(self) -> dict[str, Any]:
        """Plain-data form, stored on offers and items in the ledger."""
        return {
            "tag": self.tag,
            "display_name": self.display_name,
            "rarity": self.rarity,
            "category": self.category,
            "count": self.count,
            "item_uuid": self.item_uuid,
            "uid": self.uid,
            "reforge": self.reforge,
            "enchantments": {k: v for k, v in self.enchantments},
            "stars": self.stars,
            "gems": [g.as_dict() for g in self.gems],
            "attributes": {k: v for k, v in self.attributes},
            "hot_potato": self.hot_potato,
            "recombobulated": self.recombobulated,
            "art_of_war": self.art_of_war,
            "skin": self.skin,
            "dye": self.dye,
            "rune": list(self.rune) if self.rune else None,
            "pet": self.pet.as_dict() if self.pet else None,
            "ability_scroll": list(self.ability_scroll),
            "extras": {k: v for k, v in self.extras},
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ItemSignature:
        pet_data = data.get("pet")
        pet = None
        if pet_data:
            pet = PetInfo(
                type=pet_data.get("type", ""),
                tier=pet_data.get("tier", "COMMON"),
                exp=float(pet_data.get("exp") or 0.0),
                candy_used=int(pet_data.get("candy_used") or 0),
                skin=pet_data.get("skin"),
                held_item=pet_data.get("held_item"),
                level=int(pet_data.get("level") or 1),
                level_is_exact=bool(pet_data.get("level_is_exact", True)),
            )
        rune = data.get("rune")
        return cls(
            tag=data["tag"],
            display_name=data.get("display_name", ""),
            rarity=data.get("rarity"),
            category=data.get("category"),
            count=int(data.get("count") or 1),
            item_uuid=data.get("item_uuid"),
            uid=data.get("uid"),
            reforge=data.get("reforge"),
            enchantments=tuple(sorted((data.get("enchantments") or {}).items())),
            stars=int(data.get("stars") or 0),
            gems=tuple(
                Gem(g["slot"], g["quality"], g.get("kind")) for g in data.get("gems") or []
            ),
            attributes=tuple(sorted((data.get("attributes") or {}).items())),
            hot_potato=int(data.get("hot_potato") or 0),
            recombobulated=bool(data.get("recombobulated")),
            art_of_war=bool(data.get("art_of_war")),
            skin=data.get("skin"),
            dye=data.get("dye"),
            rune=(rune[0], int(rune[1])) if rune else None,
            pet=pet,
            ability_scroll=tuple(data.get("ability_scroll") or ()),
            extras=tuple(sorted((data.get("extras") or {}).items())),
        )

    def to_json(self) -> str:
        return json.dumps(self.as_dict(), sort_keys=True, separators=(",", ":"))

    def cache_key(self) -> str:
        """Stable hash of everything price-relevant.

        Identity fields are excluded on purpose: two identical Hyperions must
        share a cache entry, or a 36-slot inventory pays the rate limit twice
        for the same question.
        """
        payload = self.as_dict()
        for identity_field in ("item_uuid", "uid", "display_name", "count", "extras"):
            payload.pop(identity_field, None)
        blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:20]

    def summary(self) -> list[str]:
        """Short modifier chips for the item header, in the order they read."""
        chips: list[str] = []
        if self.stars:
            chips.append(f"{self.stars}*")
        if self.reforge:
            chips.append(self.reforge.title())
        if self.recombobulated:
            chips.append("Recomb")
        for name, level in self.enchantments:
            chips.append(f"{name.replace('_', ' ').title()} {level}")
        for name, level in self.attributes:
            chips.append(f"{name.replace('_', ' ').title()} {level}")
        for gem in self.gems:
            chips.append(gem.label())
        if self.hot_potato:
            chips.append(f"{self.hot_potato}x Potato")
        if self.art_of_war:
            chips.append("AOTW")
        if self.skin:
            chips.append("Skin")
        if self.dye:
            chips.append("Dyed")
        return chips

"""Pet experience and levels.

A pet is priced almost entirely on its level, so the exp-to-level conversion
has to be right.  Levels come from walking a shared cost table starting at an
offset that depends on rarity: a legendary pet needs more exp for level 2 than
a common one because it starts further along the same curve.

Golden Dragon is the exception and is deliberately handled apart, for the
reason the brief gives: Coflnet's ``PetLevel`` filter treats 100 as "100 or
more exp" rather than "level 100", so filtering a Golden Dragon by level is
meaningless.  Levels 1-100 are computed as for any legendary pet; past that
this module reports ``level_is_exact = False`` and the valuation path filters
on exp instead of inheriting a wrong level.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

#: Exp needed for each successive level, shared by every pet.  Rarity selects
#: a starting offset into this table rather than a table of its own, which is
#: why a legendary pet costs more to level than a common one.
#:
#: 119 entries, so that the legendary offset of 20 still covers 99 level-ups.
#: Verified against the published totals to reach level 100: 5,624,785 common
#: through 25,353,230 legendary.  See test_pets.py.
PET_LEVEL_COSTS: tuple[int, ...] = (
    100, 110, 120, 130, 145, 160, 175, 190, 210, 230,
    250, 275, 300, 330, 360, 400, 440, 490, 540, 600,
    660, 730, 800, 880, 960, 1050, 1150, 1260, 1380, 1510,
    1650, 1800, 1960, 2130, 2310, 2500, 2700, 2920, 3160, 3420,
    3700, 4000, 4350, 4750, 5200, 5700, 6300, 7000, 7800, 8700,
    9700, 10800, 12000, 13300, 14700, 16200, 17800, 19500, 21300, 23200,
    25200, 27400, 29800, 32400, 35200, 38200, 41400, 44800, 48400, 52200,
    56200, 60400, 64800, 69400, 74200, 79200, 84700, 90700, 97200, 104200,
    111700, 119700, 128200, 137200, 146700, 156700, 167700, 179700, 192700, 206700,
    221700, 237700, 254700, 272700, 291700, 311700, 333700, 357700, 383700, 411700,
    441700, 476700, 516700, 561700, 611700, 666700, 726700, 791700, 861700, 936700,
    1016700, 1101700, 1191700, 1286700, 1386700, 1496700, 1616700, 1746700, 1886700,
)

#: Where each rarity starts in the cost table above.
PET_RARITY_OFFSET: dict[str, int] = {
    "COMMON": 0,
    "UNCOMMON": 6,
    "RARE": 11,
    "EPIC": 16,
    "LEGENDARY": 20,
    "MYTHIC": 20,
}

GOLDEN_DRAGON = "GOLDEN_DRAGON"
JADE_DRAGON = "JADE_DRAGON"

#: Pets that level past 100.  Their curve above 100 is not modelled here.
HIGH_LEVEL_PETS: frozenset[str] = frozenset({GOLDEN_DRAGON, JADE_DRAGON})

#: Exp at which a dragon pet reaches level 100 and level 200 respectively.
DRAGON_LEVEL_100_EXP = 25_353_230
DRAGON_MAX_EXP = 210_255_385

TIER_ORDER = ("COMMON", "UNCOMMON", "RARE", "EPIC", "LEGENDARY", "MYTHIC")

#: `[Lvl 200] Golden Dragon`. The game renders the level into the name, which
#: is the only source that covers a dragon pet above level 100 -- the
#: published exp table stops there.
LEVEL_IN_NAME = re.compile(r"\[\s*Lvl\s*(\d{1,3})\s*\]", re.IGNORECASE)


def level_from_name(name: str | None) -> int | None:
    """Read the level the game printed, if it printed one."""
    if not name:
        return None
    match = LEVEL_IN_NAME.search(name)
    if not match:
        return None
    level = int(match.group(1))
    return level if 1 <= level <= 200 else None


@dataclass(frozen=True)
class PetInfo:
    """The parsed contents of the ``petInfo`` JSON string."""

    type: str
    tier: str
    exp: float = 0.0
    candy_used: int = 0
    skin: str | None = None
    held_item: str | None = None
    level: int = 1
    #: False when the level is a floor rather than a known value, which is the
    #: case for a dragon pet above level 100.
    level_is_exact: bool = True

    @property
    def is_dragon(self) -> bool:
        return self.type in HIGH_LEVEL_PETS

    @property
    def max_level(self) -> int:
        return 200 if self.is_dragon else 100

    def as_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "tier": self.tier,
            "exp": round(float(self.exp), 1),
            "candy_used": int(self.candy_used),
            "skin": self.skin,
            "held_item": self.held_item,
            "level": int(self.level),
            "level_is_exact": bool(self.level_is_exact),
        }


def level_for_exp(exp: float, tier: str, *, pet_type: str = "") -> tuple[int, bool]:
    """Return ``(level, level_is_exact)`` for a pet holding ``exp``.

    Levels above 100 on a dragon pet are reported as 100 with
    ``level_is_exact = False``.  Guessing at that curve would put a confident
    wrong number on a multi-hundred-million item, which is exactly the failure
    this app exists to avoid; callers filter such pets on exp instead.
    """
    tier = (tier or "COMMON").upper()
    offset = PET_RARITY_OFFSET.get(tier, 0)
    costs = PET_LEVEL_COSTS[offset : offset + 99]
    level = 1
    remaining = max(0.0, float(exp))
    for cost in costs:
        if remaining < cost:
            return level, True
        remaining -= cost
        level += 1
    if (pet_type or "").upper() in HIGH_LEVEL_PETS:
        return 100, False
    return 100, True


def exp_for_level(level: int, tier: str) -> int:
    """Total exp needed to reach ``level``.  The inverse of the walk above."""
    tier = (tier or "COMMON").upper()
    offset = PET_RARITY_OFFSET.get(tier, 0)
    costs = PET_LEVEL_COSTS[offset : offset + 99]
    wanted = max(1, min(int(level), 100)) - 1
    return sum(costs[:wanted])


def dragon_level_fraction(exp: float) -> float:
    """How far a dragon pet is between level 100 and level 200, as 0.0 to 1.0.

    A coarse progress figure for display only.  It is never used as a filter
    and never presented as a level.
    """
    span = DRAGON_MAX_EXP - DRAGON_LEVEL_100_EXP
    if span <= 0:
        return 0.0
    return max(0.0, min(1.0, (float(exp) - DRAGON_LEVEL_100_EXP) / span))


def parse_pet_info(raw: Any, display_name: str | None = None) -> PetInfo | None:
    """Parse the ``petInfo`` field, which is a JSON string nested inside NBT.

    ``display_name`` is used in preference to the exp table when it carries a
    level, because it is the only thing that covers a dragon pet above 100 --
    and Coflnet's ``PetLevel`` filter does accept 200, so getting this right is
    the difference between pricing a maxed Golden Dragon against other maxed
    ones and against level 1 eggs.
    """
    if raw is None:
        return None
    data: Any = raw
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
        except ValueError:
            return None
    if not isinstance(data, dict):
        return None
    pet_type = str(data.get("type") or "").upper()
    if not pet_type:
        return None
    tier = str(data.get("tier") or "COMMON").upper()
    exp = float(data.get("exp") or 0.0)
    level, exact = level_for_exp(exp, tier, pet_type=pet_type)
    printed = level_from_name(display_name)
    if printed is not None:
        level, exact = printed, True
    held = data.get("heldItem")
    return PetInfo(
        type=pet_type,
        tier=tier,
        exp=exp,
        candy_used=int(data.get("candyUsed") or 0),
        skin=str(data["skin"]) if data.get("skin") else None,
        held_item=str(held) if held else None,
        level=level,
        level_is_exact=exact,
    )

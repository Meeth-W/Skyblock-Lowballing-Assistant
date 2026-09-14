"""Deciding whether a sold auction is comparable to the item in hand.

**Why this is done here and not by the API.** Coflnet's ``/sold`` endpoint
accepts filter parameters and ignores every one of them: the same 538 sales and
the same median come back whether you ask for ten stars, Chimera V, or nothing
at all. The relaxation search was therefore a no-op -- every probe returned an
identical result, so it kept every filter and reported the unfiltered median of
the whole tag as though it were a matched comparable set.

Filtering locally fixes that and is better in three further ways. One request
returns every recent sale for a tag, so the search costs nothing extra no
matter how many filter sets it tries. There is no two-enchantment cap, so a
Hyperion can be matched on all of its enchantments rather than two. And the
match rules are visible and testable here rather than being whatever the server
decides to do this week.

Every sale carries ``flattenedNbt`` -- stars, recombobulation, hot potato
count, gems, ability scrolls -- plus its tier and full enchantment list, which
is enough to match on everything that moves a price. The reforge is the one
exception: it appears only as a prefix on the item name.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..api.models import Auction
from ..parsing.pets import level_from_name
from .modifiers import Modifier


@dataclass(frozen=True)
class SoldItem:
    """One sold auction, normalised so modifiers can be tested against it."""

    auction: Auction
    name: str = ""
    tier: str | None = None
    enchants: dict[str, int] = field(default_factory=dict)
    flat: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_auction(cls, auction: Auction) -> SoldItem:
        raw = auction.raw or {}
        flat_raw = raw.get("flattenedNbt") or raw.get("flatNbt") or {}
        flat = {str(k): str(v) for k, v in flat_raw.items()} if isinstance(flat_raw, dict) else {}
        enchants: dict[str, int] = {}
        for entry in raw.get("enchantments") or []:
            if isinstance(entry, dict):
                name = entry.get("type") or entry.get("name")
                level = entry.get("level")
                if name is not None and isinstance(level, (int, float)):
                    enchants[str(name).lower()] = int(level)
        if not enchants:
            enchants = dict(auction.enchantments)
        return cls(
            auction=auction,
            name=str(raw.get("itemName") or auction.item_name or ""),
            tier=raw.get("tier") or auction.tier,
            enchants=enchants,
            flat=flat,
        )

    @property
    def unit_price(self) -> int:
        return self.auction.unit_price

    def _int(self, key: str) -> int:
        try:
            return int(float(self.flat.get(key, 0)))
        except (TypeError, ValueError):
            return 0

    @property
    def stars(self) -> int:
        return self._int("upgrade_level") or self._int("dungeon_item_level")

    @property
    def recombobulated(self) -> bool:
        return self._int("rarity_upgrades") > 0

    @property
    def hot_potato(self) -> int:
        return self._int("hpc") or self._int("hot_potato_count")

    @property
    def art_of_war(self) -> bool:
        return self._int("art_of_war_count") > 0

    @property
    def ability_scrolls(self) -> frozenset[str]:
        return frozenset((self.flat.get("ability_scroll") or "").upper().split())

    @property
    def pet_level(self) -> int | None:
        return level_from_name(self.name)

    @property
    def pet_held_item(self) -> str | None:
        held = self.flat.get("heldItem")
        return held.upper() if held else None

    @property
    def pet_candy(self) -> int:
        return self._int("candyUsed")

    def gem_count(self, quality: str) -> int:
        """How many filled slots hold a gem of this quality."""
        wanted = quality.upper()
        return sum(
            1
            for key, value in self.flat.items()
            if not key.endswith("_gem")
            and "." not in key
            and key != "unlocked_slots"
            and value.upper() == wanted
        )

    def has_reforge(self, reforge: str) -> bool:
        """The reforge shows up only as a prefix on the item name."""
        return self.name.strip().lower().startswith(reforge.strip().lower())


#: How far either side of a pet's level still counts as comparable, as a
#: share of the level itself, with a floor so low-level pets are not pinned
#: to an implausibly narrow band.
PET_LEVEL_BAND = 0.08
PET_LEVEL_BAND_FLOOR = 5


def pet_level_tolerance(level: int) -> int:
    return max(PET_LEVEL_BAND_FLOOR, int(level * PET_LEVEL_BAND))


def modifier_matches(mod: Modifier, item: SoldItem) -> bool | None:
    """Whether a sold item carries this modifier.

    Returns ``None`` when the sale data cannot answer -- a skin or a dye, say,
    which the auction feed does not report. Those are treated as unmatchable
    and get priced separately rather than silently widening the comparables.
    """
    kind = mod.kind

    if kind == "enchantment":
        return item.enchants.get(mod.key, 0) >= mod.level
    if kind == "star":
        return item.stars == mod.level
    if kind == "recomb":
        return item.recombobulated
    if kind == "hot_potato":
        return item.hot_potato >= mod.level
    if kind == "art_of_war":
        return item.art_of_war
    if kind == "reforge":
        return item.has_reforge(mod.key)
    if kind == "gem":
        return item.gem_count(mod.key) >= mod.level
    if kind == "ability_scroll":
        return mod.key.upper() in item.ability_scrolls
    if kind == "pet_level":
        level = item.pet_level
        if level is None:
            return None
        # A band, not an exact level. Pets are sold at every level, so
        # demanding an exact match on a level 160 dragon leaves nothing to
        # compare against and the filter gets given up entirely -- which is
        # how a level 160 Golden Dragon ended up priced against level 1 eggs.
        return abs(level - mod.level) <= pet_level_tolerance(mod.level)
    if kind == "pet_held_item":
        return item.pet_held_item == mod.key.upper()
    if kind == "pet_candy":
        return item.pet_candy > 0
    # attributes, skins, dyes and runes are not reported on a sale.
    return None


def matchable(mod: Modifier, sample: list[SoldItem]) -> bool:
    """Whether this modifier can be tested against the sale feed at all."""
    if not sample:
        return False
    return any(modifier_matches(mod, item) is not None for item in sample[:20])


def matches_all(item: SoldItem, mods: list[Modifier], rarity: str | None) -> bool:
    """Whether one sale satisfies every modifier in a set."""
    if rarity and item.tier and item.tier.upper() != rarity.upper():
        return False
    # A modifier the sale cannot answer for does not disqualify it; those are
    # filtered out before they get here and priced separately instead.
    return all(modifier_matches(mod, item) is not False for mod in mods)


def select(
    items: list[SoldItem], mods: list[Modifier], rarity: str | None
) -> list[SoldItem]:
    """Every sale comparable to an item carrying ``mods``."""
    return [item for item in items if matches_all(item, mods, rarity)]

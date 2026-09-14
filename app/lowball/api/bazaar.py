"""Bazaar prices for the modifier table.

Most of what a modifier is worth is a bazaar product: an enchanted book, a
potato book, a master star, a gemstone.  Typing those prices by hand was the
worst part of keeping the pricing table honest, because they move weekly and a
stale table quietly misprices every add-back.

One keyless request to ``/v2/skyblock/bazaar`` returns the whole market, so
the whole table is refreshed in a single call.  Nothing here writes to the
value table: it returns what it found and what it could not find, and the
caller decides.

Prices are taken from ``buyPrice``, the insta-buy side of the book.  That is
what it would cost to put the modifier on an item, which is the figure a buyer
is implicitly paying for, and it is the number the rest of the app has always
meant by "what a modifier is worth".
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import httpx

from ..pricing.values import ValueTable

log = logging.getLogger(__name__)

BAZAAR_URL = "https://api.hypixel.net/v2/skyblock/bazaar"

#: Table field -> bazaar product id, for everything that is a single product.
SCALAR_PRODUCTS: dict[str, str] = {
    "recomb": "RECOMBOBULATOR_3000",
    "art_of_war": "THE_ART_OF_WAR",
    "hot_potato": "HOT_POTATO_BOOK",
    "fuming_potato": "FUMING_POTATO_BOOK",
}

#: Master stars, in the order the table stores them.
MASTER_STAR_PRODUCTS: tuple[str, ...] = (
    "FIRST_MASTER_STAR",
    "SECOND_MASTER_STAR",
    "THIRD_MASTER_STAR",
    "FOURTH_MASTER_STAR",
    "FIFTH_MASTER_STAR",
)

#: Gemstones are priced per quality, not per kind.  Several kinds trade at
#: very different prices, so the median across them is used rather than one
#: arbitrary stone.
GEM_KINDS: tuple[str, ...] = (
    "JASPER",
    "RUBY",
    "SAPPHIRE",
    "AMETHYST",
    "AMBER",
    "TOPAZ",
    "JADE",
    "OPAL",
    "AQUAMARINE",
    "CITRINE",
    "ONYX",
    "PERIDOT",
)

#: Only these qualities are traded as gemstone products.
GEM_QUALITIES: tuple[str, ...] = ("ROUGH", "FLAWED", "FINE", "FLAWLESS", "PERFECT")

#: Nothing on the bazaar corresponds to these, so a refresh leaves them alone
#: and says so rather than zeroing them.
NOT_ON_BAZAAR: tuple[str, ...] = (
    "skin",
    "dye",
    "reforge",
    "rune",
    "pet_held_item",
    "ability_scroll",
    "essence_star",
    "attribute_base",
)


@dataclass
class BazaarRefresh:
    """What a refresh changed, in terms the user can check."""

    updated: dict[str, int] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)
    products_seen: int = 0

    @property
    def count(self) -> int:
        return len(self.updated)

    def summary(self) -> str:
        parts = [f"Updated {self.count} price(s) from {self.products_seen} products"]
        if self.missing:
            parts.append(f"{len(self.missing)} not traded on the bazaar")
        return "; ".join(parts)


async def fetch_prices(
    *, client: httpx.AsyncClient | None = None, timeout: float = 15.0
) -> dict[str, int]:
    """Every bazaar product and its insta-buy price, as whole coins."""
    owns = client is None
    http = client or httpx.AsyncClient(
        timeout=timeout, headers={"User-Agent": "lowball/0.1 (personal trading assistant)"}
    )
    try:
        response = await http.get(BAZAAR_URL)
        response.raise_for_status()
        payload = response.json()
    finally:
        if owns:
            await http.aclose()

    products = payload.get("products") if isinstance(payload, dict) else None
    if not isinstance(products, dict):
        return {}

    prices: dict[str, int] = {}
    for product_id, entry in products.items():
        status = (entry or {}).get("quick_status") or {}
        price = status.get("buyPrice")
        if isinstance(price, (int, float)) and price > 0:
            prices[str(product_id)] = int(round(price))
    return prices


def _median(values: list[int]) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) // 2


#: No enchantment trades above this, and asking for more costs nothing.
MAX_BOOK_LEVEL = 10

#: Bounds on a measured level-to-level price ratio.  The range is wide on
#: purpose: a top level reached by combining sixteen books really does trade
#: at two thousand times the book below it, and clamping that to something
#: that "looks sensible" would put the lower level back where it was wrong.
#: The bounds only exist to reject a ratio drawn from a dead product.
MIN_DECAY = 1.5
MAX_DECAY = 10_000.0


def _book_price(
    prices: dict[str, int], name: str, level: int = MAX_BOOK_LEVEL
) -> tuple[int, int] | None:
    """The highest-level book the bazaar carries, and which level that is.

    The level matters as much as the price. Enchantments cap at different
    levels, and the bazaar is the authority on where: whatever it carries at
    the top is the reference level, rather than a number this file guesses.
    """
    key = name.upper()
    for candidate in range(level, 0, -1):
        price = prices.get(f"ENCHANTMENT_{key}_{candidate}")
        if price:
            return price, candidate
    return None


def refresh_values(table: ValueTable, prices: dict[str, int]) -> BazaarRefresh:
    """Write every bazaar-traded price into the table, in place.

    Returns what changed.  Anything the bazaar does not carry is left exactly
    as it was: a modifier with no product is not a modifier worth nothing.
    """
    result = BazaarRefresh(products_seen=len(prices))
    if not prices:
        return result

    for attr, product in SCALAR_PRODUCTS.items():
        price = prices.get(product)
        if price:
            setattr(table, attr, price)
            result.updated[attr] = price
        else:
            result.missing.append(attr)

    stars: list[int] = []
    for index, product in enumerate(MASTER_STAR_PRODUCTS):
        price = prices.get(product)
        stars.append(price if price else table.master_stars[index])
        if price:
            result.updated[f"master_star_{index + 1}"] = price
    table.master_stars = stars

    for quality in GEM_QUALITIES:
        found = [
            prices[f"{quality}_{kind}_GEM"]
            for kind in GEM_KINDS
            if f"{quality}_{kind}_GEM" in prices
        ]
        price = _median(found)
        if price:
            table.gems[quality] = price
            result.updated[f"gem_{quality.lower()}"] = price

    # An ultimate caps at level 5 by nature, so that is a real reference
    # rather than a guess.  Where only a lower level trades, the price is
    # scaled up the same curve ValueTable.enchant_value uses, so the two
    # agree about the same book.
    for name in list(table.ultimate_enchants):
        found = _book_price(prices, name, 5)
        if found is None:
            continue
        price, level = found
        # Rounded, not truncated: the reciprocal of a square lands a coin
        # short of the round number often enough to look like a bug.
        table.ultimate_enchants[name] = round(price / ((level / 5.0) ** 2))
        result.updated[f"enchant:{name}"] = table.ultimate_enchants[name]

    # Ordinary enchantments are taken at whatever level tops out on the
    # bazaar, and that level is recorded alongside the price. Scaling a
    # level V cap up to a notional VII would multiply its price by thirty-six.
    for name in list(table.top_tier_enchants):
        found = _book_price(prices, name)
        if found is None:
            continue
        price, level = found
        table.top_tier_enchants[name] = price
        table.top_tier_levels[name] = level
        result.updated[f"enchant:{name}"] = price

        # And how fast it falls off, measured rather than assumed. Sharpness
        # VII trades at three hundred times Sharpness VI, because two VIs make
        # one VII; a flat factor of six values every VI on every sword wrongly.
        below = _book_price(prices, name, level - 1) if level > 1 else None
        if below is not None and below[1] == level - 1 and below[0] > 0:
            ratio = price / below[0]
            if MIN_DECAY <= ratio <= MAX_DECAY:
                table.top_tier_decay[name] = round(ratio, 2)

    result.missing.extend(NOT_ON_BAZAAR)
    return result


async def refresh_from_bazaar(
    table: ValueTable, *, client: httpx.AsyncClient | None = None
) -> BazaarRefresh:
    """Fetch and apply in one step.  Runs on the asyncio side."""
    return refresh_values(table, await fetch_prices(client=client))

"""Auction house tax and listing fee arithmetic.

Two separate charges, both tiered by price (Part 6.1):

* a **listing fee** paid when an auction is created -- and paid *again* on
  every relist, which is what quietly eats the margin on a slow item;
* a **claim tax** taken from the proceeds when a sold BIN auction is claimed.

Only the claim tax is ever charged against a recorded sale, because that is
the one the user can state as a fact.  Listing fees are *modelled* rather than
recorded: they belong to the offer floor, which has to price the relists a
slow item is expected to need before the item is even bought.

Rates are held in basis points and applied with integer arithmetic, so the
numbers here are exact and reproducible rather than float-rounded.

Tier boundaries are inclusive at the top: 10,000,000 exactly sits in the
10M-100M band, and so does 100,000,000.  Only strictly above 100M reaches the
top tier.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

# (inclusive upper bound, or None for unbounded; rate in basis points)
Tier = tuple[int | None, int]

DEFAULT_CLAIM_TAX_TIERS: tuple[Tier, ...] = (
    (9_999_999, 100),      # under 10M  -> 1%
    (100_000_000, 200),    # 10M - 100M -> 2%
    (None, 250),           # over 100M  -> 2.5%
)

# The brief specifies one tier table; the listing fee mirrors it until we have
# measured otherwise.  Kept as a separate field so it can be tuned alone.
DEFAULT_LISTING_FEE_TIERS: tuple[Tier, ...] = DEFAULT_CLAIM_TAX_TIERS


@dataclass(frozen=True)
class TaxConfig:
    """Everything about the tax regime that the user can change."""

    claim_tax_tiers: tuple[Tier, ...] = DEFAULT_CLAIM_TAX_TIERS
    listing_fee_tiers: tuple[Tier, ...] = DEFAULT_LISTING_FEE_TIERS
    derpy: bool = False
    #: Derpy raises the rate; expressed as a multiplier on the basis points.
    derpy_multiplier: float = 2.0
    #: Auctions expire after this long, which sets how many relists a hold costs.
    auction_duration_hours: float = 48.0

    def with_derpy(self, on: bool) -> TaxConfig:
        return replace(self, derpy=on)


DEFAULT_TAX = TaxConfig()


def _rate_bp(price: int, tiers: tuple[Tier, ...]) -> int:
    for upper, bp in tiers:
        if upper is None or price <= upper:
            return bp
    return tiers[-1][1]


def _effective_bp(bp: int, cfg: TaxConfig) -> int:
    return int(round(bp * cfg.derpy_multiplier)) if cfg.derpy else bp


def claim_tax_rate(price: int, cfg: TaxConfig = DEFAULT_TAX) -> float:
    """Effective claim tax as a fraction, Derpy included."""
    return _effective_bp(_rate_bp(max(0, int(price)), cfg.claim_tax_tiers), cfg) / 10_000.0


def claim_tax(price: int, cfg: TaxConfig = DEFAULT_TAX) -> int:
    """Coins the auction house takes when a sale at ``price`` is claimed."""
    price = int(price)
    if price <= 0:
        return 0
    return price * _effective_bp(_rate_bp(price, cfg.claim_tax_tiers), cfg) // 10_000


def net_after_claim(price: int, cfg: TaxConfig = DEFAULT_TAX) -> int:
    """What actually lands in the purse from an auction house sale."""
    return int(price) - claim_tax(price, cfg)


def listing_fee(ask_price: int, cfg: TaxConfig = DEFAULT_TAX) -> int:
    """Coins burned to put an item up at ``ask_price``.  Paid again on relist."""
    ask_price = int(ask_price)
    if ask_price <= 0:
        return 0
    return ask_price * _effective_bp(_rate_bp(ask_price, cfg.listing_fee_tiers), cfg) // 10_000


def relist_count(hold_hours: float, cfg: TaxConfig = DEFAULT_TAX) -> int:
    """How many listings a hold of ``hold_hours`` is expected to consume.

    An item that sells inside one auction duration costs a single listing.
    Past that it is relisted, and every relist is another fee.
    """
    if hold_hours <= 0:
        return 1
    duration = max(1e-6, cfg.auction_duration_hours)
    return max(1, math.ceil(hold_hours / duration))


def expected_listing_cost(
    ask_price: int, hold_hours: float, cfg: TaxConfig = DEFAULT_TAX
) -> int:
    """Total listing fees expected across the whole hold, relists included."""
    return listing_fee(ask_price, cfg) * relist_count(hold_hours, cfg)

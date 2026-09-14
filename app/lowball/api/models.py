"""Typed views over Coflnet responses.

Field names follow the live API.  Every reader is defensive: a missing field
degrades the result rather than raising, because a partial valuation shown with
low confidence is more useful than an exception while a customer waits.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..timeutil import from_iso


def _num(data: dict[str, Any], *names: str, default: float = 0.0) -> float:
    for name in names:
        value = data.get(name)
        if isinstance(value, (int, float)):
            return float(value)
    return default


def _opt_num(data: dict[str, Any], *names: str) -> float | None:
    for name in names:
        value = data.get(name)
        if isinstance(value, (int, float)):
            return float(value)
    return None


@dataclass(frozen=True)
class PriceAnalysis:
    """``/api/item/price/{tag}/analysis``: how a tag behaves as a market."""

    tag: str
    days: int
    total_sales: int = 0
    median_price: int = 0
    avg_price: int = 0
    min_price: int = 0
    max_price: int = 0
    price_std_dev: float = 0.0
    #: Coefficient of variation, the volatility term in the offer floor.
    volatility: float = 0.0
    sales_per_day: float = 0.0
    bin_percentage: float = 0.0
    median_sell_seconds: float | None = None
    avg_sell_seconds: float | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def parse(cls, tag: str, days: int, data: dict[str, Any]) -> PriceAnalysis:
        return cls(
            tag=tag,
            days=days,
            total_sales=int(_num(data, "totalSales")),
            median_price=int(_num(data, "medianPrice")),
            avg_price=int(_num(data, "avgPrice")),
            min_price=int(_num(data, "minPrice")),
            max_price=int(_num(data, "maxPrice")),
            price_std_dev=_num(data, "priceStdDev"),
            volatility=_num(data, "priceCoeffVariation"),
            sales_per_day=_num(data, "salesPerDay"),
            bin_percentage=_num(data, "binPercentage"),
            median_sell_seconds=_opt_num(data, "medianSellTimeSeconds"),
            avg_sell_seconds=_opt_num(data, "avgSellTimeSeconds"),
            raw=data,
        )

    @property
    def is_liquid(self) -> bool:
        """Roughly a sale every couple of hours, which is fast enough to undercut."""
        return self.sales_per_day >= 12.0

    @property
    def is_thin(self) -> bool:
        return self.total_sales < 5


@dataclass(frozen=True)
class Auction:
    """One listing, active or sold.

    ``price`` is the number that matters and differs by state: a BIN listing
    is worth its ``startingBid``, a completed auction its ``highestBidAmount``.
    """

    uuid: str
    tag: str
    item_name: str = ""
    price: int = 0
    count: int = 1
    bin: bool = True
    tier: str | None = None
    reforge: str | None = None
    category: str | None = None
    seller: str | None = None
    uid: str | None = None
    start: str | None = None
    end: str | None = None
    enchantments: tuple[tuple[str, int], ...] = ()
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def parse(cls, data: dict[str, Any], *, sold: bool = False) -> Auction:
        flat = data.get("flatNbt") or {}
        if not isinstance(flat, dict):
            flat = {}
        nested = ((data.get("nbtData") or {}).get("data") or {}) if data.get("nbtData") else {}
        uid = flat.get("uid") or (nested.get("uid") if isinstance(nested, dict) else None)

        highest = _num(data, "highestBidAmount")
        starting = _num(data, "startingBid")
        # A sold auction is worth what it fetched; an unbid BIN reports zero as
        # its highest bid, so fall back to the ask.
        price = highest if (sold and highest > 0) else (starting or highest)

        enchants: list[tuple[str, int]] = []
        for entry in data.get("enchantments") or []:
            if isinstance(entry, dict):
                name = entry.get("type") or entry.get("name")
                level = entry.get("level")
                if name is not None and isinstance(level, (int, float)):
                    enchants.append((str(name).lower(), int(level)))

        reforge = data.get("reforge")
        if isinstance(reforge, str) and reforge.lower() in {"none", ""}:
            reforge = None

        return cls(
            uuid=str(data.get("uuid") or ""),
            tag=str(data.get("tag") or ""),
            item_name=str(data.get("itemName") or ""),
            price=int(price),
            count=int(_num(data, "count", default=1.0)) or 1,
            bin=bool(data.get("bin", True)),
            tier=data.get("tier"),
            reforge=str(reforge).lower() if reforge else None,
            category=data.get("category"),
            seller=data.get("auctioneerId"),
            uid=str(uid) if uid else None,
            start=data.get("start"),
            end=data.get("end"),
            enchantments=tuple(sorted(enchants)),
            raw=data,
        )

    @property
    def unit_price(self) -> int:
        """Stackables are listed as a stack; comparables need a per-item price."""
        return self.price // max(1, self.count)

    def sell_seconds(self) -> float | None:
        """How long this auction took to sell, when both ends are known."""
        if not self.start or not self.end:
            return None
        try:
            return (from_iso(self.end) - from_iso(self.start)).total_seconds()
        except (ValueError, TypeError):
            return None


@dataclass(frozen=True)
class Comparables:
    """The result of one comparable search: what the market says right now."""

    tag: str
    filters: dict[str, Any]
    sold: tuple[Auction, ...] = ()
    active: tuple[Auction, ...] = ()
    analysis: PriceAnalysis | None = None
    stale: bool = False

    @property
    def sales_count(self) -> int:
        return len(self.sold)

    @property
    def sold_prices(self) -> list[int]:
        return sorted(a.unit_price for a in self.sold if a.unit_price > 0)

    @property
    def active_prices(self) -> list[int]:
        return sorted(a.unit_price for a in self.active if a.unit_price > 0)

    @property
    def cheapest_active(self) -> tuple[Auction, ...]:
        """The three cheapest listings, surfaced so the user can eyeball them."""
        return tuple(sorted(self.active, key=lambda a: a.unit_price)[:3])

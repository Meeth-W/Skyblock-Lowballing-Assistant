"""The whole valuation, assembled.

Search for comparables, sanitise the cheapest listing, blend it with the
median, add back what was given up, score how much of that to believe, and
estimate how long it will take to sell.

The engine always returns a number.  When there is nothing to price against it
falls back to the unfiltered market median and says so through a confidence of
zero -- a number the user can see is untrustworthy is more useful than an error
message while somebody waits for a quote.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Any

from ..api.coflnet import CoflnetClient, attribution_url
from ..api.models import Auction, PriceAnalysis
from ..parsing.categories import category_of
from ..parsing.signature import ItemSignature
from .blending import Blend, LbinResult, blend, median_of, sanitise_lbin
from .confidence import Confidence, score
from .relaxation import AddBack, RelaxationSearch, SearchResult
from .sell_time import SellTimeEstimate, estimate_sell_time
from .values import DEFAULT_VALUES, ValueTable


@dataclass
class Valuation:
    sig: ItemSignature
    #: What the market says.  Read :attr:`estimate` instead unless you
    #: specifically want the computed figure rather than the one in use.
    market_estimate: int
    comparable_base: int
    addback: int
    confidence: Confidence
    blend: Blend
    lbin: LbinResult
    sell_time: SellTimeEstimate
    search: SearchResult
    #: Populated by the rules engine; every entry is badged in the UI.
    rules_fired: list[Any] = field(default_factory=list)
    fallback_used: bool = False
    notes: list[str] = field(default_factory=list)
    #: The user's own number, when they have overruled ours.  Kept beside the
    #: computed estimate rather than replacing it, so the override can be
    #: undone and the breakdown can still show what the market said.
    manual_estimate: int | None = None

    @property
    def estimate(self) -> int:
        return self.market_estimate if self.manual_estimate is None else self.manual_estimate

    def set_manual_estimate(self, coins: int | None) -> None:
        self.manual_estimate = None if coins is None else max(0, int(coins))

    @property
    def is_manual(self) -> bool:
        return self.manual_estimate is not None

    @property
    def tag(self) -> str:
        return self.sig.tag

    @property
    def category(self) -> str:
        return category_of(self.sig)

    @property
    def analysis(self) -> PriceAnalysis | None:
        return self.search.analysis

    @property
    def median(self) -> int | None:
        return self.blend.median

    @property
    def lbin_price(self) -> int | None:
        return self.lbin.price

    @property
    def recent_sales(self) -> tuple[Auction, ...]:
        return self.search.comparables.sold

    @property
    def cheapest_active(self) -> tuple[Auction, ...]:
        return self.search.comparables.cheapest_active

    @property
    def add_backs(self) -> list[AddBack]:
        return self.search.add_backs

    @property
    def volatility(self) -> float:
        return self.analysis.volatility if self.analysis else 0.0

    @property
    def attribution(self) -> str:
        return attribution_url(self.sig.tag)

    def as_event_payload(self) -> dict[str, Any]:
        """What gets written to VALUATION_RECORDED."""
        return {
            "tag": self.sig.tag,
            "signature": self.sig.as_dict(),
            "estimate": int(self.estimate),
            "market_estimate": int(self.market_estimate),
            "manual_estimate": self.manual_estimate,
            "confidence": float(self.confidence.score),
            "lbin": self.lbin.price,
            "median": self.blend.median,
            "sell_seconds": int(self.sell_time.seconds),
        }


class ValuationEngine:
    def __init__(
        self,
        client: CoflnetClient,
        *,
        conn: sqlite3.Connection | None = None,
        min_comparables: int = 5,
        values: ValueTable = DEFAULT_VALUES,
    ) -> None:
        self.client = client
        self.conn = conn
        self.search = RelaxationSearch(
            client, min_comparables=min_comparables, values=values
        )

    async def value(self, sig: ItemSignature) -> Valuation:
        result = await self.search.run(sig)
        comps = result.comparables
        notes: list[str] = []

        median = median_of(comps.sold_prices)
        lbin = sanitise_lbin(comps.active, median)
        if lbin.rejected:
            cheapest = lbin.rejected[0].unit_price
            notes.append(
                f"Ignored {lbin.rejected_count} listing"
                f"{'s' if lbin.rejected_count != 1 else ''} below the sales band,"
                f" cheapest at {cheapest:,}"
            )

        if lbin.price is None and comps.sales_count:
            # Worth saying out loud: with nothing comparable listed there is no
            # ceiling, so the estimate rests entirely on what has sold.
            notes.append("Nothing comparable listed right now; priced on sales alone")

        blended = blend(
            lbin=lbin.price,
            median=median,
            analysis=result.analysis,
            sold_prices=comps.sold_prices,
        )

        fallback = False
        base = blended.estimate
        if base <= 0:
            # Nothing matched even at the broadest filter set.  Fall back to
            # the unfiltered market median so there is still a number, and let
            # the confidence score carry the warning.
            base = result.analysis.median_price if result.analysis else 0
            fallback = base > 0
            if fallback:
                notes.append("No matching sales; using the unfiltered market median")
            else:
                notes.append("No market data for this item")

        addback = result.addback_total
        estimate = max(0, base + addback)

        confidence = score(
            sample=comps.sales_count,
            spread=blended.spread,
            kept=len(result.kept),
            dropped=len(result.dropped),
            addback_total=max(0, addback),
            estimate=estimate,
        )
        if fallback:
            confidence = Confidence(
                score=0.0,
                dots=0,
                sample=0,
                spread=confidence.spread,
                dropped=confidence.dropped,
                kept=confidence.kept,
                addback_share=confidence.addback_share,
                reasons=("No matching sales found", *confidence.reasons[1:]),
            )

        return Valuation(
            sig=sig,
            market_estimate=estimate,
            comparable_base=base,
            addback=addback,
            confidence=confidence,
            blend=blended,
            lbin=lbin,
            sell_time=estimate_sell_time(self.conn, sig, result.analysis),
            search=result,
            fallback_used=fallback,
            notes=notes,
        )

    async def value_many(self, sigs: list[ItemSignature]) -> list[Valuation]:
        """Value a whole trade, asking about each distinct item only once.

        Two identical Hyperions in one trade are one question.  The cache would
        catch the repeat anyway, but de-duplicating here also avoids queueing
        the second one behind the rate limiter.
        """
        by_key: dict[str, ItemSignature] = {}
        order: list[str] = []
        for sig in sigs:
            key = sig.cache_key()
            order.append(key)
            by_key.setdefault(key, sig)

        valued: dict[str, Valuation] = {}
        for key, sig in by_key.items():
            valued[key] = await self.value(sig)
        return [valued[key] for key in order]

"""Progressive relaxation search.

Matching on a full modifier signature finds nothing; matching on none gives a
base price that means nothing. The search walks between the two: keep as many
of the valuable modifiers as the evidence supports, give up the rest, and price
those back from their own markets.

**The search runs locally.** Coflnet's ``/sold`` endpoint accepts filter
parameters and ignores them -- the same sales and the same median come back
whatever you ask for. An earlier version trusted those parameters, so every
probe returned an identical result, the search kept every filter, and the
unfiltered median of the entire tag was reported as a matched comparable. On a
ten-star Chimera Hyperion that read 1.06B against a true 2.27B.

So one request fetches every recent sale for the tag and the matching happens
in :mod:`matching`. Trying a filter set costs nothing, which makes a greedy
walk down the value order better than the bisection this used to need: take
each modifier in turn, most valuable first, and keep it if enough comparables
survive. A modifier nothing matches is simply skipped rather than poisoning
everything below it.

Active listings are different: the auction house endpoint really does filter,
and it returns the cheapest matches, which is exactly what a lowest BIN needs.
Those are still asked for server-side, relaxed separately because the book is
far thinner than the sales history.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from ..api.coflnet import CoflnetClient, CoflnetError
from ..api.models import Auction, Comparables, PriceAnalysis
from ..parsing.signature import ItemSignature
from .matching import SoldItem, matchable, select
from .modifiers import Modifier, rank_by_value_contribution, to_filters
from .values import DEFAULT_VALUES, ValueTable

log = logging.getLogger(__name__)

#: Below this many matching sales, a modifier set is considered too specific.
DEFAULT_MIN_COMPARABLES = 5

#: A dropped modifier worth less than this share of the base price is not
#: worth an API request; it is added back from the heuristic table instead.
MIN_ADDBACK_FRACTION = 0.005

#: How many times the active-listing query may be relaxed looking for a
#: lowest BIN. Each step is a request, and the book is thin, so this is small.
MAX_ACTIVE_RELAXATIONS = 4


@dataclass
class AddBack:
    """One dropped modifier, priced on its own."""

    modifier: Modifier
    market_price: int | None
    applied: int
    source: str  # MARKET | HEURISTIC | NONE

    @property
    def label(self) -> str:
        return str(self.modifier)


@dataclass
class SearchResult:
    sig: ItemSignature
    comparables: Comparables
    kept: list[Modifier] = field(default_factory=list)
    dropped: list[Modifier] = field(default_factory=list)
    add_backs: list[AddBack] = field(default_factory=list)
    analysis: PriceAnalysis | None = None
    requests: int = 0
    steps: int = 0
    #: How many sales were considered before matching narrowed them.
    sample_size: int = 0

    @property
    def filters(self) -> dict[str, Any]:
        return dict(self.comparables.filters)

    @property
    def sales_count(self) -> int:
        return self.comparables.sales_count

    @property
    def addback_total(self) -> int:
        return sum(a.applied for a in self.add_backs)

    @property
    def dropped_labels(self) -> list[str]:
        return [str(m) for m in self.dropped]


class RelaxationSearch:
    def __init__(
        self,
        client: CoflnetClient,
        *,
        min_comparables: int = DEFAULT_MIN_COMPARABLES,
        min_addback_fraction: float = MIN_ADDBACK_FRACTION,
        price_addbacks: bool = True,
        values: ValueTable = DEFAULT_VALUES,
    ) -> None:
        self.client = client
        self.values = values
        self.min_comparables = min_comparables
        self.min_addback_fraction = min_addback_fraction
        self.price_addbacks = price_addbacks

    async def run(self, sig: ItemSignature) -> SearchResult:
        ranked = rank_by_value_contribution(sig, self.values)
        analysis_task = asyncio.ensure_future(self._analysis(sig.tag))

        sales = await self._sold(sig.tag)
        items = [SoldItem.from_auction(a) for a in sales]

        kept, dropped, matched = self._narrow(sig, ranked, items)

        active, filters = await self._find_active(sig, kept)
        analysis = await analysis_task

        result = SearchResult(
            sig=sig,
            comparables=Comparables(
                tag=sig.tag,
                filters=filters,
                sold=tuple(item.auction for item in matched),
                active=tuple(active),
                analysis=analysis,
            ),
            kept=kept,
            dropped=dropped,
            analysis=analysis,
            sample_size=len(items),
            steps=len(ranked),
        )
        result.requests = 2 + self._active_requests

        if self.price_addbacks:
            base = _median([i.unit_price for i in matched]) or (
                analysis.median_price if analysis else 0
            )
            result.add_backs = await self._price_dropped(dropped, base)
            result.requests += sum(1 for a in result.add_backs if a.source == "MARKET")
        return result

    def _narrow(
        self, sig: ItemSignature, ranked: list[Modifier], items: list[SoldItem]
    ) -> tuple[list[Modifier], list[Modifier], list[SoldItem]]:
        """Keep every modifier the evidence still supports, most valuable first.

        Greedy rather than bisecting, because testing a set costs nothing now
        that the sales are in memory. Working down the value order means the
        expensive modifiers are the ones that survive, and a modifier nothing
        matches is skipped on its own rather than taking every cheaper one with
        it.
        """
        rarity = sig.rarity
        kept: list[Modifier] = []
        dropped: list[Modifier] = []
        matched = select(items, [], rarity)

        if len(matched) < self.min_comparables:
            # Even the rarity alone is too specific to say anything.
            return [], list(ranked), matched

        for mod in ranked:
            if not mod.use_for_matching or not matchable(mod, items):
                # Either too cheap to be worth narrowing on, or something a
                # sale does not report at all -- a skin, a dye. Both are given
                # up and priced separately instead.
                dropped.append(mod)
                continue
            candidate = select(items, [*kept, mod], rarity)
            if len(candidate) >= self.min_comparables:
                kept.append(mod)
                matched = candidate
            else:
                dropped.append(mod)
        return kept, dropped, matched

    # ---- one place each for every outbound call ------------------------

    async def _sold(self, tag: str) -> list[Auction]:
        """Every recent sale for the tag.

        Deliberately unfiltered: the endpoint ignores filter parameters, and
        asking for the whole list once lets the search try any number of
        modifier sets against it for free.
        """
        try:
            return await self.client.sold(tag, None)
        except CoflnetError as exc:
            log.warning("sold lookup failed for %s: %s", tag, exc)
            return []

    async def _find_active(
        self, sig: ItemSignature, kept: list[Modifier]
    ) -> tuple[list[Auction], dict[str, Any]]:
        """The cheapest comparable listings, relaxed until something is listed.

        The active book is far thinner than the sales history -- a ten-star
        Chimera Hyperion may have six recent sales and nothing listed at all --
        so the filter set that matched the sales often matches no listing. Each
        step gives up the least valuable constraint and asks again.
        """
        self._active_requests = 0
        # Halve rather than drop one at a time: a loaded item keeps a dozen
        # modifiers, and giving them up singly would exhaust the request budget
        # long before reaching a set thin enough for anything to be listed.
        # The order is by value, so halving always keeps the expensive end.
        widths = []
        width = len(kept)
        while width > 0:
            widths.append(width)
            width //= 2
        widths.append(0)
        widths = widths[: MAX_ACTIVE_RELAXATIONS + 1]

        filters: dict[str, Any] = {}
        for width in widths:
            filters, _ = to_filters(kept[:width], sig)
            listings = await self._active(sig.tag, filters)
            self._active_requests += 1
            if listings:
                return listings, filters
        return [], filters

    async def _active(self, tag: str, filters: dict[str, Any]) -> list[Auction]:
        try:
            return await self.client.active_bin(tag, filters or None)
        except CoflnetError as exc:
            log.warning("active lookup failed for %s: %s", tag, exc)
            return []

    async def _analysis(self, tag: str) -> PriceAnalysis | None:
        try:
            return await self.client.analysis(tag)
        except CoflnetError as exc:
            log.warning("analysis failed for %s: %s", tag, exc)
            return None

    async def _price_dropped(self, dropped: list[Modifier], base: int) -> list[AddBack]:
        """Price each given-up modifier from its own market.

        Anything worth less than a fraction of the base price is added back
        from the heuristic table rather than spending a request on it: at that
        size the error is smaller than the spread on the item itself.

        Every price is then shaved twice: by the modifier's own recovery rate,
        and by the user's global discount from the pricing table. Both say the
        same thing -- a modifier already applied to an item is worth less than
        the modifier sitting on the market -- at different granularities.
        """
        threshold = max(0, int(base * self.min_addback_fraction))
        discount = self.values.modifier_multiplier
        out: list[AddBack] = []
        for mod in dropped:
            if mod.kind == "pet_candy":
                # Candy takes value away rather than adding it.
                out.append(
                    AddBack(mod, None, -int(base * 0.05 * min(1, mod.level)), "HEURISTIC")
                )
                continue
            heuristic = int(mod.rank * mod.recovery * discount)
            if not mod.priceable or mod.rank < threshold:
                out.append(AddBack(mod, None, heuristic, "HEURISTIC"))
                continue
            price = await self._lowest_bin(mod)
            if price is None:
                out.append(AddBack(mod, None, heuristic, "HEURISTIC"))
            else:
                out.append(
                    AddBack(mod, price, int(price * mod.recovery * discount), "MARKET")
                )
        return out

    async def _lowest_bin(self, mod: Modifier) -> int | None:
        if not mod.price_tag:
            return None
        try:
            return await self.client.lowest_bin(mod.price_tag, mod.price_filters or None)
        except CoflnetError as exc:
            log.info("could not price %s independently: %s", mod, exc)
            return None

    _active_requests: int = 0


def _median(values: list[int]) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) // 2


async def search(
    client: CoflnetClient,
    sig: ItemSignature,
    *,
    min_comparables: int = DEFAULT_MIN_COMPARABLES,
) -> SearchResult:
    return await RelaxationSearch(client, min_comparables=min_comparables).run(sig)

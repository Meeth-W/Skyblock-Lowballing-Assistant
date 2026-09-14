"""Relaxation search and valuation, against a market that behaves like the real one.

The fake market below reproduces the behaviour that matters: ``/sold`` returns
every recent sale for a tag and **ignores filter parameters entirely**, exactly
as Coflnet does, while ``active/bin`` really does filter. An earlier version of
this file faked server-side filtering on both, which is why the app shipped
reporting the unfiltered median of a whole tag as a matched comparable.

Sales carry the fields the matcher reads: ``flattenedNbt``, ``tier`` and the
enchantment list.
"""

from __future__ import annotations

from dataclasses import replace

import httpx
import pytest
from conftest import FakeClock

from lowball.api.cache import ApiCache
from lowball.api.coflnet import CoflnetClient
from lowball.api.ratelimit import DualWindowLimiter
from lowball.ledger import Ledger
from lowball.parsing.signature import Gem, ItemSignature
from lowball.pricing.relaxation import RelaxationSearch
from lowball.pricing.valuation import ValuationEngine

IGNORED_PARAMS = {"page", "days"}


def sale(price: int, *, name="Heroic Hyperion", tier="MYTHIC", enchants=None, **flat) -> dict:
    """One sold auction in the shape Coflnet returns."""
    return {
        "uuid": f"sold{price}",
        "tag": "HYPERION",
        "itemName": name,
        "startingBid": price,
        "highestBidAmount": price,
        "count": 1,
        "bin": True,
        "tier": tier,
        "start": "2026-09-10T00:00:00",
        "end": "2026-09-10T02:00:00",
        "enchantments": [{"type": k, "level": v} for k, v in (enchants or {}).items()],
        "flattenedNbt": {k: str(v) for k, v in flat.items()},
    }


def listing(price: int, **props) -> dict:
    return {
        "uuid": f"live{price}",
        "tag": "HYPERION",
        "itemName": props.pop("name", "Heroic Hyperion"),
        "startingBid": price,
        "highestBidAmount": 0,
        "count": props.pop("count", 1),
        "bin": True,
        "start": "2026-09-14T06:00:41",
        "end": "2026-09-28T06:00:41",
        "props": props,
    }


class FakeMarket:
    """Sold ignores filters, active honours them -- like the real API."""

    def __init__(self) -> None:
        self.sold: list[dict] = []
        self.active: list[dict] = []
        self.analysis: dict | None = None
        self.sold_requests = 0
        self.active_requests = 0
        self.calls: list[str] = []

    @staticmethod
    def _tag_of(path: str) -> str:
        parts = [p for p in path.split("/") if p]
        for marker in ("tag", "price"):
            if marker in parts:
                return parts[parts.index(marker) + 1]
        return ""

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        params = dict(request.url.params)
        self.calls.append(f"{path}?{request.url.query.decode()}")
        tag = self._tag_of(path)

        if path.endswith("/analysis"):
            return httpx.Response(200, json=self.analysis or {})

        if "/sold" in path:
            self.sold_requests += 1
            # Filters are accepted and ignored, exactly as the real endpoint does.
            hits = [s for s in self.sold if s["tag"] == tag]
            return httpx.Response(200, json=hits)

        if "/active/bin" in path:
            self.active_requests += 1
            hits = [
                dict(entry)
                for entry in self.active
                if entry["tag"] == tag and self._matches(entry, params)
            ]
            for entry in hits:
                entry.pop("props", None)
            return httpx.Response(200, json=hits)

        return httpx.Response(404, json={})

    @staticmethod
    def _matches(entry: dict, params: dict) -> bool:
        props = entry.get("props", {})
        for key, value in params.items():
            if key in IGNORED_PARAMS:
                continue
            actual = props.get(key)
            if actual is None or str(actual).lower() != str(value).lower():
                return False
        return True


def make_client(market: FakeMarket) -> CoflnetClient:
    clock = FakeClock()
    return CoflnetClient(
        ApiCache(Ledger().conn),
        limiter=DualWindowLimiter(min_interval=0.0, clock=clock, sleep=clock.sleep),
        client=httpx.AsyncClient(
            transport=httpx.MockTransport(market.handler),
            base_url="https://sky.coflnet.com",
        ),
        sleep=clock.sleep,
    )


LOADED_HYPERION = ItemSignature(
    tag="HYPERION",
    rarity="MYTHIC",
    recombobulated=True,
    reforge="heroic",
    stars=10,
    hot_potato=15,
    art_of_war=True,
    enchantments=(("ultimate_chimera", 5), ("sharpness", 7), ("critical", 7)),
    gems=(Gem("COMBAT_0", "PERFECT", "SAPPHIRE"), Gem("SAPPHIRE_0", "PERFECT", None)),
)


@pytest.fixture
def market() -> FakeMarket:
    m = FakeMarket()
    m.analysis = {
        "totalSales": 538,
        "medianPrice": 1_060_000_000,
        "priceCoeffVariation": 0.2,
        "salesPerDay": 76.0,
        "medianSellTimeSeconds": 7335.0,
        "binPercentage": 98.0,
    }
    return m


def stock_market(market: FakeMarket) -> None:
    """A tag whose sales run from plain to fully loaded, as a real one does."""
    # Twenty ordinary five-star Hyperions around a billion.
    for index in range(20):
        market.sold.append(
            sale(
                1_000_000_000 + index * 10_000_000,
                enchants={"ultimate_wise": 5},
                upgrade_level=5,
                rarity_upgrades=1,
                hpc=15,
            )
        )
    # Six ten-star Chimera ones, worth more than twice as much.
    for index in range(6):
        market.sold.append(
            sale(
                2_200_000_000 + index * 25_000_000,
                enchants={"ultimate_chimera": 5, "sharpness": 7, "critical": 7},
                upgrade_level=10,
                rarity_upgrades=1,
                hpc=15,
                art_of_war_count=1,
                COMBAT_0="PERFECT",
                SAPPHIRE_0="PERFECT",
            )
        )


async def test_the_search_narrows_to_genuinely_comparable_sales(market: FakeMarket) -> None:
    """The bug this whole layer exists to prevent.

    The endpoint hands back every sale for the tag whatever is asked of it. If
    the search trusts the server, the median of twenty ordinary Hyperions is
    reported as the price of a ten-star Chimera one.
    """
    stock_market(market)
    search = RelaxationSearch(make_client(market), min_comparables=5, price_addbacks=False)
    result = await search.run(LOADED_HYPERION)

    assert result.sample_size == 26          # everything the endpoint returned
    assert result.sales_count == 6           # what actually compares
    prices = result.comparables.sold_prices
    assert min(prices) >= 2_200_000_000


async def test_the_expensive_modifiers_are_the_ones_kept(market: FakeMarket) -> None:
    stock_market(market)
    search = RelaxationSearch(make_client(market), min_comparables=5, price_addbacks=False)
    result = await search.run(LOADED_HYPERION)

    kept = {str(m) for m in result.kept}
    assert "10 stars" in kept
    assert "Chimera 5" in kept


async def test_narrowing_costs_no_extra_requests(market: FakeMarket) -> None:
    """Trying a filter set is free once the sales are in memory."""
    stock_market(market)
    search = RelaxationSearch(make_client(market), min_comparables=5, price_addbacks=False)
    await search.run(LOADED_HYPERION)
    assert market.sold_requests == 1


async def test_a_modifier_the_feed_cannot_report_is_dropped(market: FakeMarket) -> None:
    """A skin does not appear on a sale, so it cannot be matched on.

    Keeping it would mean believing the comparables share something they were
    never checked for. It is given up and priced separately instead.
    """
    stock_market(market)
    skinned = replace(LOADED_HYPERION, skin="HYPERION_SKIN")
    search = RelaxationSearch(make_client(market), min_comparables=5, price_addbacks=False)
    result = await search.run(skinned)

    assert all(m.kind != "skin" for m in result.kept)
    assert any(m.kind == "skin" for m in result.dropped)


async def test_too_few_sales_to_compare_gives_up_everything(market: FakeMarket) -> None:
    market.sold.append(sale(1_000_000_000, upgrade_level=5))
    search = RelaxationSearch(make_client(market), min_comparables=5, price_addbacks=False)
    result = await search.run(LOADED_HYPERION)
    assert result.kept == []
    assert result.dropped


# ---- lowest BIN and the finished valuation ---------------------------------


def stock_listings(market: FakeMarket) -> None:
    """A thin book: plenty of plain Hyperions, one loaded one."""
    for index in range(4):
        market.active.append(
            listing(900_000_000 + index * 20_000_000, Rarity="MYTHIC", Stars=5)
        )
    market.active.append(
        listing(
            2_350_000_000,
            Rarity="MYTHIC",
            Stars=10,
            Enchantment="ultimate_chimera",
            EnchantLvl=5,
            Recombobulated="true",
            HotPotatoCount=15,
            ArtOfTheWar="true",
            PerfectGemsCount=2,
            SecondEnchantment="sharpness",
            SecondEnchantLvl=7,
        )
    )


async def test_the_lowest_bin_comes_from_a_comparable_listing(market: FakeMarket) -> None:
    stock_market(market)
    stock_listings(market)
    engine = ValuationEngine(make_client(market))
    valuation = await engine.value(LOADED_HYPERION)

    # Not the 900M plain Hyperion sitting at the top of the book.
    assert valuation.lbin_price == 2_350_000_000
    assert valuation.estimate > 2_000_000_000


async def test_the_active_query_relaxes_when_nothing_matches(market: FakeMarket) -> None:
    """A thin book is normal; a missing ceiling should not be."""
    stock_market(market)
    # Nothing matching the full set, but ten-star ones are listed.
    market.active.append(listing(2_100_000_000, Rarity="MYTHIC", Stars=10))
    engine = ValuationEngine(make_client(market))
    valuation = await engine.value(LOADED_HYPERION)

    assert valuation.lbin_price == 2_100_000_000
    assert market.active_requests > 1


async def test_with_nothing_listed_the_estimate_rests_on_sales(market: FakeMarket) -> None:
    stock_market(market)
    engine = ValuationEngine(make_client(market))
    valuation = await engine.value(LOADED_HYPERION)

    assert valuation.lbin_price is None
    assert valuation.estimate > 0
    assert any("Nothing comparable listed" in note for note in valuation.notes)


async def test_a_scam_listing_is_not_used_as_the_lowest_bin(market: FakeMarket) -> None:
    stock_market(market)
    stock_listings(market)
    market.active.append(
        listing(
            3_000_000,
            Rarity="MYTHIC",
            Stars=10,
            Enchantment="ultimate_chimera",
            EnchantLvl=5,
            Recombobulated="true",
            HotPotatoCount=15,
            ArtOfTheWar="true",
            PerfectGemsCount=2,
            SecondEnchantment="sharpness",
            SecondEnchantLvl=7,
        )
    )
    engine = ValuationEngine(make_client(market))
    valuation = await engine.value(LOADED_HYPERION)

    assert valuation.lbin_price == 2_350_000_000
    assert valuation.lbin.rejected_count == 1
    assert any("Ignored 1 listing" in note for note in valuation.notes)


async def test_a_valuation_blends_and_scores_itself(market: FakeMarket) -> None:
    stock_market(market)
    stock_listings(market)
    engine = ValuationEngine(make_client(market))
    valuation = await engine.value(LOADED_HYPERION)

    assert valuation.median == 2_262_500_000
    assert valuation.confidence.dots >= 2
    assert valuation.sell_time.source == "PUBLIC"
    assert valuation.attribution == "https://sky.coflnet.com/item/HYPERION"


async def test_an_item_with_no_market_at_all_still_returns(market: FakeMarket) -> None:
    market.analysis = {}
    engine = ValuationEngine(make_client(market))
    valuation = await engine.value(ItemSignature(tag="UNKNOWN_THING"))
    assert valuation.estimate == 0
    assert valuation.confidence.dots == 0
    assert "No market data for this item" in valuation.notes


async def test_identical_items_in_one_selection_are_valued_once(market: FakeMarket) -> None:
    stock_market(market)
    engine = ValuationEngine(make_client(market))
    values = await engine.value_many([LOADED_HYPERION, LOADED_HYPERION, LOADED_HYPERION])
    assert len(values) == 3
    assert values[0].estimate == values[2].estimate
    assert market.sold_requests == 1


# ---- the user's own number -------------------------------------------------
#
# The lowballer is looking at the item and knows things the comparables do not.
# Their figure has to drive every offer percentage, and it has to stay
# distinguishable from a measured one so the next glance does not read it as
# market evidence.


async def test_a_manual_estimate_replaces_the_market_one(market: FakeMarket) -> None:
    stock_market(market)
    stock_listings(market)
    engine = ValuationEngine(make_client(market))
    valuation = await engine.value(LOADED_HYPERION)
    measured = valuation.estimate

    valuation.set_manual_estimate(1_500_000_000)
    assert valuation.estimate == 1_500_000_000
    assert valuation.is_manual
    # The computed figure survives, so the breakdown can still show it.
    assert valuation.market_estimate == measured

    valuation.set_manual_estimate(None)
    assert valuation.estimate == measured
    assert not valuation.is_manual


async def test_an_override_is_written_to_the_ledger_as_such(market: FakeMarket) -> None:
    stock_market(market)
    engine = ValuationEngine(make_client(market))
    valuation = await engine.value(LOADED_HYPERION)
    valuation.set_manual_estimate(1_234_000_000)

    payload = valuation.as_event_payload()
    assert payload["estimate"] == 1_234_000_000
    assert payload["manual_estimate"] == 1_234_000_000
    assert payload["market_estimate"] == valuation.market_estimate


async def test_the_ladder_follows_a_manual_estimate(market: FakeMarket) -> None:
    """Every rung is a percentage of the estimate, so all of them move."""
    from lowball.pricing.offer import build_ladder

    stock_market(market)
    engine = ValuationEngine(make_client(market))
    valuation = await engine.value(LOADED_HYPERION)
    valuation.set_manual_estimate(1_000_000_000)

    ladder = build_ladder(valuation.estimate, hold_hours=12.0)
    assert ladder.estimate == 1_000_000_000
    assert ladder.rung_at(0.10).coins == 900_000_000


async def test_the_modifier_discount_shaves_the_add_backs(market: FakeMarket) -> None:
    """The pricing slider has to reach the estimate, not just the table.

    A skin is the clearest case: a sale never reports one, so it is always
    given up and always priced back separately.
    """
    from lowball.pricing.values import ValueTable

    stock_market(market)
    skinned = replace(LOADED_HYPERION, skin="HYPERION_SKIN")

    async def addback_with(discount: int) -> int:
        search = RelaxationSearch(
            make_client(market),
            min_comparables=5,
            values=ValueTable(modifier_discount_pct=discount),
        )
        return (await search.run(skinned)).addback_total

    full = await addback_with(0)
    halved = await addback_with(50)

    assert full > 0
    assert halved == pytest.approx(full / 2, rel=0.02)

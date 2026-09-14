"""API client behaviour, against recorded responses only.

Nothing here touches the network.  A mock transport counts requests, so the
tests can assert the thing that actually matters: that the cache and the
limiter between them stop the app asking the same question twice.
"""

from __future__ import annotations

import httpx
import pytest
from conftest import FakeClock

from lowball.api.cache import ApiCache
from lowball.api.coflnet import CoflnetClient, CoflnetError
from lowball.api.ratelimit import DualWindowLimiter
from lowball.ledger import Ledger

ANALYSIS_HYPERION = {
    "totalSales": 538,
    "avgSellTimeSeconds": 54927.76,
    "medianSellTimeSeconds": 7335.0,
    "avgPrice": 906965865.66,
    "medianPrice": 1056942042.0,
    "minPrice": 480000000,
    "maxPrice": 1400000000,
    "priceStdDev": 339000000.0,
    "priceCoeffVariation": 0.374,
    "salesPerDay": 76.86,
    "binPercentage": 98.70,
}

BIN_LISTING = {
    "uuid": "226a4371e7ff463b89b3b52dc5f7abdf",
    "count": 1,
    "startingBid": 493000000,
    "tag": "HYPERION",
    "itemName": "Hyperion",
    "start": "2026-09-14T06:00:41",
    "end": "2026-09-28T06:00:41",
    "auctioneerId": "58f8810695994eb08ddeeac2f469bd79",
    "highestBidAmount": 0,
    "bin": True,
    "tier": "LEGENDARY",
    "reforge": "None",
    "category": "WEAPON",
    "enchantments": [{"type": "ultimate_wise", "level": 5}],
    "flatNbt": {"uid": "3485ba796594"},
}


class Recorder:
    """A mock transport that replays canned responses and counts the calls."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.routes: dict[str, httpx.Response] = {}
        self.queue: dict[str, list[httpx.Response]] = {}

    def route(self, path: str, response: httpx.Response) -> None:
        self.routes[path] = response

    def enqueue(self, path: str, *responses: httpx.Response) -> None:
        """Responses served in order, for testing retry behaviour."""
        self.queue.setdefault(path, []).extend(responses)

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.calls.append(str(request.url))
        pending = self.queue.get(path)
        if pending:
            return pending.pop(0)
        if path in self.routes:
            return self.routes[path]
        return httpx.Response(404, json={"error": "not found"})

    def count(self, fragment: str) -> int:
        return sum(1 for call in self.calls if fragment in call)


@pytest.fixture
def rig():
    store = Ledger()
    recorder = Recorder()
    transport = httpx.MockTransport(recorder.handler)
    http = httpx.AsyncClient(transport=transport, base_url="https://sky.coflnet.com")
    clock = FakeClock()
    limiter = DualWindowLimiter(min_interval=0.0, clock=clock, sleep=clock.sleep)
    client = CoflnetClient(
        ApiCache(store.conn), limiter=limiter, client=http, sleep=clock.sleep
    )
    yield client, recorder
    store.close()



async def test_analysis_parses_the_live_field_names(rig) -> None:
    client, recorder = rig
    recorder.route("/api/item/price/HYPERION/analysis", httpx.Response(200, json=ANALYSIS_HYPERION))
    result = await client.analysis("HYPERION")
    assert result.median_price == 1_056_942_042
    assert result.volatility == pytest.approx(0.374)
    assert result.median_sell_seconds == pytest.approx(7335.0)
    assert result.sales_per_day == pytest.approx(76.86)
    assert result.is_liquid


async def test_a_repeated_question_costs_one_request(rig) -> None:
    client, recorder = rig
    recorder.route("/api/item/price/HYPERION/analysis", httpx.Response(200, json=ANALYSIS_HYPERION))
    for _ in range(5):
        await client.analysis("HYPERION")
    # This is the whole point of the cache: a 36-slot inventory full of the
    # same item must not spend five times the rate limit.
    assert recorder.count("analysis") == 1
    assert client.stats.cache_hits == 4


async def test_different_filters_are_different_cache_entries(rig) -> None:
    client, recorder = rig
    recorder.route("/api/auctions/tag/HYPERION/sold", httpx.Response(200, json=[BIN_LISTING]))
    await client.sold("HYPERION", {"Enchantment": "ultimate_wise", "EnchantLvl": 5})
    await client.sold("HYPERION", {"Enchantment": "ultimate_wise"})
    assert recorder.count("sold") == 2


async def test_filter_order_does_not_split_the_cache(rig) -> None:
    client, recorder = rig
    recorder.route("/api/auctions/tag/HYPERION/sold", httpx.Response(200, json=[BIN_LISTING]))
    await client.sold("HYPERION", {"Stars": 5, "Rarity": "MYTHIC"})
    await client.sold("HYPERION", {"Rarity": "MYTHIC", "Stars": 5})
    assert recorder.count("sold") == 1


async def test_active_bin_reads_price_uid_and_enchantments(rig) -> None:
    client, recorder = rig
    recorder.route(
        "/api/auctions/tag/HYPERION/active/bin", httpx.Response(200, json=[BIN_LISTING])
    )
    listings = await client.active_bin("HYPERION")
    assert len(listings) == 1
    listing = listings[0]
    assert listing.price == 493_000_000
    assert listing.uid == "3485ba796594"
    assert listing.enchantments == (("ultimate_wise", 5),)
    assert listing.reforge is None  # "None" from the API is not a reforge


async def test_stacked_listings_report_a_unit_price(rig) -> None:
    client, recorder = rig
    stacked = {**BIN_LISTING, "count": 16, "startingBid": 32_000_000}
    recorder.route(
        "/api/auctions/tag/ENCHANTED_BOOK/active/bin", httpx.Response(200, json=[stacked])
    )
    listings = await client.active_bin("ENCHANTED_BOOK")
    assert listings[0].unit_price == 2_000_000


async def test_a_429_is_honoured_then_retried(rig) -> None:
    client, recorder = rig
    recorder.enqueue(
        "/api/item/price/HYPERION/analysis",
        httpx.Response(429, headers={"Retry-After": "14"}),
        httpx.Response(200, json=ANALYSIS_HYPERION),
    )
    result = await client.analysis("HYPERION")
    assert result is not None
    assert client.stats.rate_limited == 1
    assert recorder.count("analysis") == 2


async def test_an_unknown_tag_answers_none_without_raising(rig) -> None:
    client, recorder = rig
    result = await client.analysis("NOT_A_REAL_ITEM")
    assert result is None


async def test_a_404_is_cached_so_a_typo_is_not_retried_forever(rig) -> None:
    client, recorder = rig
    for _ in range(4):
        await client.analysis("NOT_A_REAL_ITEM")
    # Three windows are tried on a miss (7, 3, 1 days); after that the negative
    # result is cached and nothing further goes out.
    assert recorder.count("NOT_A_REAL_ITEM") == 3


async def test_a_stale_price_beats_no_price_when_the_network_fails(rig) -> None:
    client, recorder = rig
    recorder.route("/api/item/price/HYPERION/analysis", httpx.Response(200, json=ANALYSIS_HYPERION))
    await client.analysis("HYPERION")

    # Expire the entry, then make every request fail.
    client.cache.conn.execute("UPDATE api_cache SET ttl_s = 0")
    recorder.routes.clear()
    recorder.enqueue(
        "/api/item/price/HYPERION/analysis",
        *[httpx.Response(500) for _ in range(6)],
    )
    result = await client.analysis("HYPERION")
    assert result is not None
    assert result.median_price == 1_056_942_042
    assert client.stats.served_stale >= 1


async def test_a_wide_analysis_window_degrades_to_a_free_one(rig) -> None:
    client, recorder = rig

    def handler(request: httpx.Request) -> httpx.Response:
        recorder.calls.append(str(request.url))
        if request.url.params.get("days") == "7":
            return httpx.Response(200, json=ANALYSIS_HYPERION)
        return httpx.Response(403, json={"error": "premium required"})

    client._client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://sky.coflnet.com"
    )
    result = await client.analysis("HYPERION", days=90)
    assert result is not None
    assert result.days == 7


async def test_a_client_error_is_raised_when_nothing_is_cached(rig) -> None:
    client, recorder = rig
    recorder.route("/api/item/price/HYPERION/analysis", httpx.Response(400))
    with pytest.raises(CoflnetError):
        await client._get(
            "/api/item/price/HYPERION/analysis", cache_key="k", ttl=60, allow_stale_on_error=False
        )

"""Resolving the seller behind a listing.

A listing names its seller as a UUID and the command a lowballer types is
``/ah <name>``, so the gap between the two is one endpoint -- and it is the one
Coflnet endpoint that answers in plain text rather than JSON, which is the
whole reason it needs its own tests.
"""

from __future__ import annotations

import httpx
import pytest
from conftest import FakeClock

from lowball.api import players
from lowball.api.cache import ApiCache
from lowball.api.coflnet import CoflnetClient, auction_url
from lowball.api.ratelimit import DualWindowLimiter
from lowball.ledger import Ledger

SELLER = "58f8810695994eb08ddeeac2f469bd79"
NAME_PATH = f"/api/player/{SELLER}/name"


@pytest.fixture
def rig():
    store = Ledger()
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return routes.get(request.url.path, httpx.Response(404, text="not found"))

    routes: dict[str, httpx.Response] = {}
    http = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://sky.coflnet.com"
    )
    clock = FakeClock()
    client = CoflnetClient(
        ApiCache(store.conn),
        limiter=DualWindowLimiter(min_interval=0.0, clock=clock, sleep=clock.sleep),
        client=http,
        sleep=clock.sleep,
    )
    yield client, routes, calls
    store.close()


async def test_a_bare_name_is_read_even_though_it_is_not_json(rig) -> None:
    client, routes, _ = rig
    # The live endpoint really does answer `FusionTorch`, unquoted, so
    # `response.json()` raises on it.  That is what broke the first attempt.
    routes[NAME_PATH] = httpx.Response(200, text="FusionTorch")
    assert await client.player_name(SELLER) == "FusionTorch"


async def test_a_quoted_name_is_read_too(rig) -> None:
    client, routes, _ = rig
    routes[NAME_PATH] = httpx.Response(200, text='"FusionTorch"')
    assert await client.player_name(SELLER) == "FusionTorch"


async def test_an_error_page_never_reaches_the_clipboard(rig) -> None:
    client, routes, _ = rig
    # Anything that is not a Minecraft name is an error dressed as a 200, and
    # pasting it into chat would be worse than copying nothing.
    routes[NAME_PATH] = httpx.Response(200, text="<html>upstream is down</html>")
    assert await client.player_name(SELLER) is None


async def test_a_name_is_asked_for_once(rig) -> None:
    client, routes, calls = rig
    routes[NAME_PATH] = httpx.Response(200, text="FusionTorch")
    for _ in range(4):
        await client.player_name(SELLER)
    # The point: clicking four prices from the same seller during one trade
    # must not spend four requests out of a shared rate limit.
    assert calls.count(NAME_PATH) == 1


async def test_an_unknown_seller_is_an_answer_not_a_failure(rig) -> None:
    client, _routes, _ = rig
    assert await client.player_name(SELLER) is None


async def test_no_uuid_asks_nothing(rig) -> None:
    client, _routes, calls = rig
    assert await client.player_name("") is None
    assert calls == []


def test_the_registry_answers_nothing_until_it_is_told() -> None:
    players.clear()
    assert players.known(SELLER) is None
    # A blank id is a question, not a crash: not every listing names a seller.
    assert players.known(None) is None
    assert players.known("") is None

    players.remember(SELLER, "FusionTorch")
    assert players.known(SELLER) == "FusionTorch"
    # Half an answer is no answer; neither half is worth storing on its own.
    players.remember(None, "Nobody")
    players.remember("other-uuid", None)
    assert players.known("other-uuid") is None
    players.clear()
    assert players.known(SELLER) is None


def test_the_listing_url_is_the_page_a_browser_should_open() -> None:
    assert auction_url("abc") == "https://sky.coflnet.com/auction/abc"

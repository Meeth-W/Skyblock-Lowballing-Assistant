"""Coflnet (SkyCofl) API client.

Every request passes through the cache first and the rate limiter second, so
the only way to spend quota is to ask a question nothing has answered recently.

Attribution: Coflnet requires a visible link wherever their data is shown.
:data:`ATTRIBUTION_URL` builds it and the valuation panel footer renders it.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

import httpx

from .cache import (
    TTL_ACTIVE_BIN,
    TTL_ANALYSIS,
    TTL_AUCTION,
    TTL_SOLD,
    ApiCache,
    scale_ttl,
)
from .models import Auction, PriceAnalysis
from .ratelimit import DualWindowLimiter

log = logging.getLogger(__name__)

BASE_URL = "https://sky.coflnet.com"

#: Free tier covers 1-7 days; wider windows need Premium.  Degrade, never fail.
FREE_ANALYSIS_DAYS = 7
ANALYSIS_FALLBACKS = (7, 3, 1)

#: Status codes worth trying again. A 500 is not among them.
RETRYABLE_STATUS = frozenset({502, 503, 504})


def attribution_url(tag: str) -> str:
    return f"https://sky.coflnet.com/item/{tag}"


class CoflnetError(RuntimeError):
    pass


class RateLimited(CoflnetError):
    def __init__(self, retry_after: float) -> None:
        super().__init__(f"rate limited, retry in {retry_after:.0f}s")
        self.retry_after = retry_after


@dataclass
class ClientStats:
    requests: int = 0
    cache_hits: int = 0
    errors: int = 0
    rate_limited: int = 0
    served_stale: int = 0


class CoflnetClient:
    """Serial, cached, rate-limited access to the Coflnet endpoints."""

    def __init__(
        self,
        cache: ApiCache,
        *,
        limiter: DualWindowLimiter | None = None,
        client: httpx.AsyncClient | None = None,
        base_url: str = BASE_URL,
        timeout: float = 12.0,
        max_retries: int = 3,
        sleep: Any = None,
    ) -> None:
        self.cache = cache
        self.limiter = limiter or DualWindowLimiter()
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        # Injected so backoff can be simulated rather than waited out.
        self._sleep = sleep or asyncio.sleep
        self._client = client
        self._owns_client = client is None
        self.stats = ClientStats()

    async def __aenter__(self) -> CoflnetClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout,
                headers={"User-Agent": "lowball/0.1 (personal trading assistant)"},
            )
        return self._client

    # ---- the one path every request takes -------------------------------

    async def _get(
        self,
        path: str,
        *,
        cache_key: str,
        ttl: int,
        params: dict[str, Any] | None = None,
        allow_stale_on_error: bool = True,
    ) -> Any:
        cached = self.cache.get(cache_key)
        if cached is not None:
            self.stats.cache_hits += 1
            return cached.payload

        params = {k: v for k, v in (params or {}).items() if v is not None}
        last_error: Exception | None = None

        for attempt in range(self.max_retries):
            await self.limiter.acquire()
            try:
                response = await self._http().get(path, params=params)
            except httpx.HTTPError as exc:
                last_error = exc
                self.stats.errors += 1
                # Back off and try again; a flaky connection is not a reason to
                # abandon a valuation.
                await self._sleep(min(4.0, 0.5 * (2**attempt)))
                continue

            if response.status_code == 429:
                retry_after = _retry_after_seconds(response)
                self.limiter.note_retry_after(retry_after)
                self.stats.rate_limited += 1
                last_error = RateLimited(retry_after)
                log.warning("Coflnet rate limit on %s, waiting %.0fs", path, retry_after)
                continue

            if response.status_code == 404:
                # An unknown tag is an answer, not a failure.  Cache it briefly
                # so a typo does not get retried on every keystroke.
                self.cache.put(cache_key, None, min(ttl, 300), source="coflnet")
                return None

            if response.status_code >= 400:
                self.stats.errors += 1
                last_error = CoflnetError(f"{response.status_code} from {path}")
                # A 500 means the query was rejected -- an unsupported filter
                # value, say -- so it will fail identically every time. Only
                # the genuinely transient codes are worth a retry; retrying a
                # 500 three times with backoff spent most of a live valuation.
                if response.status_code not in RETRYABLE_STATUS:
                    break
                await self._sleep(min(4.0, 0.5 * (2**attempt)))
                continue

            try:
                payload = response.json()
            except ValueError as exc:
                last_error = CoflnetError(f"unreadable response from {path}: {exc}")
                self.stats.errors += 1
                break

            self.stats.requests += 1
            self.cache.put(cache_key, payload, ttl, source="coflnet")
            return payload

        if allow_stale_on_error:
            stale = self.cache.get_stale(cache_key)
            if stale is not None:
                # A price from an hour ago, shown as stale, beats no price at
                # all with a customer standing there.
                self.stats.served_stale += 1
                log.info("serving stale cache for %s after %s", path, last_error)
                return stale.payload
        if last_error is not None:
            raise last_error
        return None

    # ---- endpoints ------------------------------------------------------

    async def analysis(self, tag: str, *, days: int = FREE_ANALYSIS_DAYS) -> PriceAnalysis | None:
        """Market behaviour for a tag: median, sell time, volatility, volume.

        Windows past 7 days need a Coflnet subscription.  Rather than fail the
        valuation, walk down to a window this account can actually read.
        """
        wanted = [d for d in (days, *ANALYSIS_FALLBACKS) if d <= days]
        seen: set[int] = set()
        for window in wanted:
            if window in seen:
                continue
            seen.add(window)
            key = self.cache.make_key("analysis", tag, {"days": window})
            try:
                payload = await self._get(
                    f"/api/item/price/{tag}/analysis",
                    cache_key=key,
                    ttl=TTL_ANALYSIS,
                    params={"days": window},
                )
            except CoflnetError:
                continue
            if isinstance(payload, dict) and payload:
                return PriceAnalysis.parse(tag, window, payload)
        return None

    async def active_bin(
        self, tag: str, filters: dict[str, Any] | None = None, *, page: int = 0
    ) -> list[Auction]:
        """Cheapest active BIN listings, filtered."""
        params = {**(filters or {}), "page": page}
        key = self.cache.make_key("active_bin", tag, params)
        ttl = scale_ttl(TTL_ACTIVE_BIN, None)
        payload = await self._get(
            f"/api/auctions/tag/{tag}/active/bin", cache_key=key, ttl=ttl, params=params
        )
        return _as_auctions(payload, sold=False)

    async def active_overview(
        self, tag: str, filters: dict[str, Any] | None = None, *, page: int = 0
    ) -> list[Auction]:
        params = {**(filters or {}), "page": page}
        key = self.cache.make_key("active_overview", tag, params)
        payload = await self._get(
            f"/api/auctions/tag/{tag}/active/overview",
            cache_key=key,
            ttl=TTL_ACTIVE_BIN,
            params=params,
        )
        return _as_auctions(payload, sold=False)

    async def sold(
        self,
        tag: str,
        filters: dict[str, Any] | None = None,
        *,
        page: int = 0,
        volatility: float | None = None,
    ) -> list[Auction]:
        """Recent matching sales: the comparables the estimate is built from."""
        params = {**(filters or {}), "page": page}
        key = self.cache.make_key("sold", tag, params)
        payload = await self._get(
            f"/api/auctions/tag/{tag}/sold",
            cache_key=key,
            ttl=scale_ttl(TTL_SOLD, volatility),
            params=params,
        )
        return _as_auctions(payload, sold=True)

    async def auction(self, auction_uuid: str) -> Auction | None:
        """One listing in full.  Settled auctions never change, so cache hard."""
        key = self.cache.make_key("auction", auction_uuid)
        payload = await self._get(
            f"/api/auction/{auction_uuid}", cache_key=key, ttl=TTL_AUCTION
        )
        if isinstance(payload, dict) and payload:
            return Auction.parse(payload, sold=True)
        return None

    async def lowest_bin(self, tag: str, filters: dict[str, Any] | None = None) -> int | None:
        listings = await self.active_bin(tag, filters)
        prices = sorted(a.unit_price for a in listings if a.unit_price > 0)
        return prices[0] if prices else None


def _as_auctions(payload: Any, *, sold: bool) -> list[Auction]:
    if not isinstance(payload, list):
        return []
    out = []
    for entry in payload:
        if isinstance(entry, dict):
            out.append(Auction.parse(entry, sold=sold))
    return out
def _retry_after_seconds(response: httpx.Response) -> float:
    raw = response.headers.get("Retry-After")
    if raw:
        try:
            return max(1.0, float(raw))
        except ValueError:
            pass
    return 10.0

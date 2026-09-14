"""Request pacing for the Coflnet API.

Coflnet enforces two limits in parallel, by IP: 30 requests per 10 seconds and
100 per minute.  The response headers report only the longest active window,
so the 10-second burst limit can be breached while the minute window still
looks like it has room.  Neither window can be inferred from the other, so both
are tracked here as sliding windows and a request waits for whichever is
further from letting it through.

On top of that sits a minimum interval between requests, so a burst is spread
out rather than fired all at once.  It defaults to about three a second, which
is the sustained rate the 10-second window allows anyway -- those windows are
what actually enforce compliance, and they are tested against bursts far larger
than anything the app generates.  Pacing at one a second, as an earlier version
did, made a cold valuation take ten seconds with a customer waiting.

The clock and the sleep function are injected so burst patterns can be
simulated in tests without real time passing.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

#: (max requests, window length in seconds).  Both are enforced together.
COFLNET_WINDOWS: tuple[tuple[int, float], ...] = ((30, 10.0), (100, 60.0))


@dataclass(frozen=True)
class LimiterStats:
    """What the status bar shows about remaining quota."""

    used: tuple[int, ...]
    limits: tuple[int, ...]
    penalty_seconds: float

    @property
    def tightest_fraction(self) -> float:
        """0.0 when idle, 1.0 when the closest window is full."""
        if not self.limits:
            return 0.0
        return max(u / limit for u, limit in zip(self.used, self.limits, strict=True))


class DualWindowLimiter:
    """A sliding-window limiter that honours several windows at once."""

    def __init__(
        self,
        windows: tuple[tuple[int, float], ...] = COFLNET_WINDOWS,
        *,
        min_interval: float = 0.35,
        safety_margin: float = 0.05,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        if not windows:
            raise ValueError("a limiter needs at least one window")
        self.windows = windows
        self.min_interval = float(min_interval)
        #: Added to every computed wait, so clock skew cannot round us into a breach.
        self.safety_margin = float(safety_margin)
        self._clock = clock
        self._sleep = sleep or asyncio.sleep
        self._hits: list[deque[float]] = [deque() for _ in windows]
        self._last_request: float | None = None
        self._penalty_until: float = 0.0
        self._lock = asyncio.Lock()

    def _prune(self, now: float) -> None:
        for (_, span), hits in zip(self.windows, self._hits, strict=True):
            cutoff = now - span
            while hits and hits[0] <= cutoff:
                hits.popleft()

    def _wait_needed(self, now: float) -> float:
        """Seconds until a request may go out.  Zero means now."""
        wait = 0.0
        if self._penalty_until > now:
            wait = max(wait, self._penalty_until - now)
        if self._last_request is not None:
            wait = max(wait, self._last_request + self.min_interval - now)
        for (limit, span), hits in zip(self.windows, self._hits, strict=True):
            if len(hits) >= limit:
                # The oldest hit has to age out of the window before the next
                # one can go; that is what makes this a sliding window rather
                # than a bucket that refills all at once.
                wait = max(wait, hits[0] + span - now)
        return wait

    async def acquire(self) -> None:
        """Block until a request may be sent, then record it."""
        async with self._lock:
            while True:
                now = self._clock()
                self._prune(now)
                wait = self._wait_needed(now)
                if wait <= 0:
                    for hits in self._hits:
                        hits.append(now)
                    self._last_request = now
                    return
                await self._sleep(wait + self.safety_margin)

    def note_retry_after(self, seconds: float) -> None:
        """Honour a 429.  Nothing goes out until the server says it may."""
        self._penalty_until = max(self._penalty_until, self._clock() + max(0.0, seconds))

    def penalty_remaining(self) -> float:
        return max(0.0, self._penalty_until - self._clock())

    def stats(self) -> LimiterStats:
        now = self._clock()
        self._prune(now)
        return LimiterStats(
            used=tuple(len(h) for h in self._hits),
            limits=tuple(limit for limit, _ in self.windows),
            penalty_seconds=self.penalty_remaining(),
        )

"""Rate limiter burst simulation (Part 16).

Real time never passes here.  A fake clock advances only when the limiter
sleeps, so a ten-minute burst pattern runs instantly and the assertions are
exact rather than flaky.
"""

from __future__ import annotations

import pytest
from conftest import FakeClock

from lowball.api.ratelimit import COFLNET_WINDOWS, DualWindowLimiter


def worst_window_occupancy(stamps: list[float], span: float) -> int:
    """Most requests found inside any window of ``span`` seconds."""
    worst = 0
    for index, start in enumerate(stamps):
        count = 0
        for other in stamps[index:]:
            if other < start + span:
                count += 1
            else:
                break
        worst = max(worst, count)
    return worst


async def drain(limiter: DualWindowLimiter, clock: FakeClock, n: int) -> list[float]:
    stamps = []
    for _ in range(n):
        await limiter.acquire()
        stamps.append(clock.now)
    return stamps


async def test_a_long_burst_never_breaches_either_window() -> None:
    clock = FakeClock()
    limiter = DualWindowLimiter(min_interval=0.0, clock=clock, sleep=clock.sleep)
    stamps = await drain(limiter, clock, 250)

    # A window is breached if more than `limit` requests fall inside `span`.
    # Both limits are checked because Coflnet enforces them in parallel and the
    # headers only ever report the longer one.
    assert worst_window_occupancy(stamps, 10.0) <= 30
    assert worst_window_occupancy(stamps, 60.0) <= 100


@pytest.mark.parametrize(("limit", "span"), COFLNET_WINDOWS)
async def test_each_configured_window_holds_under_pressure(limit: int, span: float) -> None:
    clock = FakeClock()
    limiter = DualWindowLimiter(min_interval=0.0, clock=clock, sleep=clock.sleep)
    stamps = await drain(limiter, clock, 400)
    assert worst_window_occupancy(stamps, span) <= limit


async def test_the_first_burst_fills_the_short_window_immediately() -> None:
    """Up to the burst limit should go out at once; the next one waits."""
    clock = FakeClock()
    limiter = DualWindowLimiter(min_interval=0.0, clock=clock, sleep=clock.sleep)
    stamps = await drain(limiter, clock, 30)
    assert stamps == [1000.0] * 30

    await limiter.acquire()
    assert clock.now >= 1010.0


async def test_a_serial_queue_paces_requests() -> None:
    clock = FakeClock()
    limiter = DualWindowLimiter(min_interval=1.0, clock=clock, sleep=clock.sleep)
    stamps = await drain(limiter, clock, 12)
    gaps = [b - a for a, b in zip(stamps[:-1], stamps[1:], strict=True)]
    assert all(gap >= 1.0 for gap in gaps)


async def test_a_36_slot_inventory_with_relaxation_stays_legal() -> None:
    """The worst realistic case from the brief: 150+ requests in one go."""
    clock = FakeClock()
    limiter = DualWindowLimiter(min_interval=1.0, clock=clock, sleep=clock.sleep)
    stamps = await drain(limiter, clock, 160)
    assert worst_window_occupancy(stamps, 10.0) <= 30
    assert worst_window_occupancy(stamps, 60.0) <= 100


async def test_retry_after_pauses_everything() -> None:
    clock = FakeClock()
    limiter = DualWindowLimiter(min_interval=0.0, clock=clock, sleep=clock.sleep)
    await limiter.acquire()
    limiter.note_retry_after(14.0)
    assert limiter.penalty_remaining() == pytest.approx(14.0)

    await limiter.acquire()
    assert clock.now >= 1014.0
    assert limiter.penalty_remaining() == 0.0


async def test_the_longest_penalty_wins() -> None:
    clock = FakeClock()
    limiter = DualWindowLimiter(min_interval=0.0, clock=clock, sleep=clock.sleep)
    limiter.note_retry_after(5.0)
    limiter.note_retry_after(30.0)
    limiter.note_retry_after(2.0)
    assert limiter.penalty_remaining() == pytest.approx(30.0)


async def test_stats_report_occupancy_for_the_status_bar() -> None:
    clock = FakeClock()
    limiter = DualWindowLimiter(min_interval=0.0, clock=clock, sleep=clock.sleep)
    await drain(limiter, clock, 15)
    stats = limiter.stats()
    assert stats.used == (15, 15)
    assert stats.limits == (30, 100)
    assert stats.tightest_fraction == pytest.approx(0.5)


async def test_old_hits_age_out_of_the_window() -> None:
    clock = FakeClock()
    limiter = DualWindowLimiter(min_interval=0.0, clock=clock, sleep=clock.sleep)
    await drain(limiter, clock, 20)
    clock.now += 61.0
    assert limiter.stats().used == (0, 0)

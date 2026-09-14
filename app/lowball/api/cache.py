"""SQLite-backed response cache.

The point of this layer is not speed, it is rate limit budget.  Coflnet allows
30 requests per 10 seconds by IP; one busy trade can ask more questions than
that on its own.  Anything answered from here is a question not asked twice.

TTLs scale with how fast an item moves.  A Hyperion repriced every few minutes
is wasted effort -- the market does not move that quickly -- while a thin,
volatile item goes stale fast.  Callers pass a volatility figure (Coflnet's
``priceCoeffVariation``) and get a sensible lifetime back.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass
from typing import Any

from ..timeutil import age_seconds, now_iso

#: Cache lifetimes in seconds, before volatility scaling.
TTL_ANALYSIS = 30 * 60
TTL_ACTIVE_BIN = 5 * 60
TTL_SOLD = 15 * 60
TTL_AUCTION = 24 * 60 * 60
TTL_DEFAULT = 10 * 60

MIN_TTL = 60
MAX_TTL = 6 * 60 * 60


def scale_ttl(base_ttl: int, volatility: float | None) -> int:
    """Shorten the lifetime of a volatile item, lengthen a stable one.

    ``volatility`` is a coefficient of variation, so 0.1 is a quiet market and
    0.6 is one where a cached price is actively misleading.
    """
    if volatility is None:
        return int(base_ttl)
    factor = 1.0 / (1.0 + max(0.0, float(volatility)) * 4.0)
    return max(MIN_TTL, min(MAX_TTL, int(base_ttl * factor)))


@dataclass(frozen=True)
class CacheEntry:
    key: str
    payload: Any
    fetched_ts: str
    ttl_s: int
    source: str | None = None

    def age(self) -> float:
        return age_seconds(self.fetched_ts)

    def is_fresh(self) -> bool:
        return self.age() < self.ttl_s


class ApiCache:
    """Durable response cache keyed on (endpoint, tag, filter signature).

    Writes come from the asyncio worker thread and reads from the GUI thread,
    so the lock is real rather than decorative even with WAL enabled.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    @staticmethod
    def make_key(endpoint: str, tag: str, filters: dict[str, Any] | None = None) -> str:
        """Stable key; filters are sorted so argument order cannot split entries."""
        if filters:
            rendered = "&".join(f"{k}={v}" for k, v in sorted(filters.items()) if v is not None)
        else:
            rendered = ""
        return f"{endpoint}|{tag}|{rendered}"

    def get(self, key: str) -> CacheEntry | None:
        with self._lock:
            row = self.conn.execute(
                "SELECT key, payload, fetched_ts, ttl_s, source FROM api_cache WHERE key = ?",
                (key,),
            ).fetchone()
        if row is None:
            self.misses += 1
            return None
        entry = CacheEntry(
            key=row["key"],
            payload=json.loads(row["payload"]),
            fetched_ts=row["fetched_ts"],
            ttl_s=int(row["ttl_s"]),
            source=row["source"],
        )
        if entry.is_fresh():
            self.hits += 1
            return entry
        self.misses += 1
        return None

    def get_stale(self, key: str) -> CacheEntry | None:
        """Ignore the TTL.

        Used when the network or the rate limit has failed us: an hour-old
        price shown as stale beats no price at all with a customer waiting.
        """
        with self._lock:
            row = self.conn.execute(
                "SELECT key, payload, fetched_ts, ttl_s, source FROM api_cache WHERE key = ?",
                (key,),
            ).fetchone()
        if row is None:
            return None
        return CacheEntry(
            key=row["key"],
            payload=json.loads(row["payload"]),
            fetched_ts=row["fetched_ts"],
            ttl_s=int(row["ttl_s"]),
            source=row["source"],
        )

    def put(self, key: str, payload: Any, ttl_s: int, *, source: str | None = None) -> None:
        blob = json.dumps(payload, separators=(",", ":"), default=str)
        with self._lock:
            self.conn.execute(
                "INSERT INTO api_cache (key, payload, fetched_ts, ttl_s, source)"
                " VALUES (?, ?, ?, ?, ?)"
                " ON CONFLICT(key) DO UPDATE SET payload = excluded.payload,"
                " fetched_ts = excluded.fetched_ts, ttl_s = excluded.ttl_s,"
                " source = excluded.source",
                (key, blob, now_iso(), int(ttl_s), source),
            )

    def purge_expired(self) -> int:
        """Drop entries whose TTL has run out.  Cheap to run on start-up."""
        with self._lock:
            rows = self.conn.execute(
                "SELECT key, fetched_ts, ttl_s FROM api_cache"
            ).fetchall()
            dead = [r["key"] for r in rows if age_seconds(r["fetched_ts"]) >= int(r["ttl_s"])]
            for key in dead:
                self.conn.execute("DELETE FROM api_cache WHERE key = ?", (key,))
        return len(dead)

    def clear(self) -> None:
        with self._lock:
            self.conn.execute("DELETE FROM api_cache")

    @property
    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return self.hits / total if total else 0.0

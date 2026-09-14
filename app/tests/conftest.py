from __future__ import annotations

import pytest

from lowball.ledger import Ledger


@pytest.fixture
def ledger() -> Ledger:
    store = Ledger()
    yield store
    store.close()


def dump_projections(store: Ledger) -> dict[str, list[tuple]]:
    """Every derived row, ordered, for comparing state before and after a rebuild."""
    tables = ("sessions", "offers", "items", "exits", "rule_firings", "valuations")
    out: dict[str, list[tuple]] = {}
    for table in tables:
        rows = store.conn.execute(f"SELECT * FROM {table}").fetchall()
        out[table] = sorted(tuple(r) for r in rows)
    return out


class FakeClock:
    """Virtual time that moves only when something waits on it.

    Lets burst patterns and backoff waits run instantly, and makes the
    assertions exact instead of timing-dependent.
    """

    def __init__(self, start: float = 1000.0) -> None:
        self.now = float(start)

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        assert seconds >= 0
        self.now += seconds

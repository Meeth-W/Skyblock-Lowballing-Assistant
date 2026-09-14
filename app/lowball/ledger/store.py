"""The Ledger facade: one object that owns the log, the projections and the
vocabulary the rest of the app uses to record what happened.

Callers never touch ``events`` or the projection tables directly.  They call a
named method here, which appends exactly one event and projects it inside a
single transaction, so the log and the derived tables can never disagree.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from ..ids import new_id
from ..tax import DEFAULT_TAX, TaxConfig
from ..tax import claim_tax as _claim_tax
from .db import apply_schema, connect, transaction
from .events import Event, EventLog, EventType
from .projections import Projector


class Ledger:
    def __init__(
        self,
        conn: sqlite3.Connection | None = None,
        *,
        path: str | Path | None = None,
        tax: TaxConfig = DEFAULT_TAX,
    ) -> None:
        self.conn = conn if conn is not None else connect(path or ":memory:")
        self.tax = tax
        apply_schema(self.conn)
        self.log = EventLog(self.conn)
        self.projector = Projector(self.conn, tax)
        # A database written by an older build has derived tables of the old
        # shape, and no amount of catching up will add a column to them.
        if (
            self.projector.watermark() == 0
            or "items" not in self._tables()
            or not self.projector.is_current()
        ):
            self.rebuild()
        else:
            self.projector.catch_up(self.log)

    @classmethod
    def open(cls, path: str | Path, *, tax: TaxConfig = DEFAULT_TAX) -> Ledger:
        return cls(path=path, tax=tax)

    def _tables(self) -> set[str]:
        rows = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        return {r["name"] for r in rows}

    def close(self) -> None:
        self.conn.close()

    # ---- writing -------------------------------------------------------

    def append(
        self,
        type: EventType | str,
        payload: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> Event:
        """Append one event and project it atomically."""
        with transaction(self.conn):
            event = self.log.append(type, payload, **kwargs)
            self.projector.apply(event)
            self.projector.set_watermark(event.id)
        return event

    def correct(
        self,
        target_event_id: int,
        *,
        patch: dict[str, Any] | None = None,
        void: bool = False,
        note: str | None = None,
    ) -> Event:
        """Fix an earlier mistake by appending a correction and rebuilding.

        A correction can rewrite an event from any point in history, so the
        only safe response is a full replay.  Corrections are rare; a rebuild
        of a season of trading takes well under a second.
        """
        event = self.log.correct(target_event_id, patch=patch, void=void, note=note)
        self.rebuild()
        return event

    def rebuild(self) -> int:
        return self.projector.rebuild(self.log)

    # ---- negotiation ---------------------------------------------------

    def start_session(
        self,
        *,
        tag: str,
        signature: Any = None,
        display_name: str | None = None,
        rarity: str | None = None,
        uid: str | None = None,
        counterparty: str | None = None,
        session_id: str | None = None,
    ) -> str:
        session_id = session_id or new_id()
        self.append(
            EventType.SESSION_STARTED,
            {
                "session_id": session_id,
                "tag": tag,
                "signature": signature,
                "display_name": display_name,
                "rarity": rarity,
                "uid": uid,
                "counterparty": counterparty,
            },
        )
        return session_id

    def record_offer(
        self,
        *,
        session_id: str,
        tag: str,
        offer_pct: float,
        offer_coins: int,
        est_value: int,
        confidence: float | None = None,
        signature: Any = None,
        counterparty: str | None = None,
        is_exploration: bool = False,
        rules_fired: list[Any] | None = None,
        offer_id: str | None = None,
    ) -> str:
        offer_id = offer_id or new_id()
        self.append(
            EventType.OFFER_MADE,
            {
                "session_id": session_id,
                "offer_id": offer_id,
                "tag": tag,
                "signature": signature,
                "est_value": int(est_value),
                "confidence": confidence,
                "offer_pct": float(offer_pct),
                "offer_coins": int(offer_coins),
                "is_exploration": bool(is_exploration),
                "counterparty": counterparty,
                "rules_fired": rules_fired or [],
            },
        )
        return offer_id

    def reject_offer(self, offer_id: str, *, session_id: str | None = None) -> Event:
        return self.append(
            EventType.OFFER_REJECTED, {"offer_id": offer_id, "session_id": session_id}
        )

    def counter_offer(
        self, offer_id: str, counter_price: int, *, session_id: str | None = None
    ) -> Event:
        return self.append(
            EventType.OFFER_COUNTERED,
            {
                "offer_id": offer_id,
                "counter_price": int(counter_price),
                "session_id": session_id,
            },
        )

    def abandon_session(self, session_id: str) -> Event:
        return self.append(EventType.SESSION_ABANDONED, {"session_id": session_id})

    # ---- item lifecycle ------------------------------------------------

    def acquire_item(
        self,
        *,
        tag: str,
        cost_basis: int,
        session_id: str | None = None,
        offer_id: str | None = None,
        uid: str | None = None,
        display_name: str | None = None,
        rarity: str | None = None,
        category: str | None = None,
        signature: Any = None,
        est_value: int | None = None,
        counterparty: str | None = None,
        item_id: str | None = None,
        ts: str | None = None,
    ) -> str:
        item_id = item_id or new_id()
        self.append(
            EventType.ITEM_ACQUIRED,
            {
                "item_id": item_id,
                "session_id": session_id,
                "offer_id": offer_id,
                "uid": uid,
                "tag": tag,
                "display_name": display_name,
                "rarity": rarity,
                "category": category,
                "signature": signature,
                "cost_basis": int(cost_basis),
                "est_value": est_value,
                "counterparty": counterparty,
            },
            ts=ts,
        )
        return item_id

    def sell_item(
        self,
        *,
        item_id: str,
        price: int,
        taxed: bool = True,
        counterparty: str | None = None,
        note: str | None = None,
        ts: str | None = None,
    ) -> Event:
        """Record that an item left for coins.

        ``price`` is the gross figure, the one the user reads off the auction
        house or agrees in a trade.  ``taxed`` decides whether the auction
        house takes its cut on top; a direct player trade does not.
        """
        tax = _claim_tax(int(price), self.tax) if taxed else 0
        return self.append(
            EventType.ITEM_SOLD,
            {
                "item_id": item_id,
                "price": int(price),
                "taxed": bool(taxed),
                "claim_tax": int(tax),
                "counterparty": counterparty,
                "note": note,
            },
            ts=ts,
        )

    def keep_item(
        self,
        *,
        item_id: str,
        market_value: int | None = None,
        note: str | None = None,
        ts: str | None = None,
    ) -> Event:
        """Take an item out of stock for personal use, at market value."""
        return self.append(
            EventType.ITEM_KEPT,
            {"item_id": item_id, "market_value": market_value, "note": note},
            ts=ts,
        )

    def unwind_exit(self, item_id: str, *, note: str | None = None) -> Event:
        """Undo an outcome recorded in error; the item goes back into stock."""
        return self.append(
            EventType.EXIT_UNWOUND, {"item_id": item_id, "note": note}
        )

    # ---- destructive --------------------------------------------------

    def clear_history(self) -> int:
        """Erase every recorded event and rebuild empty projections.

        The only operation in the app that destroys history, and it exists
        because the alternative is the user deleting the database file by
        hand and losing their settings with it.  Cached prices survive: they
        are not history, and re-fetching them would cost the rate limit.
        """
        with transaction(self.conn) as conn:
            row = conn.execute("SELECT COUNT(*) AS n FROM events").fetchone()
            removed = int(row["n"])
            conn.execute("DELETE FROM events")
        self.rebuild()
        return removed

    def record_valuation(
        self,
        *,
        tag: str,
        estimate: int,
        item_id: str | None = None,
        session_id: str | None = None,
        signature: Any = None,
        confidence: float | None = None,
        market_estimate: int | None = None,
        manual_estimate: int | None = None,
        lbin: int | None = None,
        median: int | None = None,
        sell_seconds: int | None = None,
        ts: str | None = None,
    ) -> Event:
        return self.append(
            EventType.VALUATION_RECORDED,
            {
                "item_id": item_id,
                "session_id": session_id,
                "tag": tag,
                "signature": signature,
                "estimate": int(estimate),
                # Kept apart so a price the user set by hand stays
                # distinguishable from one the market produced.
                "market_estimate": market_estimate,
                "manual_estimate": manual_estimate,
                "confidence": confidence,
                "lbin": lbin,
                "median": median,
                "sell_seconds": sell_seconds,
            },
            ts=ts,
        )

    # ---- reading -------------------------------------------------------

    def query(self, sql: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
        return self.conn.execute(sql, params).fetchall()

    def one(self, sql: str, params: tuple[Any, ...] = ()) -> sqlite3.Row | None:
        return self.conn.execute(sql, params).fetchone()

    def item(self, item_id: str) -> sqlite3.Row | None:
        return self.one("SELECT * FROM items WHERE item_id = ?", (item_id,))

    def items_in_state(self, state: str) -> list[sqlite3.Row]:
        return self.query(
            "SELECT * FROM items WHERE state = ? ORDER BY acquired_ts DESC", (state,)
        )

    def held_items(self) -> list[sqlite3.Row]:
        """Anything still representing deployed capital."""
        return self.query("SELECT * FROM items WHERE state = 'HELD' ORDER BY acquired_ts")

    def session(self, session_id: str) -> sqlite3.Row | None:
        return self.one("SELECT * FROM sessions WHERE session_id = ?", (session_id,))

    def offers_in_session(self, session_id: str) -> list[sqlite3.Row]:
        return self.query(
            "SELECT * FROM offers WHERE session_id = ? ORDER BY seq", (session_id,)
        )

    def offer(self, offer_id: str) -> sqlite3.Row | None:
        return self.one("SELECT * FROM offers WHERE offer_id = ?", (offer_id,))

    def exit_for(self, item_id: str) -> sqlite3.Row | None:
        return self.one(
            "SELECT * FROM exits WHERE item_id = ? ORDER BY ts DESC LIMIT 1", (item_id,)
        )

    def rules_fired(self, offer_id: str) -> list[str]:
        return [
            r["rule_name"]
            for r in self.query(
                "SELECT rule_name FROM rule_firings WHERE offer_id = ?", (offer_id,)
            )
        ]

    def item_by_uid(self, uid: str) -> sqlite3.Row | None:
        return self.one(
            "SELECT * FROM items WHERE uid = ? ORDER BY acquired_ts DESC LIMIT 1", (uid,)
        )

    def history(self, item_id: str) -> list[Event]:
        """Everything that ever happened to one item, corrections applied."""
        return [e for e in self.log.effective() if e.item_id == item_id]

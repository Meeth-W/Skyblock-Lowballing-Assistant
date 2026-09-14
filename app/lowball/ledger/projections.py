"""Derived state, rebuilt by replaying the event log.

Nothing outside this module writes to a projection table.  Every handler is a
pure function of the event plus whatever earlier events already put in the
tables, which is what makes a full rebuild reproduce byte-identical state.

Ids for rows that an event creates on the fly -- exits, valuations -- are
derived from the event id rather than generated randomly, so a rebuild
produces the same rows and two databases replaying the same log agree.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from typing import Any

from ..tax import DEFAULT_TAX, TaxConfig
from ..timeutil import from_iso
from .db import apply_projections, transaction
from .events import Event, EventLog, EventType

PROJECTION_NAME = "main"

#: Bumped whenever ``projections.sql`` changes shape.  A derived table that
#: gained a column cannot be caught up incrementally -- the rows already in it
#: were written by the old schema -- so a version mismatch forces a full
#: replay.  Without this an existing database keeps its old tables and the
#: first query against a new column fails.
PROJECTION_VERSION = 2

#: The version is kept in ``projection_state`` beside the watermark, under its
#: own name.  Two integers in one bookkeeping table beats migrating the table
#: that exists to record migrations.
VERSION_NAME = f"{PROJECTION_NAME}:schema"


def _json(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value, separators=(",", ":"), default=str)


class Projector:
    """Applies events to the derived tables."""

    def __init__(self, conn: sqlite3.Connection, tax: TaxConfig = DEFAULT_TAX) -> None:
        self.conn = conn
        self.tax = tax
        self._handlers: dict[str, Callable[[Event], None]] = {
            EventType.SESSION_STARTED: self._session_started,
            EventType.OFFER_MADE: self._offer_made,
            EventType.OFFER_REJECTED: self._offer_rejected,
            EventType.OFFER_COUNTERED: self._offer_countered,
            EventType.SESSION_ABANDONED: self._session_abandoned,
            EventType.ITEM_ACQUIRED: self._item_acquired,
            EventType.ITEM_SOLD: self._item_sold,
            EventType.ITEM_KEPT: self._item_kept,
            EventType.EXIT_UNWOUND: self._exit_unwound,
            # A log written by an older build still carries these; they say the
            # same thing, one taxed and one not.
            EventType.ITEM_SOLD_AH: self._item_sold,
            EventType.ITEM_SOLD_PRIVATE: self._item_sold,
            EventType.VALUATION_RECORDED: self._valuation_recorded,
        }

    # ---- driving -------------------------------------------------------

    def apply(self, event: Event) -> None:
        handler = self._handlers.get(event.type)
        if handler is not None:
            handler(event)

    def rebuild(self, log: EventLog) -> int:
        """Drop every derived table and replay the whole log into fresh ones."""
        with transaction(self.conn) as conn:
            apply_projections(conn)
            count = 0
            for event in log.effective():
                self.apply(event)
                count += 1
            self.set_watermark(log.last_id())
            self.conn.execute(
                "INSERT INTO projection_state (name, last_event_id) VALUES (?, ?)"
                " ON CONFLICT(name) DO UPDATE SET last_event_id = excluded.last_event_id",
                (VERSION_NAME, PROJECTION_VERSION),
            )
        return count

    def catch_up(self, log: EventLog) -> int:
        """Apply only events newer than the watermark."""
        since = self.watermark()
        with transaction(self.conn):
            count = 0
            for event in log.effective(since_id=since):
                self.apply(event)
                count += 1
            self.set_watermark(log.last_id())
        return count

    def schema_version(self) -> int:
        row = self.conn.execute(
            "SELECT last_event_id FROM projection_state WHERE name = ?", (VERSION_NAME,)
        ).fetchone()
        return int(row["last_event_id"]) if row else 0

    def is_current(self) -> bool:
        """Whether the derived tables were built by this version of the code."""
        return self.schema_version() == PROJECTION_VERSION

    def watermark(self) -> int:
        row = self.conn.execute(
            "SELECT last_event_id FROM projection_state WHERE name = ?", (PROJECTION_NAME,)
        ).fetchone()
        return int(row["last_event_id"]) if row else 0

    def set_watermark(self, event_id: int) -> None:
        self.conn.execute(
            "INSERT INTO projection_state (name, last_event_id) VALUES (?, ?)"
            " ON CONFLICT(name) DO UPDATE SET last_event_id = excluded.last_event_id",
            (PROJECTION_NAME, int(event_id)),
        )

    # ---- shared lookups ------------------------------------------------

    def _item_field(self, item_id: str, column: str) -> Any:
        row = self.conn.execute(
            f"SELECT {column} AS v FROM items WHERE item_id = ?", (item_id,)
        ).fetchone()
        return row["v"] if row else None

    def _hold_seconds(self, item_id: str, exit_ts: str) -> int | None:
        acquired = self._item_field(item_id, "acquired_ts")
        if not acquired:
            return None
        return int((from_iso(exit_ts) - from_iso(acquired)).total_seconds())

    def _record_exit(
        self,
        event: Event,
        *,
        item_id: str,
        route: str,
        gross: int,
        fees_total: int,
        counterparty: str | None = None,
        taxed: bool = False,
        note: str | None = None,
    ) -> None:
        cost_basis = int(self._item_field(item_id, "cost_basis") or 0)
        net = int(gross) - int(fees_total)
        # One exit per item.  Changing your mind about what happened to
        # something rewrites the row rather than giving it two histories.
        self.conn.execute("DELETE FROM exits WHERE item_id = ?", (item_id,))
        self.conn.execute(
            "INSERT INTO exits (exit_id, item_id, route, ts, gross, fees_total,"
            " net, cost_basis, profit, hold_seconds, counterparty, taxed, note)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                f"exit-{event.id}",
                item_id,
                route,
                event.ts,
                int(gross),
                int(fees_total),
                net,
                cost_basis,
                net - cost_basis,
                self._hold_seconds(item_id, event.ts),
                counterparty,
                1 if taxed else 0,
                note,
            ),
        )
        self.conn.execute(
            "UPDATE items SET exit_ts = ? WHERE item_id = ?", (event.ts, item_id)
        )

    # ---- session and offer handlers ------------------------------------

    def _session_started(self, e: Event) -> None:
        p = e.payload
        self.conn.execute(
            "INSERT OR REPLACE INTO sessions (session_id, tag, display_name, rarity,"
            " signature, uid, counterparty, started_ts, ended_ts, state, item_id, offer_count)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, 'ACTIVE', NULL, 0)",
            (
                p.get("session_id") or e.session_id,
                p.get("tag"),
                p.get("display_name"),
                p.get("rarity"),
                _json(p.get("signature")),
                p.get("uid"),
                p.get("counterparty"),
                e.ts,
            ),
        )

    def _offer_made(self, e: Event) -> None:
        p = e.payload
        session_id = p.get("session_id") or e.session_id
        seq = p.get("seq")
        if seq is None:
            row = self.conn.execute(
                "SELECT COALESCE(MAX(seq), 0) + 1 AS n FROM offers WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            seq = int(row["n"])
        self.conn.execute(
            "INSERT OR REPLACE INTO offers (offer_id, session_id, seq, tag, signature,"
            " est_value, confidence, offer_pct, offer_coins, outcome, counter_price,"
            " settled_price, is_exploration, counterparty, ts)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', NULL, NULL, ?, ?, ?)",
            (
                p.get("offer_id"),
                session_id,
                int(seq),
                p.get("tag"),
                _json(p.get("signature")),
                p.get("est_value"),
                p.get("confidence"),
                p.get("offer_pct"),
                p.get("offer_coins"),
                1 if p.get("is_exploration") else 0,
                p.get("counterparty"),
                e.ts,
            ),
        )
        self.conn.execute(
            "UPDATE sessions SET offer_count = (SELECT COUNT(*) FROM offers WHERE"
            " session_id = ?) WHERE session_id = ?",
            (session_id, session_id),
        )
        for rule in p.get("rules_fired") or []:
            name = rule if isinstance(rule, str) else rule.get("name")
            detail = None if isinstance(rule, str) else _json(rule.get("detail"))
            if name:
                self.conn.execute(
                    "INSERT OR REPLACE INTO rule_firings (offer_id, rule_name, detail)"
                    " VALUES (?, ?, ?)",
                    (p.get("offer_id"), name, detail),
                )

    def _offer_rejected(self, e: Event) -> None:
        self.conn.execute(
            "UPDATE offers SET outcome = 'REJECTED' WHERE offer_id = ?",
            (e.payload.get("offer_id"),),
        )

    def _offer_countered(self, e: Event) -> None:
        self.conn.execute(
            "UPDATE offers SET outcome = 'COUNTERED', counter_price = ? WHERE offer_id = ?",
            (e.payload.get("counter_price"), e.payload.get("offer_id")),
        )

    def _session_abandoned(self, e: Event) -> None:
        session_id = e.payload.get("session_id") or e.session_id
        # A walk-away is not a rejection: the customer never answered, which
        # says something different about the offer.
        self.conn.execute(
            "UPDATE offers SET outcome = 'ABANDONED'"
            " WHERE session_id = ? AND outcome = 'PENDING'",
            (session_id,),
        )
        self.conn.execute(
            "UPDATE sessions SET state = 'ABANDONED', ended_ts = ? WHERE session_id = ?",
            (e.ts, session_id),
        )

    # ---- item lifecycle handlers ---------------------------------------

    def _item_acquired(self, e: Event) -> None:
        p = e.payload
        item_id = p.get("item_id") or e.item_id
        session_id = p.get("session_id") or e.session_id
        self.conn.execute(
            "INSERT OR REPLACE INTO items (item_id, uid, tag, display_name, rarity,"
            " category, signature, acquired_ts, cost_basis, state, est_value_now,"
            " est_value_ts, counterparty, session_id, exit_ts)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'HELD', ?, ?, ?, ?, NULL)",
            (
                item_id,
                p.get("uid"),
                p.get("tag"),
                p.get("display_name"),
                p.get("rarity"),
                p.get("category"),
                _json(p.get("signature")),
                p.get("acquired_ts") or e.ts,
                int(p.get("cost_basis") or 0),
                p.get("est_value"),
                e.ts if p.get("est_value") is not None else None,
                p.get("counterparty"),
                session_id,
            ),
        )
        offer_id = p.get("offer_id")
        if offer_id:
            self.conn.execute(
                "UPDATE offers SET outcome = 'CONFIRMED', settled_price = ?"
                " WHERE offer_id = ?",
                (int(p.get("cost_basis") or 0), offer_id),
            )
        if session_id:
            self.conn.execute(
                "UPDATE sessions SET state = 'CONFIRMED', ended_ts = ?, item_id = ?"
                " WHERE session_id = ?",
                (e.ts, item_id, session_id),
            )

    def _exit_unwound(self, e: Event) -> None:
        """An outcome recorded in error.  The item comes back into stock."""
        item_id = e.payload.get("item_id") or e.item_id
        if not item_id:
            return
        self.conn.execute("DELETE FROM exits WHERE item_id = ?", (item_id,))
        self.conn.execute(
            "UPDATE items SET state = 'HELD', exit_ts = NULL WHERE item_id = ?",
            (item_id,),
        )

    # ---- exit handlers -------------------------------------------------

    def _item_sold(self, e: Event) -> None:
        """Every shape of sale this log has ever carried, in one handler.

        ``ITEM_SOLD`` says in its payload whether the auction house took its
        cut; the two older event types answer that by which one they are.
        """
        from ..tax import claim_tax as _claim_tax

        p = e.payload
        item_id = p.get("item_id") or e.item_id
        if not item_id:
            return
        raw_price = p.get("price")
        gross = int(raw_price if raw_price is not None else (p.get("sale_price") or 0))
        taxed = bool(p.get("taxed", e.type == EventType.ITEM_SOLD_AH))
        tax = p.get("claim_tax")
        tax = (_claim_tax(gross, self.tax) if taxed else 0) if tax is None else int(tax)
        self.conn.execute("UPDATE items SET state = 'SOLD' WHERE item_id = ?", (item_id,))
        self._record_exit(
            e,
            item_id=item_id,
            route="SOLD",
            gross=gross,
            fees_total=tax,
            counterparty=p.get("counterparty") or p.get("buyer"),
            taxed=taxed,
            note=p.get("note"),
        )

    def _item_kept(self, e: Event) -> None:
        p = e.payload
        item_id = p.get("item_id") or e.item_id
        if not item_id:
            return
        # Booked as a withdrawal at market value on the keep date.  Left in the
        # trading P&L it would read as an unsold loss forever.
        self.conn.execute("UPDATE items SET state = 'KEPT' WHERE item_id = ?", (item_id,))
        value = p.get("market_value")
        if value is None:
            value = self._item_field(item_id, "est_value_now") or 0
        self._record_exit(
            e,
            item_id=item_id,
            route="KEPT",
            gross=int(value),
            fees_total=0,
            note=p.get("note"),
        )

    def _valuation_recorded(self, e: Event) -> None:
        p = e.payload
        item_id = p.get("item_id") or e.item_id
        self.conn.execute(
            "INSERT OR REPLACE INTO valuations (valuation_id, item_id, session_id, tag,"
            " signature, estimate, confidence, lbin, median, sell_seconds, ts)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                f"val-{e.id}",
                item_id,
                p.get("session_id") or e.session_id,
                p.get("tag"),
                _json(p.get("signature")),
                p.get("estimate"),
                p.get("confidence"),
                p.get("lbin"),
                p.get("median"),
                p.get("sell_seconds"),
                e.ts,
            ),
        )
        if item_id and p.get("estimate") is not None:
            self.conn.execute(
                "UPDATE items SET est_value_now = ?, est_value_ts = ? WHERE item_id = ?",
                (int(p["estimate"]), e.ts, item_id),
            )

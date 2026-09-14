"""The append-only event log.

Every fact the app learns is written here once and never edited.  Projections
(``projections.py``) are a pure function of this table, so a bad projection is
always recoverable by rebuilding, and a bad *fact* is fixed by appending a
``MANUAL_CORRECTION`` rather than by rewriting history.

A correction carries either a ``patch``, whose fields are merged into the
payload of the target event at replay time, or ``void: true``, which makes the
replay skip the target entirely.  Corrections apply in id order, so a later one
wins field by field.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from ..ids import new_id
from ..timeutil import now_iso
from .db import transaction


class EventType(StrEnum):
    SESSION_STARTED = "SESSION_STARTED"
    OFFER_MADE = "OFFER_MADE"
    OFFER_REJECTED = "OFFER_REJECTED"
    OFFER_COUNTERED = "OFFER_COUNTERED"
    SESSION_ABANDONED = "SESSION_ABANDONED"
    ITEM_ACQUIRED = "ITEM_ACQUIRED"
    ITEM_SOLD = "ITEM_SOLD"
    ITEM_KEPT = "ITEM_KEPT"
    #: An outcome recorded in error.  The item goes back into stock, and the
    #: mistake stays in the log rather than being erased from it.
    EXIT_UNWOUND = "EXIT_UNWOUND"
    #: Superseded by ITEM_SOLD.  Still projected, because a database written
    #: by an older build has them in its log and the log is never rewritten.
    ITEM_SOLD_AH = "ITEM_SOLD_AH"
    ITEM_SOLD_PRIVATE = "ITEM_SOLD_PRIVATE"
    VALUATION_RECORDED = "VALUATION_RECORDED"
    MANUAL_CORRECTION = "MANUAL_CORRECTION"


@dataclass(frozen=True)
class Event:
    id: int
    ts: str
    type: str
    session_id: str | None
    item_id: str | None
    payload: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> Event:
        return cls(
            id=row["id"],
            ts=row["ts"],
            type=row["type"],
            session_id=row["session_id"],
            item_id=row["item_id"],
            payload=json.loads(row["payload"]),
        )

    def with_payload(self, payload: dict[str, Any]) -> Event:
        return Event(self.id, self.ts, self.type, self.session_id, self.item_id, payload)

    def get(self, key: str, default: Any = None) -> Any:
        return self.payload.get(key, default)



class EventLog:
    """Reads and writes ``events``.  Knows nothing about what events mean."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def append(
        self,
        type: EventType | str,
        payload: dict[str, Any] | None = None,
        *,
        session_id: str | None = None,
        item_id: str | None = None,
        ts: str | None = None,
    ) -> Event:
        payload = dict(payload or {})
        # Keep the indexed columns in step with the payload.  The payload is the
        # record of truth; the columns exist only so queries stay cheap.
        session_id = session_id or payload.get("session_id")
        item_id = item_id or payload.get("item_id")
        row_ts = ts or payload.get("ts") or now_iso()
        blob = json.dumps(payload, separators=(",", ":"), default=str)
        with transaction(self.conn) as conn:
            cur = conn.execute(
                "INSERT INTO events (ts, type, session_id, item_id, payload)"
                " VALUES (?, ?, ?, ?, ?)",
                (row_ts, str(type), session_id, item_id, blob),
            )
            event_id = int(cur.lastrowid)
        return Event(event_id, row_ts, str(type), session_id, item_id, payload)

    def correct(
        self,
        target_event_id: int,
        *,
        patch: dict[str, Any] | None = None,
        void: bool = False,
        note: str | None = None,
    ) -> Event:
        """Append a correction against an earlier event.

        The target stays in the log untouched.  Callers must rebuild
        projections afterwards; the Ledger facade does that automatically.
        """
        if not void and not patch:
            raise ValueError("a correction must carry a patch or void the target")
        target = self.by_id(target_event_id)
        if target is None:
            raise ValueError(f"no event with id {target_event_id}")
        if target.type == EventType.MANUAL_CORRECTION:
            raise ValueError("corrections cannot target other corrections")
        return self.append(
            EventType.MANUAL_CORRECTION,
            {
                "target_event_id": int(target_event_id),
                "target_type": target.type,
                "patch": dict(patch or {}),
                "void": bool(void),
                "note": note,
            },
            session_id=target.session_id,
            item_id=target.item_id,
        )

    def by_id(self, event_id: int) -> Event | None:
        row = self.conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
        return Event.from_row(row) if row else None

    def raw(self, *, since_id: int = 0) -> Iterator[Event]:
        """Every event as written, corrections included, in id order."""
        cur = self.conn.execute("SELECT * FROM events WHERE id > ? ORDER BY id", (since_id,))
        for row in cur:
            yield Event.from_row(row)

    def last_id(self) -> int:
        row = self.conn.execute("SELECT COALESCE(MAX(id), 0) AS n FROM events").fetchone()
        return int(row["n"])

    def has_corrections(self) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM events WHERE type = ? LIMIT 1", (EventType.MANUAL_CORRECTION,)
        ).fetchone()
        return row is not None

    def corrections(self) -> tuple[dict[int, dict[str, Any]], set[int]]:
        """Collapse every correction into (patches by target, voided targets)."""
        patches: dict[int, dict[str, Any]] = {}
        voided: set[int] = set()
        cur = self.conn.execute(
            "SELECT payload FROM events WHERE type = ? ORDER BY id",
            (EventType.MANUAL_CORRECTION,),
        )
        for row in cur:
            payload = json.loads(row["payload"])
            target = int(payload.get("target_event_id", -1))
            if target < 0:
                continue
            if payload.get("void"):
                voided.add(target)
                patches.pop(target, None)
                continue
            voided.discard(target)
            patches.setdefault(target, {}).update(payload.get("patch") or {})
        return patches, voided

    def effective(self, *, since_id: int = 0) -> Iterator[Event]:
        """Events with corrections applied and voided ones dropped.

        This is what projections replay.  ``MANUAL_CORRECTION`` rows are never
        yielded: they have no projection of their own, they only rewrite others.
        """
        patches, voided = self.corrections() if self.has_corrections() else ({}, set())
        for event in self.raw(since_id=since_id):
            if event.type == EventType.MANUAL_CORRECTION or event.id in voided:
                continue
            patch = patches.get(event.id)
            yield event.with_payload({**event.payload, **patch}) if patch else event

    def count(self, type: EventType | str | None = None) -> int:
        if type is None:
            row = self.conn.execute("SELECT COUNT(*) AS n FROM events").fetchone()
        else:
            row = self.conn.execute(
                "SELECT COUNT(*) AS n FROM events WHERE type = ?", (str(type),)
            ).fetchone()
        return int(row["n"])


def new_session_id() -> str:
    return new_id()

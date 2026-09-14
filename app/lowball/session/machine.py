"""The negotiation state machine (Part 8).

A lowball is a session, not an event.  One session covers one item and holds an
ordered chain of offers:

    session
      offer 15%   -> rejected
      offer 11%   -> countered at 12.5%
      offer 12.5% -> confirmed

Logging only the accepted offer would make every observed acceptance rate 100%
and the acceptance model worthless.  The rejections are the more valuable data,
so this machine is built so that recording them is the path of least
resistance: clicking a different rung while an offer is pending logs the
pending one as rejected on the way past, which is how a negotiation chain gets
recorded without anyone having to remember to record it.

    IDLE
      | user clicks a rung
      v
    OFFER_PENDING(pct, coins)
      |  confirm  -> CONFIRMED at the offered price
      |  reject   -> back to IDLE, the offer logged as rejected
      |  counter  -> the customer named a price
      |  bought   -> CONFIRMED at a user-entered price
      v
    CONFIRMED  -> the item enters the ledger as ACQUIRED

A session dismissed with no confirmation is ABANDONED, which is deliberately
not the same as REJECTED: the customer walked away without answering, and that
says something different about the offer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from ..ids import new_id
from ..ledger import Ledger
from ..parsing.signature import ItemSignature


class SessionState(StrEnum):
    IDLE = "IDLE"
    OFFER_PENDING = "OFFER_PENDING"
    CONFIRMED = "CONFIRMED"
    ABANDONED = "ABANDONED"


@dataclass
class PendingOffer:
    offer_id: str
    pct: float
    coins: int
    est_value: int
    is_exploration: bool = False
    rules_fired: list[dict[str, Any]] = field(default_factory=list)


class SessionError(RuntimeError):
    pass


class NegotiationSession:
    """One customer, one item, a chain of offers."""

    def __init__(
        self,
        ledger: Ledger,
        sig: ItemSignature,
        *,
        counterparty: str | None = None,
        session_id: str | None = None,
    ) -> None:
        self.ledger = ledger
        self.sig = sig
        self.counterparty = counterparty
        self.state = SessionState.IDLE
        self.pending: PendingOffer | None = None
        self.item_id: str | None = None
        self.settled_price: int | None = None
        self.session_id = ledger.start_session(
            tag=sig.tag,
            signature=sig.as_dict(),
            display_name=sig.display_name,
            rarity=sig.rarity,
            uid=sig.uid,
            counterparty=counterparty,
            session_id=session_id,
        )

    # ---- transitions ---------------------------------------------------

    def offer(
        self,
        pct: float,
        coins: int,
        *,
        est_value: int,
        confidence: float | None = None,
        is_exploration: bool = False,
        rules_fired: list[Any] | None = None,
    ) -> PendingOffer:
        """Make an offer.

        If one is already pending, it is logged as rejected first.  That is
        what makes a negotiation chain record itself: the user clicks a lower
        rung because the customer said no, and the no is captured by the act of
        clicking rather than by a separate step nobody would take.
        """
        if self.state is SessionState.CONFIRMED:
            raise SessionError("this session is already confirmed")
        if self.pending is not None:
            self.reject()

        offer_id = new_id()
        self.ledger.record_offer(
            session_id=self.session_id,
            tag=self.sig.tag,
            offer_pct=pct,
            offer_coins=coins,
            est_value=est_value,
            confidence=confidence,
            signature=self.sig.as_dict(),
            counterparty=self.counterparty,
            is_exploration=is_exploration,
            rules_fired=rules_fired or [],
            offer_id=offer_id,
        )
        self.pending = PendingOffer(
            offer_id=offer_id,
            pct=pct,
            coins=coins,
            est_value=est_value,
            is_exploration=is_exploration,
            rules_fired=[
                r if isinstance(r, dict) else {"name": str(r)} for r in (rules_fired or [])
            ],
        )
        self.state = SessionState.OFFER_PENDING
        return self.pending

    def reject(self) -> None:
        """The customer said no.  Back to IDLE with the offer logged."""
        if self.pending is None:
            return
        self.ledger.reject_offer(self.pending.offer_id, session_id=self.session_id)
        self.pending = None
        if self.state is SessionState.OFFER_PENDING:
            self.state = SessionState.IDLE

    def counter(self, price: int) -> None:
        """The customer named their own number."""
        if self.pending is None:
            raise SessionError("no offer is pending to counter")
        self.ledger.counter_offer(
            self.pending.offer_id, int(price), session_id=self.session_id
        )
        self.pending = None
        self.state = SessionState.IDLE

    def confirm(
        self,
        *,
        price: int | None = None,
        est_value: int | None = None,
        category: str | None = None,
    ) -> str:
        """The deal happened.  The item enters the ledger as acquired.

        ``price`` covers a settlement that did not land on a ladder rung --
        a counter accepted, or a number arrived at verbally.
        """
        if self.pending is None and price is None:
            raise SessionError("nothing to confirm: no offer pending and no price given")
        settled = int(price if price is not None else self.pending.coins)
        offer_id = self.pending.offer_id if self.pending else None
        estimate = est_value if est_value is not None else (
            self.pending.est_value if self.pending else None
        )

        self.item_id = self.ledger.acquire_item(
            tag=self.sig.tag,
            cost_basis=settled,
            session_id=self.session_id,
            offer_id=offer_id,
            uid=self.sig.uid,
            display_name=self.sig.display_name,
            rarity=self.sig.rarity,
            category=category,
            signature=self.sig.as_dict(),
            est_value=estimate,
            counterparty=self.counterparty,
        )
        self.settled_price = settled
        self.pending = None
        self.state = SessionState.CONFIRMED
        return self.item_id

    def abandon(self) -> None:
        """The customer left without answering.

        Distinct from a rejection on purpose: a walk-away carries different
        information about the offer, and treating it as a no would bias the
        acceptance curve downward.
        """
        if self.state is SessionState.CONFIRMED:
            return
        self.ledger.abandon_session(self.session_id)
        self.pending = None
        self.state = SessionState.ABANDONED

    # ---- reading -------------------------------------------------------

    @property
    def offers(self) -> list[Any]:
        return self.ledger.offers_in_session(self.session_id)

    @property
    def chain(self) -> list[tuple[float, int, str]]:
        """The negotiation as (pct, coins, outcome), in the order it happened."""
        return [(o["offer_pct"], o["offer_coins"], o["outcome"]) for o in self.offers]

    @property
    def is_open(self) -> bool:
        return self.state in {SessionState.IDLE, SessionState.OFFER_PENDING}


class SessionStore:
    """The sessions currently on screen, keyed by the trade they came from."""

    def __init__(self, ledger: Ledger) -> None:
        self.ledger = ledger
        self._sessions: dict[str, NegotiationSession] = {}

    def start(
        self, key: str, sig: ItemSignature, *, counterparty: str | None = None
    ) -> NegotiationSession:
        existing = self._sessions.get(key)
        if existing is not None and existing.is_open:
            return existing
        session = NegotiationSession(self.ledger, sig, counterparty=counterparty)
        self._sessions[key] = session
        return session

    def get(self, key: str) -> NegotiationSession | None:
        return self._sessions.get(key)

    def abandon_open(self) -> int:
        """Close out everything still open, e.g. when a trade screen closes."""
        closed = 0
        for session in self._sessions.values():
            if session.is_open and session.offers:
                session.abandon()
                closed += 1
        return closed

    def clear(self) -> None:
        self._sessions.clear()

    def __len__(self) -> int:
        return len(self._sessions)

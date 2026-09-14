"""The negotiation state machine (Part 8).

The point of these tests is that rejections get recorded. A tool that only
logs accepted offers reports a 100% acceptance rate forever, and the offer
model built on top of it is worthless.
"""

from __future__ import annotations

import pytest

from lowball.ledger import Ledger
from lowball.parsing.signature import ItemSignature
from lowball.session import NegotiationSession, SessionState, SessionStore
from lowball.session.machine import SessionError

HYPERION = ItemSignature(tag="HYPERION", rarity="LEGENDARY", uid="a1b2c3d4e5f6")
ESTIMATE = 847_200_000


@pytest.fixture
def session(ledger: Ledger) -> NegotiationSession:
    return NegotiationSession(ledger, HYPERION, counterparty="Notch")


def test_a_new_session_starts_idle(session: NegotiationSession) -> None:
    assert session.state is SessionState.IDLE
    assert session.pending is None
    assert session.ledger.session(session.session_id)["state"] == "ACTIVE"


def test_clicking_a_rung_opens_a_pending_offer(session: NegotiationSession) -> None:
    pending = session.offer(0.10, 762_500_000, est_value=ESTIMATE)
    assert session.state is SessionState.OFFER_PENDING
    assert session.pending is pending
    assert session.ledger.offer(pending.offer_id)["outcome"] == "PENDING"


def test_clicking_another_rung_records_the_first_as_rejected(
    session: NegotiationSession,
) -> None:
    """The mechanism that makes a negotiation chain record itself."""
    first = session.offer(0.15, 720_100_000, est_value=ESTIMATE)
    second = session.offer(0.11, 754_000_000, est_value=ESTIMATE)

    assert session.ledger.offer(first.offer_id)["outcome"] == "REJECTED"
    assert session.ledger.offer(second.offer_id)["outcome"] == "PENDING"
    assert session.state is SessionState.OFFER_PENDING


def test_a_full_negotiation_chain_is_recorded_in_order(
    session: NegotiationSession,
) -> None:
    session.offer(0.15, 720_100_000, est_value=ESTIMATE)
    session.offer(0.11, 754_000_000, est_value=ESTIMATE)
    session.counter(762_000_000)
    session.offer(0.10, 762_500_000, est_value=ESTIMATE)
    session.confirm(price=762_000_000)

    assert session.chain == [
        (0.15, 720_100_000, "REJECTED"),
        (0.11, 754_000_000, "COUNTERED"),
        (0.10, 762_500_000, "CONFIRMED"),
    ]
    assert session.state is SessionState.CONFIRMED


def test_confirming_settles_at_the_price_actually_paid(
    session: NegotiationSession,
) -> None:
    session.offer(0.10, 762_500_000, est_value=ESTIMATE)
    item_id = session.confirm(price=770_000_000)
    item = session.ledger.item(item_id)
    assert item["cost_basis"] == 770_000_000
    assert item["state"] == "HELD"
    assert item["uid"] == "a1b2c3d4e5f6"
    assert item["counterparty"] == "Notch"


def test_confirming_without_a_price_uses_the_offer(session: NegotiationSession) -> None:
    session.offer(0.10, 762_500_000, est_value=ESTIMATE)
    item_id = session.confirm()
    assert session.ledger.item(item_id)["cost_basis"] == 762_500_000


def test_a_counter_records_the_price_the_customer_named(
    session: NegotiationSession,
) -> None:
    pending = session.offer(0.11, 754_000_000, est_value=ESTIMATE)
    session.counter(762_000_000)
    row = session.ledger.offer(pending.offer_id)
    assert row["outcome"] == "COUNTERED"
    assert row["counter_price"] == 762_000_000
    assert session.state is SessionState.IDLE


def test_a_walk_away_is_abandoned_not_rejected(session: NegotiationSession) -> None:
    pending = session.offer(0.15, 720_100_000, est_value=ESTIMATE)
    session.abandon()
    assert session.ledger.offer(pending.offer_id)["outcome"] == "ABANDONED"
    assert session.state is SessionState.ABANDONED
    assert session.ledger.session(session.session_id)["state"] == "ABANDONED"


def test_a_confirmed_session_cannot_take_another_offer(
    session: NegotiationSession,
) -> None:
    session.offer(0.10, 762_500_000, est_value=ESTIMATE)
    session.confirm()
    with pytest.raises(SessionError, match="already confirmed"):
        session.offer(0.12, 745_000_000, est_value=ESTIMATE)


def test_abandoning_a_confirmed_session_is_a_no_op(session: NegotiationSession) -> None:
    session.offer(0.10, 762_500_000, est_value=ESTIMATE)
    session.confirm()
    session.abandon()
    assert session.state is SessionState.CONFIRMED


def test_confirming_with_nothing_pending_needs_a_price(
    session: NegotiationSession,
) -> None:
    with pytest.raises(SessionError, match="no offer pending"):
        session.confirm()


def test_countering_with_nothing_pending_is_refused(
    session: NegotiationSession,
) -> None:
    with pytest.raises(SessionError, match="no offer is pending"):
        session.counter(1)


def test_exploration_and_rules_are_carried_onto_the_offer(
    session: NegotiationSession,
) -> None:
    pending = session.offer(
        0.13,
        737_000_000,
        est_value=ESTIMATE,
        is_exploration=True,
        rules_fired=[{"name": "Skins are illiquid", "detail": "offer at -25%"}],
    )
    row = session.ledger.offer(pending.offer_id)
    assert row["is_exploration"] == 1
    assert session.ledger.rules_fired(pending.offer_id) == ["Skins are illiquid"]


def test_the_store_reuses_an_open_session_for_the_same_slot(ledger: Ledger) -> None:
    store = SessionStore(ledger)
    first = store.start("slot-0", HYPERION)
    again = store.start("slot-0", HYPERION)
    assert again is first


def test_the_store_starts_a_fresh_session_once_one_is_closed(ledger: Ledger) -> None:
    store = SessionStore(ledger)
    first = store.start("slot-0", HYPERION)
    first.offer(0.1, 1, est_value=1)
    first.confirm()
    second = store.start("slot-0", HYPERION)
    assert second is not first


def test_closing_a_trade_abandons_what_is_still_open(ledger: Ledger) -> None:
    store = SessionStore(ledger)
    live = store.start("slot-0", HYPERION)
    live.offer(0.15, 720_100_000, est_value=ESTIMATE)
    untouched = store.start("slot-1", ItemSignature(tag="TERMINATOR"))

    assert store.abandon_open() == 1
    assert live.state is SessionState.ABANDONED
    # A session where nothing was ever offered is not an abandoned negotiation.
    assert untouched.state is SessionState.IDLE

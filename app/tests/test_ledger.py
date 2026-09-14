"""The event log and its projections (Part 15 step 1).

These tests exist because everything else in the app reads from this layer.
They assert three things: that a lifecycle projects correctly, that a full
replay reproduces identical state, and that a correction rewrites derived
state without touching history.
"""

from __future__ import annotations

import pytest
from conftest import dump_projections

from lowball.ledger import EventType, Ledger


def test_a_full_lifecycle_projects_correctly(ledger: Ledger) -> None:
    session_id = ledger.start_session(tag="HYPERION", counterparty="Notch", rarity="LEGENDARY")
    first = ledger.record_offer(
        session_id=session_id,
        tag="HYPERION",
        offer_pct=0.15,
        offer_coins=720_100_000,
        est_value=847_200_000,
        confidence=0.8,
    )
    ledger.reject_offer(first)
    second = ledger.record_offer(
        session_id=session_id,
        tag="HYPERION",
        offer_pct=0.10,
        offer_coins=762_500_000,
        est_value=847_200_000,
        confidence=0.8,
    )
    item_id = ledger.acquire_item(
        tag="HYPERION",
        cost_basis=762_500_000,
        session_id=session_id,
        offer_id=second,
        uid="a1b2c3d4e5f6",
        est_value=847_200_000,
    )

    offers = ledger.offers_in_session(session_id)
    assert [o["seq"] for o in offers] == [1, 2]
    assert offers[0]["outcome"] == "REJECTED"
    assert offers[1]["outcome"] == "CONFIRMED"
    assert offers[1]["settled_price"] == 762_500_000

    session = ledger.session(session_id)
    assert session["state"] == "CONFIRMED"
    assert session["item_id"] == item_id
    assert session["offer_count"] == 2

    item = ledger.item(item_id)
    assert item["state"] == "HELD"
    assert item["cost_basis"] == 762_500_000
    assert item["uid"] == "a1b2c3d4e5f6"


def test_rejected_offers_are_kept_because_they_are_the_useful_data(ledger: Ledger) -> None:
    session_id = ledger.start_session(tag="NECRON_HANDLE")
    for pct, coins in ((0.15, 100), (0.12, 120), (0.09, 140)):
        offer = ledger.record_offer(
            session_id=session_id,
            tag="NECRON_HANDLE",
            offer_pct=pct,
            offer_coins=coins,
            est_value=200,
        )
        ledger.reject_offer(offer)
    ledger.abandon_session(session_id)

    outcomes = [o["outcome"] for o in ledger.offers_in_session(session_id)]
    assert outcomes == ["REJECTED", "REJECTED", "REJECTED"]
    assert ledger.session(session_id)["state"] == "ABANDONED"


def test_a_pending_offer_at_walk_away_is_abandoned_not_rejected(ledger: Ledger) -> None:
    session_id = ledger.start_session(tag="TERMINATOR")
    offer = ledger.record_offer(
        session_id=session_id, tag="TERMINATOR", offer_pct=0.1, offer_coins=90, est_value=100
    )
    ledger.abandon_session(session_id)
    assert ledger.offer(offer)["outcome"] == "ABANDONED"


def test_countering_records_the_counter_price(ledger: Ledger) -> None:
    session_id = ledger.start_session(tag="HYPERION")
    offer = ledger.record_offer(
        session_id=session_id, tag="HYPERION", offer_pct=0.11, offer_coins=110, est_value=124
    )
    ledger.counter_offer(offer, 125)
    row = ledger.offer(offer)
    assert row["outcome"] == "COUNTERED"
    assert row["counter_price"] == 125


def _bought_and_sold(ledger: Ledger) -> str:
    """A Hyperion bought at 700M and sold on the auction house at 850M."""
    item_id = ledger.acquire_item(tag="HYPERION", cost_basis=700_000_000)
    ledger.sell_item(item_id=item_id, price=850_000_000)
    return item_id


def test_a_taxed_sale_charges_the_claim_tax(ledger: Ledger) -> None:
    item_id = _bought_and_sold(ledger)
    exit_row = ledger.exit_for(item_id)
    assert exit_row["route"] == "SOLD"
    assert exit_row["gross"] == 850_000_000
    # 2.5% claim tax on a sale over 100M.
    assert exit_row["fees_total"] == 21_250_000
    assert exit_row["net"] == 828_750_000
    assert exit_row["profit"] == 128_750_000
    assert ledger.item(item_id)["state"] == "SOLD"


def test_an_untaxed_sale_keeps_the_whole_price(ledger: Ledger) -> None:
    item_id = ledger.acquire_item(tag="HYPERION", cost_basis=700_000_000)
    ledger.sell_item(
        item_id=item_id, price=690_000_000, taxed=False, counterparty="OtherLowballer"
    )

    exit_row = ledger.exit_for(item_id)
    assert exit_row["route"] == "SOLD"
    assert exit_row["fees_total"] == 0
    assert exit_row["net"] == 690_000_000
    assert exit_row["profit"] == -10_000_000
    assert exit_row["counterparty"] == "OtherLowballer"


def test_changing_an_outcome_replaces_it_rather_than_adding_one(ledger: Ledger) -> None:
    """Marking something sold twice is a correction, not two sales."""
    item_id = ledger.acquire_item(tag="HYPERION", cost_basis=700_000_000)
    ledger.sell_item(item_id=item_id, price=850_000_000)
    ledger.sell_item(item_id=item_id, price=900_000_000, taxed=False)

    rows = ledger.query("SELECT * FROM exits WHERE item_id = ?", (item_id,))
    assert len(rows) == 1
    assert rows[0]["gross"] == 900_000_000
    assert rows[0]["fees_total"] == 0


def test_keeping_something_already_sold_replaces_the_sale(ledger: Ledger) -> None:
    item_id = ledger.acquire_item(tag="HYPERION", cost_basis=700_000_000)
    ledger.sell_item(item_id=item_id, price=850_000_000)
    ledger.keep_item(item_id=item_id, market_value=860_000_000)

    assert ledger.item(item_id)["state"] == "KEPT"
    assert ledger.exit_for(item_id)["route"] == "KEPT"
    assert len(ledger.query("SELECT * FROM exits WHERE item_id = ?", (item_id,))) == 1


def test_unwinding_an_outcome_returns_the_item_to_stock(ledger: Ledger) -> None:
    item_id = ledger.acquire_item(tag="HYPERION", cost_basis=700_000_000)
    ledger.sell_item(item_id=item_id, price=850_000_000)
    ledger.unwind_exit(item_id)

    row = ledger.item(item_id)
    assert row["state"] == "HELD"
    assert row["exit_ts"] is None
    assert ledger.exit_for(item_id) is None


def test_a_legacy_auction_house_sale_still_projects(ledger: Ledger) -> None:
    """Older databases carry ITEM_SOLD_AH; the log is never rewritten."""
    item_id = ledger.acquire_item(tag="HYPERION", cost_basis=700_000_000)
    ledger.append(
        EventType.ITEM_SOLD_AH,
        {"item_id": item_id, "sale_price": 850_000_000, "claim_tax": 21_250_000},
    )
    exit_row = ledger.exit_for(item_id)
    assert exit_row["route"] == "SOLD"
    assert exit_row["gross"] == 850_000_000
    assert exit_row["fees_total"] == 21_250_000


def test_kept_items_book_as_a_withdrawal_at_market_value(ledger: Ledger) -> None:
    item_id = ledger.acquire_item(tag="HYPERION", cost_basis=700_000_000)
    ledger.keep_item(item_id=item_id, market_value=860_000_000, note="using it")
    exit_row = ledger.exit_for(item_id)
    assert exit_row["route"] == "KEPT"
    assert exit_row["gross"] == 860_000_000
    assert exit_row["profit"] == 160_000_000
    assert ledger.item(item_id)["state"] == "KEPT"


def test_keeping_falls_back_to_the_last_recorded_valuation(ledger: Ledger) -> None:
    item_id = ledger.acquire_item(tag="HYPERION", cost_basis=700_000_000)
    ledger.record_valuation(tag="HYPERION", item_id=item_id, estimate=830_000_000)
    ledger.keep_item(item_id=item_id)
    assert ledger.exit_for(item_id)["gross"] == 830_000_000


def test_clearing_history_empties_the_log_and_the_projections(ledger: Ledger) -> None:
    _bought_and_sold(ledger)
    removed = ledger.clear_history()

    assert removed > 0
    assert ledger.log.count() == 0
    assert ledger.query("SELECT * FROM items") == []
    assert ledger.query("SELECT * FROM exits") == []
    assert ledger.projector.watermark() == 0
    # And the ledger is still usable afterwards.
    again = ledger.acquire_item(tag="TERMINATOR", cost_basis=1)
    assert ledger.item(again)["state"] == "HELD"


def _busy_ledger(ledger: Ledger) -> str:
    """A session, a purchase, a sale, and a second item kept."""
    session_id = ledger.start_session(tag="HYPERION", counterparty="Notch")
    offer = ledger.record_offer(
        session_id=session_id,
        tag="HYPERION",
        offer_pct=0.12,
        offer_coins=700_000_000,
        est_value=800_000_000,
        confidence=0.75,
        rules_fired=["Skins are illiquid"],
    )
    item_id = ledger.acquire_item(
        tag="HYPERION", cost_basis=700_000_000, session_id=session_id, offer_id=offer
    )
    ledger.sell_item(item_id=item_id, price=850_000_000)

    kept = ledger.acquire_item(tag="TERMINATOR", cost_basis=180_000_000)
    ledger.record_valuation(tag="TERMINATOR", item_id=kept, estimate=204_000_000)
    ledger.keep_item(item_id=kept)
    return item_id


def test_a_rebuild_reproduces_identical_state(ledger: Ledger) -> None:
    _busy_ledger(ledger)
    before = dump_projections(ledger)
    ledger.rebuild()
    assert dump_projections(ledger) == before


def test_rebuilding_twice_is_stable(ledger: Ledger) -> None:
    _busy_ledger(ledger)
    ledger.rebuild()
    once = dump_projections(ledger)
    ledger.rebuild()
    assert dump_projections(ledger) == once


def test_the_watermark_tracks_the_log(ledger: Ledger) -> None:
    _busy_ledger(ledger)
    assert ledger.projector.watermark() == ledger.log.last_id()


def test_rule_firings_survive_a_rebuild(ledger: Ledger) -> None:
    _busy_ledger(ledger)
    ledger.rebuild()
    offer_id = ledger.query("SELECT offer_id FROM offers")[0]["offer_id"]
    assert ledger.rules_fired(offer_id) == ["Skins are illiquid"]


def test_a_correction_rewrites_derived_state_without_editing_history(ledger: Ledger) -> None:
    item_id = ledger.acquire_item(tag="HYPERION", cost_basis=700_000_000)
    ledger.sell_item(item_id=item_id, price=850_000_000)
    assert ledger.exit_for(item_id)["profit"] == 128_750_000

    acquired = next(
        e for e in ledger.log.raw() if e.type == EventType.ITEM_ACQUIRED
    )
    events_before = ledger.log.count()
    ledger.correct(acquired.id, patch={"cost_basis": 750_000_000}, note="typo at the trade")

    # The original event is still there, unedited, alongside the correction.
    assert ledger.log.by_id(acquired.id).payload["cost_basis"] == 700_000_000
    assert ledger.log.count() == events_before + 1
    # Derived state moved.
    assert ledger.item(item_id)["cost_basis"] == 750_000_000
    assert ledger.exit_for(item_id)["profit"] == 78_750_000


def test_the_last_correction_wins_field_by_field(ledger: Ledger) -> None:
    item_id = ledger.acquire_item(tag="HYPERION", cost_basis=700_000_000)
    acquired = next(e for e in ledger.log.raw() if e.type == EventType.ITEM_ACQUIRED)
    ledger.correct(acquired.id, patch={"cost_basis": 720_000_000, "rarity": "LEGENDARY"})
    ledger.correct(acquired.id, patch={"cost_basis": 730_000_000})
    row = ledger.item(item_id)
    assert row["cost_basis"] == 730_000_000
    assert row["rarity"] == "LEGENDARY"


def test_voiding_removes_an_event_from_the_replay(ledger: Ledger) -> None:
    item_id = ledger.acquire_item(tag="HYPERION", cost_basis=700_000_000)
    ledger.sell_item(item_id=item_id, price=850_000_000)
    sold = next(e for e in ledger.log.raw() if e.type == EventType.ITEM_SOLD)
    ledger.correct(sold.id, void=True, note="sold the wrong item")
    assert ledger.exit_for(item_id) is None
    assert ledger.item(item_id)["state"] == "HELD"
    assert ledger.log.by_id(sold.id).payload["price"] == 850_000_000


def test_a_correction_cannot_target_another_correction(ledger: Ledger) -> None:
    item_id = ledger.acquire_item(tag="HYPERION", cost_basis=1)
    acquired = next(e for e in ledger.log.raw() if e.type == EventType.ITEM_ACQUIRED)
    correction = ledger.correct(acquired.id, patch={"cost_basis": 2})
    with pytest.raises(ValueError, match="cannot target"):
        ledger.correct(correction.id, patch={"cost_basis": 3})
    assert ledger.item(item_id)["cost_basis"] == 2


def test_an_empty_correction_is_refused(ledger: Ledger) -> None:
    ledger.acquire_item(tag="HYPERION", cost_basis=1)
    acquired = next(e for e in ledger.log.raw() if e.type == EventType.ITEM_ACQUIRED)
    with pytest.raises(ValueError, match="patch or void"):
        ledger.correct(acquired.id)


def test_history_for_one_item_reads_back_in_order(ledger: Ledger) -> None:
    item_id = _busy_ledger(ledger)
    types = [e.type for e in ledger.history(item_id)]
    assert types == [
        EventType.ITEM_ACQUIRED,
        EventType.ITEM_SOLD,
    ]


def test_a_database_from_an_older_build_rebuilds_its_projections() -> None:
    """A derived table that gained a column cannot be caught up incrementally.

    The rows already in it were written by the old schema, so the first query
    against the new column fails. A version mismatch has to force a replay.
    """
    from lowball.ledger.projections import PROJECTION_VERSION, VERSION_NAME, Projector

    store = Ledger()
    try:
        item_id = store.acquire_item(tag="HYPERION", cost_basis=700_000_000)
        store.sell_item(item_id=item_id, price=850_000_000)

        # Pretend the tables were built by an older projection schema, and
        # drop a column it did not have.
        store.conn.execute(
            "UPDATE projection_state SET last_event_id = ? WHERE name = ?",
            (PROJECTION_VERSION - 1, VERSION_NAME),
        )
        store.conn.execute("ALTER TABLE exits DROP COLUMN taxed")
        assert not Projector(store.conn).is_current()

        reopened = Ledger(store.conn)
        assert reopened.projector.is_current()
        assert reopened.exit_for(item_id)["taxed"] == 1
    finally:
        store.close()


def test_a_current_database_is_not_rebuilt_unnecessarily() -> None:
    """A rebuild on every start would replay a season of trading each time."""
    store = Ledger()
    try:
        store.acquire_item(tag="HYPERION", cost_basis=1)
        watermark = store.projector.watermark()
        reopened = Ledger(store.conn)
        assert reopened.projector.watermark() == watermark
        assert reopened.projector.is_current()
    finally:
        store.close()

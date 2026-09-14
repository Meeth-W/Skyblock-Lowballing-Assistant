"""Wiring: uplink to valuation to session to ledger.

The one place that knows the order things happen in.  A trade snapshot arrives
on the asyncio thread, each item is normalised by the rules, valued, laddered
and recommended, and the result crosses to the GUI thread as a signal.

**Threading.**  The ledger connection belongs to the GUI thread and takes every
write.  The asyncio side gets its own connection to the same file for the API
cache and for the read-only queries the valuation needs.  WAL makes that safe;
sharing one connection across both would not be.
"""

from __future__ import annotations

import contextlib
import logging
import sqlite3
from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import QObject, Signal

from .api.bazaar import fetch_prices
from .api.cache import ApiCache
from .api.coflnet import CoflnetClient
from .config import Settings
from .ledger import Ledger, connect
from .money import format_coins
from .parsing.categories import category_of
from .parsing.signature import ItemSignature
from .pricing.acceptance import AcceptanceCurve, fit_curve
from .pricing.offer import OfferLadder, Rung, build_ladder, recommend
from .pricing.valuation import Valuation, ValuationEngine
from .pricing.values import ValueTable, load_values, save_values
from .rules import RuleEngine, load_rules
from .session import SessionStore
from .ui.workers import AsyncBridge, report_failure
from .uplink import (
    Hello,
    ItemsSelected,
    SelectionCleared,
    SelectionView,
    TradeCompleted,
    UplinkServer,
    UplinkStatus,
)
from .uplink.trade import SettledTrade

log = logging.getLogger(__name__)


@dataclass
class PricedItem:
    """One item on the table, with everything computed about it."""

    index: int
    sig: ItemSignature
    duplicates: int
    valuation: Valuation | None = None
    ladder: OfferLadder | None = None
    curve: AcceptanceCurve | None = None
    #: What the rules decided, kept so the ladder can be rebuilt when the
    #: user overrides the estimate without re-running the whole search.
    decision: Any | None = None

    @property
    def total_estimate(self) -> int:
        if self.valuation is None:
            return 0
        return self.valuation.estimate * max(1, self.duplicates)


class AppController(QObject):
    selection_changed = Signal(list)
    item_pending = Signal(int, object)
    item_valued = Signal(int, object, object)
    totals_changed = Signal(object, object)
    uplink_changed = Signal(object)
    ledger_changed = Signal()
    settled_trade = Signal(object, object)
    status_message = Signal(str)
    #: A bazaar refresh finished: either {product: price} or the exception.
    bazaar_prices = Signal(object)

    def __init__(self, settings: Settings, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.bridge = AsyncBridge(self)

        settings.data_dir.mkdir(parents=True, exist_ok=True)
        self.ledger = Ledger.open(settings.db_path)
        self.sessions = SessionStore(self.ledger)
        self.values: ValueTable = load_values(settings.values_file)
        self.rules = RuleEngine(self._load_rules(), values=self.values)
        if not settings.values_file.exists():
            # Write the defaults out on first run so there is something to edit.
            save_values(self.values, settings.values_file)

        # A second connection for the asyncio thread. Same file, WAL, so the
        # prefetch and the valuation can read while the GUI writes.
        self.async_conn: sqlite3.Connection = connect(settings.db_path)
        self.cache = ApiCache(self.async_conn)
        self.coflnet = CoflnetClient(self.cache)
        self.engine = ValuationEngine(
            self.coflnet,
            conn=self.async_conn,
            min_comparables=settings.min_comparables,
            values=self.values,
        )

        self.uplink = UplinkServer(
            port=settings.uplink_port,
            on_message=self._on_uplink_message,
            on_status=self.uplink_changed.emit,
        )

        self.items: list[PricedItem] = []
        self.selection: SelectionView | None = None
        self._selection_generation = 0
        # Who the last completed trade was with. The selection itself carries
        # no counterparty -- items can be picked out of a chest with nobody
        # present -- so the name only becomes known when the trade lands.
        self._last_settled: SettledTrade | None = None

    def _load_rules(self) -> list:
        path = self.settings.rules_file
        try:
            return load_rules(path if path.exists() else None)
        except Exception as exc:  # noqa: BLE001 - a bad rule file must not block start-up
            log.warning("could not load rules from %s: %s", path, exc)
            return []

    def reload_rules(self) -> int:
        self.rules = RuleEngine(self._load_rules(), values=self.values)
        return len(self.rules)

    def reload_values(self) -> ValueTable:
        """Re-read the modifier prices, and point everything at the new ones."""
        self.values = load_values(self.settings.values_file)
        self.engine.search.values = self.values
        # Rules ask what a modifier is worth, so they read the same table.
        self.rules.values = self.values
        return self.values

    def save_values(self, table: ValueTable) -> ValueTable:
        """Write an edited pricing table and apply it without a restart."""
        save_values(table, self.settings.values_file)
        return self.reload_values()

    def fetch_bazaar_prices(self) -> None:
        """Ask the bazaar for the whole market, once, off the GUI thread.

        The result goes out on :attr:`bazaar_prices` rather than being applied
        here: the pricing editor may have unsaved changes on screen, and a
        fetch should fill those in rather than throw them away.
        """
        if not self.bridge.is_running:
            # Checked before the coroutine is built, or it is left unawaited.
            # Reported the same way a failed request is, so the button never
            # ends up disabled with nothing said.
            self.bazaar_prices.emit(RuntimeError("the app is still starting up"))
            return
        future = self.bridge.submit(fetch_prices())

        def _done(done) -> None:
            if done.cancelled():
                return
            error = done.exception()
            # Emitted from the asyncio thread; Qt queues it to the GUI one.
            self.bazaar_prices.emit(error if error is not None else done.result())

        future.add_done_callback(_done)

    # ---- lifecycle ------------------------------------------------------

    def start(self) -> None:
        self.bridge.start()
        report_failure(self.bridge.submit(self.uplink.serve_forever()), "uplink server")
        self.status_message.emit(
            f"Listening for the mod on ws://127.0.0.1:{self.settings.uplink_port}"
        )
        tags = self.settings.prefetch_tags
        if tags:
            report_failure(self.bridge.submit(self._prefetch(tags)), "hot set prefetch")

    def stop(self) -> None:
        self.uplink.stop()
        if self.bridge.is_running:
            # Shutting down must not raise; a failed close here would leave
            # the window up with no way to exit cleanly.
            with contextlib.suppress(Exception):
                self.bridge.submit(self.coflnet.aclose()).result(timeout=3)
        self.bridge.stop()
        self.async_conn.close()
        self.ledger.close()

    async def _prefetch(self, tags: list[str]) -> None:
        """Warm the cache before the first customer arrives.

        Serial and unhurried: this is background work, and it must never sit in
        front of a live trade in the rate limiter's queue.
        """
        for tag in tags:
            try:
                await self.coflnet.analysis(tag)
            except Exception:  # noqa: BLE001 - one cold tag is not a failure
                continue
        self.status_message.emit(f"Prefetched {len(tags)} common items")

    # ---- inbound from the mod -------------------------------------------

    def _on_uplink_message(self, message: Any) -> None:
        if isinstance(message, ItemsSelected):
            self._on_selection(SelectionView.from_message(message))
        elif isinstance(message, SelectionCleared):
            self._on_selection(SelectionView())
        elif isinstance(message, TradeCompleted):
            settled = SettledTrade.from_message(message)
            self._last_settled = settled
            # Work out which picked item it settles, when that is knowable.
            # When several items moved at once chat cannot say, and the UI
            # shows the total rather than guessing.
            self.settled_trade.emit(settled, settled.match_in(self.selection))
        elif isinstance(message, Hello):
            self.status_message.emit(
                f"{message.player_name or 'Player'} connected on {message.mc_version}"
            )

    def _on_selection(self, view: SelectionView) -> None:
        if view.failures:
            # Say so rather than quietly showing fewer items than were picked.
            slots = ", ".join(str(slot) for slot, _ in view.failures)
            reason = view.failures[0][1]
            self.status_message.emit(
                f"Could not read {len(view.failures)} picked item(s)"
                f" from slot {slots}: {reason}"
            )
        if not view.changed_from(self.selection):
            return
        self.selection = view
        self._selection_generation += 1
        generation = self._selection_generation

        self.items = [
            PricedItem(index=i, sig=item.sig, duplicates=item.duplicates)
            for i, item in enumerate(view.items)
        ]
        self.selection_changed.emit([(item.sig, item.duplicates) for item in self.items])
        self.totals_changed.emit(None, None)

        for item in self.items:
            self.item_pending.emit(item.index, item.sig)
            report_failure(
                self.bridge.submit(self._value_item(generation, item)),
                f"valuing {item.sig.tag}",
            )

    async def _value_item(self, generation: int, item: PricedItem) -> None:
        """Price one item, then build its ladder and recommendation.

        Normalisation runs before the valuation because it changes which
        comparables are even searched for.
        """
        normalised, normalisation_firings = self.rules.normalise(item.sig)
        valuation = await self.engine.value(normalised)

        if generation != self._selection_generation:
            # The selection changed while this was in flight. Throwing the
            # result away is correct: showing it would put a price against an
            # item that is no longer picked.
            return

        decision = self.rules.evaluate(normalised, {"estimate": valuation.estimate})
        valuation.rules_fired = normalisation_firings + decision.firings

        item.valuation = valuation
        item.decision = decision
        self._rebuild_ladder(item)

    def _rebuild_ladder(self, item: PricedItem) -> None:
        """Ladder, acceptance curve and recommendation for a priced item.

        Separate from the search because the user can overrule the estimate
        by hand, and when they do every percentage on the ladder has to move
        with it -- without spending another round of requests to find that
        out.
        """
        valuation = item.valuation
        decision = item.decision
        if valuation is None or decision is None:
            return
        sig = valuation.sig

        estimate = valuation.estimate
        if decision.max_coins is not None:
            estimate = min(estimate, decision.max_coins)

        analysis = valuation.analysis
        ladder = build_ladder(
            estimate,
            hold_hours=valuation.sell_time.hours,
            volatility=valuation.volatility,
            volatility_window_days=float(analysis.days) if analysis else 7.0,
            config=self.settings.offer_config(),
            rule_pct=decision.offer_pct,
            rule_name=decision.badge_for("offer_pct"),
        )
        curve = fit_curve(
            self.async_conn,
            tag=sig.tag,
            category=category_of(sig),
            bucket=_bucket_for(estimate),
        )
        recommend(ladder, curve, tag=sig.tag, config=self.settings.offer_config())
        if decision.excluded:
            ladder.warnings.insert(0, "Rule says never buy this")
        if valuation.manual_estimate is not None:
            ladder.warnings.append("Valued by hand, not by the market")

        item.ladder = ladder
        item.curve = curve
        self.item_valued.emit(item.index, valuation, ladder)
        self._emit_totals()

    def override_estimate(self, index: int, coins: int | None) -> None:
        """Replace the estimate with the user's own number, or restore ours.

        The computed figure is kept rather than overwritten, so the override
        can be undone and so the breakdown can still show what the market
        actually said.
        """
        if not (0 <= index < len(self.items)):
            return
        item = self.items[index]
        if item.valuation is None:
            return
        item.valuation.set_manual_estimate(coins)
        self._rebuild_ladder(item)
        if coins is None:
            self.status_message.emit(
                f"{item.sig.tag} back to the market estimate"
                f" of {format_coins(item.valuation.estimate)}"
            )
        else:
            self.status_message.emit(
                f"{item.sig.tag} valued by hand at {format_coins(coins)}"
            )

    def _emit_totals(self) -> None:
        priced = [i for i in self.items if i.valuation is not None]
        if not priced:
            self.totals_changed.emit(None, None)
            return
        total = sum(i.total_estimate for i in priced)
        offer = 0
        for item in priced:
            if item.ladder is not None and item.ladder.recommended is not None:
                offer += item.ladder.recommended.coins * max(1, item.duplicates)
            else:
                offer += item.total_estimate
        self.totals_changed.emit(total, offer)

    # ---- outbound from the UI -------------------------------------------

    def _session_for(self, index: int):
        item = self.items[index]
        return self.sessions.start(
            f"{self._selection_generation}:{index}",
            item.sig,
            counterparty=self._last_settled.counterparty if self._last_settled else None,
        )

    def make_offer(self, index: int, rung: Rung) -> None:
        if not (0 <= index < len(self.items)):
            return
        item = self.items[index]
        if item.valuation is None:
            return
        session = self._session_for(index)
        session.offer(
            rung.pct,
            rung.coins,
            est_value=item.valuation.estimate,
            confidence=item.valuation.confidence.score,
            is_exploration=bool(
                item.ladder
                and item.ladder.recommended
                and item.ladder.recommended.is_exploration
                and abs(item.ladder.recommended.pct - rung.pct) < 1e-9
            ),
            rules_fired=[f.as_dict() for f in item.valuation.rules_fired],
        )
        self.ledger_changed.emit()
        self.status_message.emit(f"Offered {rung.coins_label} at {rung.pct_label}")

    def reject_offer(self, index: int, rung: Rung) -> None:
        session = self.sessions.get(f"{self._selection_generation}:{index}")
        if session is None:
            return
        session.reject()
        self.ledger_changed.emit()
        self.status_message.emit(f"Logged {rung.pct_label} as rejected")

    def confirm_sale(self, index: int, rung: Rung, price: int) -> None:
        if not (0 <= index < len(self.items)):
            return
        item = self.items[index]
        session = self.sessions.get(f"{self._selection_generation}:{index}")
        if session is None or item.valuation is None:
            return
        # A session opened before the trade landed has no counterparty yet;
        # the settled trade is where that name comes from.
        if session.counterparty is None and self._last_settled is not None:
            session.counterparty = self._last_settled.counterparty
        item_id = session.confirm(
            price=price,
            est_value=item.valuation.estimate,
            category=category_of(item.sig),
        )
        # Record the valuation against the item so it can be marked to market
        # later and so the estimate at purchase stays comparable with what was
        # actually realised.
        payload = item.valuation.as_event_payload()
        payload["item_id"] = item_id
        self.ledger.record_valuation(**payload)
        self.ledger_changed.emit()
        self.status_message.emit(f"Bought {item.sig.tag} for {rung.coins_label}")

    def abandon_all(self) -> None:
        if self.sessions.abandon_open():
            self.ledger_changed.emit()

    def clear_history(self) -> int:
        """Erase every trade ever recorded.  The user has already confirmed."""
        removed = self.ledger.clear_history()
        # Open sessions point at events that no longer exist; keeping them
        # would write offers into a session the log has never heard of.
        self.sessions.clear()
        self.ledger_changed.emit()
        return removed

    @property
    def uplink_status(self) -> UplinkStatus:
        return self.uplink.status


def _bucket_for(coins: int) -> str:
    from .money import value_bucket

    return value_bucket(coins)

"""Synthetic trading history.

The acceptance model and most of the charts say nothing until weeks of real
data exist. Rather than build them blind, this generates a plausible season of
lowballing so the statistics tab and the acceptance curve can be developed and
looked at properly.

Offers are drawn from a known acceptance curve, so the fitted model has
something real to recover. Deliberately included: rejections, counters,
walk-aways, items still sitting in stock a fortnight later, a few sold at a
loss, and some kept for personal use. A demo where everything works is a demo
that hides every interesting case.
"""

from __future__ import annotations

import math
import random
from datetime import timedelta

from .config import Settings
from .ledger import Ledger
from .parsing.signature import ItemSignature
from .timeutil import to_iso, utcnow

#: The ground truth the demo offers are drawn from.
TRUE_INTERCEPT = 3.0
TRUE_SLOPE = -18.0

CATALOGUE: tuple[tuple[str, str, str, int, float], ...] = (
    # tag, display name, category, typical value, volatility
    ("HYPERION", "Hyperion", "Weapon", 850_000_000, 0.37),
    ("TERMINATOR", "Terminator", "Weapon", 420_000_000, 0.28),
    ("NECRON_HANDLE", "Necron's Handle", "Weapon", 780_000_000, 0.22),
    ("JUJU_SHORTBOW", "Juju Shortbow", "Weapon", 95_000_000, 0.31),
    ("POWER_WITHER_HELMET", "Necron's Helmet", "Armor", 145_000_000, 0.26),
    ("CRIMSON_CHESTPLATE", "Crimson Chestplate", "Armor", 210_000_000, 0.44),
    ("SHADOW_FURY", "Shadow Fury", "Weapon", 62_000_000, 0.19),
    ("PET", "Golden Dragon", "Pet", 640_000_000, 0.33),
    ("LIVID_DAGGER", "Livid Dagger", "Weapon", 38_000_000, 0.24),
    ("HEGEMONY_ARTIFACT", "Hegemony Artifact", "Accessory", 290_000_000, 0.18),
)

RARITIES = ("LEGENDARY", "MYTHIC", "EPIC", "LEGENDARY", "MYTHIC")


def _accepts(pct: float, rng: random.Random) -> bool:
    probability = 1.0 / (1.0 + math.exp(-(TRUE_INTERCEPT + TRUE_SLOPE * pct)))
    return rng.random() < probability


def seed_demo_data(
    settings: Settings, *, sessions: int = 180, seed: int = 4, days: int = 60
) -> int:
    """Fill the ledger with a season of trading. Returns the event count."""
    ledger = Ledger.open(settings.db_path)
    try:
        if ledger.log.count() > 0:
            return 0
        return _seed(ledger, sessions=sessions, seed=seed, days=days)
    finally:
        ledger.close()


def _seed(ledger: Ledger, *, sessions: int, seed: int, days: int) -> int:
    rng = random.Random(seed)
    now = utcnow()
    start = now - timedelta(days=days)
    customers = [f"Customer{i:02d}" for i in range(1, 26)]

    for index in range(sessions):
        # A quarter of sessions land in the last fortnight. Left to a uniform
        # spread, almost everything would have sold by now and the held
        # position, the ageing chart and the dead-capital figure would all
        # sit at zero -- which are exactly the parts worth looking at.
        if rng.random() < 0.25:
            opened = now - timedelta(days=rng.uniform(0.05, 14))
        else:
            opened = start + timedelta(seconds=rng.uniform(0, days * 86400 * 0.72))
        tag, name, category, typical, volatility = rng.choice(CATALOGUE)
        estimate = int(typical * rng.uniform(0.72, 1.28))
        sig = ItemSignature(
            tag=tag,
            display_name=name,
            rarity=rng.choice(RARITIES),
            category=category,
            uid=f"{index:012x}",
        )
        customer = rng.choice(customers)

        session_id = ledger.start_session(
            tag=tag,
            signature=sig.as_dict(),
            display_name=name,
            rarity=sig.rarity,
            uid=sig.uid,
            counterparty=customer,
        )
        ledger.record_valuation(
            tag=tag,
            session_id=session_id,
            estimate=estimate,
            confidence=rng.uniform(0.45, 0.95),
            signature=sig.as_dict(),
            ts=to_iso(opened),
        )

        # A negotiation: start deep, walk up until the customer says yes.
        percentages = sorted(
            rng.sample([0.07, 0.08, 0.09, 0.10, 0.11, 0.12, 0.13, 0.14, 0.15],
                       rng.randint(1, 3)),
            reverse=True,
        )
        settled: int | None = None
        accepted_offer: str | None = None
        offer_time = opened
        for step, pct in enumerate(percentages):
            offer_time = offer_time + timedelta(seconds=rng.uniform(20, 240))
            coins = int(estimate * (1 - pct))
            exploring = rng.randrange(15) == 0
            offer_id = ledger.record_offer(
                session_id=session_id,
                tag=tag,
                offer_pct=pct,
                offer_coins=coins,
                est_value=estimate,
                confidence=rng.uniform(0.4, 0.95),
                signature=sig.as_dict(),
                counterparty=customer,
                is_exploration=exploring,
            )
            if _accepts(pct, rng):
                settled = coins
                accepted_offer = offer_id
                break
            if step == len(percentages) - 1 and rng.random() < 0.18:
                # The customer names their own number and it gets taken.
                counter = int(coins * rng.uniform(1.02, 1.08))
                # The offer itself was declined, so it stays COUNTERED: the
                # acceptance curve must not learn that this percentage landed.
                ledger.counter_offer(offer_id, counter, session_id=session_id)
                settled = counter
                break
            ledger.reject_offer(offer_id, session_id=session_id)

        if settled is None:
            if rng.random() < 0.4:
                ledger.abandon_session(session_id)
            continue

        item_id = ledger.acquire_item(
            tag=tag,
            cost_basis=settled,
            session_id=session_id,
            offer_id=accepted_offer,
            uid=sig.uid,
            display_name=name,
            rarity=sig.rarity,
            category=category,
            signature=sig.as_dict(),
            est_value=estimate,
            counterparty=customer,
            ts=to_iso(offer_time),
        )
        _resolve(ledger, rng, item_id, estimate, volatility, offer_time, now)

    return ledger.log.count()


def _resolve(
    ledger: Ledger,
    rng: random.Random,
    item_id: str,
    estimate: int,
    volatility: float,
    acquired,
    now,
) -> None:
    """Decide what happened to an item after it was bought.

    Deliberately bimodal. Most items move within a day or two; roughly one in
    six is a slow mover that sits for a week or more and is still sitting
    there now. That second mode is the whole reason the dead-capital figures
    exist, so the demo has to contain it rather than hope a lognormal tail
    produces one.
    """
    if rng.random() < 0.06:
        # Kept for personal use: a withdrawal at market value, reported apart.
        ledger.keep_item(
            item_id=item_id,
            market_value=int(estimate * rng.uniform(0.95, 1.05)),
            note="personal use",
            ts=to_iso(acquired + timedelta(hours=rng.uniform(1, 60))),
        )
        return

    if rng.random() < 0.16:
        # Never moved. This is the case the dead-capital figure and the
        # ageing chart exist for, so the demo produces it outright rather
        # than hoping the hold-time tail reaches past today.
        _mark_to_market(ledger, rng, item_id, estimate, now)
        return

    if rng.random() < 0.18:
        hold_hours = rng.uniform(72, 480)
    else:
        hold_hours = max(0.3, rng.lognormvariate(1.4, 0.9) * (1 + volatility))
    sold_at = acquired + timedelta(hours=hold_hours)

    if sold_at >= now:
        # Bought, not yet sold. Marked to market so it reads as deployed
        # capital rather than as nothing.
        _mark_to_market(ledger, rng, item_id, estimate, now)
        return

    # A slow item does not hold its price: the longer it sat, the more the
    # asking price had to come down to move it at all.
    patience = min(1.0, hold_hours / 240.0)
    multiplier = rng.uniform(0.96, 1.04) - patience * rng.uniform(0.05, 0.25)
    ledger.sell_item(
        item_id=item_id,
        price=max(1, int(estimate * multiplier)),
        taxed=rng.random() > 0.15,
        counterparty=f"Buyer{rng.randrange(900):03d}",
        ts=to_iso(sold_at),
    )


def _mark_to_market(ledger: Ledger, rng: random.Random, item_id: str, estimate: int, now) -> None:
    """Still held: give it a current valuation so it shows as deployed capital."""
    ledger.record_valuation(
        tag="",
        item_id=item_id,
        estimate=int(estimate * rng.uniform(0.92, 1.06)),
        ts=to_iso(now),
    )

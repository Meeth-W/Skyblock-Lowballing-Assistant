"""Turning what the user picked into something priceable, and matching a
completed trade back onto it.

Two halves that meet in the middle. The selection carries NBT, so it can be
valued properly. The trade announcement carries only display names, because
that is all chat says -- so it is matched against what was already on screen
rather than parsed into items of its own.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..parsing.nbt import NbtDecodeError
from ..parsing.parser import signature_from_b64
from ..parsing.signature import ItemSignature
from .protocol import ItemsSelected, SelectedSlot, TradeCompleted, TradedItem

#: Star glyphs SkyBlock appends to upgraded gear. Dropped when matching a chat
#: name to an item, because chat and the item tooltip do not always agree on
#: which glyph a master star draws as.
_STARS = re.compile(r"[\u272a\u278a-\u278e\u2776-\u277a\u2780-\u2789\u24f5-\u24fe\u2460-\u2473]+")
_FORMAT = re.compile(r"[\u00a7&][0-9a-fk-orA-FK-OR]")
_NON_WORD = re.compile(r"[^a-z0-9 ]+")


def normalise_name(name: str) -> str:
    """Reduce a display name to something two sources can agree on."""
    text = _FORMAT.sub("", name or "")
    text = _STARS.sub(" ", text)
    text = _NON_WORD.sub(" ", text.lower())
    return " ".join(text.split())


def signatures_from_slots(
    slots: tuple[SelectedSlot, ...],
) -> tuple[list[tuple[SelectedSlot, ItemSignature]], list[tuple[int, str]]]:
    """Decode each picked slot.

    Returns what could be read and, separately, why anything else could not.
    An item the user picked and then never saw a price for is a bug report
    waiting to happen, so the reason is carried rather than swallowed.
    """
    out: list[tuple[SelectedSlot, ItemSignature]] = []
    failures: list[tuple[int, str]] = []
    for slot in slots:
        try:
            sig = signature_from_b64(slot.nbt_b64)
        except NbtDecodeError as exc:
            failures.append((slot.slot, str(exc)))
            continue
        if sig is None:
            failures.append((slot.slot, "no SkyBlock id in the item data"))
            continue
        out.append((slot, sig))
    return out, failures


@dataclass
class SelectedItem:
    slot: int
    sig: ItemSignature
    #: How many identical items are in the selection, so it is priced once.
    duplicates: int = 1
    count: int = 1
    source: str | None = None

    @property
    def key(self) -> str:
        return self.sig.cache_key()

    @property
    def normalised_name(self) -> str:
        return normalise_name(self.sig.display_name or self.sig.tag)


@dataclass
class SelectionView:
    """Everything the user currently has picked out."""

    items: list[SelectedItem] = field(default_factory=list)
    captured_at: str | None = None
    #: (slot, reason) for anything picked that could not be read.
    failures: list[tuple[int, str]] = field(default_factory=list)

    @classmethod
    def from_message(cls, message: ItemsSelected) -> SelectionView:
        decoded, failures = signatures_from_slots(message.items)
        return cls(
            items=_collapse(decoded),
            captured_at=message.captured_at,
            failures=failures,
        )

    @property
    def signatures(self) -> list[ItemSignature]:
        return [item.sig for item in self.items]

    @property
    def is_empty(self) -> bool:
        return not self.items

    def changed_from(self, other: SelectionView | None) -> bool:
        if other is None:
            return True
        return [i.key for i in self.items] != [i.key for i in other.items]

    def index_of_name(self, name: str) -> int | None:
        """Which picked item a chat name refers to, if exactly one does."""
        wanted = normalise_name(name)
        matches = [i for i, item in enumerate(self.items) if item.normalised_name == wanted]
        if len(matches) == 1:
            return matches[0]
        if matches:
            return None
        # Fall back to a containment match, which catches a reforge prefix
        # appearing on one side but not the other.
        loose = [
            i
            for i, item in enumerate(self.items)
            if wanted and (wanted in item.normalised_name or item.normalised_name in wanted)
        ]
        return loose[0] if len(loose) == 1 else None


def _collapse(
    pairs: list[tuple[SelectedSlot, ItemSignature]],
) -> list[SelectedItem]:
    """Group identical items so the engine is asked about each once."""
    items: list[SelectedItem] = []
    index: dict[str, SelectedItem] = {}
    for slot, sig in pairs:
        key = sig.cache_key()
        existing = index.get(key)
        if existing is not None:
            existing.duplicates += 1
            continue
        item = SelectedItem(
            slot=slot.slot, sig=sig, count=slot.count, source=slot.source
        )
        index[key] = item
        items.append(item)
    return items


@dataclass
class SettledTrade:
    """What the server said actually changed hands.

    This is ground truth for the price and it pre-fills the confirmation. It is
    never used to confirm on the user's behalf: chat reports the trade as a
    whole, so when several items moved at once it cannot say which offer any
    part of the total settles. The click stays.
    """

    counterparty: str | None
    received: tuple[TradedItem, ...]
    given: tuple[TradedItem, ...]
    coins_delta: int
    captured_at: str | None = None

    @classmethod
    def from_message(cls, message: TradeCompleted) -> SettledTrade:
        return cls(
            counterparty=message.counterparty,
            received=message.items_received,
            given=message.items_given,
            coins_delta=message.coins_delta,
            captured_at=message.captured_at,
        )

    @property
    def coins_paid(self) -> int:
        """Coins that left the purse.  A purchase is a negative delta."""
        return -self.coins_delta if self.coins_delta < 0 else 0

    @property
    def is_purchase(self) -> bool:
        return bool(self.received) and self.coins_delta < 0

    @property
    def received_count(self) -> int:
        return sum(item.count for item in self.received)

    @property
    def is_unambiguous(self) -> bool:
        """One item in, coins out: the whole price belongs to that item."""
        return self.is_purchase and self.received_count == 1

    def describe(self) -> str:
        names = ", ".join(
            f"{item.count}x {item.name}" if item.count > 1 else item.name
            for item in self.received
        )
        return names or "nothing"

    def match_in(self, selection: SelectionView | None) -> int | None:
        """Index of the selected item this trade settles, when that is certain.

        Returns None when several items moved or the name matches more than
        one thing on screen, because a pre-filled wrong price is worse than an
        empty box.
        """
        if selection is None or not self.is_unambiguous:
            return None
        return selection.index_of_name(self.received[0].name)

"""The mod-to-app message protocol.

One direction only.  The mod connects, sends, and never receives anything from
this side.  That is not a simplification, it is the compliance boundary: an
app-to-mod channel is the first step toward the app causing something to happen
in game, and Hypixel's rules put a ban on the line.  There is deliberately no
encoder here, only decoders.

Messages arrive as JSON.  Anything unrecognised is dropped with a log line
rather than raised on -- a mod built against a newer protocol should degrade,
not take the app down mid-trade.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765

#: Refuse anything larger than this; a full selection of NBT is a few hundred KB.
MAX_MESSAGE_BYTES = 4 * 1024 * 1024


class MessageType(StrEnum):
    HELLO = "hello"
    ITEMS_SELECTED = "items_selected"
    SELECTION_CLEARED = "selection_cleared"
    TRADE_COMPLETED = "trade_completed"
    HEARTBEAT = "heartbeat"


class ProtocolError(ValueError):
    pass


@dataclass(frozen=True)
class Hello:
    mod_version: str = ""
    mc_version: str = ""
    player_uuid: str | None = None
    player_name: str | None = None


@dataclass(frozen=True)
class SelectedSlot:
    """One item the user picked out, with the NBT to price it from."""

    slot: int
    nbt_b64: str
    count: int = 1
    source: str | None = None

    @classmethod
    def parse(cls, data: Any, index: int = 0) -> SelectedSlot | None:
        if isinstance(data, str):
            return cls(index, data)
        if not isinstance(data, dict):
            return None
        payload = data.get("nbt_b64") or data.get("nbt")
        if not payload:
            return None
        try:
            slot = int(data.get("slot", index))
        except (TypeError, ValueError):
            slot = index
        try:
            count = max(1, int(data.get("count", 1)))
        except (TypeError, ValueError):
            count = 1
        return cls(slot, str(payload), count, data.get("source"))


@dataclass(frozen=True)
class ItemsSelected:
    """The user's current selection, in the order they picked it.

    The mod sends the whole selection on every change rather than a delta, so
    a dropped message cannot leave the two sides disagreeing about what is
    selected.
    """

    items: tuple[SelectedSlot, ...] = ()
    captured_at: str | None = None


@dataclass(frozen=True)
class SelectionCleared:
    """The selection is empty; clear the valuation view."""


@dataclass(frozen=True)
class TradedItem:
    """An item as chat named it.  No NBT: chat does not carry any."""

    count: int
    name: str


@dataclass(frozen=True)
class TradeCompleted:
    """Ground truth for an accepted deal, read from the server's own message.

    Used to pre-fill the confirmation, never to replace the explicit click:
    chat says what changed hands in total, not which offer it settles.
    """

    counterparty: str | None = None
    items_received: tuple[TradedItem, ...] = ()
    items_given: tuple[TradedItem, ...] = ()
    coins_delta: int = 0
    captured_at: str | None = None


@dataclass(frozen=True)
class Heartbeat:
    ts: str | None = None


Message = Hello | ItemsSelected | SelectionCleared | TradeCompleted | Heartbeat


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _traded_items(raw: Any) -> tuple[TradedItem, ...]:
    if not isinstance(raw, list):
        return ()
    out: list[TradedItem] = []
    for entry in raw:
        if isinstance(entry, str):
            out.append(TradedItem(1, entry))
            continue
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        if not name:
            continue
        out.append(TradedItem(max(1, _int(entry.get("count"), 1)), str(name)))
    return tuple(out)


def _selected(raw: Any) -> tuple[SelectedSlot, ...]:
    if not isinstance(raw, list):
        return ()
    out = []
    for index, entry in enumerate(raw):
        slot = SelectedSlot.parse(entry, index)
        if slot is not None:
            out.append(slot)
    return tuple(out)


def decode(raw: str | bytes) -> Message | None:
    """Parse one frame.  Returns None for anything this build does not know."""
    if isinstance(raw, bytes):
        if len(raw) > MAX_MESSAGE_BYTES:
            raise ProtocolError(f"message of {len(raw)} bytes exceeds the cap")
        raw = raw.decode("utf-8", errors="replace")
    elif len(raw) > MAX_MESSAGE_BYTES:
        raise ProtocolError(f"message of {len(raw)} characters exceeds the cap")

    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise ProtocolError(f"not JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ProtocolError("a message must be a JSON object")

    kind = str(data.get("type") or "")

    if kind == MessageType.HELLO:
        return Hello(
            mod_version=str(data.get("mod_version") or ""),
            mc_version=str(data.get("mc_version") or ""),
            player_uuid=data.get("player_uuid"),
            player_name=data.get("player_name"),
        )

    if kind == MessageType.ITEMS_SELECTED:
        items = _selected(data.get("items"))
        if not items:
            # An empty selection means the same thing as clearing it; treating
            # them alike keeps the app from showing a stale list.
            return SelectionCleared()
        return ItemsSelected(items=items, captured_at=data.get("captured_at"))

    if kind == MessageType.SELECTION_CLEARED:
        return SelectionCleared()

    if kind == MessageType.TRADE_COMPLETED:
        return TradeCompleted(
            counterparty=data.get("counterparty") or data.get("counterparty_name"),
            items_received=_traded_items(data.get("items_received")),
            items_given=_traded_items(data.get("items_given")),
            coins_delta=_int(data.get("coins_delta")),
            captured_at=data.get("captured_at"),
        )

    if kind == MessageType.HEARTBEAT:
        return Heartbeat(ts=data.get("ts"))

    return None

"""Headless uplink listener, for bringing the mod up the first time.

Runs the WebSocket server on its own and prints what arrives, decoded. No Qt,
no API calls, no database: when something is wrong between the mod and the app
this narrows it to one side or the other in a few seconds.

    python -m lowball --listen
"""

from __future__ import annotations

import asyncio
import contextlib
import pathlib
import sys
from typing import Any

from .money import format_coins
from .parsing.categories import category_of
from .parsing.nbt import describe_payload
from .parsing.parser import signature_from_b64
from .timeutil import now_iso
from .uplink import (
    Hello,
    ItemsSelected,
    SelectionCleared,
    SettledTrade,
    TradeCompleted,
    UplinkServer,
    UplinkStatus,
)


def _safe(text: str) -> str:
    """Item names carry glyphs a Windows console cannot encode."""
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    return text.encode(encoding, errors="replace").decode(encoding, errors="replace")


def _say(text: str) -> None:
    print(_safe(text), flush=True)


def _stamp() -> str:
    return now_iso()[11:23]


def _describe(sig: Any, slot: int | None = None) -> str:
    where = f"slot {slot:>2}  " if slot is not None else ""
    chips = ", ".join(sig.summary()[:4]) or "no modifiers"
    name = sig.display_name or sig.tag
    return (
        f"    {where}{sig.tag:<28} {name[:28]:<28} "
        f"{(sig.rarity or '?'):<10} {category_of(sig):<10} {chips}"
    )


def _on_status(status: UplinkStatus) -> None:
    _say(f"[{_stamp()}] {status.label}")


def _on_message(message: Any) -> None:
    if isinstance(message, Hello):
        _say(
            f"[{_stamp()}] hello: {message.player_name} "
            f"(mod {message.mod_version}, mc {message.mc_version})"
        )
        return

    if isinstance(message, ItemsSelected):
        source = message.items[0].source if message.items else None
        _say(
            f"[{_stamp()}] items_selected: {len(message.items)} picked"
            f"{f' from {source}' if source else ''}"
        )
        # Decode each slot on its own rather than through SelectionView, which
        # skips what it cannot read. When an item does not come through, the
        # reason is the whole point of running this.
        for slot in message.items:
            try:
                sig = signature_from_b64(slot.nbt_b64)
            except Exception as exc:  # noqa: BLE001 - diagnosing is the job here
                _report_failure(slot, f"{type(exc).__name__}: {exc}")
                continue
            if sig is None:
                _report_failure(slot, "decoded, but no SkyBlock id in ExtraAttributes")
                continue
            _say(_describe(sig, slot.slot))
        return

    if isinstance(message, SelectionCleared):
        _say(f"[{_stamp()}] selection_cleared")
        return

    if isinstance(message, TradeCompleted):
        settled = SettledTrade.from_message(message)
        direction = "paid" if settled.coins_delta < 0 else "received"
        _say(
            f"[{_stamp()}] trade_completed with {settled.counterparty or '?'}: "
            f"{direction} {format_coins(abs(settled.coins_delta))}"
        )
        for item in settled.received:
            _say(f"    + {item.count}x {item.name}")
        for item in settled.given:
            _say(f"    - {item.count}x {item.name}")
        return

    _say(f"[{_stamp()}] {type(message).__name__}: {message}")


_DUMP_DIR = pathlib.Path("failed-items")


def _report_failure(slot: Any, reason: str) -> None:
    """Say why an item did not come through, and keep the bytes that did."""
    _say(f"    slot {slot.slot}: COULD NOT READ -- {reason}")
    try:
        _DUMP_DIR.mkdir(parents=True, exist_ok=True)
        stem = _DUMP_DIR / f"slot{slot.slot}"
        stem.with_suffix(".b64").write_text(slot.nbt_b64, encoding="utf-8")
        stem.with_suffix(".txt").write_text(
            describe_payload(slot.nbt_b64), encoding="utf-8"
        )
        _say(f"      payload written to {stem.with_suffix('.b64')}")
    except OSError as exc:
        _say(f"      (could not write the payload: {exc})")
    for line in describe_payload(slot.nbt_b64).splitlines()[:24]:
        _say(f"      {line}")


async def listen(port: int = 8765) -> None:
    server = UplinkServer(port=port, on_message=_on_message, on_status=_on_status)
    _say(f"[{_stamp()}] listening on ws://127.0.0.1:{port} -- start Minecraft now")
    _say(f"[{_stamp()}] open any container, hit Select items, and click something")
    await server.serve_forever()


def main(port: int = 8765) -> int:
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(listen(port))
    return 0

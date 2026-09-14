"""The inbound link from the mod.

One test here is a compliance test rather than a behaviour test: the server
must never write a frame. That boundary is what keeps the mod read-only, and
it is worth a test that fails loudly if anyone ever adds a reply.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
import websockets

from lowball.uplink import (
    Hello,
    ItemsSelected,
    ProtocolError,
    SelectionCleared,
    SelectionView,
    SettledTrade,
    UplinkServer,
    decode,
    normalise_name,
)

FIXTURES = Path(__file__).parent / "fixtures"
HYPERION = (FIXTURES / "hyperion_wither_impact.component.b64").read_text(encoding="utf-8")
TERMINATOR = (FIXTURES / "runed_terminator.component.b64").read_text(encoding="utf-8")


def frame(**payload) -> str:
    return json.dumps(payload)


def selection(*items) -> str:
    return frame(
        type="items_selected",
        items=[
            {"slot": slot, "count": count, "source": "Large Chest", "nbt_b64": nbt}
            for slot, nbt, count in items
        ],
        captured_at="2026-09-14T10:30:00Z",
    )


def test_hello_is_decoded() -> None:
    message = decode(
        frame(
            type="hello",
            mod_version="0.2.0",
            mc_version="26.1.2",
            player_uuid="abc",
            player_name="Notch",
        )
    )
    assert isinstance(message, Hello)
    assert message.mc_version == "26.1.2"
    assert message.player_name == "Notch"


def test_a_selection_carries_slot_count_and_source() -> None:
    message = decode(selection((13, HYPERION, 1), (27, TERMINATOR, 16)))
    assert isinstance(message, ItemsSelected)
    assert [s.slot for s in message.items] == [13, 27]
    assert message.items[1].count == 16
    assert message.items[0].source == "Large Chest"


def test_an_empty_selection_reads_as_cleared() -> None:
    # The two mean the same thing to the app, and treating them alike stops a
    # stale list being left on screen.
    assert isinstance(decode(frame(type="items_selected", items=[])), SelectionCleared)
    assert isinstance(decode(frame(type="selection_cleared")), SelectionCleared)


def test_an_unknown_message_type_is_ignored_not_fatal() -> None:
    assert decode(frame(type="something_new", data=1)) is None


def test_malformed_frames_raise_rather_than_corrupting_state() -> None:
    with pytest.raises(ProtocolError, match="not JSON"):
        decode("{not json")
    with pytest.raises(ProtocolError, match="JSON object"):
        decode("[1, 2, 3]")


def test_an_oversized_frame_is_refused() -> None:
    with pytest.raises(ProtocolError, match="exceeds the cap"):
        decode("x" * (4 * 1024 * 1024 + 1))


def test_a_selection_view_prices_each_distinct_item_once() -> None:
    view = SelectionView.from_message(
        decode(selection((0, HYPERION, 1), (1, HYPERION, 1), (2, TERMINATOR, 1)))
    )
    assert [i.sig.tag for i in view.items] == ["HYPERION", "TERMINATOR"]
    assert view.items[0].duplicates == 2


def test_undecodable_slots_are_skipped_not_fatal() -> None:
    view = SelectionView.from_message(
        decode(selection((0, "not-base64-nbt", 1), (1, HYPERION, 1)))
    )
    # One item lost, not a broken selection.
    assert [i.sig.tag for i in view.items] == ["HYPERION"]


def test_a_selection_knows_when_it_changed() -> None:
    one = SelectionView.from_message(decode(selection((0, HYPERION, 1))))
    same = SelectionView.from_message(decode(selection((0, HYPERION, 1))))
    more = SelectionView.from_message(decode(selection((0, HYPERION, 1), (1, TERMINATOR, 1))))
    assert not same.changed_from(one)
    assert more.changed_from(one)
    assert one.changed_from(None)


# ---- completed trades, read out of chat -------------------------------------


def completed(counterparty: str, received: list, given: list, coins: int) -> str:
    return frame(
        type="trade_completed",
        counterparty=counterparty,
        items_received=[{"count": c, "name": n} for c, n in received],
        items_given=[{"count": c, "name": n} for c, n in given],
        coins_delta=coins,
    )


def test_a_purchase_reports_what_left_the_purse() -> None:
    settled = SettledTrade.from_message(
        decode(completed("Thxnndrr", [(1, "Ancient Warden Helmet")], [], -390_000_000))
    )
    assert settled.is_purchase
    assert settled.coins_paid == 390_000_000
    assert settled.counterparty == "Thxnndrr"
    assert settled.is_unambiguous


def test_a_sale_is_not_a_purchase() -> None:
    settled = SettledTrade.from_message(
        decode(completed("Alice", [], [(1, "Terminator")], 250_000_000))
    )
    assert not settled.is_purchase
    assert settled.coins_paid == 0


def test_several_items_at_once_cannot_be_attributed() -> None:
    """Chat reports the trade as a whole, so the price cannot be split."""
    settled = SettledTrade.from_message(
        decode(
            completed(
                "Thxnndrr",
                [(1, "Ancient Warden Helmet"), (1, "Ancient Burning Crimson Boots")],
                [],
                -390_000_000,
            )
        )
    )
    assert settled.is_purchase
    assert not settled.is_unambiguous
    assert settled.match_in(SelectionView()) is None


def test_star_glyphs_do_not_stop_a_name_matching() -> None:
    # Chat and the item tooltip do not always draw stars the same way.
    assert normalise_name("Heroic Hyperion \u272a\u272a\u272a\u272a\u272a") == "heroic hyperion"
    assert normalise_name("\u00a76Ancient Warden Helmet") == "ancient warden helmet"


def test_a_settled_trade_finds_the_item_it_belongs_to() -> None:
    view = SelectionView.from_message(decode(selection((0, HYPERION, 1), (1, TERMINATOR, 1))))
    name = view.items[0].sig.display_name
    settled = SettledTrade.from_message(decode(completed("Cust", [(1, name)], [], -800_000_000)))
    assert settled.match_in(view) == 0


def test_a_name_matching_nothing_leaves_the_box_empty() -> None:
    view = SelectionView.from_message(decode(selection((0, HYPERION, 1))))
    settled = SettledTrade.from_message(
        decode(completed("Cust", [(1, "Midas Sword")], [], -800_000_000))
    )
    # A pre-filled wrong price is worse than an empty box.
    assert settled.match_in(view) is None


# ---- the live socket --------------------------------------------------------


async def run_server(server: UplinkServer) -> asyncio.Task:
    task = asyncio.ensure_future(server.serve_forever())
    for _ in range(100):
        await asyncio.sleep(0.01)
        if server._server is not None:
            return task
    task.cancel()
    raise AssertionError("the uplink never started listening")


async def test_the_server_receives_a_selection_over_a_real_socket() -> None:
    received: list[object] = []
    server = UplinkServer(port=8799, on_message=received.append)
    task = await run_server(server)
    try:
        async with websockets.connect("ws://127.0.0.1:8799") as client:
            await client.send(frame(type="hello", mod_version="0.2.0", mc_version="26.1.2",
                                    player_name="Notch"))
            await client.send(selection((0, HYPERION, 1)))
            for _ in range(100):
                await asyncio.sleep(0.01)
                if len(received) >= 2:
                    break
            while_connected = (server.status.connected, server.status.player_name)
    finally:
        server.stop()
        await asyncio.wait_for(task, timeout=2)

    assert isinstance(received[0], Hello)
    assert isinstance(received[1], ItemsSelected)
    assert while_connected == (True, "Notch")


async def test_the_server_never_sends_anything_back() -> None:
    """The compliance boundary, as a test.

    An app-to-mod channel is the first step toward the app causing something to
    happen in game. There is no encoder in the protocol module and no write in
    the handler; this asserts it stays that way.
    """
    server = UplinkServer(port=8798, on_message=lambda _m: None)
    task = await run_server(server)
    try:
        async with websockets.connect("ws://127.0.0.1:8798") as client:
            await client.send(frame(type="hello", mod_version="0.2.0"))
            await client.send(frame(type="heartbeat", ts="now"))
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(client.recv(), timeout=0.4)
    finally:
        server.stop()
        await asyncio.wait_for(task, timeout=2)


async def test_a_handler_that_raises_does_not_drop_the_feed() -> None:
    seen: list[object] = []

    def handler(message: object) -> None:
        seen.append(message)
        raise RuntimeError("handler exploded")

    server = UplinkServer(port=8797, on_message=handler)
    task = await run_server(server)
    try:
        async with websockets.connect("ws://127.0.0.1:8797") as client:
            await client.send(frame(type="heartbeat", ts="1"))
            await client.send(frame(type="heartbeat", ts="2"))
            for _ in range(100):
                await asyncio.sleep(0.01)
                if len(seen) >= 2:
                    break
    finally:
        server.stop()
        await asyncio.wait_for(task, timeout=2)

    assert len(seen) == 2
    assert server.status.errors == 2


def test_the_uplink_refuses_to_bind_anywhere_but_loopback() -> None:
    with pytest.raises(ValueError, match="loopback only"):
        UplinkServer(host="0.0.0.0")

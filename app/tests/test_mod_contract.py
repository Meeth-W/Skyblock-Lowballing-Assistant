"""The wire contract between the mod and the app.

``mod_messages.jsonl`` is not hand-written. It is the real output of the
compiled mod, captured by running it on the JVM (see
``fixtures/ModMessageProbe.java``). Two things are pinned here that cannot be
checked from Python alone:

* the hand-rolled JSON, which the mod builds without a serialisation library;
* the chat parser, driven with the exact text Hypixel prints when a trade
  completes -- including the rank prefix, the abbreviated coin amounts, and
  the star glyphs on an upgraded item;
* the item payload builder, whose output is parsed here by the same code the
  app uses. The first build shipped items that reached the app and could not
  be read at all, which no test on either side alone would have caught.

Regenerate after changing Messages.kt or TradeChatWatcher.kt:

    javac -encoding UTF-8 -cp <mod jar>;<kotlin-stdlib> -d out ModMessageProbe.java
    java -Dstdout.encoding=UTF-8 -cp out;<mod jar>;<kotlin-stdlib> ModMessageProbe \
        > mod_messages.jsonl
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lowball.parsing.parser import signature_from_b64
from lowball.uplink import (
    Hello,
    ItemsSelected,
    SelectionCleared,
    SettledTrade,
    TradeCompleted,
    decode,
)

FIXTURE = Path(__file__).parent / "fixtures" / "mod_messages.jsonl"
LINES = [
    line for line in FIXTURE.read_text(encoding="utf-8").splitlines() if line.strip()
]
DECODED = [decode(line) for line in LINES]
TRADES = [m for m in DECODED if isinstance(m, TradeCompleted)]


def test_the_fixture_covers_every_message_the_mod_sends() -> None:
    assert {type(m) for m in DECODED} == {
        Hello,
        ItemsSelected,
        SelectionCleared,
        TradeCompleted,
    }


@pytest.mark.parametrize("line", LINES)
def test_every_recorded_message_decodes(line: str) -> None:
    assert decode(line) is not None


def test_hello_survives_a_name_needing_escapes() -> None:
    hello = DECODED[0]
    # The mod escapes quotes and backslashes by hand; this is that code path.
    # Spelled out with chr(92) so the expected value cannot be misread as an
    # escape sequence: the name is Notch, a double quote, a backslash, then "x".
    assert hello.player_name == 'Notch"' + chr(92) + "x"
    assert hello.mc_version == "26.1.2"


def test_a_selection_keeps_slots_counts_and_source() -> None:
    picked = DECODED[1]
    assert [s.slot for s in picked.items] == [13, 27]
    assert [s.count for s in picked.items] == [1, 16]
    assert picked.items[0].source == "Large Chest"


def test_every_picked_item_can_actually_be_priced() -> None:
    """The regression test for the bug that made the first build useless.

    Items reached the app and decoded to something without ExtraAttributes in
    it, so every one was silently skipped and nothing ever appeared. Python
    tests passed against fixtures Python had written, and the mod compiled;
    only running the real encoder through the real parser catches it.
    """
    for slot in DECODED[1].items:
        sig = signature_from_b64(slot.nbt_b64)
        assert sig is not None, f"slot {slot.slot} produced no SkyBlock item"
        assert sig.tag


def test_the_payload_builder_carries_the_whole_signature() -> None:
    hyperion, book = (signature_from_b64(s.nbt_b64) for s in DECODED[1].items)

    assert hyperion.tag == "HYPERION"
    assert hyperion.rarity == "MYTHIC"          # read from the lore line
    assert hyperion.category == "SWORD"
    assert hyperion.reforge == "heroic"
    assert hyperion.stars == 5
    assert hyperion.recombobulated is True
    assert hyperion.enchant_level("ultimate_wise") == 5
    assert hyperion.uid == "a1b2c3d4e5f6"       # the auction-house join key

    # A stackable has no identity to be tracked by, and that must survive too.
    assert book.tag == "ENCHANTED_BOOK"
    assert book.count == 16
    assert book.is_stackable
    assert book.uid is None


def test_the_chat_parser_read_a_four_item_purchase() -> None:
    """The first screenshot: four pieces bought for 390M."""
    trade = TRADES[0]
    assert trade.counterparty == "Thxnndrr"          # the [MVP+] rank is stripped
    assert trade.coins_delta == -390_000_000         # "390M coins" on a minus line
    assert [i.name for i in trade.items_received] == [
        "Ancient Warden Helmet",
        "Ancient Burning Crimson Chestplate",
        "Ancient Burning Crimson Leggings",
        "Ancient Burning Crimson Boots",
    ]
    settled = SettledTrade.from_message(trade)
    assert settled.is_purchase
    # Four items at one price: chat cannot say which offer any part settles.
    assert not settled.is_unambiguous


def test_the_chat_parser_handles_lines_in_either_order() -> None:
    """The second screenshot puts the coins line before the item."""
    trade = TRADES[1]
    assert trade.counterparty == "koreacantplayMC"
    assert trade.coins_delta == -1_600_000_000      # "1.6B coins"
    assert len(trade.items_received) == 1
    assert trade.items_received[0].name.startswith("Heroic Hyperion")
    assert SettledTrade.from_message(trade).is_unambiguous


def test_star_glyphs_survive_the_wire_intact() -> None:
    # Normalisation strips them for matching, but the name is carried as sent.
    assert "\u272a" in TRADES[1].items_received[0].name


def test_a_sale_without_a_rank_prefix_is_read_correctly() -> None:
    trade = TRADES[2]
    assert trade.counterparty == "Alice"
    assert trade.coins_delta == 250_000_000         # "250,000,000 coins", received
    assert [i.name for i in trade.items_given] == ["Terminator"]
    assert not SettledTrade.from_message(trade).is_purchase

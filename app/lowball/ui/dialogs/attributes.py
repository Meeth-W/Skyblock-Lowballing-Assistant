"""What an item actually is.

The ledger row has room for a name and a price. Everything that made the item
worth what it was -- the enchantments, the stars, the gems, the pet's level --
lives in the signature stored alongside it, and this is where that is read
back. Opened by clicking the item name.

Nothing here is editable. The signature is what was parsed from the item at
the moment it changed hands; rewriting it afterwards would make the price
stop explaining itself.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ...money import format_coins, format_coins_exact
from ...parsing.categories import category_of
from ...parsing.signature import ItemSignature
from ..theme import (
    GRID,
    SIZE_BODY,
    SIZE_MICRO,
    SIZE_SECTION,
    WEIGHT_EMPHASIS,
    rarity_colour,
    stylesheet,
    ui_font,
)
from ..widgets.primitives import Hairline, KeyValueRow, SectionLabel


def _title(sig: ItemSignature) -> str:
    return sig.display_name or sig.tag.replace("_", " ").title()


class ItemAttributesDialog(QDialog):
    """Everything the signature knows, grouped and read-only."""

    def __init__(
        self,
        sig: ItemSignature,
        *,
        facts: list[tuple[str, str]] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(_title(sig))
        self.setStyleSheet(stylesheet())
        self.setMinimumWidth(460)
        self.resize(500, 620)

        root = QVBoxLayout(self)
        root.setContentsMargins(GRID * 6, GRID * 5, GRID * 6, GRID * 5)
        root.setSpacing(GRID * 2)

        heading = QLabel(_title(sig))
        heading.setFont(ui_font(SIZE_SECTION, WEIGHT_EMPHASIS))
        heading.setStyleSheet(f"color: {rarity_colour(sig.rarity)};")
        root.addWidget(heading)

        subtitle = QLabel(
            "  ".join(
                part
                for part in (sig.rarity or "", category_of(sig), sig.tag)
                if part
            )
        )
        subtitle.setObjectName("faint")
        subtitle.setFont(ui_font(SIZE_MICRO))
        subtitle.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        root.addWidget(subtitle)
        root.addWidget(Hairline())

        body = QWidget()
        self.body = QVBoxLayout(body)
        self.body.setContentsMargins(0, GRID, 0, 0)
        self.body.setSpacing(GRID * 3)

        if facts:
            self._section("In the ledger", facts)
        for title, rows in _sections(sig):
            self._section(title, rows)
        self.body.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(body)
        root.addWidget(scroll, 1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        close = QPushButton("Close")
        close.setObjectName("primary")
        close.clicked.connect(self.accept)
        buttons.addWidget(close)
        holder = QWidget()
        holder.setLayout(buttons)
        root.addWidget(holder)

    def _section(self, title: str, rows: list[tuple[str, str]]) -> None:
        if not rows:
            return
        block = QWidget()
        layout = QVBoxLayout(block)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        layout.addWidget(SectionLabel(title))
        layout.addWidget(Hairline())
        for label, value in rows:
            row = KeyValueRow(label, value, numeric=False)
            row.value.setFont(ui_font(SIZE_BODY))
            row.value.setWordWrap(True)
            layout.addWidget(row)
        self.body.addWidget(block)


def _pretty(name: str) -> str:
    return name.replace("_", " ").title()


def _sections(sig: ItemSignature) -> list[tuple[str, list[tuple[str, str]]]]:
    """The signature, grouped the way a trader reads an item."""
    out: list[tuple[str, list[tuple[str, str]]]] = []

    basics: list[tuple[str, str]] = []
    if sig.count > 1:
        basics.append(("Stack size", str(sig.count)))
    if sig.reforge:
        basics.append(("Reforge", sig.reforge.title()))
    if sig.stars:
        basics.append(("Stars", str(sig.stars)))
    if sig.recombobulated:
        basics.append(("Recombobulated", "yes"))
    if sig.art_of_war:
        basics.append(("The Art of War", "applied"))
    if sig.hot_potato:
        kind = "hot potato" if sig.hot_potato <= 10 else "hot potato and fuming"
        basics.append(("Potato books", f"{sig.hot_potato} ({kind})"))
    if sig.rune:
        basics.append(("Rune", f"{_pretty(sig.rune[0])} {sig.rune[1]}"))
    if sig.skin:
        basics.append(("Skin", sig.skin))
    if sig.dye:
        basics.append(("Dye", sig.dye))
    for scroll in sig.ability_scroll:
        basics.append(("Ability scroll", _pretty(scroll)))
    out.append(("Item", basics))

    if sig.enchantments:
        out.append(
            (
                f"Enchantments ({len(sig.enchantments)})",
                [(_pretty(name), str(level)) for name, level in sig.enchantments],
            )
        )
    if sig.attributes:
        out.append(
            (
                "Attributes",
                [(_pretty(name), str(level)) for name, level in sig.attributes],
            )
        )
    if sig.gems:
        out.append(("Gemstones", [(gem.label(), gem.slot) for gem in sig.gems]))

    pet = sig.pet
    if pet is not None:
        rows = [
            ("Type", _pretty(pet.type)),
            ("Tier", pet.tier.title()),
            (
                "Level",
                f"{pet.level}" if pet.level_is_exact else f"{pet.level}+ (not exact)",
            ),
            ("Experience", f"{int(pet.exp):,}"),
        ]
        if pet.candy_used:
            rows.append(("Candy used", str(pet.candy_used)))
        if pet.held_item:
            rows.append(("Held item", _pretty(pet.held_item.replace("PET_ITEM_", ""))))
        if pet.skin:
            rows.append(("Pet skin", pet.skin))
        out.append(("Pet", rows))

    identity: list[tuple[str, str]] = []
    if sig.uid:
        identity.append(("Item uuid", sig.uid))
    if sig.item_uuid:
        identity.append(("Full uuid", sig.item_uuid))
    for key, value in sig.extras:
        identity.append((_pretty(key), str(value)))
    out.append(("Identity", identity))
    return out


def ledger_facts(row: Any) -> list[tuple[str, str]]:
    """The ledger's own columns, as rows for the dialog's first section."""
    facts: list[tuple[str, str]] = []
    cost = int(row["cost_basis"] or 0)
    facts.append(("Paid", f"{format_coins(cost)}  ({format_coins_exact(cost)})"))
    if row["est_value_now"]:
        facts.append(("Valued at", format_coins(int(row["est_value_now"]))))
    if row["acquired_ts"]:
        facts.append(("Acquired", str(row["acquired_ts"])[:16].replace("T", " ")))
    if row["counterparty"]:
        facts.append(("Bought from", str(row["counterparty"])))
    facts.append(("Outcome", (row["state"] or "held").title()))
    return facts

"""What each modifier is worth, and which are worth filtering on.

Two jobs, both of which the user needs to be able to change without editing
code:

* **ordering** -- which modifiers the comparable search gives up last;
* **the filter threshold** -- an item carries twenty enchantments and most are
  worth nothing. Insisting a comparable share all of them leaves nothing to
  compare against, so only the ones above a value threshold are matched on and
  the rest are priced back in separately.

The numbers below are a starting point, not a price feed. Enchantment prices
move constantly, so the table is written to ``values.yaml`` in the data
directory on first run and read from there afterwards -- edit it there, or
from the Config tab, and the search follows.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from io import StringIO
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

#: Only enchantments worth at least this much are matched on. An item has
#: twenty of them and most cost a few hundred thousand; demanding a comparable
#: share every one of them finds nothing.
DEFAULT_MIN_ENCHANT_FILTER_VALUE = 50_000_000

#: Ultimate enchantments, valued at level 5.
ULTIMATE_ENCHANTS: dict[str, int] = {
    "ultimate_chimera": 120_000_000,
    "ultimate_fatal_tempo": 40_000_000,
    "ultimate_duplex": 20_000_000,
    "ultimate_one_for_all": 15_000_000,
    "ultimate_inferno": 12_000_000,
    "ultimate_the_one": 10_000_000,
    "ultimate_legion": 8_000_000,
    "ultimate_swarm": 6_000_000,
    "ultimate_no_pain_no_gain": 5_000_000,
    "ultimate_last_stand": 4_000_000,
    "ultimate_soul_eater": 3_000_000,
    "ultimate_combo": 3_000_000,
    "ultimate_wise": 2_000_000,
    "ultimate_rend": 2_000_000,
    "ultimate_bank": 2_000_000,
    "ultimate_flash": 1_500_000,
    "ultimate_habanero_tactics": 1_500_000,
    "ultimate_jerry": 500_000,
}
DEFAULT_ULTIMATE_VALUE = 3_000_000

#: Ordinary enchantments whose top levels are expensive in their own right.
#: Valued at the level given; lower levels scale down steeply.
TOP_TIER_ENCHANTS: dict[str, int] = {
    "sharpness": 60_000_000,
    "critical": 55_000_000,
    "ender_slayer": 50_000_000,
    "giant_killer": 50_000_000,
    "power": 55_000_000,
    "growth": 45_000_000,
    "protection": 45_000_000,
    "smite": 30_000_000,
    "bane_of_arthropods": 30_000_000,
    "dragon_hunter": 90_000_000,
    "vicious": 60_000_000,
    "champion": 25_000_000,
    "cubism": 20_000_000,
    "impaling": 20_000_000,
    "thunderlord": 25_000_000,
    "titan_killer": 25_000_000,
    "lethality": 30_000_000,
    "execute": 20_000_000,
    "cleave": 15_000_000,
    "syphon": 12_000_000,
    "vampirism": 12_000_000,
    "venomous": 12_000_000,
    "first_strike": 20_000_000,
    "triple_strike": 20_000_000,
    "looting": 8_000_000,
    "scavenger": 6_000_000,
    "luck": 6_000_000,
    "fire_aspect": 4_000_000,
    "experience": 4_000_000,
    "prosecute": 12_000_000,
    "thunderbolt": 12_000_000,
    "magmarizer": 8_000_000,
}
#: The level those prices refer to, for an enchantment with no entry in
#: ``top_tier_levels``. Below the reference level, value falls away fast.
TOP_TIER_LEVEL = 7

#: How much a price falls per level below the reference level, where nothing
#: better has been measured. Six is about right for an enchantment combined
#: one level at a time; the real figure is often far steeper, because the top
#: level of a combinable enchantment takes many books to reach. The bazaar
#: refresh measures it per enchantment and overwrites this.
ENCHANT_LEVEL_DECAY = 6.0

#: The level each of those prices actually refers to, where it is not the
#: default. Enchantments cap at different levels -- Sharpness goes to VII by
#: combining, Looting stops at V -- and treating a level V cap as "two levels
#: short of VII" multiplies its price by thirty-six.
TOP_TIER_LEVELS: dict[str, int] = {
    "looting": 5,
    "scavenger": 5,
    "luck": 7,
    "fire_aspect": 3,
    "experience": 4,
    "dragon_hunter": 5,
    "impaling": 3,
    "thunderlord": 7,
    "syphon": 5,
    "vampirism": 6,
    "venomous": 6,
    "cleave": 6,
    "champion": 10,
    "prosecute": 6,
    "thunderbolt": 6,
    "magmarizer": 6,
    "titan_killer": 7,
    "lethality": 6,
    "execute": 6,
    "first_strike": 5,
    "triple_strike": 5,
    "cubism": 6,
    "vicious": 5,
}
COMMON_ENCHANT_VALUE = 400_000


@dataclass
class ValueTable:
    """The tunable half of the valuation, in one editable object."""

    min_enchant_filter_value: int = DEFAULT_MIN_ENCHANT_FILTER_VALUE
    #: Percentage shaved off every modifier price before it is added back into
    #: an item's value.  A book on the bazaar is worth its bazaar price; the
    #: same book already applied to a sword is worth less than that, because
    #: nobody can take it off again.  Per-kind recovery still applies on top.
    modifier_discount_pct: int = 0
    ultimate_enchants: dict[str, int] = field(
        default_factory=lambda: dict(ULTIMATE_ENCHANTS)
    )
    top_tier_enchants: dict[str, int] = field(
        default_factory=lambda: dict(TOP_TIER_ENCHANTS)
    )
    default_ultimate_value: int = DEFAULT_ULTIMATE_VALUE
    common_enchant_value: int = COMMON_ENCHANT_VALUE
    top_tier_level: int = TOP_TIER_LEVEL
    #: Per-enchantment override of the level a price refers to. Filled in by
    #: the bazaar refresh from whatever level actually trades.
    top_tier_levels: dict[str, int] = field(
        default_factory=lambda: dict(TOP_TIER_LEVELS)
    )
    #: Measured price ratio between one level and the next, per enchantment.
    #: Sharpness VII trades at three hundred times Sharpness VI, not six.
    top_tier_decay: dict[str, float] = field(default_factory=dict)

    recomb: int = 12_000_000
    art_of_war: int = 5_000_000
    reforge: int = 3_000_000
    rune: int = 2_000_000
    skin: int = 50_000_000
    dye: int = 200_000_000
    hot_potato: int = 100_000
    fuming_potato: int = 1_200_000
    pet_held_item: int = 10_000_000
    ability_scroll: int = 80_000_000
    essence_star: int = 2_000_000
    attribute_base: int = 250_000

    #: Prices for individual skins, by their SkyBlock id.  Empty by default:
    #: skins do not have a single price, and a rule that asks whether one is
    #: worth keeping needs the real number rather than an average.  Anything
    #: not listed here falls back to :attr:`skin`.
    skin_values: dict[str, int] = field(default_factory=dict)

    gems: dict[str, int] = field(
        default_factory=lambda: {
            "PERFECT": 8_000_000,
            "FLAWLESS": 1_500_000,
            "FINE": 200_000,
            "FLAWED": 30_000,
            "ROUGH": 5_000,
        }
    )
    master_stars: list[int] = field(
        default_factory=lambda: [30_000_000, 60_000_000, 120_000_000, 250_000_000, 500_000_000]
    )

    def reference_level(self, name: str) -> int:
        """The level this enchantment's listed price refers to.

        Not a constant, because enchantments cap at different levels. Reading
        a Looting V price as though it were two levels short of a notional VII
        would value every Looting book at a thirty-sixth of its real worth --
        or inflate it by the same factor coming back the other way.
        """
        return int(self.top_tier_levels.get(name.lower(), self.top_tier_level))

    def decay_for(self, name: str) -> float:
        """How steeply this enchantment loses value per level below the top."""
        return max(1.0, float(self.top_tier_decay.get(name.lower(), ENCHANT_LEVEL_DECAY)))

    def enchant_value(self, name: str, level: int) -> int:
        """Rough worth of one enchantment at a given level.

        Value concentrates at the top level: a Sharpness VI is worth a small
        fraction of a VII, and a I is worth nothing at all.
        """
        name = name.lower()
        if name.startswith("ultimate_"):
            base = self.ultimate_enchants.get(name, self.default_ultimate_value)
            return int(base * (min(level, 5) / 5.0) ** 2)
        top = self.top_tier_enchants.get(name)
        if top is None:
            return int(self.common_enchant_value * max(1, level - 4))
        gap = max(0, self.reference_level(name) - level)
        # Each level below the top divides the price by the measured ratio,
        # which for a combinable enchantment is far steeper than it looks:
        # two Sharpness VI make a VII, so a VII is worth many times a VI.
        return int(top / (self.decay_for(name) ** gap))

    @property
    def modifier_multiplier(self) -> float:
        """What survives the discount, as a fraction."""
        return max(0.0, 1.0 - min(100, max(0, int(self.modifier_discount_pct))) / 100.0)

    def skin_value(self, skin: str | None) -> int:
        """What one skin is worth, falling back to the generic figure."""
        if not skin:
            return 0
        return int(self.skin_values.get(str(skin).upper(), self.skin))

    def gem_value(self, quality: str) -> int:
        return int(self.gems.get(str(quality).upper(), 50_000))

    def is_filter_worthy(self, name: str, level: int) -> bool:
        return self.enchant_value(name, level) >= self.min_enchant_filter_value

    # ---- persistence ---------------------------------------------------

    def as_dict(self) -> dict[str, Any]:
        return {
            "min_enchant_filter_value": self.min_enchant_filter_value,
            "modifier_discount_pct": self.modifier_discount_pct,
            "default_ultimate_value": self.default_ultimate_value,
            "common_enchant_value": self.common_enchant_value,
            "top_tier_level": self.top_tier_level,
            "top_tier_levels": dict(self.top_tier_levels),
            "top_tier_decay": dict(self.top_tier_decay),
            "recomb": self.recomb,
            "art_of_war": self.art_of_war,
            "reforge": self.reforge,
            "rune": self.rune,
            "skin": self.skin,
            "dye": self.dye,
            "hot_potato": self.hot_potato,
            "fuming_potato": self.fuming_potato,
            "pet_held_item": self.pet_held_item,
            "ability_scroll": self.ability_scroll,
            "essence_star": self.essence_star,
            "attribute_base": self.attribute_base,
            "gems": dict(self.gems),
            "skin_values": dict(self.skin_values),
            "master_stars": list(self.master_stars),
            "ultimate_enchants": dict(self.ultimate_enchants),
            "top_tier_enchants": dict(self.top_tier_enchants),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ValueTable:
        table = cls()
        for key, value in (data or {}).items():
            if not hasattr(table, key):
                continue
            current = getattr(table, key)
            if isinstance(current, dict) and isinstance(value, dict):
                # Decay ratios are fractional; every other map is whole coins.
                cast = float if key == "top_tier_decay" else int
                current.update({str(k): cast(v) for k, v in value.items()})
            elif isinstance(current, list) and isinstance(value, list):
                setattr(table, key, [int(v) for v in value])
            elif isinstance(current, int) and not isinstance(value, dict | list):
                setattr(table, key, int(value))
        return table


def _yaml() -> YAML:
    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.indent(mapping=2, sequence=4, offset=2)
    return yaml


def load_values(path: Path | None) -> ValueTable:
    """Read the table, falling back to the built-in defaults.

    An unreadable file is ignored rather than fatal: starting with the default
    prices is recoverable, refusing to start is not.
    """
    if path is None or not path.exists():
        return ValueTable()
    try:
        return ValueTable.from_dict(_yaml().load(path.read_text(encoding="utf-8")))
    except Exception:  # noqa: BLE001 - any unreadable file falls back
        return ValueTable()


def dump_values(table: ValueTable) -> str:
    stream = StringIO()
    _yaml().dump(table.as_dict(), stream)
    return stream.getvalue()


def save_values(table: ValueTable, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump_values(table), encoding="utf-8")
    return path


DEFAULT_VALUES = ValueTable()

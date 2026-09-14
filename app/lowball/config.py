"""Application settings.

Stored as YAML next to the database, round-tripped so a hand-edited file keeps
its comments and its ordering.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from io import StringIO
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

from .pricing.offer import OfferConfig
from .tax import TaxConfig

APP_DIR_NAME = ".lowball"


def default_data_dir() -> Path:
    override = os.environ.get("LOWBALL_DATA_DIR")
    if override:
        return Path(override)
    return Path.home() / APP_DIR_NAME


@dataclass
class Settings:
    data_dir: Path = field(default_factory=default_data_dir)

    #: The uplink listens here.  Loopback only; the mod runs on this machine.
    uplink_port: int = 8765

    #: Comparable sales needed before a filter set is considered specific enough.
    min_comparables: int = 5

    #: Tags prefetched on start so the first trade of a session is not cold.
    prefetch_tags: list[str] = field(default_factory=list)

    target_margin: float = 0.05
    target_hourly_return: int = 2_000_000
    exploration_every: int = 15
    derpy: bool = False

    rules_path: Path | None = None
    values_path: Path | None = None

    @property
    def db_path(self) -> Path:
        return self.data_dir / "lowball.db"

    @property
    def settings_path(self) -> Path:
        return self.data_dir / "settings.yaml"

    @property
    def rules_file(self) -> Path:
        return self.rules_path or (self.data_dir / "rules.yaml")

    @property
    def values_file(self) -> Path:
        """Modifier prices and the filter threshold, editable by the user."""
        return self.values_path or (self.data_dir / "values.yaml")

    def offer_config(self) -> OfferConfig:
        return OfferConfig(
            target_margin=self.target_margin,
            target_hourly_return=self.target_hourly_return,
            exploration_every=self.exploration_every,
            tax=TaxConfig(derpy=self.derpy),
        )

    def with_derpy(self, on: bool) -> Settings:
        return replace(self, derpy=on)


_SCALAR_FIELDS = (
    "uplink_port",
    "min_comparables",
    "target_margin",
    "target_hourly_return",
    "exploration_every",
    "derpy",
)


def _yaml() -> YAML:
    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.indent(mapping=2, sequence=4, offset=2)
    return yaml


def load_settings(path: Path | None = None) -> Settings:
    """Read settings, falling back to defaults for anything absent.

    A settings file that cannot be parsed is ignored rather than fatal: the app
    starting with defaults is recoverable, the app refusing to start because of
    a stray tab is not.
    """
    settings = Settings()
    target = path or settings.settings_path
    if not target.exists():
        return settings
    try:
        data = _yaml().load(target.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - any unreadable file falls back to defaults
        return settings
    if not isinstance(data, dict):
        return settings

    for key in _SCALAR_FIELDS:
        if key in data and data[key] is not None:
            current = getattr(settings, key)
            try:
                setattr(settings, key, type(current)(data[key]) if current is not None
                        else data[key])
            except (TypeError, ValueError):
                continue
    if isinstance(data.get("prefetch_tags"), list):
        settings.prefetch_tags = [str(t).upper() for t in data["prefetch_tags"]]
    if data.get("data_dir"):
        settings.data_dir = Path(str(data["data_dir"]))
    if data.get("rules_path"):
        settings.rules_path = Path(str(data["rules_path"]))
    return settings


def save_settings(settings: Settings, path: Path | None = None) -> Path:
    target = path or settings.settings_path
    target.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {key: getattr(settings, key) for key in _SCALAR_FIELDS}
    payload["prefetch_tags"] = list(settings.prefetch_tags)
    stream = StringIO()
    _yaml().dump(payload, stream)
    target.write_text(stream.getvalue(), encoding="utf-8")
    return target


def ensure_data_dir(settings: Settings) -> Path:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    return settings.data_dir


#: A starting hot set: commonly lowballed tags, prefetched so the first trade
#: of a session does not pay for a cold cache while a customer waits.
DEFAULT_PREFETCH_TAGS: tuple[str, ...] = (
    "HYPERION", "VALKYRIE", "SCYLLA", "ASTRAEA",
    "TERMINATOR", "JUJU_SHORTBOW", "BONE_BOW",
    "NECRON_HANDLE", "NECRON_BLADE", "GIANTS_SWORD",
    "POWER_WITHER_HELMET", "POWER_WITHER_CHESTPLATE",
    "POWER_WITHER_LEGGINGS", "POWER_WITHER_BOOTS",
    "TANK_WITHER_HELMET", "WISE_WITHER_HELMET", "SPEED_WITHER_HELMET",
    "CRIMSON_HELMET", "CRIMSON_CHESTPLATE", "CRIMSON_LEGGINGS", "CRIMSON_BOOTS",
    "AURORA_HELMET", "FERVOR_HELMET", "TERROR_HELMET", "HOLLOW_HELMET",
    "SHADOW_ASSASSIN_CHESTPLATE", "FROZEN_BLAZE_CHESTPLATE",
    "DAEDALUS_AXE", "LIVID_DAGGER", "SHADOW_FURY", "FLOWER_OF_TRUTH",
    "ATOMSPLIT_KATANA", "VORPAL_KATANA", "SPIRIT_SCEPTRE",
    "PET", "ENCHANTED_BOOK", "ATTRIBUTE_SHARD",
    "RECOMBOBULATOR_3000", "FUMING_POTATO_BOOK", "HOT_POTATO_BOOK",
    "FIRST_MASTER_STAR", "SECOND_MASTER_STAR", "THIRD_MASTER_STAR",
    "FOURTH_MASTER_STAR", "FIFTH_MASTER_STAR",
    "PERFECT_JASPER_GEM", "PERFECT_SAPPHIRE_GEM", "PERFECT_AMBER_GEM",
    "PERFECT_RUBY_GEM", "PERFECT_AMETHYST_GEM", "PERFECT_TOPAZ_GEM",
    "HEGEMONY_ARTIFACT", "IMPLOSION_SCROLL", "WITHER_SHIELD_SCROLL",
    "SHADOW_WARP_SCROLL", "MIDAS_SWORD", "MIDAS_STAFF",
)

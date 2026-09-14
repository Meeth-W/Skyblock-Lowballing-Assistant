"""What a rule is allowed to say, as data.

The rule builder in the Config tab is generated from this file: every dropdown
of fields, every operator list, every value editor, and every normalisation
comes from here.  So does the engine's own validation.  One list, so a rule the
builder can express is a rule the engine understands and vice versa -- the
alternative is a menu offering a condition that silently never fires.

Adding a condition field means adding an entry here *and* producing it in
:func:`lowball.rules.engine.build_context`.  Adding a normalisation means an
entry here *and* a branch in ``_normalised_signature``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..parsing.categories import (
    ACCESSORY,
    ARMOR,
    BOOK,
    CONSUMABLE,
    COSMETIC,
    EQUIPMENT,
    MATERIAL,
    OTHER,
    PET,
    TOOL,
    WEAPON,
)
from ..parsing.signature import GEM_QUALITIES, RARITIES

#: Value kinds, which decide both the editor widget and the operators offered.
TEXT = "text"
NUMBER = "number"
COINS = "coins"
BOOLEAN = "boolean"
CHOICE = "choice"
MAP = "map"

OPERATORS_BY_KIND: dict[str, tuple[str, ...]] = {
    TEXT: ("eq", "ne", "contains", "matches", "in", "not_in", "exists"),
    NUMBER: ("eq", "ne", "lt", "lte", "gt", "gte", "in", "not_in", "exists"),
    COINS: ("lt", "lte", "gt", "gte", "eq", "ne", "exists"),
    BOOLEAN: ("eq",),
    CHOICE: ("eq", "ne", "in", "not_in", "exists"),
    MAP: ("contains", "exists"),
}

#: How each operator reads in a sentence, for the builder's own prose.
OPERATOR_LABELS: dict[str, str] = {
    "eq": "is",
    "ne": "is not",
    "lt": "is less than",
    "lte": "is at most",
    "gt": "is more than",
    "gte": "is at least",
    "in": "is one of",
    "not_in": "is none of",
    "contains": "contains",
    "matches": "matches the pattern",
    "exists": "is present",
}

CATEGORIES: tuple[str, ...] = (
    WEAPON, ARMOR, EQUIPMENT, ACCESSORY, PET, TOOL, CONSUMABLE, BOOK,
    COSMETIC, MATERIAL, OTHER,
)

PET_TIERS: tuple[str, ...] = ("COMMON", "UNCOMMON", "RARE", "EPIC", "LEGENDARY", "MYTHIC")


@dataclass(frozen=True)
class FieldSpec:
    """One thing a condition may test."""

    name: str
    label: str
    kind: str
    group: str
    choices: tuple[str, ...] = ()
    help: str = ""

    @property
    def operators(self) -> tuple[str, ...]:
        return OPERATORS_BY_KIND[self.kind]


#: Every field :func:`build_context` produces, grouped the way the builder
#: shows them.
FIELDS: tuple[FieldSpec, ...] = (
    # ---- identity ----
    FieldSpec("tag", "Item id", TEXT, "Item", help="The SkyBlock id, e.g. HYPERION"),
    FieldSpec("name", "Display name", TEXT, "Item"),
    FieldSpec("category", "Category", CHOICE, "Item", CATEGORIES),
    FieldSpec("rarity", "Rarity", CHOICE, "Item", RARITIES),
    FieldSpec(
        "base_rarity",
        "Rarity before recombobulation",
        CHOICE,
        "Item",
        RARITIES,
        "What comparables are keyed on, so a recombobulated item still matches",
    ),
    FieldSpec("count", "Stack size", NUMBER, "Item"),
    FieldSpec(
        "is_stackable",
        "stackable",
        BOOLEAN,
        "Item",
        help="No item uuid, so it cannot be tracked to a listing",
    ),
    FieldSpec("estimate", "Estimated value", COINS, "Item", help="The valuation, in coins"),
    # ---- modifiers ----
    FieldSpec("reforge", "Reforge", TEXT, "Modifiers"),
    FieldSpec("stars", "Stars", NUMBER, "Modifiers"),
    FieldSpec("hot_potato", "Potato books", NUMBER, "Modifiers"),
    FieldSpec("recombobulated", "recombobulated", BOOLEAN, "Modifiers"),
    FieldSpec("art_of_war", "Art of War'd", BOOLEAN, "Modifiers"),
    FieldSpec("gem_count", "Gemstones fitted", NUMBER, "Modifiers"),
    FieldSpec("has_skin", "skinned", BOOLEAN, "Modifiers"),
    FieldSpec("has_dye", "dyed", BOOLEAN, "Modifiers"),
    FieldSpec("skin", "Skin id", TEXT, "Modifiers"),
    FieldSpec("dye", "Dye id", TEXT, "Modifiers"),
    FieldSpec("rune", "Rune", TEXT, "Modifiers"),
    FieldSpec("ability_scroll_count", "Ability scrolls", NUMBER, "Modifiers"),
    FieldSpec(
        "enchantments",
        "Enchantments",
        MAP,
        "Modifiers",
        help="Test whether a named enchantment is present at all",
    ),
    FieldSpec("attributes", "Attributes", MAP, "Modifiers"),
    # ---- what the modifiers are worth ----
    FieldSpec(
        "top_enchant_value",
        "Best enchantment value",
        COINS,
        "Worth",
        help="The single most valuable enchantment on the item, from the pricing table",
    ),
    FieldSpec("enchant_value_total", "Total enchantment value", COINS, "Worth"),
    FieldSpec("attribute_value_total", "Total attribute value", COINS, "Worth"),
    FieldSpec("gem_value_total", "Total gemstone value", COINS, "Worth"),
    FieldSpec("star_value", "Star value", COINS, "Worth"),
    FieldSpec(
        "skin_value",
        "Skin value",
        COINS,
        "Worth",
        help="From the skin prices in the pricing table, or the default skin value",
    ),
    FieldSpec("pet_skin_value", "Pet skin value", COINS, "Worth"),
    FieldSpec(
        "modifier_value_total",
        "Total modifier value",
        COINS,
        "Worth",
        help="The whole item minus its base, as the pricing table sees it",
    ),
    # ---- pets ----
    FieldSpec("is_pet", "a pet", BOOLEAN, "Pets"),
    FieldSpec("pet_type", "Pet type", TEXT, "Pets"),
    FieldSpec("pet_tier", "Pet tier", CHOICE, "Pets", PET_TIERS),
    FieldSpec("pet_level", "Pet level", NUMBER, "Pets"),
    FieldSpec(
        "pet_level_is_exact",
        "an exactly levelled pet",
        BOOLEAN,
        "Pets",
        help="False on a pet that levels past 100, where the level filter lies",
    ),
    FieldSpec("pet_exp", "Pet experience", NUMBER, "Pets"),
    FieldSpec("pet_candy", "Candy used", NUMBER, "Pets"),
    FieldSpec("pet_held_item", "Held item", TEXT, "Pets"),
    FieldSpec("pet_skin", "Pet skin id", TEXT, "Pets"),
)

FIELDS_BY_NAME: dict[str, FieldSpec] = {f.name: f for f in FIELDS}

FIELD_GROUPS: tuple[str, ...] = ("Item", "Modifiers", "Worth", "Pets")


def field_spec(name: str) -> FieldSpec | None:
    """The spec for a field, or None for one written by hand.

    ``enchant:sharpness`` and ``attribute:mana_pool`` are addressed per name
    and cannot be enumerated, so they have no spec and the builder shows them
    as free text.
    """
    return FIELDS_BY_NAME.get(name)


@dataclass(frozen=True)
class NormaliseSpec:
    """One rewrite a rule may perform before the item is valued."""

    key: str
    label: str
    kind: str
    choices: tuple[str, ...] = ()
    help: str = ""
    #: What the builder offers when the rewrite is first added.
    default: object = None


#: Normalisation is the strongest thing a rule can do, because it changes
#: which comparables are searched for rather than adjusting a number after
#: the fact.
NORMALISATIONS: tuple[NormaliseSpec, ...] = (
    NormaliseSpec(
        "pet_level",
        "Treat the pet as level",
        NUMBER,
        default=1,
        help="Prices the pet against that level's comparables instead",
    ),
    NormaliseSpec("pet_candy", "Treat candy used as", NUMBER, default=0),
    NormaliseSpec(
        "pet_skin", "Treat the pet skin as", CHOICE, ("none",), default="none",
        help="A cheap skin adds nothing a buyer will pay for; price it as bare",
    ),
    NormaliseSpec("skin", "Treat the skin as", CHOICE, ("none",), default="none"),
    NormaliseSpec("dye", "Treat the dye as", CHOICE, ("none",), default="none"),
    NormaliseSpec("reforge", "Treat the reforge as", CHOICE, ("none",), default="none"),
    NormaliseSpec("stars", "Treat stars as", NUMBER, default=0),
    NormaliseSpec("hot_potato", "Treat potato books as", NUMBER, default=0),
    NormaliseSpec(
        "recombobulated", "Treat recombobulated as", BOOLEAN, default=False
    ),
    NormaliseSpec("rarity", "Treat the rarity as", CHOICE, RARITIES),
    NormaliseSpec(
        "drop_enchants_below",
        "Ignore enchantments worth under",
        COINS,
        default=10_000_000,
        help=(
            "Drops them from the item entirely, so they are neither matched on "
            "nor added back"
        ),
    ),
    NormaliseSpec(
        "drop_attributes_below", "Ignore attributes worth under", COINS,
        default=10_000_000,
    ),
    NormaliseSpec(
        "drop_gems_below",
        "Ignore gemstones under",
        CHOICE,
        GEM_QUALITIES,
        default="FINE",
        help="Anything below this quality is treated as an empty slot",
    ),
    NormaliseSpec("gems", "Ignore every gemstone", BOOLEAN, default=True),
)

NORMALISATIONS_BY_KEY: dict[str, NormaliseSpec] = {n.key: n for n in NORMALISATIONS}

#: Value the builder writes, and the engine reads, for "there isn't one".
NONE_WORDS: frozenset[str] = frozenset({"none", "null", "nothing", ""})


def is_none_word(value: object) -> bool:
    return value is None or (
        isinstance(value, str) and value.strip().lower() in NONE_WORDS
    )


@dataclass(frozen=True)
class ActionSpec:
    """One thing a rule may do once it has fired."""

    key: str
    label: str
    kind: str
    help: str = ""
    choices: tuple[str, ...] = field(default=())


ACTIONS: tuple[ActionSpec, ...] = (
    ActionSpec(
        "offer_pct",
        "Offer this far below the estimate",
        NUMBER,
        "A percentage. Overrides the recommendation for this item.",
    ),
    ActionSpec(
        "max_coins", "Never pay more than", COINS, "A hard cap, whatever it is worth."
    ),
    ActionSpec("exclude", "Never buy this", BOOLEAN, "Warns instead of recommending."),
    ActionSpec(
        "valuation",
        "Value it by",
        CHOICE,
        "Overrides how the estimate is derived.",
        ("median_only", "lbin_only"),
    ),
    ActionSpec("note", "Say", TEXT, "Free text, shown beside the badge."),
    ActionSpec(
        "stop",
        "Stop evaluating further rules",
        BOOLEAN,
        "Nothing after this rule runs, whatever its priority.",
    ),
)

ACTIONS_BY_KEY: dict[str, ActionSpec] = {a.key: a for a in ACTIONS}

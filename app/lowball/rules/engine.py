"""Evaluating rules against an item.

Two phases, because some actions have to happen before the item is priced and
some after.

``normalise`` runs first and rewrites the signature -- pricing a level 37 pet
as a level 1 changes which comparables are even searched for.  Everything else
runs against the finished valuation.

Rules are evaluated in ascending priority.  For each action the first rule to
set it wins, so a priority 10 rule beats a priority 20 one and the file reads
top to bottom the way its author expects.

Every rule that fires is returned.  Nothing here applies a change quietly: a
silent override is worse than no rule at all, so the firing list is carried
through to the offer, badged beside the number, and written to the ledger.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from ..parsing.categories import category_of
from ..parsing.signature import ItemSignature
from ..pricing.values import DEFAULT_VALUES, ValueTable
from .catalogue import is_none_word
from .model import Firing, Rule


def _worth(sig: ItemSignature, values: ValueTable) -> dict[str, int]:
    """What each family of modifiers on this item is worth, in coins.

    Rules about value need a number, not a flag: "a skin worth less than 50M"
    and "an enchantment worth more than 10M" are the questions a lowballer
    actually asks, and neither can be expressed as a predicate over names.
    The figures come from the same pricing table the valuation uses, so a rule
    and the estimate never disagree about what something is worth.
    """
    enchants = [values.enchant_value(name, level) for name, level in sig.enchantments]
    attributes = [
        values.attribute_base * (2 ** max(0, level - 1)) for _, level in sig.attributes
    ]
    gems = [values.gem_value(gem.quality) for gem in sig.gems]
    master = max(0, sig.stars - 5)
    stars = values.essence_star * min(sig.stars, 5) + sum(values.master_stars[:master])
    skin = values.skin_value(sig.skin)
    pet_skin = values.skin_value(sig.pet.skin) if sig.pet else 0

    extras = 0
    extras += values.recomb if sig.recombobulated else 0
    extras += values.art_of_war if sig.art_of_war else 0
    extras += values.reforge if sig.reforge else 0
    extras += values.rune if sig.rune else 0
    extras += values.dye if sig.dye else 0
    extras += values.hot_potato * sig.hot_potato
    extras += values.ability_scroll * len(sig.ability_scroll)
    if sig.pet and sig.pet.held_item:
        extras += values.pet_held_item

    return {
        "top_enchant_value": max(enchants, default=0),
        "enchant_value_total": sum(enchants),
        "attribute_value_total": sum(attributes),
        "gem_value_total": sum(gems),
        "star_value": int(stars),
        "skin_value": skin,
        "pet_skin_value": pet_skin,
        "modifier_value_total": int(
            sum(enchants) + sum(attributes) + sum(gems) + stars + skin + pet_skin + extras
        ),
    }


def build_context(
    sig: ItemSignature,
    extra: dict[str, Any] | None = None,
    *,
    values: ValueTable = DEFAULT_VALUES,
) -> dict[str, Any]:
    """Flatten an item into the fields a rule may test."""
    pet = sig.pet
    context: dict[str, Any] = {
        "tag": sig.tag,
        "name": sig.display_name,
        "rarity": sig.rarity,
        "base_rarity": sig.base_rarity,
        "category": category_of(sig),
        "count": sig.count,
        "is_pet": sig.is_pet,
        "is_stackable": sig.is_stackable,
        "has_skin": sig.has_skin,
        "has_dye": sig.dye is not None,
        "skin": sig.skin,
        "dye": sig.dye,
        "reforge": sig.reforge,
        "stars": sig.stars,
        "hot_potato": sig.hot_potato,
        "recombobulated": sig.recombobulated,
        "art_of_war": sig.art_of_war,
        "gem_count": len(sig.gems),
        "enchantments": sig.enchant_map,
        "attributes": sig.attribute_map,
        "rune": sig.rune[0] if sig.rune else None,
        "ability_scroll_count": len(sig.ability_scroll),
        "pet_type": pet.type if pet else None,
        "pet_tier": pet.tier if pet else None,
        "pet_level": pet.level if pet else None,
        "pet_level_is_exact": pet.level_is_exact if pet else None,
        "pet_exp": pet.exp if pet else None,
        "pet_candy": pet.candy_used if pet else None,
        "pet_held_item": pet.held_item if pet else None,
        "pet_skin": pet.skin if pet else None,
    }
    context.update(_worth(sig, values))
    # Per-name access, so a rule can read `enchant:ultimate_wise` directly.
    for name, level in sig.enchantments:
        context[f"enchant:{name}"] = level
    for name, level in sig.attributes:
        context[f"attribute:{name}"] = level
    context.update(extra or {})
    return context


def _normalised_signature(
    sig: ItemSignature, changes: dict[str, Any], values: ValueTable
) -> ItemSignature:
    """Apply a rule's normalisations to a copy of the signature."""
    from ..parsing.signature import GEM_QUALITIES

    updates: dict[str, Any] = {}
    pet = sig.pet
    for field_name, value in changes.items():
        if field_name == "pet_level" and pet is not None:
            from ..parsing.pets import exp_for_level

            level = int(value)
            pet = replace(
                pet,
                level=level,
                exp=float(exp_for_level(level, pet.tier)),
                level_is_exact=True,
            )
        elif field_name == "pet_candy" and pet is not None:
            pet = replace(pet, candy_used=int(value))
        elif field_name == "pet_skin" and pet is not None:
            pet = replace(
                pet, skin=None if is_none_word(value) else str(value).upper()
            )
        elif field_name == "stars":
            updates["stars"] = int(value)
        elif field_name == "hot_potato":
            updates["hot_potato"] = int(value)
        elif field_name == "recombobulated":
            updates["recombobulated"] = bool(value)
        elif field_name == "reforge":
            updates["reforge"] = None if is_none_word(value) else str(value).lower()
        elif field_name == "skin":
            updates["skin"] = None if is_none_word(value) else str(value).upper()
        elif field_name == "dye":
            updates["dye"] = None if is_none_word(value) else str(value).upper()
        elif field_name == "rarity":
            updates["rarity"] = None if is_none_word(value) else str(value).upper()
        elif field_name == "enchantments":
            updates["enchantments"] = tuple(sorted((dict(value)).items()))
        elif field_name == "drop_enchants_below":
            # Dropped outright rather than merely unmatched: a cheap
            # enchantment that is neither searched on nor added back is what
            # "ignore it" has to mean, or it comes back through the add-back.
            floor = int(value)
            updates["enchantments"] = tuple(
                (name, level)
                for name, level in sig.enchantments
                if values.enchant_value(name, level) >= floor
            )
        elif field_name == "drop_attributes_below":
            floor = int(value)
            updates["attributes"] = tuple(
                (name, level)
                for name, level in sig.attributes
                if values.attribute_base * (2 ** max(0, level - 1)) >= floor
            )
        elif field_name == "drop_gems_below":
            order = list(GEM_QUALITIES)
            try:
                cut = order.index(str(value).upper())
            except ValueError:
                cut = 0
            updates["gems"] = tuple(
                gem
                for gem in sig.gems
                if gem.quality.upper() in order and order.index(gem.quality.upper()) >= cut
            )
        elif field_name == "gems":
            updates["gems"] = ()
    if pet is not sig.pet:
        updates["pet"] = pet
    return replace(sig, **updates) if updates else sig


class Decision:
    """The combined effect of every rule that fired."""

    def __init__(self) -> None:
        self.offer_pct: float | None = None
        self.max_coins: int | None = None
        self.excluded: bool = False
        self.valuation_method: str | None = None
        self.notes: list[str] = []
        self.firings: list[Firing] = []

    @property
    def fired(self) -> bool:
        return bool(self.firings)

    @property
    def rule_names(self) -> list[str]:
        return [f.name for f in self.firings]

    def badge_for(self, action: str) -> str | None:
        """Which rule is responsible for a given number, for the inline badge."""
        for firing in self.firings:
            if action == "offer_pct" and firing.rule.action.offer_pct is not None:
                return firing.name
            if action == "max_coins" and firing.rule.action.max_coins is not None:
                return firing.name
            if action == "exclude" and firing.rule.action.exclude:
                return firing.name
        return None

    def as_payload(self) -> list[dict[str, Any]]:
        return [f.as_dict() for f in self.firings]


class RuleEngine:
    def __init__(
        self,
        rules: list[Rule] | None = None,
        *,
        values: ValueTable = DEFAULT_VALUES,
    ) -> None:
        self.rules = sorted(rules or [], key=lambda r: (r.priority, r.name))
        # The same table the valuation prices modifiers from, so a rule about
        # what something is worth agrees with the number on screen.
        self.values = values

    def __len__(self) -> int:
        return len(self.rules)

    def normalise(
        self, sig: ItemSignature, extra: dict[str, Any] | None = None
    ) -> tuple[ItemSignature, list[Firing]]:
        """Rewrite the item before it is valued.

        Runs before any pricing because normalisation changes which comparables
        are searched for in the first place.
        """
        context = build_context(sig, extra, values=self.values)
        firings: list[Firing] = []
        current = sig
        for rule in self.rules:
            if not rule.action.normalise or not rule.matches(context):
                continue
            updated = _normalised_signature(current, rule.action.normalise, self.values)
            if updated != current:
                current = updated
                firings.append(Firing(rule, rule.action.describe()))
                # The context is rebuilt so a later rule sees the normalised
                # item, not the one the customer handed over.
                context = build_context(current, extra, values=self.values)
            if rule.action.stop:
                break
        return current, firings

    def evaluate(
        self, sig: ItemSignature, extra: dict[str, Any] | None = None
    ) -> Decision:
        """Apply every non-normalising action, first rule per action wins."""
        context = build_context(sig, extra, values=self.values)
        decision = Decision()
        for rule in self.rules:
            if not rule.matches(context):
                continue
            action = rule.action
            applied: list[str] = []
            superseded_by: str | None = None
            if action.offer_pct is not None:
                if decision.offer_pct is None:
                    decision.offer_pct = action.offer_pct
                    applied.append(f"offer at -{action.offer_pct * 100:.0f}%")
                else:
                    superseded_by = decision.badge_for("offer_pct")
            if action.max_coins is not None and (
                decision.max_coins is None or action.max_coins < decision.max_coins
            ):
                decision.max_coins = action.max_coins
                applied.append(f"cap at {action.max_coins:,}")
            if action.exclude and not decision.excluded:
                decision.excluded = True
                applied.append("never buy")
            if action.valuation and decision.valuation_method is None:
                decision.valuation_method = action.valuation
                applied.append(f"value by {action.valuation}")
            if action.note:
                decision.notes.append(action.note)
                applied.append(action.note)
            if applied:
                decision.firings.append(Firing(rule, ", ".join(applied)))
            elif superseded_by:
                # The rule matched but something stronger got there first.
                # Badge it anyway: a rule that silently does nothing is how a
                # user ends up believing a protection is in place that is not.
                decision.firings.append(
                    Firing(rule, f"superseded by {superseded_by}")
                )
            if rule.action.stop and applied:
                break
        return decision


def golden_dragon_is_special(sig: ItemSignature) -> bool:
    """Whether the PetLevel filter would lie about this item.

    Coflnet reads ``PetLevel=100`` as "100 or more exp", not "level 100", so on
    a pet that levels past 100 the filter matches almost the entire market.
    The parser already flags these by leaving ``level_is_exact`` false; this is
    the predicate the rule file and the modifier builder both read.
    """
    return bool(sig.pet and not sig.pet.level_is_exact)

"""The rules engine (Part 7)."""

from __future__ import annotations

import pytest

from lowball.parsing.pets import PetInfo
from lowball.parsing.signature import Gem, ItemSignature
from lowball.rules import RuleEngine, RuleError, dump_rules, load_rules, load_rules_text

SKINNED = ItemSignature(tag="POWER_WITHER_HELMET", rarity="LEGENDARY", skin="NECRON_TIED")
PLAIN = ItemSignature(tag="HYPERION", rarity="LEGENDARY")
LOW_PET = ItemSignature(
    tag="PET", rarity="EPIC", pet=PetInfo(type="WOLF", tier="EPIC", exp=120000.0, level=42)
)


def engine_from(text: str) -> RuleEngine:
    return RuleEngine(load_rules_text(text))


def test_a_bare_value_means_equality() -> None:
    engine = engine_from(
        """
        - name: Only Hyperions
          when: {tag: HYPERION}
          then: {offer_pct: 12}
        """
    )
    assert engine.evaluate(PLAIN).offer_pct == pytest.approx(0.12)
    assert engine.evaluate(SKINNED).offer_pct is None


def test_operators_read_the_way_they_are_written() -> None:
    engine = engine_from(
        """
        - name: Cheap stars only
          when: {stars: {lt: 5}}
          then: {offer_pct: 10}
        """
    )
    assert engine.evaluate(ItemSignature(tag="X", stars=3)).offer_pct == pytest.approx(0.10)
    assert engine.evaluate(ItemSignature(tag="X", stars=5)).offer_pct is None


def test_every_condition_must_hold() -> None:
    engine = engine_from(
        """
        - name: Starred and recombed
          when: {stars: {gte: 5}, recombobulated: true}
          then: {offer_pct: 9}
        """
    )
    assert engine.evaluate(ItemSignature(tag="X", stars=5, recombobulated=True)).fired
    assert not engine.evaluate(ItemSignature(tag="X", stars=5)).fired


def test_the_lowest_priority_number_wins_an_action() -> None:
    engine = engine_from(
        """
        - name: Broad
          priority: 50
          when: {tag: HYPERION}
          then: {offer_pct: 20}
        - name: Specific
          priority: 10
          when: {tag: HYPERION}
          then: {offer_pct: 8}
        """
    )
    decision = engine.evaluate(PLAIN)
    assert decision.offer_pct == pytest.approx(0.08)
    # Both are badged; the weaker one says why it did nothing, so the user
    # is never left wondering whether their rule is working.
    assert decision.rule_names == ["Specific", "Broad"]
    assert decision.badge_for("offer_pct") == "Specific"
    assert decision.firings[1].detail == "superseded by Specific"


def test_the_tightest_coin_cap_wins_even_out_of_order() -> None:
    engine = engine_from(
        """
        - name: Loose cap
          priority: 10
          when: {tag: HYPERION}
          then: {max_coins: 900000000}
        - name: Tight cap
          priority: 20
          when: {tag: HYPERION}
          then: {max_coins: 500000000}
        """
    )
    assert engine.evaluate(PLAIN).max_coins == 500_000_000


def test_every_firing_is_reported_so_nothing_is_silent() -> None:
    engine = RuleEngine(load_rules())
    decision = engine.evaluate(SKINNED)
    assert decision.fired
    assert "Skins are illiquid" in decision.rule_names
    assert all(firing.detail for firing in decision.firings)


def test_normalisation_rewrites_the_item_before_it_is_valued() -> None:
    engine = RuleEngine(load_rules())
    normalised, firings = engine.normalise(LOW_PET)
    assert normalised.pet.level == 1
    assert normalised.pet.exp < LOW_PET.pet.exp
    assert [f.name for f in firings] == ["Low pets price as level 1"]


def test_normalisation_leaves_a_high_pet_alone() -> None:
    engine = RuleEngine(load_rules())
    high = ItemSignature(
        tag="PET", pet=PetInfo(type="WOLF", tier="LEGENDARY", exp=3e7, level=100)
    )
    normalised, firings = engine.normalise(high)
    assert normalised is high
    assert firings == []


def test_a_later_rule_sees_the_normalised_item() -> None:
    engine = engine_from(
        """
        - name: Flatten stars
          priority: 10
          when: {tag: X}
          then: {normalise: {stars: 0}}
        - name: Unstarred items are cheap
          priority: 20
          when: {stars: 0}
          then: {normalise: {recombobulated: false}}
        """
    )
    normalised, firings = engine.normalise(
        ItemSignature(tag="X", stars=5, recombobulated=True)
    )
    assert normalised.stars == 0
    assert normalised.recombobulated is False
    assert len(firings) == 2


def test_exclusion_is_carried_through() -> None:
    engine = engine_from(
        """
        - name: Never buy these
          when: {tag: {matches: "^MUSEUM"}}
          then: {exclude: true, note: Cannot be resold}
        """
    )
    decision = engine.evaluate(ItemSignature(tag="MUSEUM_TICKET"))
    assert decision.excluded
    assert decision.notes == ["Cannot be resold"]
    assert decision.badge_for("exclude") == "Never buy these"


def test_stop_halts_evaluation() -> None:
    engine = engine_from(
        """
        - name: First
          priority: 10
          when: {tag: HYPERION}
          then: {offer_pct: 9, stop: true}
        - name: Second
          priority: 20
          when: {tag: HYPERION}
          then: {max_coins: 1}
        """
    )
    decision = engine.evaluate(PLAIN)
    assert decision.rule_names == ["First"]
    assert decision.max_coins is None


def test_an_empty_attribute_map_does_not_count_as_existing() -> None:
    engine = engine_from(
        """
        - name: Has attributes
          when: {attributes: {exists: true}}
          then: {offer_pct: 15}
        """
    )
    assert not engine.evaluate(PLAIN).fired
    assert engine.evaluate(ItemSignature(tag="X", attributes=(("lifeline", 5),))).fired


def test_gems_can_be_counted() -> None:
    engine = engine_from(
        """
        - name: Gemmed
          when: {gem_count: {gte: 2}}
          then: {offer_pct: 11}
        """
    )
    gemmed = ItemSignature(
        tag="X", gems=(Gem("COMBAT_0", "PERFECT"), Gem("UNIVERSAL_0", "PERFECT"))
    )
    assert engine.evaluate(gemmed).fired


def test_a_named_enchantment_can_be_tested_directly() -> None:
    engine = engine_from(
        """
        - name: Chimera is the whole price
          when: {"enchant:ultimate_chimera": {gte: 4}}
          then: {offer_pct: 7}
        """
    )
    item = ItemSignature(tag="HYPERION", enchantments=(("ultimate_chimera", 5),))
    assert engine.evaluate(item).offer_pct == pytest.approx(0.07)
    assert not engine.evaluate(PLAIN).fired


def test_the_shipped_defaults_load_and_are_well_formed() -> None:
    rules = load_rules()
    assert rules
    assert all(rule.name for rule in rules)
    # Priorities are what make the file readable top to bottom.
    assert [r.priority for r in rules] == sorted(r.priority for r in rules)


def test_rules_round_trip_through_yaml() -> None:
    original = load_rules()
    reparsed = load_rules_text(dump_rules(original))
    assert [r.name for r in reparsed] == [r.name for r in sorted(
        original, key=lambda r: (r.priority, r.name)
    )]
    assert [r.action.offer_pct for r in reparsed] == [
        r.action.offer_pct for r in sorted(original, key=lambda r: (r.priority, r.name))
    ]


def test_a_percentage_written_as_25_means_25_percent() -> None:
    engine = engine_from(
        """
        - name: Quarter off
          when: {tag: HYPERION}
          then: {offer_pct: 25}
        """
    )
    assert engine.evaluate(PLAIN).offer_pct == pytest.approx(0.25)


def test_a_fraction_is_also_accepted() -> None:
    engine = engine_from(
        """
        - name: Quarter off
          when: {tag: HYPERION}
          then: {offer_pct: 0.25}
        """
    )
    assert engine.evaluate(PLAIN).offer_pct == pytest.approx(0.25)


def test_a_nonsense_discount_is_refused_at_load_time() -> None:
    with pytest.raises(RuleError, match="not a sane discount"):
        load_rules_text(
            """
            - name: Free please
              when: {tag: HYPERION}
              then: {offer_pct: 99}
            """
        )


def test_an_unknown_action_is_refused_rather_than_ignored() -> None:
    with pytest.raises(RuleError, match="unknown action"):
        load_rules_text(
            """
            - name: Typo
              when: {tag: HYPERION}
              then: {offer_percent: 12}
            """
        )


def test_an_unknown_operator_is_refused() -> None:
    with pytest.raises(RuleError, match="unknown operator"):
        load_rules_text(
            """
            - name: Typo
              when: {stars: {greater_than: 5}}
              then: {offer_pct: 12}
            """
        )


def test_a_nameless_rule_is_refused_because_it_could_not_be_badged() -> None:
    with pytest.raises(RuleError, match="no name"):
        load_rules_text("- when: {tag: HYPERION}\n  then: {offer_pct: 12}")


def test_duplicate_names_are_refused() -> None:
    with pytest.raises(RuleError, match="both called"):
        load_rules_text(
            """
            - name: Same
              when: {tag: A}
              then: {offer_pct: 10}
            - name: Same
              when: {tag: B}
              then: {offer_pct: 11}
            """
        )


def test_a_disabled_rule_does_not_fire() -> None:
    engine = engine_from(
        """
        - name: Off for now
          enabled: false
          when: {tag: HYPERION}
          then: {offer_pct: 9}
        """
    )
    assert not engine.evaluate(PLAIN).fired


# ---- rules about what a modifier is worth ---------------------------------
#
# The rules that motivated this: "a pet skin worth under 50M is not really a
# skin" and "an enchantment worth under 10M is noise". Both need a coin figure
# for a modifier, not a predicate over its name.

GEMMED = ItemSignature(
    tag="HYPERION",
    rarity="LEGENDARY",
    enchantments=(("sharpness", 7), ("thunderlord", 3), ("luck", 5)),
    gems=(Gem("COMBAT_0", "PERFECT", "JASPER"), Gem("COMBAT_1", "ROUGH", "JASPER")),
)
SKINNED_PET = ItemSignature(
    tag="PET",
    rarity="LEGENDARY",
    pet=PetInfo(type="GOLDEN_DRAGON", tier="LEGENDARY", exp=2.6e7, level=100,
                skin="PET_SKIN_GOLDEN_DRAGON_TOY"),
)


def test_the_context_prices_each_family_of_modifier() -> None:
    from lowball.rules import build_context

    context = build_context(GEMMED)
    assert context["top_enchant_value"] == 60_000_000       # sharpness 7
    assert context["gem_value_total"] == 8_005_000          # perfect + rough
    assert context["enchant_value_total"] > context["top_enchant_value"]
    assert context["modifier_value_total"] >= context["enchant_value_total"]


def test_a_cheap_skin_can_be_normalised_away() -> None:
    engine = engine_from(
        """
        - name: Cheap pet skins do not count
          when:
            is_pet: true
            pet_skin_value: {lt: 500000000}
          then:
            normalise: {pet_skin: none}
        """
    )
    normalised, firings = engine.normalise(SKINNED_PET)
    assert normalised.pet.skin is None
    assert [f.name for f in firings] == ["Cheap pet skins do not count"]


def test_an_expensive_skin_is_left_alone() -> None:
    """The same rule must not fire once the skin is worth keeping."""
    from lowball.pricing.values import ValueTable

    values = ValueTable()
    values.skin_values["PET_SKIN_GOLDEN_DRAGON_TOY"] = 900_000_000
    engine = RuleEngine(
        load_rules_text(
            """
            - name: Cheap pet skins do not count
              when:
                is_pet: true
                pet_skin_value: {lt: 500000000}
              then:
                normalise: {pet_skin: none}
            """
        ),
        values=values,
    )
    normalised, firings = engine.normalise(SKINNED_PET)
    assert normalised.pet.skin == "PET_SKIN_GOLDEN_DRAGON_TOY"
    assert firings == []


def test_cheap_enchantments_can_be_dropped_outright() -> None:
    """Dropped, not merely unmatched: an ignored enchantment must not come
    back through the add-back either."""
    engine = engine_from(
        """
        - name: Ignore the cheap ones
          when: {top_enchant_value: {gt: 0}}
          then:
            normalise: {drop_enchants_below: 10000000}
        """
    )
    normalised, _ = engine.normalise(GEMMED)
    assert dict(normalised.enchantments) == {"sharpness": 7}


def test_low_quality_gems_can_be_treated_as_empty_slots() -> None:
    engine = engine_from(
        """
        - name: Rough gems are an empty slot
          when: {gem_count: {gt: 0}}
          then:
            normalise: {drop_gems_below: FINE}
        """
    )
    normalised, _ = engine.normalise(GEMMED)
    assert [g.quality for g in normalised.gems] == ["PERFECT"]


def test_an_unknown_normalisation_is_refused_rather_than_ignored() -> None:
    with pytest.raises(RuleError, match="normalises unknown field"):
        load_rules_text(
            """
            - name: Typo
              when: {tag: HYPERION}
              then: {normalise: {drop_enchants_under: 10000000}}
            """
        )


def test_every_catalogued_field_is_actually_produced() -> None:
    """The rule builder offers exactly these; a field with no value would be
    a menu entry that silently never matches."""
    from lowball.rules import build_context
    from lowball.rules.catalogue import FIELDS

    context = build_context(GEMMED, {"estimate": 1})
    assert [f.name for f in FIELDS if f.name not in context] == []


def test_every_catalogued_normalisation_is_actually_applied() -> None:
    from lowball.rules.catalogue import NORMALISATIONS
    from lowball.rules.model import ACTION_KEYS, Action

    for spec in NORMALISATIONS:
        # Parsing is what rejects an unknown key, so this covers the pairing
        # between the menu and the engine.
        Action.parse({"normalise": {spec.key: spec.default}}, "test")
    assert "normalise" in ACTION_KEYS

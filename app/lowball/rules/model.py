"""Rule definitions and the predicate language.

A rule is a predicate over an item plus an action.  Both halves are plain data
so the whole rule set round-trips through YAML the user can read, diff and
share.

Conditions are a dict of ``field: expectation``.  A bare value means equality;
a nested dict is an operator, so ``pet_level: {lt: 100}`` reads as written.
Every condition in a rule must hold -- there is no implicit "or", because a
rule whose firing conditions are hard to predict is worse than no rule.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .catalogue import NORMALISATIONS_BY_KEY, OPERATOR_LABELS, is_none_word

OPERATORS = frozenset(
    {"eq", "ne", "lt", "lte", "gt", "gte", "in", "not_in", "contains", "matches", "exists"}
)


class RuleError(ValueError):
    """A rule file that cannot be trusted to mean what it says."""


def _compare(value: Any, op: str, expected: Any) -> bool:
    if op == "exists":
        # An empty map or list counts as absent.  `attributes: {exists: true}`
        # is asking whether the item has any attributes, not whether the field
        # is present in the context.
        present = value is not None and (
            bool(value) if isinstance(value, (dict, list, tuple, set, str)) else True
        )
        return present is bool(expected)
    if value is None:
        # An absent field matches nothing except an explicit exists: false.
        return False
    try:
        if op == "eq":
            return _loose_eq(value, expected)
        if op == "ne":
            return not _loose_eq(value, expected)
        if op == "lt":
            return float(value) < float(expected)
        if op == "lte":
            return float(value) <= float(expected)
        if op == "gt":
            return float(value) > float(expected)
        if op == "gte":
            return float(value) >= float(expected)
        if op == "in":
            return any(_loose_eq(value, item) for item in expected)
        if op == "not_in":
            return not any(_loose_eq(value, item) for item in expected)
        if op == "contains":
            if isinstance(value, dict):
                return str(expected).lower() in {str(k).lower() for k in value}
            if isinstance(value, (list, tuple, set)):
                return any(_loose_eq(item, expected) for item in value)
            return str(expected).lower() in str(value).lower()
        if op == "matches":
            return re.search(str(expected), str(value), re.IGNORECASE) is not None
    except (TypeError, ValueError):
        return False
    raise RuleError(f"unknown operator {op!r}")


def _loose_eq(value: Any, expected: Any) -> bool:
    if isinstance(value, bool) or isinstance(expected, bool):
        return bool(value) == bool(expected)
    if isinstance(value, (int, float)) and isinstance(expected, (int, float)):
        return float(value) == float(expected)
    return str(value).strip().lower() == str(expected).strip().lower()


@dataclass(frozen=True)
class Condition:
    field: str
    op: str
    expected: Any

    def matches(self, context: dict[str, Any]) -> bool:
        return _compare(context.get(self.field), self.op, self.expected)

    def describe(self) -> str:
        """The condition as a phrase, e.g. "pet skin value is less than 50M"."""
        from ..money import format_coins
        from .catalogue import BOOLEAN, COINS, field_spec

        spec = field_spec(self.field)
        name = spec.label if spec else self.field
        if spec is not None and spec.kind == BOOLEAN:
            # Boolean labels are written as adjectives, so they read straight:
            # "is a pet", "is not skinned".
            return f"is {name}" if bool(self.expected) else f"is not {name}"
        if self.op == "exists":
            return f"{name} {'is present' if self.expected else 'is absent'}"
        verb = OPERATOR_LABELS.get(self.op, self.op)
        expected = self.expected
        if isinstance(expected, (list, tuple)):
            expected = ", ".join(str(v) for v in expected)
        elif spec is not None and spec.kind == COINS:
            expected = format_coins(expected)
        return f"{name} {verb} {expected}"


def parse_conditions(when: dict[str, Any] | None) -> list[Condition]:
    conditions: list[Condition] = []
    for field_name, expectation in (when or {}).items():
        if isinstance(expectation, dict):
            if not expectation:
                raise RuleError(f"empty condition on {field_name!r}")
            for op, expected in expectation.items():
                if op not in OPERATORS:
                    raise RuleError(
                        f"unknown operator {op!r} on {field_name!r};"
                        f" expected one of {sorted(OPERATORS)}"
                    )
                conditions.append(Condition(field_name, op, expected))
        else:
            conditions.append(Condition(field_name, "eq", expectation))
    return conditions


#: Everything a rule is allowed to do.
ACTION_KEYS = frozenset(
    {"offer_pct", "max_coins", "exclude", "normalise", "valuation", "note", "stop"}
)


@dataclass(frozen=True)
class Action:
    """What a rule does when it fires."""

    #: Override the recommended offer, as a percentage below the estimate.
    offer_pct: float | None = None
    #: Hard cap in coins, whatever the valuation says.
    max_coins: int | None = None
    #: Never buy this.
    exclude: bool = False
    #: Fields to rewrite on the signature before it is valued.
    normalise: dict[str, Any] = field(default_factory=dict)
    #: Override how the estimate is derived, e.g. ``median_only``.
    valuation: str | None = None
    note: str | None = None
    #: Stop evaluating further rules once this one fires.
    stop: bool = False

    @classmethod
    def parse(cls, then: dict[str, Any] | None, rule_name: str) -> Action:
        then = then or {}
        unknown = set(then) - ACTION_KEYS
        if unknown:
            raise RuleError(
                f"rule {rule_name!r} has unknown action(s) {sorted(unknown)};"
                f" expected one of {sorted(ACTION_KEYS)}"
            )
        pct = then.get("offer_pct")
        if pct is not None:
            pct = float(pct)
            if pct > 1.0:
                # Rules are written as "offer_pct: 25", meaning 25% below.
                pct = pct / 100.0
            if not 0.0 <= pct <= 0.95:
                raise RuleError(
                    f"rule {rule_name!r} sets offer_pct to {then['offer_pct']!r},"
                    " which is not a sane discount"
                )
        normalise = dict(then.get("normalise") or {})
        unknown_rewrites = set(normalise) - set(NORMALISATIONS_BY_KEY)
        if unknown_rewrites:
            # Refused rather than ignored: a normalisation that silently does
            # nothing is how a user ends up trusting a rule that never fired.
            raise RuleError(
                f"rule {rule_name!r} normalises unknown field(s)"
                f" {sorted(unknown_rewrites)}; expected one of"
                f" {sorted(NORMALISATIONS_BY_KEY)}"
            )
        return cls(
            offer_pct=pct,
            max_coins=int(then["max_coins"]) if then.get("max_coins") is not None else None,
            exclude=bool(then.get("exclude", False)),
            normalise=normalise,
            valuation=then.get("valuation"),
            note=then.get("note"),
            stop=bool(then.get("stop", False)),
        )

    @property
    def affects_valuation(self) -> bool:
        return bool(self.normalise) or self.valuation is not None

    def describe(self) -> str:
        parts: list[str] = []
        if self.offer_pct is not None:
            parts.append(f"offer at -{self.offer_pct * 100:.0f}%")
        if self.max_coins is not None:
            parts.append(f"cap at {self.max_coins:,}")
        if self.exclude:
            parts.append("never buy")
        for key, value in self.normalise.items():
            parts.append(describe_normalisation(key, value))
        if self.valuation:
            parts.append(f"value by {self.valuation}")
        if not parts and self.note:
            # A rule whose only effect is a note still does something worth
            # naming: it puts a warning next to the number.
            return f"warn: {self.note}"
        return ", ".join(parts) or "no effect"


@dataclass(frozen=True)
class Rule:
    name: str
    priority: int
    conditions: list[Condition]
    action: Action
    enabled: bool = True

    def matches(self, context: dict[str, Any]) -> bool:
        return self.enabled and all(c.matches(context) for c in self.conditions)

    def describe(self) -> str:
        when = " and ".join(c.describe() for c in self.conditions) or "always"
        return f"When {when}, {self.action.describe()}."


@dataclass(frozen=True)
class Firing:
    """A rule that fired, and what it changed.  Always badged in the UI."""

    rule: Rule
    detail: str

    @property
    def name(self) -> str:
        return self.rule.name

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.rule.name, "detail": self.detail}


def describe_normalisation(key: str, value: Any) -> str:
    """One rewrite, in the words the builder shows for it."""
    from ..money import format_coins
    from .catalogue import BOOLEAN, COINS

    spec = NORMALISATIONS_BY_KEY.get(key)
    if spec is None:
        return f"treat {key} as {value}"
    label = spec.label[0].lower() + spec.label[1:]
    if spec.kind == BOOLEAN and key == "gems":
        return label
    if is_none_word(value):
        return f"{label} nothing"
    if spec.kind == COINS:
        return f"{label} {format_coins(value)}"
    return f"{label} {value}"

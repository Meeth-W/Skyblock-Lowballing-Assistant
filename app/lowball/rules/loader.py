"""Loading and saving the rule file.

ruamel round-trips, so a user who has commented and ordered their rules gets
that file back when the app rewrites it rather than a machine-normalised one.

A malformed rule file raises rather than being partially applied.  Half a rule
set is worse than none: the user would believe protections are in place that
are not.
"""

from __future__ import annotations

from io import StringIO
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

from .model import Action, Rule, RuleError, parse_conditions

DEFAULTS_PATH = Path(__file__).with_name("defaults.yaml")


def _yaml() -> YAML:
    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.indent(mapping=2, sequence=4, offset=2)
    return yaml


def parse_rules(data: Any) -> list[Rule]:
    if data is None:
        return []
    if isinstance(data, dict):
        data = data.get("rules", [])
    if not isinstance(data, list):
        raise RuleError("a rule file must be a list of rules, or a mapping with 'rules'")

    rules: list[Rule] = []
    seen: set[str] = set()
    for index, entry in enumerate(data):
        if not isinstance(entry, dict):
            raise RuleError(f"rule {index} is not a mapping")
        name = str(entry.get("name") or "").strip()
        if not name:
            raise RuleError(f"rule {index} has no name; every rule must be nameable")
        if name in seen:
            raise RuleError(f"two rules are both called {name!r}")
        seen.add(name)
        try:
            priority = int(entry.get("priority", 100))
        except (TypeError, ValueError) as exc:
            raise RuleError(f"rule {name!r} has a non-numeric priority") from exc
        rules.append(
            Rule(
                name=name,
                priority=priority,
                conditions=parse_conditions(entry.get("when")),
                action=Action.parse(entry.get("then"), name),
                enabled=bool(entry.get("enabled", True)),
            )
        )
    return rules


def load_rules(path: str | Path | None = None) -> list[Rule]:
    """Read a rule file, falling back to the shipped defaults."""
    target = Path(path) if path else DEFAULTS_PATH
    if not target.exists():
        if path is None:
            return []
        raise RuleError(f"no rule file at {target}")
    try:
        data = _yaml().load(target.read_text(encoding="utf-8"))
    except YAMLError as exc:
        raise RuleError(f"{target.name} is not valid YAML: {exc}") from exc
    return parse_rules(data)


def load_rules_text(text: str) -> list[Rule]:
    try:
        return parse_rules(_yaml().load(text))
    except YAMLError as exc:
        raise RuleError(f"not valid YAML: {exc}") from exc


def dump_rules(rules: list[Rule]) -> str:
    """Serialise rules back to YAML.  Used when the UI edits them."""
    payload = []
    for rule in sorted(rules, key=lambda r: (r.priority, r.name)):
        entry: dict[str, Any] = {"name": rule.name, "priority": rule.priority}
        when: dict[str, Any] = {}
        for condition in rule.conditions:
            if condition.op == "eq":
                when[condition.field] = condition.expected
            else:
                when.setdefault(condition.field, {})[condition.op] = condition.expected
        entry["when"] = when
        then: dict[str, Any] = {}
        action = rule.action
        if action.offer_pct is not None:
            then["offer_pct"] = round(action.offer_pct * 100, 2)
        if action.max_coins is not None:
            then["max_coins"] = action.max_coins
        if action.exclude:
            then["exclude"] = True
        if action.normalise:
            then["normalise"] = dict(action.normalise)
        if action.valuation:
            then["valuation"] = action.valuation
        if action.note:
            then["note"] = action.note
        if action.stop:
            then["stop"] = True
        entry["then"] = then
        if not rule.enabled:
            entry["enabled"] = False
        payload.append(entry)

    stream = StringIO()
    _yaml().dump(payload, stream)
    return stream.getvalue()

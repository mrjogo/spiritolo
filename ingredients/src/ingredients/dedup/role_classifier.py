"""Deterministic role classification for recipe_ingredients rows.

Inputs: (taxonomy_node_slug, role_default, amount, unit, position, raw_text).
Output: (role, role_source) where role_source is 'default' (taxonomy), 'rule'
(contextual override), or 'manual' (set by an explicit reviewer — never
emitted by this function; reserved).

No DB access. No LLM. Caller assembles the input dict by joining
recipe_ingredients with taxonomy_nodes.
"""

from __future__ import annotations

from typing import Any

# Volume in fluid ounces above which a "modifier" or "bitters" substance
# in position 1 is reclassified as base_spirit. 1.5 oz is the rough
# threshold between accent and structural; tighter thresholds over-fire
# on Reverse Manhattans, looser thresholds miss Trinidad Sours.
_BASE_SPIRIT_OZ = 1.5

_OZ_PER_UNIT = {
    "oz": 1.0, "ounce": 1.0, "ounces": 1.0,
    "ml": 0.0338,
    "cl": 0.338,
    "tsp": 0.166, "teaspoon": 0.166,
    "tbsp": 0.5, "tablespoon": 0.5,
    "dash": 0.03125,  # ~1/32 oz, for sanity in heuristics
    "dashes": 0.03125,
    "drop": 0.001, "drops": 0.001,
    "splash": 0.125,
}

_WASH_HINTS = ("rinse", "spritz", "wash", "mist", "spray")


def _to_oz(amount: float | None, unit: str | None) -> float | None:
    if amount is None:
        return None
    if not unit:
        return None
    factor = _OZ_PER_UNIT.get(unit.lower())
    if factor is None:
        return None
    return float(amount) * factor


def classify_role(ing: dict[str, Any]) -> tuple[str, str]:
    role_default = ing.get("role_default")
    amount = ing.get("amount")
    unit = ing.get("unit")
    position = ing.get("position") or 99
    raw_text = (ing.get("raw_text") or "").lower()
    oz = _to_oz(amount, unit)

    # Rule: wash-hint substance with tiny amount.
    if any(h in raw_text for h in _WASH_HINTS) and oz is not None and oz < 0.25:
        return "wash", "rule"

    # Rule: position 1 with structural amount of bitters → base_spirit.
    if (
        role_default == "bitters"
        and position == 1
        and oz is not None
        and oz >= _BASE_SPIRIT_OZ
    ):
        return "base_spirit", "rule"

    # Rule: position 1 with structural amount of modifier → base_spirit.
    # (Catches Reverse Manhattan, Adonis, Bamboo.)
    if (
        role_default == "modifier"
        and position == 1
        and oz is not None
        and oz >= _BASE_SPIRIT_OZ
    ):
        return "base_spirit", "rule"

    # Default-from-taxonomy.
    if role_default is not None:
        return role_default, "default"

    # Heuristic for nodes without role_default: position 1 + structural
    # amount → base_spirit. Otherwise 'other' (audit will flag).
    if position == 1 and oz is not None and oz >= _BASE_SPIRIT_OZ:
        return "base_spirit", "rule"

    return "other", "default"

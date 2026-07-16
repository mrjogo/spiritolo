"""Deterministic role classification for recipe_ingredients rows.

Inputs: (taxonomy_node_slug, default_role, amount, unit, position, raw_text).
Output: (role, role_source) where role_source is 'default' (taxonomy), 'rule'
(contextual override), or 'manual' (set by an explicit reviewer — never
emitted by this function; reserved).

No DB access. No LLM. Caller assembles the input dict by joining
recipe_ingredients with taxonomy_nodes.
"""

from __future__ import annotations

from typing import Any

from recipegf import UnitValidator

# Volume in fluid ounces above which a "modifier" or "bitters" substance
# in position 1 is reclassified as base_spirit. 1.5 oz is the rough
# threshold between accent and structural; tighter thresholds over-fire
# on Reverse Manhattans, looser thresholds miss Trinidad Sours.
_BASE_SPIRIT_OZ = 1.5

# RecipeGF is the unit authority for the approximate-volume conversion too:
# get_approx_ml gives a unit's conventional millilitres (None for ratio /
# container units with no fixed volume, e.g. part / bottle), converted to oz.
# The oz base is RecipeGF's own oz approx_ml, so an oz amount round-trips exactly.
_UNITS = UnitValidator()
_ML_PER_OZ = _UNITS.get_approx_ml("oz")

_WASH_HINTS = ("rinse", "spritz", "wash", "mist", "spray")


def _to_oz(amount: float | None, unit: str | None) -> float | None:
    if amount is None or not unit:
        return None
    approx_ml = _UNITS.get_approx_ml(_UNITS.normalize(unit))
    if approx_ml is None:
        return None
    return float(amount) * approx_ml / _ML_PER_OZ


def classify_role(ing: dict[str, Any]) -> tuple[str, str]:
    default_role = ing.get("default_role")
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
        default_role == "bitters"
        and position == 1
        and oz is not None
        and oz >= _BASE_SPIRIT_OZ
    ):
        return "base_spirit", "rule"

    # Rule: position 1 with structural amount of modifier → base_spirit.
    # (Catches Reverse Manhattan, Adonis, Bamboo.)
    if (
        default_role == "modifier"
        and position == 1
        and oz is not None
        and oz >= _BASE_SPIRIT_OZ
    ):
        return "base_spirit", "rule"

    # Default-from-taxonomy.
    if default_role is not None:
        return default_role, "default"

    # Heuristic for nodes without default_role: position 1 + structural
    # amount → base_spirit. Otherwise 'other' (audit will flag).
    if position == 1 and oz is not None and oz >= _BASE_SPIRIT_OZ:
        return "base_spirit", "rule"

    return "other", "default"

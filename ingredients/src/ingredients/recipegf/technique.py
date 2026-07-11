"""Infer a cocktail's primary mixing technique from its JSON-LD instructions.

Deterministic keyword scan over the flattened ``recipeInstructions`` text.
Returns a :class:`Technique` or ``None`` (ambiguous / no signal) — ``None`` and
the muddle carve-out both route to propose→review in the converter rather than
guessing a step template that might silently drop or invent a step.

This is intentionally conservative: better to park a recipe for review than to
emit a plausible-but-wrong verb-frame doc. The keyword tables are part of the
``CONVERTER_VERSION`` contract — edit them, bump the version.
"""

from __future__ import annotations

import enum
from typing import Any


class Technique(enum.Enum):
    STIR = "stir"
    SHAKE = "shake"
    BUILD = "build"
    BLEND = "blend"


# Ordered by priority: the first family whose any-keyword appears wins. Blend
# and shake are unmistakable primary techniques; stir outranks the weaker
# build signals; build is the catch-all "combined in the serving glass" family.
_TECHNIQUE_KEYWORDS: list[tuple[Technique, tuple[str, ...]]] = [
    (Technique.BLEND, ("blend", "blender", "blitz")),
    (Technique.SHAKE, ("shake", "shaken", "shaking", "dry shake", "dry-shake")),
    (Technique.STIR, ("stir", "stirred", "stirring")),
    (Technique.BUILD, (
        "build", "built", "pour over ice", "over ice",
        "fill the glass", "fill glass", "fill with", "top with", "top up",
        "add to a", "combine in", "in the glass", "in a highball",
        "serve over", "on the rocks",
    )),
]

# Muddling can't be faithfully represented by the v1 templates without a
# dedicated pre-step, so any mention routes the recipe to review (the honest
# propose→review outcome rather than dropping the muddle).
_MUDDLE_KEYWORDS = ("muddle", "muddled", "muddling")

# Ingredient-name hints that a built drink is "topped" with an effervescent
# pour (→ spiritolo/top for that ingredient's final add).
TOPPER_HINTS = (
    "soda", "club soda", "tonic", "ginger beer", "ginger ale", "cola",
    "seltzer", "sparkling", "champagne", "prosecco", "cava", "sparkling wine",
    "lemonade", "cream soda",
)


def flatten_instructions(jsonld: dict[str, Any] | None) -> str:
    """Flatten Schema.org ``recipeInstructions`` (string | list of strings |
    list of HowToStep/HowToSection objects) into one lowercased blob.

    Tolerant of the messy real-world shapes: unknown items contribute their
    ``text``/``name`` if present, else are skipped.
    """
    if not jsonld:
        return ""
    raw = jsonld.get("recipeInstructions")
    parts: list[str] = []

    def _walk(node: Any) -> None:
        if node is None:
            return
        if isinstance(node, str):
            parts.append(node)
        elif isinstance(node, list):
            for item in node:
                _walk(item)
        elif isinstance(node, dict):
            # HowToStep → text; HowToSection → itemListElement (recurse).
            if isinstance(node.get("text"), str):
                parts.append(node["text"])
            elif isinstance(node.get("name"), str):
                parts.append(node["name"])
            if "itemListElement" in node:
                _walk(node["itemListElement"])

    _walk(raw)
    return " ".join(parts).lower()


def mentions_muddle(text: str) -> bool:
    """True iff the (already-lowercased) instruction text mentions muddling."""
    return any(kw in text for kw in _MUDDLE_KEYWORDS)


def infer_technique(jsonld: dict[str, Any] | None) -> Technique | None:
    """Primary technique for a recipe, or ``None`` if no keyword matched."""
    text = flatten_instructions(jsonld)
    if not text:
        return None
    for technique, keywords in _TECHNIQUE_KEYWORDS:
        if any(kw in text for kw in keywords):
            return technique
    return None

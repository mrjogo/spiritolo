"""Assemble + validate the pin-2 imported-recipe bundle.

Bundle shape (the frozen pin-2 contract Barbot's importer consumes):

    {
      "recipe": <RecipeGF recipe object>,          # the inner `recipe`, not {"recipe": ...}
      "verbs":  [<spiritolo/ verb-defs it uses>],  # self-contained, no registry lookup
      "meta":   {"slug": ..., "source": ..., "imported_at": ...}
    }

Self-contained: the bundle carries every ``spiritolo/`` verb-def its recipe
references, so a consumer validates it with **zero** live Spiritolo/registry
lookups —
    RecipeValidator(VerbRegistry().load_overlay(bundle["verbs"])).validate({"recipe": bundle["recipe"]})
— exactly the check :func:`validate_bundle` runs here.

Seam guarantees enforced (raise on violation, so a bad bundle can never be
emitted): the id is reverse-DNS and passes ``is_valid_recipe_id`` (a bare
``spiritolo/<slug>`` is rejected); ``meta["slug"]`` equals
``parse_recipe_id(id).slug`` (via RecipeGF's parser, not string splitting);
``meta`` carries the full ``slug/source/imported_at`` triple Barbot's DB CHECK
needs.
"""

from __future__ import annotations

from typing import Any

from recipegf import RecipeValidator, is_valid_recipe_id, parse_recipe_id

from .verbs import overlay_registry
from .version import RECIPE_AUTHORITY


class BundleError(ValueError):
    """A bundle violated a seam guarantee. Raised, never returned — callers
    treat these as bugs in the converter, not per-recipe review items."""


def build_bundle(
    recipe: dict[str, Any],
    verb_defs: list[dict[str, Any]],
    *,
    slug: str,
    source: str,
    imported_at: str,
) -> dict[str, Any]:
    """Assemble a pin-2 bundle and enforce the seam guarantees.

    ``recipe`` is the inner RecipeGF recipe object (with ``id``/``schema``/…).
    ``verb_defs`` are the ``spiritolo/`` defs the recipe uses (from
    ``verbs.verb_defs_for``). ``imported_at`` is an ISO-8601 timestamp string.

    Raises :class:`BundleError` on any seam violation; otherwise returns the
    validated bundle dict.
    """
    recipe_id = recipe.get("id")
    if not isinstance(recipe_id, str) or not is_valid_recipe_id(recipe_id):
        raise BundleError(f"recipe id {recipe_id!r} is not a valid RecipeGF recipe id")

    parsed = parse_recipe_id(recipe_id)
    if parsed.authority != RECIPE_AUTHORITY:
        raise BundleError(
            f"recipe id authority {parsed.authority!r} is not the reverse-DNS "
            f"Spiritolo authority {RECIPE_AUTHORITY!r}"
        )
    if parsed.slug != slug:
        raise BundleError(
            f"meta slug {slug!r} != parse_recipe_id(id).slug {parsed.slug!r}"
        )

    bundle = {
        "recipe": recipe,
        "verbs": verb_defs,
        "meta": {"slug": slug, "source": source, "imported_at": imported_at},
    }

    result = validate_bundle(bundle)
    if not result.valid:
        detail = "; ".join(f"{e.path}: {e.message}" for e in result.errors[:5])
        raise BundleError(f"assembled bundle failed validation: {detail}")

    return bundle


def validate_bundle(bundle: dict[str, Any]):
    """Validate a bundle exactly as a consumer (Barbot) would: rebuild the
    ``core ∪ bundle['verbs']`` registry and validate ``{"recipe": recipe}``.

    Returns a ``recipegf.ValidationResult``. This is the canonical
    consumer-side check — it must pass with only what the bundle carries, no
    external lookups.
    """
    registry = overlay_registry(bundle.get("verbs") or [])
    return RecipeValidator(registry).validate({"recipe": bundle["recipe"]})

"""Spiritolo → RecipeGF export stage.

Emits validated RecipeGF *pin-2 bundles* from Spiritolo recipe data, so
Barbot can import finished, self-contained recipe docs with no runtime
cross-dependency on Spiritolo.

Layers (all pure-Python, no DB, unit-testable in isolation):
  - ``slug``      — mint kebab-case drink slugs from ``recipe_clusters.canonical_name``.
  - ``technique`` — infer stir/shake/build/blend from jsonld instruction text.
  - ``converter`` — a ``SourceRecipe`` → RecipeGF verb-frame ``recipe`` (or an
                    ``Uncertain`` outcome routed to propose→review).
  - ``bundle``    — assemble + validate the pin-2 ``{recipe, verbs, meta}`` shape.
  - ``verbs``     — load the in-repo ``spiritolo/`` extension verb-defs and build
                    a ``core ∪ spiritolo/`` overlay registry.

The DB/CLI wiring (``db``, ``proposals``) reads clusters from Supabase and
persists/exports bundles; it is a thin shell over the pure core above.

Versioning: ``CONVERTER_VERSION`` in ``version.py`` — bump when conversion
rules (templates, technique keywords, slug rules, ingredient handling) change,
then re-run the export stage (``ingredients.cli export``): delete the export
stage's ``job_items`` rows, or rely on the version bump itself, to re-queue
affected recipes.
"""

from __future__ import annotations

from .bundle import build_bundle, validate_bundle
from .converter import ConversionResult, Ok, SourceIngredient, SourceRecipe, Uncertain, convert_recipe
from .slug import mint_slug
from .technique import Technique, infer_technique
from .verbs import overlay_registry, spiritolo_verb_defs
from .version import CONVERTER_VERSION

__all__ = [
    "CONVERTER_VERSION",
    "mint_slug",
    "Technique",
    "infer_technique",
    "SourceRecipe",
    "SourceIngredient",
    "ConversionResult",
    "Ok",
    "Uncertain",
    "convert_recipe",
    "build_bundle",
    "validate_bundle",
    "spiritolo_verb_defs",
    "overlay_registry",
]

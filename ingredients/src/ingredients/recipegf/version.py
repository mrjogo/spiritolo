"""Version constant for the RecipeGF export stage.

Bump CONVERTER_VERSION when the JSON-LD → RecipeGF conversion changes in a
way that would produce a different bundle for the same input: technique
keyword table, step templates, slug-minting rules, ingredient/unit handling,
the id encoding version, or the set of spiritolo/ extension verbs emitted.

Bumping requires re-running the export stage (``ingredients.cli export``):
delete the export stage's ``job_items`` rows (or rely on the version bump
itself) so prior-version bundles fall back onto the export work queue.

This is a distinct axis from the recipe-id ``:vN`` encoding version (which
travels in the doc id) — a stage-logic bump does not necessarily change the
on-the-wire encoding. The two happen to both be "1" today.
"""

from __future__ import annotations

CONVERTER_VERSION = "v1"

# Reverse-DNS authority Spiritolo mints recipe ids under. The spiritolo
# namespace is reserved for VERBS, never for recipe authorities, so a bare
# ``spiritolo/<slug>`` recipe id is intentionally invalid — recipe ids always
# carry a reverse-DNS authority.
RECIPE_AUTHORITY = "com.spiritolo"

# Recipe-id encoding version (the ``:vN`` suffix). See docstring above.
RECIPE_ENCODING_VERSION = 1

# RecipeGF cocktail schema const the emitted docs declare.
RECIPE_SCHEMA = "recipegf/cocktail/v1"

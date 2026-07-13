"""Assemble a recipe's pin-2 RecipeGF bundle on demand from the relational rows.

The bundle is NOT stored — it is generated from `recipes` + `recipe_ingredients`
(+ the shared `ingredient_resolutions` for each ingredient's portable `ref`) +
`recipe_steps` + the in-repo `spiritolo/` verb-defs, every time it is asked for.
So a taxonomy correction (which only touches `ingredient_resolutions`) is
reflected the next time the bundle is generated, with no per-recipe rewrite. A
published bundle is frozen separately (see the export stage).

The ingredient `ref` is the reverse-DNS portable identity `com.spiritolo/<slug>`;
the drink id is `com.spiritolo/<slug>:v1`. Both are minted here from the shared
resolution + the recipe's slug, then the assembled bundle is validated against
`core ∪ spiritolo/` before it is returned — an invalid bundle is never emitted.
"""

from __future__ import annotations

from typing import Any

import psycopg
from recipegf import RecipeId, format_ingredient_ref, format_recipe_id
from recipegf.ingredient_ref import IngredientRef

from .bundle import build_bundle
from .slug import mint_slug
from .verbs import is_spiritolo_verb, verb_defs_for
from .version import RECIPE_AUTHORITY, RECIPE_ENCODING_VERSION, RECIPE_SCHEMA

# Ingredient names in recipe_ingredients join to ingredient_resolutions on this
# normalized key: lower(btrim(name)). It must match the map stage's
# normalization and the taxonomy_public recipe_count join.


class UnresolvedIngredient(LookupError):
    """A recipe ingredient has no resolved taxonomy slug, so a governed bundle
    cannot be minted yet. Callers treat this as "not ready", not a bug."""


def _recipe_slug(header: dict[str, Any]) -> str | None:
    """The kebab slug for the drink: the frozen `recipe_slug` if the recipe has
    one, else minted from the canonical (or raw) name."""
    return (
        header.get("recipe_slug")
        or mint_slug(header.get("canonical_name"))
        or mint_slug(header.get("title"))
    )


def _load_header(conn: psycopg.Connection, recipe_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        """
        select id, title, canonical_name, recipe_slug, equipment, source_url
        from recipes where id = %s
        """,
        (recipe_id,),
    ).fetchone()
    if row is None:
        return None
    return {
        "id": row[0], "title": row[1], "canonical_name": row[2],
        "recipe_slug": row[3], "equipment": list(row[4] or []), "source_url": row[5],
    }


def _load_ingredients(conn: psycopg.Connection, recipe_id: int) -> list[dict[str, Any]]:
    """RecipeGF ingredient objects for the recipe, each carrying its portable
    `ref` resolved through the SHARED name-keyed resolution.

    Raises :class:`UnresolvedIngredient` if any ingredient name has no
    taxonomy_slug — the bundle can't name a substance it hasn't governed.
    """
    rows = conn.execute(
        """
        select ri.position, ri.name, ri.amount, ri.amount_max, ri.unit,
               ri.modifiers, ir.taxonomy_slug
        from recipe_ingredients ri
        left join ingredient_resolutions ir
          on ir.normalized_name = lower(btrim(ri.name))
        where ri.recipe_id = %s
        order by ri.position
        """,
        (recipe_id,),
    ).fetchall()

    ingredients: list[dict[str, Any]] = []
    for position, name, amount, amount_max, unit, modifiers, slug in rows:
        if not slug:
            raise UnresolvedIngredient(
                f"ingredient at position {position} ({name!r}) has no resolved "
                "taxonomy slug"
            )
        quantity: dict[str, Any] = {"amount": float(amount) if amount is not None else 0.0,
                                    "unit": unit}
        if amount_max is not None:
            quantity["amount_max"] = float(amount_max)
        ingredient: dict[str, Any] = {
            "name": slug,
            "ref": format_ingredient_ref(IngredientRef(RECIPE_AUTHORITY, slug)),
            "quantity": quantity,
        }
        if modifiers:
            ingredient["modifiers"] = list(modifiers)
        ingredients.append(ingredient)
    return ingredients


def _load_steps(conn: psycopg.Connection, recipe_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        select verb, roles, result, modifiers
        from recipe_steps where recipe_id = %s order by step_index
        """,
        (recipe_id,),
    ).fetchall()
    steps: list[dict[str, Any]] = []
    for verb, roles, result, modifiers in rows:
        step: dict[str, Any] = {"verb": verb, **(roles or {}), "result": result}
        if modifiers:
            step["modifiers"] = list(modifiers)
        steps.append(step)
    return steps


def generate_bundle(
    conn: psycopg.Connection,
    recipe_id: int,
    *,
    imported_at: str,
) -> dict[str, Any] | None:
    """Assemble + validate the pin-2 bundle for one recipe, or ``None`` if the
    recipe row does not exist.

    The bundle is `{recipe, verbs, meta}`: `recipe` is the RecipeGF object with a
    `com.spiritolo/<slug>:v1` id and each ingredient carrying its `com.spiritolo/
    <slug>` ref; `verbs` are the `spiritolo/` defs its steps reference; `meta`
    carries the slug/source/imported_at triple. Raises
    :class:`UnresolvedIngredient` when an ingredient has no resolution yet and
    :class:`~.bundle.BundleError` on a seam violation (invalid slug/id, failed
    validation) — both are "not emittable", never a silent bad bundle.
    """
    header = _load_header(conn, recipe_id)
    if header is None:
        return None

    slug = _recipe_slug(header)
    if slug is None:
        from .bundle import BundleError

        raise BundleError(
            f"recipe {recipe_id} has no canonical name to mint a slug from"
        )

    ingredients = _load_ingredients(conn, recipe_id)
    steps = _load_steps(conn, recipe_id)

    recipe = {
        "schema": RECIPE_SCHEMA,
        "id": format_recipe_id(RecipeId(RECIPE_AUTHORITY, slug, RECIPE_ENCODING_VERSION)),
        "title": header.get("title") or header.get("canonical_name") or slug,
        "ingredients": ingredients,
        "equipment": header["equipment"],
        "steps": steps,
    }
    used = sorted({s["verb"] for s in steps if is_spiritolo_verb(s["verb"])})
    return build_bundle(
        recipe,
        verb_defs_for(used),
        slug=slug,
        source=header.get("source_url") or "",
        imported_at=imported_at,
    )

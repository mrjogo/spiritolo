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

from .bundle import BundleError, build_bundle
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


_HEADER_COLS = "id, title, canonical_name, recipe_slug, equipment, source_url"


def _header_from_row(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "id": row[0], "title": row[1], "canonical_name": row[2],
        "recipe_slug": row[3], "equipment": list(row[4] or []), "source_url": row[5],
    }


def _load_header(conn: psycopg.Connection, recipe_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        f"select {_HEADER_COLS} from recipes where id = %s", (recipe_id,)
    ).fetchone()
    return _header_from_row(row) if row is not None else None


# recipe_ingredients + resolution columns, shared by the single and bulk loads.
_INGREDIENT_COLS = (
    "ri.position, ri.name, ri.amount, ri.amount_max, ri.unit, ri.modifiers, "
    "ir.taxonomy_slug"
)
_INGREDIENT_JOIN = (
    "from recipe_ingredients ri "
    "left join ingredient_resolutions ir "
    "on ir.normalized_name = lower(btrim(ri.name))"
)


def _ingredients_from_rows(rows: list[tuple[Any, ...]]) -> list[dict[str, Any]]:
    """RecipeGF ingredient objects from ``(position, name, amount, amount_max,
    unit, modifiers, taxonomy_slug)`` rows (position order), each carrying its
    portable `ref` from the SHARED name-keyed resolution.

    Raises :class:`UnresolvedIngredient` if any row has no taxonomy_slug — the
    bundle can't name a substance it hasn't governed. Pure (no DB)."""
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


def _load_ingredients(conn: psycopg.Connection, recipe_id: int) -> list[dict[str, Any]]:
    """RecipeGF ingredient objects for one recipe (see _ingredients_from_rows)."""
    rows = conn.execute(
        f"select {_INGREDIENT_COLS} {_INGREDIENT_JOIN} "
        "where ri.recipe_id = %s order by ri.position",
        (recipe_id,),
    ).fetchall()
    return _ingredients_from_rows(rows)


def _steps_from_rows(rows: list[tuple[Any, ...]]) -> list[dict[str, Any]]:
    """RecipeGF steps from ``(verb, roles, result, modifiers)`` rows (step
    order). Pure (no DB)."""
    steps: list[dict[str, Any]] = []
    for verb, roles, result, modifiers in rows:
        step: dict[str, Any] = {"verb": verb, **(roles or {}), "result": result}
        if modifiers:
            step["modifiers"] = list(modifiers)
        steps.append(step)
    return steps


def _load_steps(conn: psycopg.Connection, recipe_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        "select verb, roles, result, modifiers "
        "from recipe_steps where recipe_id = %s order by step_index",
        (recipe_id,),
    ).fetchall()
    return _steps_from_rows(rows)


def _build_recipe_bundle(
    header: dict[str, Any],
    slug: str,
    ingredients: list[dict[str, Any]],
    steps: list[dict[str, Any]],
    imported_at: str,
) -> dict[str, Any]:
    """Assemble + validate the bundle from a header, its already-validated
    non-null ``slug``, and pre-loaded ingredients + steps, then build+validate.
    Raises :class:`~.bundle.BundleError` on a validation seam violation. Pure
    given its inputs (no DB).

    The slug-None check is the CALLER's job and must run BEFORE ingredients are
    assembled, so a slugless recipe raises BundleError ahead of any
    UnresolvedIngredient — preserving generate_bundle's original per-field
    order (slug first, then ingredients)."""
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
        raise BundleError(
            f"recipe {recipe_id} has no canonical name to mint a slug from"
        )
    ingredients = _load_ingredients(conn, recipe_id)
    steps = _load_steps(conn, recipe_id)
    return _build_recipe_bundle(header, slug, ingredients, steps, imported_at)


def generate_bundles(
    conn: psycopg.Connection,
    recipe_ids: list[int],
    *,
    imported_at: str,
) -> list[tuple[int, Any]]:
    """Batch form of :func:`generate_bundle`: three bulk reads for the whole
    chunk (headers, ingredients+resolution, steps) instead of three per recipe,
    then assemble each bundle from the pre-fetched rows with NO per-recipe DB
    read.

    Returns ``(recipe_id, result)`` in the given order, where result is the
    bundle dict, ``None`` if the recipe row vanished, or an
    ``UnresolvedIngredient`` / ``BundleError`` instance — caught per recipe so one
    unready/invalid recipe never aborts the batch. Each recipe's result is
    identical to what ``generate_bundle`` would return/raise for it."""
    ids = list(recipe_ids)
    if not ids:
        return []

    headers = {
        row[0]: _header_from_row(row)
        for row in conn.execute(
            f"select {_HEADER_COLS} from recipes where id = any(%s)", (ids,)
        ).fetchall()
    }
    ingredients_by_recipe: dict[int, list[tuple[Any, ...]]] = {}
    for row in conn.execute(
        f"select ri.recipe_id, {_INGREDIENT_COLS} {_INGREDIENT_JOIN} "
        "where ri.recipe_id = any(%s) order by ri.recipe_id, ri.position",
        (ids,),
    ).fetchall():
        ingredients_by_recipe.setdefault(row[0], []).append(row[1:])
    steps_by_recipe: dict[int, list[tuple[Any, ...]]] = {}
    for row in conn.execute(
        "select recipe_id, verb, roles, result, modifiers "
        "from recipe_steps where recipe_id = any(%s) order by recipe_id, step_index",
        (ids,),
    ).fetchall():
        steps_by_recipe.setdefault(row[0], []).append(row[1:])

    results: list[tuple[int, Any]] = []
    for recipe_id in ids:
        header = headers.get(recipe_id)
        if header is None:
            results.append((recipe_id, None))
            continue
        try:
            slug = _recipe_slug(header)
            if slug is None:
                raise BundleError(
                    f"recipe {recipe_id} has no canonical name to mint a slug from"
                )
            ingredients = _ingredients_from_rows(ingredients_by_recipe.get(recipe_id, []))
            steps = _steps_from_rows(steps_by_recipe.get(recipe_id, []))
            results.append(
                (recipe_id, _build_recipe_bundle(header, slug, ingredients, steps, imported_at))
            )
        except (UnresolvedIngredient, BundleError) as exc:
            results.append((recipe_id, exc))
    return results

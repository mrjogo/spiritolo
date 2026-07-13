"""convert stage — deterministic verb-frame conversion -> `recipe_steps`.

Runs the pure technique->template converter over each mapped recipe and persists
its RecipeGF verb-frame steps into `recipe_steps` plus the derived equipment and
minted slug onto `recipes`. Ingredient roles (needed to bucket ice/garnish/body)
are classified inline from the taxonomy default role — roles are ephemeral, not a
stored column. A recipe the converter can't yet emit records a `pending` run
(an ingredient isn't mapped) or `proposes_new` (needs a rules/technique review);
either way no steps are written. Versioned at `CONVERTER_VERSION`.
"""

from __future__ import annotations

import json
from typing import Any

import psycopg
from psycopg.types.json import Json

from ingredients.dedup.alias_layer import fetch_aliases_dict
from ingredients.dedup.role_classifier import classify_role
from ingredients.pipeline.stages import base, naming
from ingredients.recipegf.converter import (
    REASON_MISSING_ROLES,
    REASON_UNRESOLVED_INGREDIENT,
    Ok,
    SourceIngredient,
    SourceRecipe,
    convert_recipe,
)
from ingredients.recipegf.version import CONVERTER_VERSION

STAGE = "convert"

# Converter reasons that mean "an upstream stage isn't done" -> retry (pending);
# everything else is a genuine review item -> proposes_new.
_PENDING_REASONS = frozenset({REASON_UNRESOLVED_INGREDIENT, REASON_MISSING_ROLES})

_RESERVED_STEP_KEYS = {"verb", "result", "modifiers"}


def _source_ingredients(conn: psycopg.Connection, recipe_id: int) -> list[SourceIngredient]:
    """recipe_ingredients joined to their resolved slug + the taxonomy node's
    default role, with a role classified inline."""
    rows = conn.execute(
        """
        select ri.position, ri.raw_text, ri.amount, ri.amount_max, ri.unit,
               ri.name, ir.taxonomy_slug, n.default_role
        from recipe_ingredients ri
        left join ingredient_resolutions ir
          on ir.normalized_name = lower(btrim(ri.name))
        left join taxonomy_nodes n on n.slug = ir.taxonomy_slug
        where ri.recipe_id = %s
        order by ri.position
        """,
        (recipe_id,),
    ).fetchall()
    ingredients: list[SourceIngredient] = []
    for pos, raw, amount, amount_max, unit, name, slug, default_role in rows:
        role, _ = classify_role({
            "default_role": default_role,
            "amount": float(amount) if amount is not None else None,
            "unit": unit,
            "position": pos,
            "raw_text": raw,
        })
        ingredients.append(SourceIngredient(
            position=pos, raw_text=raw, name=name, slug=slug,
            amount=float(amount) if amount is not None else None,
            amount_max=float(amount_max) if amount_max is not None else None,
            unit=unit, role=role,
        ))
    return ingredients


def _persist_steps(conn: psycopg.Connection, recipe_id: int, ok: Ok) -> None:
    recipe = ok.recipe
    conn.execute("delete from recipe_steps where recipe_id = %s", (recipe_id,))
    for idx, step in enumerate(recipe.get("steps") or []):
        roles = {k: v for k, v in step.items() if k not in _RESERVED_STEP_KEYS}
        modifiers = step.get("modifiers") or []
        conn.execute(
            "insert into recipe_steps (recipe_id, step_index, verb, roles, result, modifiers) "
            "values (%s, %s, %s, %s::jsonb, %s, %s)",
            (recipe_id, idx, step["verb"], json.dumps(roles), step["result"], list(modifiers)),
        )
    conn.execute(
        "update recipes set equipment = %s, recipe_slug = %s where id = %s",
        (list(recipe.get("equipment") or []), ok.slug, recipe_id),
    )


def convert_stage_fn(job: dict[str, Any], conn: psycopg.Connection, providers: Any) -> dict[str, Any]:
    """Convert each queued recipe into verb-frame steps."""
    site, limit = base.scope(job)
    recipe_ids = base.recipe_queue(
        conn, stage=STAGE, version=CONVERTER_VERSION, site=site, limit=limit
    )
    aliases = fetch_aliases_dict(conn) if recipe_ids else {}
    counts = {"converted": 0, "pending": 0, "proposes_new": 0}

    for recipe_id in recipe_ids:
        header = conn.execute(
            "select title, canonical_name, source_url, source from recipes where id = %s",
            (recipe_id,),
        ).fetchone()
        if header is None:
            continue
        title, canonical_name, source_url, source = header
        if canonical_name is None:
            canonical_name = naming.canonical_name_for(conn, aliases, title)
            conn.execute(
                "update recipes set canonical_name = %s where id = %s",
                (canonical_name, recipe_id),
            )

        recipe = SourceRecipe(
            canonical_name=canonical_name or title or "",
            source_url=source_url or "",
            jsonld=source or {},
            ingredients=_source_ingredients(conn, recipe_id),
        )
        result = convert_recipe(recipe)

        if isinstance(result, Ok):
            _persist_steps(conn, recipe_id, result)
            outcome, counts_key = "resolved", "converted"
        elif result.reason in _PENDING_REASONS:
            outcome, counts_key = "pending", "pending"
        else:
            outcome, counts_key = "proposes_new", "proposes_new"
        counts[counts_key] += 1
        base.record(
            conn,
            recipe_id=recipe_id,
            stage=STAGE,
            version=CONVERTER_VERSION,
            outcome=outcome,
            method="deterministic",
            job_id=job.get("id"),
            payload=None if isinstance(result, Ok)
            else {"reason": result.reason, "detail": result.detail},
        )
    return counts

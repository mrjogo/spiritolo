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

STAGE = "convert-steps"

# Converter reasons that mean "an upstream stage isn't done" -> retry (pending);
# everything else is a genuine review item -> proposes_new.
_PENDING_REASONS = frozenset({REASON_UNRESOLVED_INGREDIENT, REASON_MISSING_ROLES})

_RESERVED_STEP_KEYS = {"verb", "result", "modifiers"}


# The join `_source_ingredients` runs per recipe, chunked into a single bulk
# fetch keyed on `ri.recipe_id = any(%s)`. Column order matches
# `_ingredient_from_row` below (recipe_id first, then the per-ingredient fields).
_INGREDIENTS_SQL = """
    select ri.recipe_id, ri.position, ri.raw_text, ri.amount, ri.amount_max,
           ri.unit, ri.name, ir.taxonomy_slug, n.default_role
    from recipe_ingredients ri
    left join ingredient_resolutions ir
      on ir.normalized_name = lower(btrim(ri.name))
    left join taxonomy_nodes n on n.slug = ir.taxonomy_slug
    where ri.recipe_id = any(%s)
    order by ri.recipe_id, ri.position
"""


def _ingredient_from_row(pos, raw, amount, amount_max, unit, name, slug, default_role) -> SourceIngredient:
    """Build one `SourceIngredient` from a fetched join row (role classified
    inline). Identical construction to the former per-recipe `_source_ingredients`."""
    role, _ = classify_role({
        "default_role": default_role,
        "amount": float(amount) if amount is not None else None,
        "unit": unit,
        "position": pos,
        "raw_text": raw,
    })
    return SourceIngredient(
        position=pos, raw_text=raw, name=name, slug=slug,
        amount=float(amount) if amount is not None else None,
        amount_max=float(amount_max) if amount_max is not None else None,
        unit=unit, role=role,
    )


def _fetch_ingredients(conn: psycopg.Connection, recipe_ids: list[int]) -> dict[int, list[SourceIngredient]]:
    """Bulk form of `_source_ingredients` for a chunk: one query over all ids,
    grouped by recipe_id (preserving position order)."""
    grouped: dict[int, list[SourceIngredient]] = {rid: [] for rid in recipe_ids}
    if not recipe_ids:
        return grouped
    rows = conn.execute(_INGREDIENTS_SQL, (recipe_ids,)).fetchall()
    for recipe_id, pos, raw, amount, amount_max, unit, name, slug, default_role in rows:
        grouped[recipe_id].append(
            _ingredient_from_row(pos, raw, amount, amount_max, unit, name, slug, default_role)
        )
    return grouped


def _step_rows(recipe_id: int, ok: Ok) -> list[tuple]:
    """recipe_steps insert param tuples for an Ok result (roles/modifiers
    extraction identical to the former `_persist_steps`)."""
    rows: list[tuple] = []
    for idx, step in enumerate(ok.recipe.get("steps") or []):
        roles = {k: v for k, v in step.items() if k not in _RESERVED_STEP_KEYS}
        modifiers = step.get("modifiers") or []
        rows.append((recipe_id, idx, step["verb"], json.dumps(roles), step["result"], list(modifiers)))
    return rows


def convert_stage_fn(
    job: dict[str, Any],
    conn: psycopg.Connection,
    providers: Any,
    *,
    chunk_size: int = base.CHUNK_SIZE,
) -> dict[str, Any]:
    """Convert each queued recipe into verb-frame steps.

    DB writes are batched per chunk: each chunk bulk-fetches headers +
    ingredients, runs the pure converter per recipe in queue order, then flushes
    the chunk's canonical-name/step/equipment writes and its ledger rows in one
    transaction.
    """
    site, limit = base.scope(job)
    if job.get("id"):
        recipe_ids = base.run_item_ids(conn, job_id=job["id"], stage=STAGE)
    else:
        recipe_ids = base.recipe_queue(
            conn, stage=STAGE, version=CONVERTER_VERSION, site=site, limit=limit
        )
    aliases = fetch_aliases_dict(conn) if recipe_ids else {}
    counts = {"converted": 0, "pending": 0, "proposes_new": 0}

    for chunk in base.chunked(recipe_ids, chunk_size):
        with conn.transaction():
            headers = {
                row[0]: row
                for row in conn.execute(
                    "select id, title, canonical_name, source_url, source "
                    "from recipes where id = any(%s)",
                    (chunk,),
                ).fetchall()
            }
            present_ids = [rid for rid in chunk if rid in headers]
            ingredients_by_recipe = _fetch_ingredients(conn, present_ids)

            canonical_updates: list[tuple] = []
            ok_ids: list[int] = []
            step_inserts: list[tuple] = []
            equipment_updates: list[tuple] = []
            records: list[dict[str, Any]] = []

            for recipe_id in chunk:
                header = headers.get(recipe_id)
                if header is None:
                    continue
                _id, title, canonical_name, source_url, source = header
                if canonical_name is None:
                    canonical_name = naming.canonical_name_for(conn, aliases, title)
                    canonical_updates.append((canonical_name, recipe_id))

                recipe = SourceRecipe(
                    canonical_name=canonical_name or title or "",
                    source_url=source_url or "",
                    jsonld=source or {},
                    ingredients=ingredients_by_recipe.get(recipe_id, []),
                )
                result = convert_recipe(recipe)

                if isinstance(result, Ok):
                    ok_ids.append(recipe_id)
                    step_inserts.extend(_step_rows(recipe_id, result))
                    equipment_updates.append(
                        (list(result.recipe.get("equipment") or []), result.slug, recipe_id)
                    )
                    outcome, counts_key = "resolved", "converted"
                elif result.reason in _PENDING_REASONS:
                    outcome, counts_key = "pending", "pending"
                else:
                    outcome, counts_key = "proposes_new", "proposes_new"
                counts[counts_key] += 1
                records.append({
                    "recipe_id": recipe_id,
                    "stage": STAGE,
                    "version": CONVERTER_VERSION,
                    "outcome": outcome,
                    "method": "deterministic",
                    "job_id": job.get("id"),
                    "payload": None if isinstance(result, Ok)
                    else {"reason": result.reason, "detail": result.detail},
                })

            with conn.cursor() as cur:
                if canonical_updates:
                    cur.executemany(
                        "update recipes set canonical_name = %s where id = %s",
                        canonical_updates,
                    )
                if ok_ids:
                    cur.execute(
                        "delete from recipe_steps where recipe_id = any(%s)", (ok_ids,)
                    )
                if step_inserts:
                    cur.executemany(
                        "insert into recipe_steps (recipe_id, step_index, verb, roles, result, modifiers) "
                        "values (%s, %s, %s, %s::jsonb, %s, %s)",
                        step_inserts,
                    )
                if equipment_updates:
                    cur.executemany(
                        "update recipes set equipment = %s, recipe_slug = %s where id = %s",
                        equipment_updates,
                    )
            base.record_many(conn, records)
            base.finalize_run(
                conn, stage=STAGE, version=CONVERTER_VERSION,
                ids=[str(r) for r in chunk],
            )
    return counts

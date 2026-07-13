"""parse stage — deterministic ingredient parser → `recipe_ingredients` rows.

For each queued recipe it parses every `source.recipeIngredient` string with the
deterministic parser (the stage's deterministic tier) into a RecipeGF ingredient
row: name + (amount, amount_max, unit) + string[] modifiers + raw_text. The rows
replace any prior parse for that recipe, and one `stage_runs` row records the
outcome at `PARSER_VERSION`. A row the parser can't structure is still stored
(name/amount null, raw_text preserved) so nothing is silently dropped and the
map/export stages can see it.

Deterministic today; an LLM tier for the abstained rows slots in behind the same
provider-chain seam (the `providers` arg) without changing this stage's writes.
"""

from __future__ import annotations

from typing import Any

import psycopg

from ingredients.parser import PARSER_VERSION, parse

from . import base

STAGE = "parse"


def _recipe_ingredient_strings(source: dict[str, Any] | None) -> list[str]:
    """The `recipeIngredient` strings from a recipe's JSON-LD (non-strings and
    empties dropped, order preserved)."""
    if not source:
        return []
    raw = source.get("recipeIngredient") or source.get("recipeIngredients") or []
    if isinstance(raw, str):
        raw = [raw]
    return [s for s in raw if isinstance(s, str) and s.strip()]


def _write_rows(conn: psycopg.Connection, recipe_id: int, strings: list[str], site: str | None) -> int:
    """Replace `recipe_ingredients` for one recipe with a fresh parse. Returns
    the number of rows that parsed to a structured name."""
    conn.execute("delete from recipe_ingredients where recipe_id = %s", (recipe_id,))
    structured = 0
    for position, raw in enumerate(strings):
        result = parse(raw, site=site)
        modifiers = [result.modifier] if result.modifier else []
        conn.execute(
            """
            insert into recipe_ingredients
                (recipe_id, position, name, amount, amount_max, unit, modifiers, raw_text)
            values (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (recipe_id, position, result.name, result.amount, result.amount_max,
             result.unit, modifiers, result.raw_text),
        )
        if result.name:
            structured += 1
    return structured


def parse_stage_fn(job: dict[str, Any], conn: psycopg.Connection, providers: Any) -> dict[str, Any]:
    """Parse every queued recipe's ingredients into `recipe_ingredients`."""
    site, limit = base.scope(job)
    recipe_ids = base.recipe_queue(
        conn, stage=STAGE, version=PARSER_VERSION, site=site, limit=limit
    )
    counts = {"parsed": 0, "empty": 0}
    for recipe_id in recipe_ids:
        row = conn.execute(
            "select source, site from recipes where id = %s", (recipe_id,)
        ).fetchone()
        source, rsite = (row[0], row[1]) if row else (None, site)
        strings = _recipe_ingredient_strings(source)
        structured = _write_rows(conn, recipe_id, strings, rsite)
        outcome = "resolved" if structured else "abstain"
        counts["parsed" if structured else "empty"] += 1
        base.record(
            conn,
            recipe_id=recipe_id,
            stage=STAGE,
            version=PARSER_VERSION,
            outcome=outcome,
            method="deterministic",
            job_id=job.get("id"),
            payload={"ingredient_rows": len(strings), "structured": structured},
        )
    return counts

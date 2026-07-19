"""parse stage — deterministic ingredient parser → `recipe_ingredients` rows.

For each queued recipe it parses every `source.recipeIngredient` string with the
deterministic parser (the stage's deterministic tier) into a RecipeGF ingredient
row: name + (amount, amount_max, unit) + string[] modifiers + raw_text. The rows
replace any prior parse for that recipe, and one `job_items` row records the
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

STAGE = "parse-ingredients"


def _recipe_ingredient_strings(source: dict[str, Any] | None) -> list[str]:
    """The `recipeIngredient` strings from a recipe's JSON-LD (non-strings and
    empties dropped, order preserved)."""
    if not source:
        return []
    raw = source.get("recipeIngredient") or source.get("recipeIngredients") or []
    if isinstance(raw, str):
        raw = [raw]
    return [s for s in raw if isinstance(s, str) and s.strip()]


_INSERT_ROWS_SQL = """
    insert into recipe_ingredients
        (recipe_id, position, name, amount, amount_max, unit, modifiers, raw_text)
    values (%s, %s, %s, %s, %s, %s, %s, %s)
"""


def _parse_rows(recipe_id: int, strings: list[str], site: str | None) -> tuple[list[tuple], int]:
    """Parse one recipe's ingredient strings into `recipe_ingredients` insert
    tuples. Returns (tuples, structured_count) — the count is rows that parsed
    to a structured name. Pure/CPU-only; no DB I/O."""
    tuples: list[tuple] = []
    structured = 0
    for position, raw in enumerate(strings):
        result = parse(raw, site=site)
        modifiers = [result.modifier] if result.modifier else []
        tuples.append(
            (recipe_id, position, result.name, result.amount, result.amount_max,
             result.unit, modifiers, result.raw_text)
        )
        if result.name:
            structured += 1
    return tuples, structured


def parse_stage_fn(
    job: dict[str, Any],
    conn: psycopg.Connection,
    providers: Any,
    *,
    chunk_size: int = base.CHUNK_SIZE,
) -> dict[str, Any]:
    """Parse every queued recipe's ingredients into `recipe_ingredients`.

    DB writes are batched per chunk: each chunk bulk-fetches its recipes, parses
    them in-memory, then in ONE transaction deletes the chunk's prior rows, bulk-
    inserts the fresh rows, and UPSERTs the chunk's `job_items` in one executemany.
    """
    site, limit = base.scope(job)
    if job.get("id"):
        recipe_ids = base.run_item_ids(conn, job_id=job["id"], stage=STAGE)
    else:
        recipe_ids = base.recipe_queue(
            conn, stage=STAGE, version=PARSER_VERSION, site=site, limit=limit
        )
    counts = {"parsed": 0, "empty": 0}
    for chunk in base.chunked(recipe_ids, chunk_size):
        with conn.transaction():
            rows = conn.execute(
                "select id, source, site from recipes where id = any(%s)", (chunk,)
            ).fetchall()
            by_id = {r[0]: (r[1], r[2]) for r in rows}

            insert_tuples: list[tuple] = []
            records: list[dict[str, Any]] = []
            for recipe_id in chunk:
                source, rsite = by_id.get(recipe_id, (None, site))
                strings = _recipe_ingredient_strings(source)
                row_tuples, structured = _parse_rows(recipe_id, strings, rsite)
                insert_tuples.extend(row_tuples)
                outcome = "resolved" if structured else "abstain"
                counts["parsed" if structured else "empty"] += 1
                records.append({
                    "recipe_id": recipe_id,
                    "stage": STAGE,
                    "version": PARSER_VERSION,
                    "outcome": outcome,
                    "method": "deterministic",
                    "job_id": job.get("id"),
                    "payload": {"ingredient_rows": len(strings), "structured": structured},
                })

            conn.execute(
                "delete from recipe_ingredients where recipe_id = any(%s)", (chunk,)
            )
            if insert_tuples:
                with conn.cursor() as cur:
                    cur.executemany(_INSERT_ROWS_SQL, insert_tuples)
            base.record_many(conn, records)
            base.finalize_run(
                conn, stage=STAGE, version=PARSER_VERSION,
                ids=[str(r) for r in chunk],
            )
    return counts

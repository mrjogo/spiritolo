"""export stage — generate the pin-2 bundle on demand and freeze it.

For each queued recipe it generates the bundle from the current rows + shared
resolution + verb-defs (`generate_bundle`), then FREEZES that snapshot into
`recipe_exports` (keyed by recipe + converter version) — the live representation
stays generated-on-demand and current with the taxonomy; only the published
snapshot is frozen. The minted slug is written back to `recipes.recipe_slug` so
the drink's identity is stable across regenerations. One `job_items` row records
the outcome at `CONVERTER_VERSION`: `resolved` (frozen), `pending` (an
ingredient isn't resolved yet — comes back after the map stage), or `failed`
(a seam violation, e.g. an unbuildable recipe).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import psycopg
from psycopg.types.json import Json

from ingredients.recipegf.bundle import BundleError
from ingredients.recipegf.generate import UnresolvedIngredient, generate_bundles
from ingredients.recipegf.version import CONVERTER_VERSION

from . import base

STAGE = "export-recipegf"

# _freeze's two statements, hoisted so a chunk can flush them with executemany.
_FREEZE_EXPORT_SQL = """
    insert into recipe_exports
        (recipe_id, recipe_slug, recipe_ref, converter_version, bundle)
    values (%s, %s, %s, %s, %s)
    on conflict (recipe_id, converter_version) do update set
        recipe_slug = excluded.recipe_slug,
        recipe_ref  = excluded.recipe_ref,
        bundle      = excluded.bundle,
        exported_at = now()
"""

_FREEZE_SLUG_SQL = (
    "update recipes set recipe_slug = %s where id = %s and recipe_slug is distinct from %s"
)


def export_stage_fn(
    job: dict[str, Any],
    conn: psycopg.Connection,
    providers: Any,
    *,
    chunk_size: int = base.CHUNK_SIZE,
) -> dict[str, Any]:
    """Generate + freeze the bundle for every queued recipe.

    Both halves are batched per chunk: ``generate_bundles`` does three bulk reads
    for the chunk (no per-recipe reads), and the recipe_exports UPSERTs, slug
    UPDATEs, and ledger rows flush together in one transaction.
    """
    site, limit = base.scope(job)
    if job.get("id"):
        recipe_ids = base.run_item_ids(conn, job_id=job["id"], stage=STAGE)
    else:
        recipe_ids = base.recipe_queue(
            conn, stage=STAGE, version=CONVERTER_VERSION, site=site, limit=limit
        )
    imported_at = datetime.now(timezone.utc).isoformat()
    counts = {"exported": 0, "pending": 0, "failed": 0}

    for chunk in base.chunked(recipe_ids, chunk_size):
        export_rows: list[tuple[Any, ...]] = []
        slug_updates: list[tuple[Any, ...]] = []
        records: list[dict[str, Any]] = []
        with conn.transaction():
            for recipe_id, result in generate_bundles(conn, chunk, imported_at=imported_at):
                if result is None:
                    continue  # recipe vanished between queue and process
                error_code: str | None = None
                if isinstance(result, UnresolvedIngredient):
                    outcome = "pending"
                    counts["pending"] += 1
                elif isinstance(result, BundleError):
                    outcome = "failed"
                    error_code = "bundle_error"
                    counts["failed"] += 1
                else:
                    bundle = result
                    recipe = bundle["recipe"]
                    slug = bundle["meta"]["slug"]
                    export_rows.append(
                        (recipe_id, slug, recipe["id"], CONVERTER_VERSION, Json(bundle))
                    )
                    slug_updates.append((slug, recipe_id, slug))
                    outcome = "resolved"
                    counts["exported"] += 1
                records.append(
                    {
                        "recipe_id": recipe_id,
                        "stage": STAGE,
                        "version": CONVERTER_VERSION,
                        "outcome": outcome,
                        "method": "deterministic",
                        "job_id": job.get("id"),
                        "error_code": error_code,
                    }
                )
            if export_rows:
                with conn.cursor() as cur:
                    cur.executemany(_FREEZE_EXPORT_SQL, export_rows)
                    cur.executemany(_FREEZE_SLUG_SQL, slug_updates)
            base.record_many(conn, records)
    return counts

"""export stage — generate the pin-2 bundle on demand and freeze it.

For each queued recipe it generates the bundle from the current rows + shared
resolution + verb-defs (`generate_bundle`), then FREEZES that snapshot into
`recipe_exports` (keyed by recipe + converter version) — the live representation
stays generated-on-demand and current with the taxonomy; only the published
snapshot is frozen. The minted slug is written back to `recipes.recipe_slug` so
the drink's identity is stable across regenerations. One `stage_runs` row records
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
from ingredients.recipegf.generate import UnresolvedIngredient, generate_bundle
from ingredients.recipegf.version import CONVERTER_VERSION

from . import base

STAGE = "export"


def _freeze(conn: psycopg.Connection, recipe_id: int, bundle: dict[str, Any]) -> None:
    """UPSERT the frozen bundle for (recipe, converter version) and pin the slug
    back onto the recipe."""
    recipe = bundle["recipe"]
    slug = bundle["meta"]["slug"]
    conn.execute(
        """
        insert into recipe_exports
            (recipe_id, recipe_slug, recipe_ref, converter_version, bundle)
        values (%s, %s, %s, %s, %s)
        on conflict (recipe_id, converter_version) do update set
            recipe_slug = excluded.recipe_slug,
            recipe_ref  = excluded.recipe_ref,
            bundle      = excluded.bundle,
            exported_at = now()
        """,
        (recipe_id, slug, recipe["id"], CONVERTER_VERSION, Json(bundle)),
    )
    conn.execute(
        "update recipes set recipe_slug = %s where id = %s and recipe_slug is distinct from %s",
        (slug, recipe_id, slug),
    )


def export_stage_fn(job: dict[str, Any], conn: psycopg.Connection, providers: Any) -> dict[str, Any]:
    """Generate + freeze the bundle for every queued recipe."""
    site, limit = base.scope(job)
    recipe_ids = base.recipe_queue(
        conn, stage=STAGE, version=CONVERTER_VERSION, site=site, limit=limit
    )
    imported_at = datetime.now(timezone.utc).isoformat()
    counts = {"exported": 0, "pending": 0, "failed": 0}

    for recipe_id in recipe_ids:
        outcome: str
        error_code: str | None = None
        try:
            bundle = generate_bundle(conn, recipe_id, imported_at=imported_at)
            if bundle is None:
                continue  # recipe vanished between queue and process
            _freeze(conn, recipe_id, bundle)
            outcome = "resolved"
            counts["exported"] += 1
        except UnresolvedIngredient:
            outcome = "pending"
            counts["pending"] += 1
        except BundleError as exc:
            outcome = "failed"
            error_code = "bundle_error"
            counts["failed"] += 1
            _ = exc
        base.record(
            conn,
            recipe_id=recipe_id,
            stage=STAGE,
            version=CONVERTER_VERSION,
            outcome=outcome,
            method="deterministic",
            job_id=job.get("id"),
            error_code=error_code,
        )
    return counts

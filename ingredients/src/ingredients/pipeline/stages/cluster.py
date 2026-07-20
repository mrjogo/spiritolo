"""role/cluster stage — pure dedup over taxonomy slugs -> cluster identity.

For each queued recipe it classifies ingredient roles, rolls each resolved slug
up to the curated antichain, and hashes ``(canonical_name, role-tagged antichain
slug set)`` into a cluster key (and a finer variant key). Roles are ephemeral
(classified inline, never stored); the resolved slug comes from the shared
``ingredient_resolutions``. It writes ``recipes.cluster_id`` / ``variant_key``
and UPSERTs the ``recipe_clusters`` row, recomputing counts at the end. Versioned
at ``DEDUP_VERSION``; one ``job_items`` row per recipe.
"""

from __future__ import annotations

from typing import Any

import psycopg
from psycopg.types.json import Json

from ingredients.dedup.alias_layer import fetch_aliases_dict
from ingredients.dedup.cluster import (
    compute_cluster_key,
    compute_variant_key,
    ingredient_set_json,
)
from ingredients.dedup.role_classifier import classify_role
from ingredients.dedup.rollup import roll_up_to_antichain
from ingredients.dedup.version import DEDUP_VERSION
from ingredients.pipeline.stages import base, naming

STAGE = "cluster-recipes"


def _node_meta(conn: psycopg.Connection) -> dict[int, str]:
    """taxonomy node id -> slug snapshot for antichain-slug lookup."""
    return {
        r[0]: r[1]
        for r in conn.execute("select id, slug from taxonomy_nodes").fetchall()
    }


_INGREDIENTS_SQL = """
    select ri.recipe_id, ri.position, ri.raw_text, ri.amount, ri.amount_max, ri.unit,
           ir.taxonomy_slug, n.id, n.default_role, n.is_defining_garnish
    from recipe_ingredients ri
    left join ingredient_resolutions ir
      on ir.normalized_name = lower(btrim(ri.name))
    left join taxonomy_nodes n on n.slug = ir.taxonomy_slug
    where ri.recipe_id = any(%s)
    order by ri.recipe_id, ri.position
"""


def _ingredients_from_rows(
    conn: psycopg.Connection,
    rows: list[tuple[Any, ...]],
    node_meta: dict[int, str],
    rollup_cache: dict[int, int],
) -> list[dict[str, Any]]:
    """Build the per-ingredient dicts for ONE recipe from its already-fetched
    join rows (position, raw_text, amount, amount_max, unit, taxonomy_slug,
    node_id, default_role, is_defining_garnish). Identical classify_role +
    antichain-rollup logic to the original per-recipe query."""
    out: list[dict[str, Any]] = []
    for pos, raw, amount, amount_max, unit, slug, node_id, default_role, defining_garnish in rows:
        role, _ = classify_role({
            "default_role": default_role,
            "amount": float(amount) if amount is not None else None,
            "unit": unit,
            "position": pos,
            "raw_text": raw,
        })
        antichain_slug: str | None = None
        if node_id is not None:
            antichain_id = rollup_cache.get(node_id)
            if antichain_id is None:
                antichain_id = roll_up_to_antichain(conn, node_id)
                rollup_cache[node_id] = antichain_id
            antichain_slug = node_meta.get(antichain_id)
        out.append({
            "role": role,
            "antichain_slug": antichain_slug,
            "taxonomy_slug": slug,
            "amount": float(amount) if amount is not None else None,
            "amount_max": float(amount_max) if amount_max is not None else None,
            "unit": unit,
            "is_defining_garnish": bool(defining_garnish) if defining_garnish is not None else False,
        })
    return out


_UPSERT_CLUSTER_SQL = """
    insert into recipe_clusters (cluster_key, canonical_name, ingredient_set, version)
    values (%s, %s, %s, %s)
    on conflict (cluster_key) do update set
        canonical_name = excluded.canonical_name,
        ingredient_set = excluded.ingredient_set,
        version        = excluded.version
"""

_UPDATE_CANONICAL_SQL = "update recipes set canonical_name = %s where id = %s"
_UPDATE_CLUSTER_SQL = "update recipes set cluster_id = %s, variant_key = %s where id = %s"


def _recompute_counts(conn: psycopg.Connection) -> None:
    conn.execute(
        """
        update recipe_clusters c set
            recipe_count = sub.recipe_count,
            source_count = sub.source_count,
            representative_recipe_id = sub.rep_id
        from (
            select cluster_id,
                   count(*)             as recipe_count,
                   count(distinct site) as source_count,
                   min(id)              as rep_id
            from recipes
            where cluster_id is not null
            group by cluster_id
        ) sub
        where c.cluster_key = sub.cluster_id
        """
    )


def cluster_stage_fn(
    job: dict[str, Any],
    conn: psycopg.Connection,
    providers: Any,
    *,
    chunk_size: int = base.CHUNK_SIZE,
) -> dict[str, Any]:
    """Cluster every queued recipe by its role-tagged antichain slug set.

    Per-recipe DB writes are batched: each chunk of recipes is fetched, computed,
    and flushed in one transaction with bulk statements + one ledger executemany.
    All once-per-run setup (aliases / node_meta / rollup_cache) is loaded before
    the loop and shared across chunks; recipes are processed in queue order.
    """
    site, limit = base.scope(job)
    job_id = job.get("id")
    if job_id:
        recipe_ids = base.run_item_ids(conn, job_id=job_id, stage=STAGE)
    else:
        recipe_ids = base.recipe_queue(
            conn, stage=STAGE, version=DEDUP_VERSION, site=site, limit=limit
        )
    if not recipe_ids:
        return {"clustered": 0}

    aliases = fetch_aliases_dict(conn)
    node_meta = _node_meta(conn)
    rollup_cache: dict[int, int] = {}
    counts = {"clustered": 0, "skipped": 0, "pending": 0}

    for chunk in base.chunked(recipe_ids, chunk_size):
        # Recipes with any provisional-node ingredient aren't eligible yet — their
        # taxonomy identity isn't final, so clustering them now would freeze a
        # wrong key. Gate before any per-recipe rollup/hash work.
        blocked = base.recipes_with_provisional_ingredients(conn, chunk)
        # Bulk fetch headers, skipping absent ids.
        headers = {
            r[0]: (r[1], r[2])
            for r in conn.execute(
                "select id, title, canonical_name from recipes where id = any(%s)",
                (chunk,),
            ).fetchall()
        }
        # Bulk fetch ingredients, grouped by recipe_id, position-ordered.
        by_recipe: dict[int, list[tuple[Any, ...]]] = {}
        for row in conn.execute(_INGREDIENTS_SQL, (chunk,)).fetchall():
            by_recipe.setdefault(row[0], []).append(row[1:])

        canonical_updates: list[tuple[Any, ...]] = []
        cluster_upserts: list[tuple[Any, ...]] = []
        recipe_updates: list[tuple[Any, ...]] = []
        records: list[dict[str, Any]] = []

        for recipe_id in chunk:
            header = headers.get(recipe_id)
            if header is None:
                continue
            if recipe_id in blocked:
                counts["pending"] += 1
                records.append({
                    "recipe_id": recipe_id, "stage": STAGE, "version": DEDUP_VERSION,
                    "outcome": "pending", "method": "deterministic", "job_id": job_id,
                })
                continue
            title, canonical_name = header
            if canonical_name is None:
                canonical_name = naming.canonical_name_for(conn, aliases, title)
                canonical_updates.append((canonical_name, recipe_id))
            if not canonical_name:
                counts["skipped"] += 1
                records.append({
                    "recipe_id": recipe_id, "stage": STAGE, "version": DEDUP_VERSION,
                    "outcome": "abstain", "method": "deterministic", "job_id": job_id,
                })
                continue

            ingredients = _ingredients_from_rows(
                conn, by_recipe.get(recipe_id, []), node_meta, rollup_cache
            )
            cluster_key = compute_cluster_key(canonical_name, ingredients)
            variant_key = compute_variant_key(cluster_key, ingredients)
            cluster_upserts.append(
                (cluster_key, canonical_name, Json(ingredient_set_json(ingredients)), DEDUP_VERSION)
            )
            recipe_updates.append((cluster_key, variant_key, recipe_id))
            counts["clustered"] += 1
            records.append({
                "recipe_id": recipe_id, "stage": STAGE, "version": DEDUP_VERSION,
                "outcome": "resolved", "method": "deterministic", "job_id": job_id,
            })

        with conn.transaction():
            with conn.cursor() as cur:
                if canonical_updates:
                    cur.executemany(_UPDATE_CANONICAL_SQL, canonical_updates)
                if cluster_upserts:
                    cur.executemany(_UPSERT_CLUSTER_SQL, cluster_upserts)
                if recipe_updates:
                    cur.executemany(_UPDATE_CLUSTER_SQL, recipe_updates)
            base.record_many(conn, records)
            base.finalize_run(
                conn, stage=STAGE, version=DEDUP_VERSION,
                ids=[str(r) for r in chunk],
            )

    _recompute_counts(conn)
    return counts

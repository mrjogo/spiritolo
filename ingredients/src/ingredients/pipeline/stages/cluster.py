"""role/cluster stage — pure dedup over taxonomy slugs -> cluster identity.

For each queued recipe it classifies ingredient roles, rolls each resolved slug
up to the curated antichain, and hashes ``(canonical_name, role-tagged antichain
slug set)`` into a cluster key (and a finer variant key). Roles are ephemeral
(classified inline, never stored); the resolved slug comes from the shared
``ingredient_resolutions``. It writes ``recipes.cluster_id`` / ``variant_key``
and UPSERTs the ``recipe_clusters`` row, recomputing counts at the end. Versioned
at ``DEDUP_VERSION``; one ``stage_runs`` row per recipe.
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

STAGE = "cluster"


def _node_meta(conn: psycopg.Connection) -> dict[int, str]:
    """taxonomy node id -> slug snapshot for antichain-slug lookup."""
    return {
        r[0]: r[1]
        for r in conn.execute("select id, slug from taxonomy_nodes").fetchall()
    }


def _recipe_ingredients(
    conn: psycopg.Connection,
    recipe_id: int,
    node_meta: dict[int, str],
    rollup_cache: dict[int, int],
) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        select ri.position, ri.raw_text, ri.amount, ri.amount_max, ri.unit,
               ir.taxonomy_slug, n.id, n.default_role, n.is_defining_garnish
        from recipe_ingredients ri
        left join ingredient_resolutions ir
          on ir.normalized_name = lower(btrim(ri.name))
        left join taxonomy_nodes n on n.slug = ir.taxonomy_slug
        where ri.recipe_id = %s
        order by ri.position
        """,
        (recipe_id,),
    ).fetchall()
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


def _upsert_cluster(
    conn: psycopg.Connection, cluster_key: str, canonical_name: str,
    ingredients: list[dict[str, Any]],
) -> None:
    conn.execute(
        """
        insert into recipe_clusters (cluster_key, canonical_name, ingredient_set, version)
        values (%s, %s, %s, %s)
        on conflict (cluster_key) do update set
            canonical_name = excluded.canonical_name,
            ingredient_set = excluded.ingredient_set,
            version        = excluded.version
        """,
        (cluster_key, canonical_name, Json(ingredient_set_json(ingredients)), DEDUP_VERSION),
    )


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


def cluster_stage_fn(job: dict[str, Any], conn: psycopg.Connection, providers: Any) -> dict[str, Any]:
    """Cluster every queued recipe by its role-tagged antichain slug set."""
    site, limit = base.scope(job)
    recipe_ids = base.recipe_queue(
        conn, stage=STAGE, version=DEDUP_VERSION, site=site, limit=limit
    )
    if not recipe_ids:
        return {"clustered": 0}

    aliases = fetch_aliases_dict(conn)
    node_meta = _node_meta(conn)
    rollup_cache: dict[int, int] = {}
    counts = {"clustered": 0, "skipped": 0}

    for recipe_id in recipe_ids:
        header = conn.execute(
            "select title, canonical_name from recipes where id = %s", (recipe_id,)
        ).fetchone()
        if header is None:
            continue
        title, canonical_name = header
        if canonical_name is None:
            canonical_name = naming.canonical_name_for(conn, aliases, title)
            conn.execute(
                "update recipes set canonical_name = %s where id = %s",
                (canonical_name, recipe_id),
            )
        if not canonical_name:
            counts["skipped"] += 1
            base.record(conn, recipe_id=recipe_id, stage=STAGE, version=DEDUP_VERSION,
                        outcome="abstain", method="deterministic", job_id=job.get("id"))
            continue

        ingredients = _recipe_ingredients(conn, recipe_id, node_meta, rollup_cache)
        cluster_key = compute_cluster_key(canonical_name, ingredients)
        variant_key = compute_variant_key(cluster_key, ingredients)
        _upsert_cluster(conn, cluster_key, canonical_name, ingredients)
        conn.execute(
            "update recipes set cluster_id = %s, variant_key = %s where id = %s",
            (cluster_key, variant_key, recipe_id),
        )
        counts["clustered"] += 1
        base.record(conn, recipe_id=recipe_id, stage=STAGE, version=DEDUP_VERSION,
                    outcome="resolved", method="deterministic", job_id=job.get("id"))

    _recompute_counts(conn)
    return counts

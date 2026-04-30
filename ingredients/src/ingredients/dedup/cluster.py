"""Cluster + variant key derivation, plus the cluster compute orchestrator.

Pure key functions (compute_cluster_key, compute_variant_key, in_cluster_key)
are at the top; the DB-touching orchestrator (run_cluster_compute) is at
the bottom.

The allow-list (INCLUDED_ROLES) is the invariant the spec calls out: a
future role added elsewhere in the codebase does NOT enter the cluster
key without an explicit addition here AND a DEDUP_VERSION bump.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections import Counter
from typing import Any

import psycopg

from .role_classifier import classify_role
from .rollup import roll_up_to_antichain
from .version import DEDUP_VERSION

log = logging.getLogger("dedup.cluster")

INCLUDED_ROLES = frozenset({
    "base_spirit", "modifier", "citrus", "sweetener",
    "bitters", "dilution", "wash", "other",
})


def in_cluster_key(ing: dict[str, Any]) -> bool:
    # Unresolved ingredient (D's mapper hasn't mapped it) → exclude per spec:
    # "treat as role='other' and exclude from the cluster key (with a flag for
    # audit)." Without this guard, sorted() on tuples containing None would
    # raise TypeError under real-world data where some rows have
    # taxonomy_node_id IS NULL.
    if ing.get("antichain_node_id") is None:
        return False
    role = ing.get("role")
    if role == "garnish":
        return bool(ing.get("is_defining_garnish"))
    return role in INCLUDED_ROLES


def _canonical_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def compute_cluster_key(canonical_name: str, ingredients: list[dict[str, Any]]) -> str:
    """Cluster identity = sha256(canonical_name, sorted set of (role, antichain_node_id))."""
    members = sorted(
        (ing["role"], ing["antichain_node_id"])
        for ing in ingredients
        if in_cluster_key(ing)
    )
    payload = _canonical_json({
        "canonical_name": canonical_name,
        "ingredients": members,
    })
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def compute_variant_key(cluster_key: str, ingredients: list[dict[str, Any]]) -> str:
    """Variant identity adds taxonomy_node_id (specific node), amount,
    amount_max, unit. Two recipes share a variant iff their amounts +
    brands match within the same cluster.
    """
    members = sorted(
        (
            ing["role"],
            ing["antichain_node_id"],
            ing.get("taxonomy_node_id"),
            ing.get("amount"),
            ing.get("amount_max"),
            ing.get("unit"),
        )
        for ing in ingredients
        if in_cluster_key(ing)
    )
    payload = _canonical_json({
        "cluster_key": cluster_key,
        "ingredients": members,
    })
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _fetch_recipe_ingredients(
    conn: psycopg.Connection, recipe_id: int,
) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        select ri.id,
               ri.position,
               ri.raw_text,
               ri.amount,
               ri.amount_max,
               ri.unit,
               ri.taxonomy_node_id,
               n.slug,
               n.role_default,
               n.is_defining_garnish
        from recipe_ingredients ri
        left join taxonomy_nodes n on n.id = ri.taxonomy_node_id
        where ri.recipe_id = %s
        order by ri.position
        """,
        (recipe_id,),
    ).fetchall()
    return [
        {
            "id": r[0],
            "position": r[1],
            "raw_text": r[2],
            "amount": float(r[3]) if r[3] is not None else None,
            "amount_max": float(r[4]) if r[4] is not None else None,
            "unit": r[5],
            "taxonomy_node_id": r[6],
            "taxonomy_node_slug": r[7],
            "role_default": r[8],
            "is_defining_garnish": bool(r[9]) if r[9] is not None else False,
        }
        for r in rows
    ]


def _fetch_recipes_to_cluster(
    conn: psycopg.Connection, *, dedup_version: str,
    site: str | None, limit: int | None,
) -> list[tuple[int, str, str]]:
    params: list[object] = [dedup_version]
    site_clause = ""
    if site is not None:
        site_clause = "and r.site = %s"
        params.append(site)

    sql = f"""
        select r.id, r.canonical_name, r.name
        from recipes r
        where r.canonical_name is not null
          and (r.dedup_version is null or r.dedup_version <> %s)
          {site_clause}
        order by r.id
    """
    if limit is not None:
        sql += " limit %s"
        params.append(limit)
    return [(row[0], row[1], row[2]) for row in conn.execute(sql, params).fetchall()]


def _ingredient_set_jsonb(ingredients: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items = sorted(
        {
            (ing["role"], ing["antichain_node_id"], ing.get("antichain_slug"))
            for ing in ingredients
            if in_cluster_key(ing)
        }
    )
    return [
        {"role": role, "antichain_node_id": node_id, "antichain_slug": slug}
        for role, node_id, slug in items
    ]


def run_cluster_compute(
    conn: psycopg.Connection,
    *,
    site: str | None = None,
    limit: int | None = None,
    dry_run: bool = False,
) -> dict[str, int]:
    """Tag roles, compute cluster + variant keys, write recipe_clusters
    + recipes.cluster_id + recipes.variant_key + recipe_ingredients.role.
    When dry_run=True, all DB writes and commit are skipped.
    """
    counts: Counter[str] = Counter()
    recipes = _fetch_recipes_to_cluster(
        conn, dedup_version=DEDUP_VERSION, site=site, limit=limit,
    )
    cluster_lookup: dict[str, int] = {}

    for recipe_id, canonical_name, _raw_name in recipes:
        ingredients = _fetch_recipe_ingredients(conn, recipe_id)

        for ing in ingredients:
            role, role_source = classify_role(ing)
            ing["role"] = role
            ing["role_source"] = role_source
            antichain_id = (
                roll_up_to_antichain(conn, ing["taxonomy_node_id"])
                if ing["taxonomy_node_id"] is not None
                else None
            )
            ing["antichain_node_id"] = antichain_id
            if antichain_id is not None:
                slug_row = conn.execute(
                    "select slug, is_cluster_node from taxonomy_nodes where id = %s",
                    (antichain_id,),
                ).fetchone()
                ing["antichain_slug"] = slug_row[0] if slug_row else None
                if slug_row and not slug_row[1]:
                    counts["underspecified"] += 1

        if not dry_run:
            for ing in ingredients:
                conn.execute(
                    """
                    update recipe_ingredients
                       set role = %s, role_source = %s
                     where id = %s
                    """,
                    (ing["role"], ing["role_source"], ing["id"]),
                )

        in_key_ings = [ing for ing in ingredients if in_cluster_key(ing)]
        if not in_key_ings:
            counts["skipped_no_ingredients"] += 1
            continue

        cluster_key = compute_cluster_key(canonical_name, ingredients)
        if cluster_key in cluster_lookup:
            cluster_id = cluster_lookup[cluster_key]
        else:
            if not dry_run:
                row = conn.execute(
                    """
                    insert into recipe_clusters
                        (cluster_key, canonical_name, ingredient_set, dedup_version)
                    values (%s, %s, %s::jsonb, %s)
                    on conflict (cluster_key) do update
                        set canonical_name = excluded.canonical_name,
                            dedup_version  = excluded.dedup_version
                    returning id
                    """,
                    (cluster_key, canonical_name,
                     _canonical_json(_ingredient_set_jsonb(ingredients)),
                     DEDUP_VERSION),
                ).fetchone()
                cluster_id = row[0]
            else:
                # In dry_run mode assign a placeholder so cluster_lookup still
                # deduplicates within the batch (negative to avoid collisions).
                cluster_id = -(len(cluster_lookup) + 1)
            cluster_lookup[cluster_key] = cluster_id
            counts["clusters_created"] += 1

        if not dry_run:
            variant_key = compute_variant_key(cluster_key, ingredients)
            conn.execute(
                """
                update recipes
                   set cluster_id    = %s,
                       variant_key   = %s,
                       dedup_version = %s
                 where id = %s
                """,
                (cluster_id, variant_key, DEDUP_VERSION, recipe_id),
            )
        counts["recipes_clustered"] += 1

    if not dry_run:
        conn.execute(
            """
            update recipe_clusters c
               set recipe_count = sub.recipe_count,
                   source_count = sub.source_count,
                   representative_recipe_id = sub.rep_id
            from (
                select cluster_id,
                       count(*)              as recipe_count,
                       count(distinct site)  as source_count,
                       min(id)               as rep_id
                from recipes
                where cluster_id is not null
                  and dedup_version = %s
                group by cluster_id
            ) sub
            where c.id = sub.cluster_id
            """,
            (DEDUP_VERSION,),
        )
        conn.commit()

    return dict(counts)

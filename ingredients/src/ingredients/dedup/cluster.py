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
from spiritolo_common.interrupt import InterruptHandler

from .role_classifier import classify_role
from .rollup import roll_up_to_antichain
from .version import DEDUP_VERSION

log = logging.getLogger("dedup.cluster")

INCLUDED_ROLES = frozenset({
    "base_spirit", "modifier", "citrus", "sweetener",
    "bitters", "dilution", "wash", "other",
})

# Number of recipes to process between commits. Each recipe contributes
# ~5-10 buffered ingredient role updates plus one recipe cluster update,
# so a flush of 100 recipes is ~500-1000 row updates per round-trip.
BATCH_FLUSH_SIZE = 100


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


def _none_safe_sort_key(t: tuple[Any, ...]) -> tuple[Any, ...]:
    """Wrap each tuple element so None is comparable with any concrete type.
    Python 3 raises TypeError on `None < 1.5` etc; expanding each value to
    `(is_none, value)` puts all-None entries first/last consistently and
    avoids cross-type comparisons within the sort.
    """
    return tuple((v is None, v) for v in t)


def compute_variant_key(cluster_key: str, ingredients: list[dict[str, Any]]) -> str:
    """Variant identity adds taxonomy_node_id (specific node), amount,
    amount_max, unit. Two recipes share a variant iff their amounts +
    brands match within the same cluster.
    """
    members = sorted(
        (
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
        ),
        key=_none_safe_sort_key,
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


def _fetch_node_metadata(conn: psycopg.Connection) -> dict[int, tuple[str, bool]]:
    """Snapshot every taxonomy node's slug + is_cluster_node into a dict.
    Eliminates one round-trip per ingredient in the hot loop."""
    return {
        row[0]: (row[1], bool(row[2]))
        for row in conn.execute(
            "select id, slug, is_cluster_node from taxonomy_nodes"
        ).fetchall()
    }


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


def _flush_role_updates(
    conn: psycopg.Connection, role_updates: list[tuple[int, str, str]],
) -> None:
    """Bulk UPDATE recipe_ingredients role + role_source. Caller commits."""
    if not role_updates:
        return
    ids = [r[0] for r in role_updates]
    roles = [r[1] for r in role_updates]
    sources = [r[2] for r in role_updates]
    conn.execute(
        """
        update recipe_ingredients ri
           set role = v.role,
               role_source = v.role_source
          from unnest(%s::bigint[], %s::text[], %s::text[])
                as v(id, role, role_source)
         where ri.id = v.id
        """,
        (ids, roles, sources),
    )
    role_updates.clear()


def _flush_recipe_updates(
    conn: psycopg.Connection, recipe_updates: list[tuple[int, int, str]],
) -> None:
    """Bulk UPDATE recipes cluster_id + variant_key + dedup_version. Caller commits."""
    if not recipe_updates:
        return
    rids = [r[0] for r in recipe_updates]
    cluster_ids = [r[1] for r in recipe_updates]
    variant_keys = [r[2] for r in recipe_updates]
    conn.execute(
        """
        update recipes r
           set cluster_id    = v.cluster_id,
               variant_key   = v.variant_key,
               dedup_version = %s
          from unnest(%s::bigint[], %s::bigint[], %s::text[])
                as v(id, cluster_id, variant_key)
         where r.id = v.id
        """,
        (DEDUP_VERSION, rids, cluster_ids, variant_keys),
    )
    recipe_updates.clear()


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
    from spiritolo_common.progress import make_progress

    counts: Counter[str] = Counter()
    recipes = _fetch_recipes_to_cluster(
        conn, dedup_version=DEDUP_VERSION, site=site, limit=limit,
    )
    total = len(recipes)
    if total == 0:
        log.info("nothing to cluster")
        return dict(counts)
    log.info("clustering %d recipes (dedup_version=%s)", total, DEDUP_VERSION)

    # Snapshot taxonomy metadata + memoize antichain rollup. Each unique
    # node_id rolls up to the same antichain ancestor every time, so the
    # cache turns ~ingredients_per_recipe * recipes lookups into ~unique-nodes.
    node_meta = _fetch_node_metadata(conn)
    rollup_cache: dict[int, int] = {}

    def rollup(node_id: int | None) -> int | None:
        if node_id is None:
            return None
        cached = rollup_cache.get(node_id)
        if cached is not None:
            return cached
        result = roll_up_to_antichain(conn, node_id)
        rollup_cache[node_id] = result
        return result

    role_updates: list[tuple[int, str, str]] = []
    recipe_updates: list[tuple[int, int, str]] = []
    cluster_lookup: dict[str, int] = {}

    progress = make_progress(total=total)
    with InterruptHandler() as interrupt:
        try:
            for idx, (recipe_id, canonical_name, _raw_name) in enumerate(recipes, start=1):
                if interrupt.requested:
                    break
                ingredients = _fetch_recipe_ingredients(conn, recipe_id)

                for ing in ingredients:
                    role, role_source = classify_role(ing)
                    ing["role"] = role
                    ing["role_source"] = role_source
                    antichain_id = rollup(ing["taxonomy_node_id"])
                    ing["antichain_node_id"] = antichain_id
                    if antichain_id is not None:
                        meta = node_meta.get(antichain_id)
                        ing["antichain_slug"] = meta[0] if meta else None
                        if meta and not meta[1]:
                            counts["underspecified"] += 1

                if not dry_run:
                    for ing in ingredients:
                        role_updates.append(
                            (ing["id"], ing["role"], ing["role_source"]),
                        )

                in_key_ings = [ing for ing in ingredients if in_cluster_key(ing)]
                if not in_key_ings:
                    counts["skipped_no_ingredients"] += 1
                    progress(idx)
                    if not dry_run and (idx % BATCH_FLUSH_SIZE == 0):
                        _flush_role_updates(conn, role_updates)
                        _flush_recipe_updates(conn, recipe_updates)
                        conn.commit()
                    continue

                cluster_key = compute_cluster_key(canonical_name, ingredients)
                if cluster_key in cluster_lookup:
                    cluster_id = cluster_lookup[cluster_key]
                else:
                    if not dry_run:
                        # Insert (or upsert) eagerly so we have the cluster_id
                        # to attach to recipe rows in this and subsequent
                        # iterations of the same batch. Commits land at the
                        # next flush boundary — Ctrl-C between flushes rolls
                        # back the new cluster, which is harmless: the next
                        # run recreates it via on-conflict-do-update.
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
                        # dry_run: assign placeholder so cluster_lookup still
                        # deduplicates within the batch (negative to avoid collisions).
                        cluster_id = -(len(cluster_lookup) + 1)
                    cluster_lookup[cluster_key] = cluster_id
                    counts["clusters_created"] += 1

                if not dry_run:
                    variant_key = compute_variant_key(cluster_key, ingredients)
                    recipe_updates.append((recipe_id, cluster_id, variant_key))
                counts["recipes_clustered"] += 1
                progress(idx)

                if not dry_run and (idx % BATCH_FLUSH_SIZE == 0):
                    _flush_role_updates(conn, role_updates)
                    _flush_recipe_updates(conn, recipe_updates)
                    conn.commit()
        except KeyboardInterrupt:
            # Second Ctrl-C: do NOT flush; abort with whatever has been
            # committed in prior batches.
            raise
        if not dry_run:
            _flush_role_updates(conn, role_updates)
            _flush_recipe_updates(conn, recipe_updates)
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

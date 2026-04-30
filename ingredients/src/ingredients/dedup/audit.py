"""Five audit queries for the dedup pipeline. Operator-triaged via the
`cluster audit` CLI subcommand. No automated remediation in v1.
"""

from __future__ import annotations

from typing import Any

import psycopg

_NAME_DIVERGENCE_THRESHOLD = 4
_HIGH_DIVERSITY_THRESHOLD = 3
_EDITORIAL_PATTERNS = ("best", "perfect", "ultimate", "easiest", "world s best")


def audit_name_divergence_within_cluster(conn: psycopg.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        f"""
        select c.id as cluster_id, c.canonical_name,
               count(distinct r.name) as distinct_names,
               array_agg(distinct r.name order by r.name) as names
        from recipes r
        join recipe_clusters c on c.id = r.cluster_id
        where r.cluster_id is not null
        group by c.id, c.canonical_name
        having count(distinct r.name) >= {_NAME_DIVERGENCE_THRESHOLD}
        order by distinct_names desc
        """
    ).fetchall()
    return [
        {"cluster_id": r[0], "canonical_name": r[1],
         "distinct_names": r[2], "names": r[3]}
        for r in rows
    ]


def audit_same_canonical_across_clusters(conn: psycopg.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        select canonical_name, count(*) as cluster_count,
               array_agg(id order by id) as cluster_ids
        from recipe_clusters
        group by canonical_name
        having count(*) > 1
        order by cluster_count desc
        """
    ).fetchall()
    return [
        {"canonical_name": r[0], "cluster_count": r[1], "cluster_ids": r[2]}
        for r in rows
    ]


def audit_underspecified_ingredients(conn: psycopg.Connection) -> list[dict[str, Any]]:
    """Recipes with >= 1 ingredient that resolves to a node where
    is_cluster_node = false (meaning rollup hit the "above the cut" case)."""
    rows = conn.execute(
        """
        select r.cluster_id, c.canonical_name,
               count(distinct r.id) as recipe_count,
               array_agg(distinct n.slug) as offending_slugs
        from recipes r
        join recipe_clusters c on c.id = r.cluster_id
        join recipe_ingredients ri on ri.recipe_id = r.id
        join taxonomy_nodes n on n.id = ri.taxonomy_node_id
        where r.cluster_id is not null
          and n.is_cluster_node = false
          and ri.role in ('base_spirit', 'modifier', 'bitters')
        group by r.cluster_id, c.canonical_name
        order by recipe_count desc
        """
    ).fetchall()
    return [
        {"cluster_id": r[0], "canonical_name": r[1],
         "recipe_count": r[2], "offending_slugs": r[3]}
        for r in rows
    ]


def audit_high_in_stack_diversity(conn: psycopg.Connection) -> list[dict[str, Any]]:
    """Clusters where a single role slot has many different specific
    taxonomy_node_ids — surfaces sub-spirit-defining cases."""
    rows = conn.execute(
        f"""
        select r.cluster_id, c.canonical_name, ri.role,
               count(distinct ri.taxonomy_node_id) as distinct_specific_nodes
        from recipes r
        join recipe_clusters c on c.id = r.cluster_id
        join recipe_ingredients ri on ri.recipe_id = r.id
        where r.cluster_id is not null
          and ri.role in ('base_spirit', 'modifier')
        group by r.cluster_id, c.canonical_name, ri.role
        having count(distinct ri.taxonomy_node_id) >= {_HIGH_DIVERSITY_THRESHOLD}
        order by distinct_specific_nodes desc
        """
    ).fetchall()
    return [
        {"cluster_id": r[0], "canonical_name": r[1], "role": r[2],
         "distinct_specific_nodes": r[3]}
        for r in rows
    ]


def audit_singleton_editorial_names(conn: psycopg.Connection) -> list[dict[str, Any]]:
    """Recipes that didn't end up in a multi-recipe cluster AND whose
    raw name has editorial markers — likely a name-normalization miss."""
    pattern_clause = " or ".join(
        "lower(r.name) like %s" for _ in _EDITORIAL_PATTERNS
    )
    params = [f"%{p}%" for p in _EDITORIAL_PATTERNS]
    rows = conn.execute(
        f"""
        select r.id, r.name, r.canonical_name, r.cluster_id
        from recipes r
        where ({pattern_clause})
          and (
            r.cluster_id is null
            or r.cluster_id in (
                select cluster_id from recipes
                where cluster_id is not null
                group by cluster_id
                having count(*) = 1
            )
          )
        order by r.id
        """,
        params,
    ).fetchall()
    return [
        {"id": r[0], "name": r[1], "canonical_name": r[2], "cluster_id": r[3]}
        for r in rows
    ]


def run_all_audits(conn: psycopg.Connection) -> dict[str, list[dict[str, Any]]]:
    return {
        "name_divergence_within_cluster":  audit_name_divergence_within_cluster(conn),
        "same_canonical_across_clusters":  audit_same_canonical_across_clusters(conn),
        "underspecified_ingredients":      audit_underspecified_ingredients(conn),
        "high_in_stack_diversity":         audit_high_in_stack_diversity(conn),
        "singleton_editorial_names":       audit_singleton_editorial_names(conn),
    }

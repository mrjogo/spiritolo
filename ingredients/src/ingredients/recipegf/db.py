"""DB access for the RecipeGF export stage. Pure-SQL helpers; the caller
passes the psycopg connection (matches dedup/mapping ``db.py`` convention).

The stage reads ``recipe_clusters`` (drink identity) joined to each cluster's
representative recipe (``recipes.jsonld`` + its parsed/roled
``recipe_ingredients``, joined to ``taxonomy_nodes.slug``) and writes the
emitted bundle back onto the cluster row.
"""

from __future__ import annotations

import json
from typing import Any

import psycopg

from .converter import SourceIngredient, SourceRecipe


def fetch_export_queue(
    conn: psycopg.Connection,
    *,
    converter_version: str,
    site: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Clusters needing (re)export: no bundle at the current CONVERTER_VERSION
    and a resolvable representative recipe.

    ``site`` scopes on the representative recipe's site. Returns dicts with
    ``cluster_id``/``canonical_name``/``representative_recipe_id``/
    ``source_url``/``jsonld``.
    """
    params: list[Any] = [converter_version]
    site_clause = ""
    if site is not None:
        site_clause = "and r.site = %s"
        params.append(site)
    sql = f"""
        select c.id, c.canonical_name, c.representative_recipe_id,
               r.source_url, r.jsonld
        from recipe_clusters c
        join recipes r on r.id = c.representative_recipe_id
        where (c.recipegf_version is null or c.recipegf_version <> %s)
          {site_clause}
        order by c.id
    """
    if limit is not None:
        sql += " limit %s"
        params.append(limit)
    rows = conn.execute(sql, params).fetchall()
    return [
        {
            "cluster_id": r[0], "canonical_name": r[1],
            "representative_recipe_id": r[2], "source_url": r[3], "jsonld": r[4],
        }
        for r in rows
    ]


def fetch_source_ingredients(
    conn: psycopg.Connection, recipe_id: int
) -> list[SourceIngredient]:
    """The parsed+roled ingredients of one recipe, joined to their taxonomy
    slug, as :class:`SourceIngredient` rows ordered by position."""
    rows = conn.execute(
        """
        select ri.position, ri.raw_text, ri.amount, ri.amount_max, ri.unit,
               ri.name, ri.role, tn.slug
        from recipe_ingredients ri
        left join taxonomy_nodes tn on tn.id = ri.taxonomy_node_id
        where ri.recipe_id = %s
        order by ri.position
        """,
        (recipe_id,),
    ).fetchall()
    return [
        SourceIngredient(
            position=r[0], raw_text=r[1],
            amount=float(r[2]) if r[2] is not None else None,
            amount_max=float(r[3]) if r[3] is not None else None,
            unit=r[4], name=r[5], role=r[6], slug=r[7],
        )
        for r in rows
    ]


def build_source_recipe(
    conn: psycopg.Connection, queue_row: dict[str, Any]
) -> SourceRecipe:
    """Assemble a :class:`SourceRecipe` from a ``fetch_export_queue`` row."""
    ingredients = fetch_source_ingredients(conn, queue_row["representative_recipe_id"])
    return SourceRecipe(
        canonical_name=queue_row["canonical_name"],
        source_url=queue_row["source_url"] or "",
        jsonld=queue_row["jsonld"] or {},
        ingredients=ingredients,
    )


def write_bundle(
    conn: psycopg.Connection,
    *,
    cluster_id: int,
    slug: str,
    bundle: dict[str, Any],
    source: str,
    converter_version: str,
) -> None:
    """Persist a successful export onto the cluster row. Caller commits."""
    conn.execute(
        """
        update recipe_clusters
           set recipegf_slug        = %s,
               recipegf_bundle      = %s::jsonb,
               recipegf_source      = %s,
               recipegf_version     = %s,
               recipegf_status      = 'exported',
               recipegf_exported_at = now()
         where id = %s
        """,
        (slug, json.dumps(bundle), source, converter_version, cluster_id),
    )


def park_uncertain(
    conn: psycopg.Connection,
    *,
    cluster_id: int,
    proposed_slug: str | None,
    source: str,
    converter_version: str,
) -> None:
    """Mark a cluster as parked (uncertain) at the current version so it drops
    off the queue until a version bump or reset. Caller commits (usually
    alongside :func:`ingredients.recipegf.proposals.enqueue_proposal`)."""
    conn.execute(
        """
        update recipe_clusters
           set recipegf_slug        = %s,
               recipegf_bundle      = null,
               recipegf_source      = %s,
               recipegf_version     = %s,
               recipegf_status      = 'uncertain',
               recipegf_exported_at = now()
         where id = %s
        """,
        (proposed_slug, source, converter_version, cluster_id),
    )


def count_exported_rows(
    conn: psycopg.Connection,
    *,
    except_version: str | None = None,
    older_than: str | None = None,
) -> int:
    """Count clusters carrying a bundle stamp we would clear on ``--reset``."""
    sql = "select count(*) from recipe_clusters where recipegf_version is not null"
    params: list[Any] = []
    if except_version is not None:
        sql += " and recipegf_version <> %s"
        params.append(except_version)
    if older_than is not None:
        sql += " and recipegf_exported_at < %s"
        params.append(older_than)
    return conn.execute(sql, params).fetchone()[0]


def clear_exported_rows(
    conn: psycopg.Connection,
    *,
    except_version: str | None = None,
    older_than: str | None = None,
) -> int:
    """Null the recipegf_* columns on clusters in scope so they re-queue.
    Caller commits. Returns rowcount."""
    sql = """
        update recipe_clusters
           set recipegf_slug = null, recipegf_bundle = null,
               recipegf_source = null, recipegf_version = null,
               recipegf_status = null, recipegf_exported_at = null
         where recipegf_version is not null
    """
    params: list[Any] = []
    if except_version is not None:
        sql += " and recipegf_version <> %s"
        params.append(except_version)
    if older_than is not None:
        sql += " and recipegf_exported_at < %s"
        params.append(older_than)
    cur = conn.execute(sql, params)
    return cur.rowcount

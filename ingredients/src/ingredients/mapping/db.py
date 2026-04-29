"""DB access for the mapper. Caller passes a psycopg connection so the
fixture-DB tests and the production worker share the same code paths.

A name is "in scope" if it has at least one recipe_ingredients row whose
mapper_version is NULL or differs from the current MAPPER_VERSION.
Updates fan out to every row sharing the normalized name string.
"""

from __future__ import annotations

import psycopg

from .types import MapperSource


def fetch_unique_pending_names(
    conn: psycopg.Connection, *, mapper_version: str,
    site: str | None = None, limit: int | None = None,
) -> list[str]:
    """Distinct normalized names lacking a current-version mapping."""
    params: list[object] = [mapper_version]
    site_clause = ""
    if site is not None:
        site_clause = "and r.site = %s"
        params.append(site)

    sql = f"""
        select distinct lower(trim(ri.name)) as n
        from recipe_ingredients ri
        join recipes r on r.id = ri.recipe_id
        where ri.name is not null
          and ri.parse_status = 'parsed'
          and (ri.mapper_version is null or ri.mapper_version <> %s)
          {site_clause}
        order by n
    """
    if limit is not None:
        sql += " limit %s"
        params.append(limit)
    return [row[0] for row in conn.execute(sql, params).fetchall()]


def write_resolution(
    conn: psycopg.Connection, *, normalized_name: str,
    taxonomy_node_id: int, source: MapperSource, mapper_version: str,
) -> int:
    """UPDATE every row whose normalized name matches. Returns rowcount."""
    cur = conn.execute(
        """
        update recipe_ingredients
           set taxonomy_node_id = %s,
               mapper_source    = %s,
               mapper_version   = %s,
               mapper_at        = now()
         where lower(trim(name)) = %s
        """,
        (taxonomy_node_id, source, mapper_version, normalized_name),
    )
    conn.commit()
    return cur.rowcount


def write_pending(
    conn: psycopg.Connection, *, normalized_name: str, mapper_version: str,
) -> int:
    """Mark every row whose normalized name matches as pending_llm. Returns rowcount."""
    cur = conn.execute(
        """
        update recipe_ingredients
           set taxonomy_node_id = null,
               mapper_source    = 'pending_llm',
               mapper_version   = %s,
               mapper_at        = now()
         where lower(trim(name)) = %s
        """,
        (mapper_version, normalized_name),
    )
    conn.commit()
    return cur.rowcount


def write_abstain(
    conn: psycopg.Connection, *, normalized_name: str, mapper_version: str,
) -> int:
    """Mark rows as abstained (Phase 2 considered and declined)."""
    cur = conn.execute(
        """
        update recipe_ingredients
           set taxonomy_node_id = null,
               mapper_source    = 'abstain',
               mapper_version   = %s,
               mapper_at        = now()
         where lower(trim(name)) = %s
        """,
        (mapper_version, normalized_name),
    )
    conn.commit()
    return cur.rowcount


def fetch_pending_llm_names(
    conn: psycopg.Connection, *, mapper_version: str, limit: int | None = None,
) -> list[str]:
    """Distinct names currently marked pending_llm at this version."""
    sql = """
        select distinct lower(trim(name)) as n
        from recipe_ingredients
        where mapper_source = 'pending_llm' and mapper_version = %s
        order by n
    """
    params: list[object] = [mapper_version]
    if limit is not None:
        sql += " limit %s"
        params.append(limit)
    return [row[0] for row in conn.execute(sql, params).fetchall()]

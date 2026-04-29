"""Reset + sample helpers for the map CLI."""

from __future__ import annotations

from typing import Any

import psycopg


def count_mapped_rows(
    conn: psycopg.Connection,
    *,
    site: str | None,
    except_version: str | None,
    older_than: str | None,
) -> int:
    sql, params = _filter_clause(
        "select count(*)", site=site, except_version=except_version, older_than=older_than,
    )
    return conn.execute(sql, params).fetchone()[0]


def clear_mapping_columns(
    conn: psycopg.Connection,
    *,
    site: str | None,
    except_version: str | None,
    older_than: str | None,
) -> int:
    sql, params = _filter_clause(
        "update recipe_ingredients ri "
        "set taxonomy_node_id = null, mapper_source = null, "
        "    mapper_version = null, mapper_at = null",
        site=site, except_version=except_version, older_than=older_than,
    )
    cur = conn.execute(sql, params)
    conn.commit()
    return cur.rowcount


def sample_pending(
    conn: psycopg.Connection,
    *,
    n: int,
    mapper_version: str,
    site: str | None = None,
) -> list[str]:
    """Return up to N random distinct pending names. Read-only."""
    params: list[Any] = [mapper_version]
    site_clause = ""
    if site is not None:
        site_clause = "and r.site = %s"
        params.append(site)
    params.append(n)
    rows = conn.execute(
        f"""
        select name_normalized
        from (
            select distinct lower(trim(ri.name)) as name_normalized
            from recipe_ingredients ri
            join recipes r on r.id = ri.recipe_id
            where ri.name is not null
              and ri.parse_status = 'parsed'
              and (ri.mapper_version is null or ri.mapper_version <> %s)
              {site_clause}
        ) sub
        order by random()
        limit %s
        """,
        params,
    ).fetchall()
    return [r[0] for r in rows]


def _filter_clause(
    select: str, *, site: str | None,
    except_version: str | None, older_than: str | None,
) -> tuple[str, list[Any]]:
    clauses = ["ri.mapper_version is not null"]
    params: list[Any] = []
    if site is not None:
        clauses.append("ri.recipe_id in (select id from recipes where site = %s)")
        params.append(site)
    if except_version is not None:
        clauses.append("ri.mapper_version <> %s")
        params.append(except_version)
    if older_than is not None:
        clauses.append("ri.mapper_at < %s::timestamptz")
        params.append(older_than)
    where = " where " + " and ".join(clauses)
    # Distinguish UPDATE (uses alias `ri`) from SELECT (also uses `ri`).
    if select.lstrip().lower().startswith("update"):
        return select + where, params
    return f"{select} from recipe_ingredients ri{where}", params

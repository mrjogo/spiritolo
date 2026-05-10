"""DB access for E's name normalizer + cluster compute. Pure-SQL helpers;
caller passes the psycopg connection.

The orchestrator works in two registers: the *raw* recipes.name as it
appears on the row, and the *normalized* form produced by
normalize_cocktail_name. Layer-1 and Layer-2 lookups key on the normalized
form. write_normalization fans the resolution out to every recipes row
whose .name matches the raw form passed in (no normalization fold here —
the orchestrator owns the raw → normalized translation per row).
"""

from __future__ import annotations

import psycopg

from .types import NormalizerSource


def fetch_unresolved_recipe_names(
    conn: psycopg.Connection, *, normalizer_version: str,
    site: str | None = None, limit: int | None = None,
) -> list[str]:
    """Distinct raw names lacking a current-version normalization.

    Excludes recipes whose canonical_name_source is 'pending_llm' at the
    current version — those are queued for Phase 2, not Phase 1.
    """
    params: list[object] = [normalizer_version, normalizer_version]
    site_clause = ""
    if site is not None:
        site_clause = "and site = %s"
        params.append(site)

    sql = f"""
        select distinct name
        from recipes
        where name is not null
          and (normalizer_version is null
               or (normalizer_version <> %s
                   and canonical_name_source <> 'pending_llm')
               or (normalizer_version = %s
                   and canonical_name_source is null))
          {site_clause}
        order by name
    """
    if limit is not None:
        sql += " limit %s"
        params.append(limit)
    return [row[0] for row in conn.execute(sql, params).fetchall()]


def fetch_pending_canonical_names(
    conn: psycopg.Connection, *, normalizer_version: str,
    limit: int | None = None,
) -> list[str]:
    """Distinct raw names whose current-version row is at canonical_name_source='pending_llm'."""
    sql = """
        select distinct name from recipes
        where canonical_name_source = 'pending_llm'
          and normalizer_version = %s
        order by name
    """
    params: list[object] = [normalizer_version]
    if limit is not None:
        sql += " limit %s"
        params.append(limit)
    return [row[0] for row in conn.execute(sql, params).fetchall()]


def write_normalization(
    conn: psycopg.Connection, *, raw_name: str, normalized: str,
    canonical_name: str, source: NormalizerSource, normalizer_version: str,
) -> int:
    """Stamp every recipes row whose name matches the raw form. Returns rowcount.

    The `normalized` arg is accepted but unused at this layer — the
    orchestrator passes it for forward-compat (a future variant might
    fan-out to all rows whose normalized(name) matches, not just whose
    raw .name matches). For v1, raw-name match is sufficient because
    distinct raw names are processed per-call.
    """
    cur = conn.execute(
        """
        update recipes
           set canonical_name        = %s,
               canonical_name_source = %s,
               normalizer_version    = %s,
               normalized_at         = now()
         where name = %s
        """,
        (canonical_name, source, normalizer_version, raw_name),
    )
    conn.commit()
    return cur.rowcount


def write_pending_normalize(
    conn: psycopg.Connection, *, raw_name: str, normalizer_version: str,
) -> int:
    cur = conn.execute(
        """
        update recipes
           set canonical_name        = null,
               canonical_name_source = 'pending_llm',
               normalizer_version    = %s,
               normalized_at         = now()
         where name = %s
        """,
        (normalizer_version, raw_name),
    )
    conn.commit()
    return cur.rowcount


def write_normalizations_batch(
    conn: psycopg.Connection, *,
    items: list[tuple[str, str]],
    source: NormalizerSource,
    normalizer_version: str,
) -> int:
    """Bulk UPDATE for many (raw_name, canonical_name) pairs sharing one
    source. Caller commits."""
    if not items:
        return 0
    raw_names = [r for r, _ in items]
    canonical_names = [c for _, c in items]
    cur = conn.execute(
        """
        update recipes r
           set canonical_name        = v.canonical,
               canonical_name_source = %s,
               normalizer_version    = %s,
               normalized_at         = now()
          from unnest(%s::text[], %s::text[]) as v(raw, canonical)
         where r.name = v.raw
        """,
        (source, normalizer_version, raw_names, canonical_names),
    )
    return cur.rowcount


def write_pending_normalize_batch(
    conn: psycopg.Connection, *, raw_names: list[str], normalizer_version: str,
) -> int:
    """Bulk pending_llm marker for many raw names. Caller commits."""
    if not raw_names:
        return 0
    cur = conn.execute(
        """
        update recipes r
           set canonical_name        = null,
               canonical_name_source = 'pending_llm',
               normalizer_version    = %s,
               normalized_at         = now()
          from unnest(%s::text[]) as v(raw)
         where r.name = v.raw
        """,
        (normalizer_version, raw_names),
    )
    return cur.rowcount


def write_normalize_abstain(
    conn: psycopg.Connection, *, raw_name: str, normalizer_version: str,
) -> int:
    cur = conn.execute(
        """
        update recipes
           set canonical_name        = null,
               canonical_name_source = 'abstain',
               normalizer_version    = %s,
               normalized_at         = now()
         where name = %s
        """,
        (normalizer_version, raw_name),
    )
    conn.commit()
    return cur.rowcount


def park_attempted_names(
    conn: psycopg.Connection, *, normalizer_version: str, names: list[str],
) -> int:
    """Flip recipes rows from 'pending_llm' to 'pending_llm_tried' for the
    given normalizer_version, restricted to rows whose name is in `names`.
    Caller commits.

    Used by the chunked Phase-2 drain after each chunk's ingest: names
    that did not get a clearing action stay at 'pending_llm' and would
    otherwise re-appear in the next chunk's fetch_pending_canonical_names.
    Parking them excludes them from the queue until a version bump or
    `normalize-names retry-failures` resurrects them.

    Returns rowcount. Empty `names` is a no-op returning 0."""
    if not names:
        return 0
    cur = conn.execute(
        """
        update recipes
           set canonical_name_source = 'pending_llm_tried'
         where normalizer_version = %s
           and canonical_name_source = 'pending_llm'
           and name = any(%s::text[])
        """,
        (normalizer_version, names),
    )
    return cur.rowcount


def unpark_failures(
    conn: psycopg.Connection, *, normalizer_version: str, limit: int | None = None,
) -> int:
    """Flip 'pending_llm_tried' rows at the given normalizer_version back to
    'pending_llm' so the next `normalize-names resolve-pending` re-submits them.
    Caller commits.

    With `limit=N`, flips at most N rows (selected by id, no ordering
    guarantees beyond Postgres's default). Without `limit`, flips
    everything at the version. Returns rowcount."""
    if limit is None:
        cur = conn.execute(
            """
            update recipes
               set canonical_name_source = 'pending_llm'
             where normalizer_version = %s
               and canonical_name_source = 'pending_llm_tried'
            """,
            (normalizer_version,),
        )
    else:
        cur = conn.execute(
            """
            update recipes
               set canonical_name_source = 'pending_llm'
             where id in (
                 select id from recipes
                  where normalizer_version = %s
                    and canonical_name_source = 'pending_llm_tried'
                  limit %s
             )
            """,
            (normalizer_version, limit),
        )
    return cur.rowcount


def add_cocktail_alias(
    conn: psycopg.Connection, *, alias: str, canonical_name: str,
    source: str = "llm",
) -> None:
    conn.execute(
        """
        insert into cocktail_aliases (alias, canonical_name, source)
        values (%s, %s, %s)
        on conflict do nothing
        """,
        (alias, canonical_name, source),
    )
    conn.commit()

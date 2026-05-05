"""Read-side DB queries used by the uploader.

Centralized so tests can exercise each query in isolation without
spinning up the full CLI.
"""
from __future__ import annotations

import datetime as dt
from typing import Iterable

import psycopg

from .tables import OwnedTable


def fetch_applied_migrations(conn: psycopg.Connection) -> tuple[str, ...]:
    """Read every `version` from supabase_migrations.schema_migrations.

    Sorted ascending so the result is order-stable across calls and
    regardless of insert order.
    """
    rows = conn.execute(
        "select version from supabase_migrations.schema_migrations "
        "order by version"
    ).fetchall()
    return tuple(r[0] for r in rows)


def fetch_max_updated_at_per_table(
    conn: psycopg.Connection,
    tables: Iterable[OwnedTable],
) -> dict[str, dt.datetime | None]:
    """For each table, return max(updated_at) (or None if empty)."""
    out: dict[str, dt.datetime | None] = {}
    for t in tables:
        row = conn.execute(
            f"select max(updated_at) from public.{t.name}"
        ).fetchone()
        out[t.name] = row[0] if row else None
    return out


def fetch_dirty_rows_per_table(
    conn: psycopg.Connection,
    tables: Iterable[OwnedTable],
    after: dt.datetime,
) -> dict[str, list[dict]]:
    """For each table, return rows with updated_at > `after`, as dicts
    keyed by column name. Empty list when none."""
    out: dict[str, list[dict]] = {}
    for t in tables:
        cur = conn.execute(
            f"select * from public.{t.name} where updated_at > %s",
            (after,),
        )
        cols = [d.name for d in cur.description]
        out[t.name] = [dict(zip(cols, row)) for row in cur.fetchall()]
    return out

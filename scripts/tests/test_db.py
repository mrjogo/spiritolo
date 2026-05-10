"""DB-layer queries: applied migrations, max(updated_at), dirty set."""
from __future__ import annotations

import datetime as dt

import psycopg

from upload_to_staging.db import (
    fetch_applied_migrations,
    fetch_max_updated_at_per_table,
    fetch_dirty_rows_per_table,
)
from upload_to_staging.tables import OWNED_TABLES


def test_fetch_applied_migrations_returns_versions(fresh_db_pair):
    local_url, _ = fresh_db_pair
    with psycopg.connect(local_url) as conn:
        got = fetch_applied_migrations(conn)
    # The conftest seeds at least one migration.
    assert len(got) > 0
    assert all(isinstance(v, str) and v for v in got)
    # Sorted ascending.
    assert list(got) == sorted(got)


def test_max_updated_at_empty_tables(fresh_db_pair):
    _, staging_url = fresh_db_pair
    with psycopg.connect(staging_url) as conn:
        got = fetch_max_updated_at_per_table(conn, OWNED_TABLES)
    assert set(got.keys()) == {t.name for t in OWNED_TABLES}
    for v in got.values():
        assert v is None


def test_dirty_rows_returns_only_recent(fresh_db_pair):
    local_url, _ = fresh_db_pair
    with psycopg.connect(local_url, autocommit=True) as conn:
        # Two old recipes (pre-T), one new (post-T).
        conn.execute(
            "insert into recipes (source_url, site, name, jsonld, fetched_at) values "
            "('u1', 's', 'old1', '{}'::jsonb, now()), "
            "('u2', 's', 'old2', '{}'::jsonb, now())"
        )
        # Sleep just enough that updated_at differs; pg now() advances per stmt.
        T = dt.datetime.now(dt.timezone.utc)
        # New row inserted strictly after T.
        import time
        time.sleep(0.05)
        conn.execute(
            "insert into recipes (source_url, site, name, jsonld, fetched_at) values "
            "('u3', 's', 'new1', '{}'::jsonb, now())"
        )

        recipes_table = next(t for t in OWNED_TABLES if t.name == "recipes")
        got = fetch_dirty_rows_per_table(conn, [recipes_table], T)
        rows = got["recipes"]
        names = sorted(r["name"] for r in rows)
        assert names == ["new1"]

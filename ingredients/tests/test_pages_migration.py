"""Schema-level integration tests for the `pages` migration.

`pages` is one of the two durable pipeline inputs (the other being the
object-store HTML corpus read by ingredients.pipeline.corpus). It replaces the
scraper's SQLite
`pages` table with a lightweight per-URL row in Postgres — no
snapshot/attempts/fetch_error bookkeeping (that history now lives in
job_items.payload / audit_log).

This is the sole migration for `pages`; ingredients/tests/test_corpus_reader.py
covers only the read-side corpus module and adds no migration of its own.
"""
from __future__ import annotations

import psycopg
import pytest


def _columns(db_conn, table):
    return {
        row[0]: (row[1], row[2], row[3])
        for row in db_conn.execute(
            """
            select column_name, data_type, is_nullable, column_default
            from information_schema.columns
            where table_name = %s
            """,
            (table,),
        ).fetchall()
    }


def test_pages_columns(db_conn):
    cols = _columns(db_conn, "pages")

    assert cols["url"][:2] == ("text", "NO")
    assert cols["site"][:2] == ("text", "NO")
    assert cols["corpus_key"][:2] == ("text", "YES")
    assert cols["content_type"][:2] == ("text", "YES")
    assert cols["denylist"][:2] == ("boolean", "NO")
    assert "false" in (cols["denylist"][2] or "").lower()
    assert cols["denylist_reason"][:2] == ("text", "YES")
    assert cols["fetch_status"][:2] == ("text", "YES")
    assert cols["discovered_at"][:2] == ("timestamp with time zone", "NO")
    assert cols["fetched_at"][:2] == ("timestamp with time zone", "YES")


def test_pages_no_snapshot_or_attempts_columns(db_conn):
    # The legacy SQLite pages table (scraper/src/scraper/db.py) tracked
    # per-field snapshots and attempt/error bookkeeping directly on the row.
    # That history now lives in job_items.payload / audit_log; none of it
    # belongs on the lightweight Postgres `pages` row.
    cols = set(_columns(db_conn, "pages"))
    legacy = {
        "pages_status_before",
        "attempts",
        "fetch_error",
        "status",
        "sitemap_source",
        "html_path",
        "disabled_reason",
    }
    assert not (cols & legacy)


def test_pages_indexes_exist(db_conn):
    idx = {
        row[0]
        for row in db_conn.execute(
            "select indexname from pg_indexes where tablename = 'pages'"
        ).fetchall()
    }
    assert "pages_site_idx" in idx
    assert "pages_content_idx" in idx
    assert "pages_denylist_idx" in idx


def test_pages_fetch_status_check_constraint_rejects_unknown(db_conn):
    db_conn.execute(
        "insert into pages (url, site) values ('http://test/pages-check', 'test')"
    )
    with pytest.raises(psycopg.errors.CheckViolation):
        db_conn.execute(
            "update pages set fetch_status = 'bogus' where url = 'http://test/pages-check'"
        )


def test_pages_fetch_status_check_constraint_accepts_known_values(db_conn):
    db_conn.execute(
        "insert into pages (url, site) values ('http://test/pages-ok', 'test')"
    )
    for value in ("ok", "blocked", "failed"):
        db_conn.execute(
            "update pages set fetch_status = %s where url = 'http://test/pages-ok'",
            (value,),
        )


def test_url_unique_constraint(db_conn):
    db_conn.execute(
        "insert into pages (url, site) values ('http://test/dup', 'test')"
    )
    with pytest.raises(psycopg.errors.UniqueViolation):
        db_conn.execute(
            "insert into pages (url, site) values ('http://test/dup', 'test')"
        )


def test_rls_deny_all(db_conn):
    """RLS is enabled and neither anon nor authenticated can read/write
    `pages` directly — there is no RPC surface for it; only the table owner /
    service_role (BYPASSRLS, granted broad access on
    real Supabase — not replicated by the conftest's stub roles) touch it
    directly."""
    row = db_conn.execute(
        "select relrowsecurity from pg_class where relname = 'pages'"
    ).fetchone()
    assert row is not None and row[0] is True

    db_conn.execute(
        "insert into pages (url, site) values ('http://test/rls', 'test')"
    )

    for role in ("anon", "authenticated"):
        db_conn.execute(f"set role {role}")  # role names are fixed literals
        try:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                db_conn.execute("select 1 from pages").fetchall()
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                db_conn.execute(
                    "insert into pages (url, site) values ('http://test/rls-write', 'test')"
                )
        finally:
            db_conn.execute("reset role")

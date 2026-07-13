"""Schema + boundary tests for the stage_config reference table.

stage_config is a small operator-rewired table ({stage, metered,
requires_approval}) the /ops TriggerBar consults before deciding whether a
run needs a CostConfirmModal — never hardcoded in the UI. Runs against
TEST_DB_URL (skips-loud if unset, mirroring test_jobs_schema.py); the
ingredients conftest auto-applies the new stage_config migration before
these run.

Note on the migration's seed rows: the auto-migrate conftest TRUNCATEs
every public table immediately after applying migrations, every session, so
the DB tests below can never observe the migration's INSERT surviving into
a test. The seed values themselves are pinned by a separate, non-DB test
that reads the migration file's text directly.
"""
from __future__ import annotations

import os
import re
import uuid
from pathlib import Path

import psycopg
import pytest

pytestmark_db = pytest.mark.skipif(
    os.environ.get("TEST_DB_URL") is None,
    reason="TEST_DB_URL not set; DB-integration tests skip",
)

_MIGRATION = (
    Path(__file__).resolve().parent.parent.parent
    / "supabase" / "migrations" / "20260718090000_stage_config.sql"
)


def _become(conn, *, admin: bool) -> uuid.UUID:
    """Insert an auth.users row (the on_auth_user_created trigger makes the
    profiles row) and rewire auth.uid() to it. Runs as the DB owner."""
    uid = uuid.uuid4()
    conn.execute("insert into auth.users (id, email) values (%s, %s)", (uid, f"{uid}@test"))
    conn.execute("update profiles set is_admin = %s where id = %s", (admin, uid))
    conn.execute(
        f"create or replace function auth.uid() returns uuid "
        f"language sql stable as $$ select '{uid}'::uuid $$"
    )
    return uid


# ---------------------------------------------------------------------------
# Seed values — pinned from the migration text itself (no DB needed; the
# auto-migrate conftest's clean-slate TRUNCATE means the DB tests below
# never see the seed rows survive into a test).
# ---------------------------------------------------------------------------

def test_migration_seeds_the_current_chain():
    sql = _MIGRATION.read_text()
    seeded = dict(
        (stage, metered == "true")
        for stage, metered, _approval in re.findall(
            r"\('([\w-]+)',\s*(true|false),\s*(true|false)\)", sql,
        )
    )
    assert set(seeded) == {
        "discover", "classify", "fetch", "extract",
        "parse", "map", "role", "cluster", "export",
    }
    # fetch is the one stage that goes through ScraperAPI (a metered HTTP
    # API); every other stage defaults to a free deterministic/local chain.
    assert seeded["fetch"] is True
    assert seeded["parse"] is False
    assert seeded["classify"] is False
    assert sum(seeded.values()) == 1, "exactly one stage (fetch) is metered today"


# ---------------------------------------------------------------------------
# Shape + boundary — against TEST_DB_URL (post-truncate, so self-seeding).
# ---------------------------------------------------------------------------

@pytestmark_db
def test_stage_config_shape(db_conn):
    cols = {
        r[0]: (r[1], r[2])
        for r in db_conn.execute(
            "select column_name, data_type, is_nullable "
            "from information_schema.columns "
            "where table_schema = 'public' and table_name = 'stage_config'"
        ).fetchall()
    }
    assert cols["stage"][0] == "text"
    assert cols["metered"] == ("boolean", "NO")
    assert cols["requires_approval"] == ("boolean", "NO")

    pk_cols = [
        r[0]
        for r in db_conn.execute(
            "select kcu.column_name from information_schema.table_constraints tc "
            "join information_schema.key_column_usage kcu "
            "on tc.constraint_name = kcu.constraint_name "
            "where tc.table_name = 'stage_config' and tc.constraint_type = 'PRIMARY KEY'"
        ).fetchall()
    ]
    assert pk_cols == ["stage"]


@pytestmark_db
def test_stage_config_admin_gated_read(db_conn):
    db_conn.execute("delete from profiles")
    db_conn.execute("delete from auth.users")
    db_conn.execute("truncate table stage_config")
    db_conn.execute(
        "insert into stage_config (stage, metered, requires_approval) "
        "values ('fetch', true, true), ('parse', false, false)"
    )

    # anon: no grant at all -> permission denied, independent of RLS.
    db_conn.execute("set role anon")
    try:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            db_conn.execute("select * from stage_config limit 1")
    finally:
        db_conn.execute("reset role")

    # authenticated non-admin: has the table grant, but the is_admin() RLS
    # policy filters every row away.
    _become(db_conn, admin=False)
    db_conn.execute("set role authenticated")
    try:
        rows = db_conn.execute("select * from stage_config").fetchall()
        assert rows == []
    finally:
        db_conn.execute("reset role")

    # authenticated admin: sees every row.
    _become(db_conn, admin=True)
    db_conn.execute("set role authenticated")
    try:
        count = db_conn.execute("select count(*) from stage_config").fetchone()[0]
        assert count == 2
    finally:
        db_conn.execute("reset role")

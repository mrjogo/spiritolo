"""Read-surface tests for the /ops DB browsers: recipe_exports admin access
and the audit_log_public projection.

recipe_exports shipped with RLS enabled but no policy and no grant (deny-all,
the same convention as `pages`); this migration adds the admin-read policy +
grant those browsers need. audit.log lives outside the schemas PostgREST
exposes, so audit_log_public is a plain security_invoker view in `public`
that inherits the SAME is_admin()-gated RLS policy already on audit.log.

Runs against TEST_DB_URL (skips-loud if unset); the ingredients conftest
auto-applies the new migration before these run.
"""
from __future__ import annotations

import os
import uuid

import psycopg
import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("TEST_DB_URL") is None,
    reason="TEST_DB_URL not set; DB-integration tests skip",
)


def _become(conn: psycopg.Connection, *, admin: bool) -> uuid.UUID:
    uid = uuid.uuid4()
    conn.execute("insert into auth.users (id, email) values (%s, %s)", (uid, f"{uid}@test"))
    conn.execute("update profiles set is_admin = %s where id = %s", (admin, uid))
    conn.execute(
        f"create or replace function auth.uid() returns uuid "
        f"language sql stable as $$ select '{uid}'::uuid $$"
    )
    conn.commit()
    return uid


@pytest.fixture
def clean(db_conn):
    db_conn.execute("truncate table recipes restart identity cascade")
    db_conn.execute("truncate table recipe_exports restart identity cascade")
    db_conn.execute("delete from profiles")
    db_conn.execute("delete from auth.users")
    yield db_conn
    db_conn.execute("truncate table recipes restart identity cascade")
    db_conn.execute("truncate table recipe_exports restart identity cascade")
    db_conn.execute("delete from profiles")
    db_conn.execute("delete from auth.users")


def _insert_export(conn) -> int:
    recipe_id = conn.execute(
        "insert into recipes (source_url, site, source) values "
        "('https://ex.test/x', 'ex', '{}'::jsonb) returning id"
    ).fetchone()[0]
    conn.execute(
        "insert into recipe_exports (recipe_id, recipe_slug, recipe_ref, "
        "converter_version, bundle) values (%s, 'x', 'com.spiritolo/x:v1', 'v1', '{}'::jsonb)",
        (recipe_id,),
    )
    return recipe_id


def test_recipe_exports_admin_gated_read(clean):
    conn = clean
    _insert_export(conn)
    conn.commit()

    conn.execute("set role anon")
    try:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("select * from recipe_exports limit 1")
    finally:
        conn.execute("reset role")

    _become(conn, admin=False)
    conn.execute("set role authenticated")
    try:
        rows = conn.execute("select * from recipe_exports").fetchall()
        assert rows == []
    finally:
        conn.execute("reset role")

    _become(conn, admin=True)
    conn.execute("set role authenticated")
    try:
        count = conn.execute("select count(*) from recipe_exports").fetchone()[0]
        assert count == 1
    finally:
        conn.execute("reset role")


def test_audit_log_public_is_security_invoker(db_conn):
    opts = db_conn.execute(
        "select reloptions from pg_class where oid = 'public.audit_log_public'::regclass"
    ).fetchone()[0]
    assert opts is not None and any("security_invoker=true" in o for o in opts)


def test_audit_log_public_admin_gated_read(clean):
    # audit.log is never wholesale-truncated between test files (it lives
    # outside the `public` schema the session-level fixture sweeps), so a
    # marker pk scopes this test to its own row instead of a fragile global
    # count that would drift with whatever other tests have logged this run.
    conn = clean
    marker = str(uuid.uuid4())
    conn.execute(
        "insert into audit.log (table_name, pk, op, actor_kind, source) "
        "values ('recipes', %s, 'I', 'system', 'unknown')",
        (marker,),
    )
    conn.commit()

    conn.execute("set role anon")
    try:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("select * from audit_log_public limit 1")
    finally:
        conn.execute("reset role")

    _become(conn, admin=False)
    conn.execute("set role authenticated")
    try:
        rows = conn.execute(
            "select * from audit_log_public where pk = %s", (marker,)
        ).fetchall()
        assert rows == []
    finally:
        conn.execute("reset role")

    _become(conn, admin=True)
    conn.execute("set role authenticated")
    try:
        count = conn.execute(
            "select count(*) from audit_log_public where pk = %s", (marker,)
        ).fetchone()[0]
        assert count == 1
    finally:
        conn.execute("reset role")

"""DB-side tests for the enqueue_job / approve_job SECURITY DEFINER RPCs.

Both functions guard on ``public.is_admin()`` (reads profiles.is_admin filtered
by ``auth.uid()``) and are the *sole* write path onto ``jobs`` — RLS is deny-all,
EXECUTE is granted to ``authenticated`` only. Each test rewires ``auth.uid()`` to
a freshly-inserted admin/non-admin user (as the DB owner), then ``set role`` to
exercise the real grant boundary. Skips-loud if TEST_DB_URL is unset, mirroring
test_taxonomy_rpcs.
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


@pytest.fixture
def rpc_db(db_conn):
    """Autocommit connection with the queue + auth surface cleaned.

    Order matters: truncate jobs first (its created_by/approved_by FK auth.users),
    then clear profiles + auth.users.
    """
    db_conn.execute("reset role")
    db_conn.execute("truncate table jobs restart identity cascade")
    db_conn.execute("delete from profiles")
    db_conn.execute("delete from auth.users")
    yield db_conn
    db_conn.execute("reset role")


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


_ENQUEUE = (
    "select enqueue_job(%s::text, %s::text, %s::jsonb, %s::text, "
    "%s::boolean, %s::int, %s::int)"
)


def test_enqueue_job_admin_only(rpc_db):
    conn = rpc_db

    # Non-admin authenticated session -> 42501.
    _become(conn, admin=False)
    conn.execute("set role authenticated")
    try:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute(_ENQUEUE, ("parse-ingredients", "run", "{}", None, False, None, None))
    finally:
        conn.execute("reset role")

    # Admin authenticated session -> returns a bigint, row stamped created_by.
    admin_uid = _become(conn, admin=True)
    conn.execute("set role authenticated")
    try:
        new_id = conn.execute(
            _ENQUEUE, ("parse-ingredients", "run", "{}", None, False, None, None)
        ).fetchone()[0]
    finally:
        conn.execute("reset role")

    assert isinstance(new_id, int)
    row = conn.execute(
        "select stage, state, created_by from jobs where id = %s", (new_id,)
    ).fetchone()
    assert row[0] == "parse-ingredients"
    assert row[1] == "queued"
    assert str(row[2]) == str(admin_uid)


def test_enqueue_free_vs_metered_state(rpc_db):
    conn = rpc_db
    _become(conn, admin=True)

    free_id = conn.execute(
        _ENQUEUE, ("map-ingredient", "run", "{}", None, False, None, None)
    ).fetchone()[0]
    metered_id = conn.execute(
        _ENQUEUE, ("map-ingredient", "run", "{}", None, True, 750, 2000)
    ).fetchone()[0]

    free = conn.execute(
        "select state, requires_approval, cost_estimate_cents from jobs where id = %s",
        (free_id,),
    ).fetchone()
    assert free == ("queued", False, None)

    metered = conn.execute(
        "select state, requires_approval, cost_estimate_cents, max_cost_cents "
        "from jobs where id = %s",
        (metered_id,),
    ).fetchone()
    assert metered == ("awaiting_approval", True, 750, 2000)


def test_enqueue_anon_cannot_insert_directly(rpc_db):
    conn = rpc_db

    # anon: no table INSERT grant -> permission denied.
    conn.execute("set role anon")
    try:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("insert into jobs (stage) values ('parse')")
    finally:
        conn.execute("reset role")

    # authenticated: read-only grant, still cannot INSERT directly (the RPC is
    # the only write path).
    conn.execute("set role authenticated")
    try:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("insert into jobs (stage) values ('parse')")
    finally:
        conn.execute("reset role")


def test_approve_job_gates_metered(rpc_db):
    conn = rpc_db
    from ingredients.queue.claim import claim_one

    _become(conn, admin=True)
    jid = conn.execute(
        _ENQUEUE, ("map-ingredient", "run", "{}", None, True, 500, 5000)
    ).fetchone()[0]

    # awaiting_approval -> not claimable.
    assert claim_one(conn, worker_id="w1", max_cost_cents=100000) is None

    # approve_job by a non-admin is rejected.
    _become(conn, admin=False)
    conn.execute("set role authenticated")
    try:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("select approve_job(%s)", (jid,))
    finally:
        conn.execute("reset role")

    # approve_job by an admin flips approved/approved_by/state.
    admin_uid = _become(conn, admin=True)
    conn.execute("set role authenticated")
    try:
        conn.execute("select approve_job(%s)", (jid,))
    finally:
        conn.execute("reset role")

    row = conn.execute(
        "select approved, approved_by, state from jobs where id = %s", (jid,)
    ).fetchone()
    assert row[0] is True
    assert str(row[1]) == str(admin_uid)
    assert row[2] == "queued"

    # Now claimable.
    claimed = claim_one(conn, worker_id="w1", max_cost_cents=100000)
    assert claimed is not None and claimed["id"] == jid

    # approve_job on an already-claimed job is a no-op (state stays 'running').
    conn.execute("select approve_job(%s)", (jid,))
    assert conn.execute(
        "select state from jobs where id = %s", (jid,)
    ).fetchone()[0] == "running"

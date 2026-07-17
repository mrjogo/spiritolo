"""Schema + behavior + boundary tests for the stage_run_outcome_counts view.

Aggregates stage_runs by (stage, outcome) for the /ops dashboard's
StatusPill row + accumulated-cost badge — the one dashboard aggregate that
can be computed today without the relational content tables (recipe_docs/
recipes), which haven't landed yet. security_invoker=true so the existing
admin-only RLS policy on stage_runs applies to the view too, instead of the
view owner's broader privileges leaking through — which in turn requires
stage_runs to actually GRANT SELECT to authenticated, a grant the original
stage_runs migration omitted; this migration adds it.

Runs against TEST_DB_URL (skips-loud if unset); the ingredients conftest
auto-applies the new migrations before these run.
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


def _become(conn, *, admin: bool) -> uuid.UUID:
    uid = uuid.uuid4()
    conn.execute("insert into auth.users (id, email) values (%s, %s)", (uid, f"{uid}@test"))
    conn.execute("update profiles set is_admin = %s where id = %s", (admin, uid))
    conn.execute(
        f"create or replace function auth.uid() returns uuid "
        f"language sql stable as $$ select '{uid}'::uuid $$"
    )
    return uid


def _insert_run(conn, entity_id, stage, outcome, *, cost_cents=None, method="llm"):
    conn.execute(
        "insert into stage_runs (entity_type, entity_id, stage, version, outcome, method, cost_cents) "
        "values ('recipe', %s, %s, 'v1', %s, %s, %s)",
        (entity_id, stage, outcome, method, cost_cents),
    )
    # The view counts only the LIVE version (stage_runs is append-versioned), so
    # point the stage at v1 for these single-version fixtures.
    conn.execute(
        "insert into stage_live_version (stage, version) values (%s, 'v1') "
        "on conflict (stage) do update set version = 'v1'",
        (stage,),
    )


@pytest.fixture
def clean_stage_runs(db_conn):
    db_conn.execute("truncate table stage_runs restart identity cascade")
    db_conn.execute("delete from stage_live_version")
    yield db_conn
    db_conn.execute("truncate table stage_runs restart identity cascade")
    db_conn.execute("delete from stage_live_version")


def test_view_is_security_invoker(db_conn):
    opts = db_conn.execute(
        "select reloptions from pg_class where oid = 'stage_run_outcome_counts'::regclass"
    ).fetchone()[0]
    assert opts is not None and any("security_invoker=true" in o for o in opts)


def test_stage_runs_grants_select_to_authenticated(db_conn):
    # The original stage_runs migration wrote an is_admin() RLS policy for
    # `authenticated` but never GRANTed the table to that role, so no
    # authenticated session — not even an admin — could ever reach the
    # policy. This migration's added grant is what makes the view (and any
    # future admin read surface over stage_runs) actually usable.
    grants = {
        r[0]
        for r in db_conn.execute(
            "select grantee from information_schema.role_table_grants "
            "where table_schema = 'public' and table_name = 'stage_runs' "
            "and privilege_type = 'SELECT'"
        ).fetchall()
    }
    assert "authenticated" in grants


def test_aggregates_count_and_cost_per_stage_outcome(clean_stage_runs):
    conn = clean_stage_runs
    _insert_run(conn, 1, "extract", "resolved", cost_cents=10)
    _insert_run(conn, 2, "extract", "resolved", cost_cents=20)
    _insert_run(conn, 3, "extract", "abstain")
    _insert_run(conn, 4, "fetch", "resolved", cost_cents=5)

    rows = {
        (r[0], r[1]): (r[2], r[3])
        for r in conn.execute(
            "select stage, outcome, run_count, cost_cents from stage_run_outcome_counts "
            "where stage in ('extract', 'fetch') order by stage, outcome"
        ).fetchall()
    }
    assert rows[("extract", "resolved")] == (2, 30)
    assert rows[("extract", "abstain")] == (1, 0)
    assert rows[("fetch", "resolved")] == (1, 5)


def test_view_counts_live_version_only(clean_stage_runs):
    # stage_runs is append-versioned; the view counts only the LIVE version, so
    # a bumped entity contributes its live-version outcome, not both versions.
    conn = clean_stage_runs
    _insert_run(conn, 1, "map", "pending")  # v1, live pointer -> v1
    conn.execute(
        "insert into stage_runs (entity_type, entity_id, stage, version, outcome, method) "
        "values ('recipe', 1, 'map', 'v2', 'resolved', 'llm')"
    )
    conn.execute(
        "insert into stage_live_version (stage, version) values ('map', 'v2') "
        "on conflict (stage) do update set version = excluded.version"
    )
    rows = dict(
        conn.execute(
            "select outcome, run_count from stage_run_outcome_counts where stage = 'map'"
        ).fetchall()
    )
    assert rows == {"resolved": 1}


def test_admin_gated_read(clean_stage_runs):
    conn = clean_stage_runs
    _insert_run(conn, 1, "extract", "resolved", cost_cents=10)
    conn.execute("delete from profiles")
    conn.execute("delete from auth.users")

    conn.execute("set role anon")
    try:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("select * from stage_run_outcome_counts limit 1")
    finally:
        conn.execute("reset role")

    _become(conn, admin=False)
    conn.execute("set role authenticated")
    try:
        rows = conn.execute("select * from stage_run_outcome_counts").fetchall()
        assert rows == []
    finally:
        conn.execute("reset role")

    _become(conn, admin=True)
    conn.execute("set role authenticated")
    try:
        rows = conn.execute("select * from stage_run_outcome_counts").fetchall()
        assert len(rows) == 1
    finally:
        conn.execute("reset role")

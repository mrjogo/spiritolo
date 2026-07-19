"""Schema-shape tests for the Postgres-as-queue tables.

Asserts the ``jobs`` migrations produce the columns,
enum, CHECKs, defaults, partial indexes, RLS + realtime membership the
worker/UI depend on. Runs against ``TEST_DB_URL`` (skips-loud if unset,
mirroring the taxonomy-RPC suite; the migrations conftest auto-applies
the new ``*.sql`` files before these run).
"""
from __future__ import annotations

import os

import psycopg
import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("TEST_DB_URL") is None,
    reason="TEST_DB_URL not set; DB-integration tests skip",
)


def _columns(conn, table: str) -> dict[str, tuple[str, str]]:
    return {
        r[0]: (r[1], r[2])
        for r in conn.execute(
            "select column_name, data_type, is_nullable "
            "from information_schema.columns "
            "where table_schema = 'public' and table_name = %s",
            (table,),
        ).fetchall()
    }


def _checks(conn, table: str) -> list[str]:
    return [
        r[0]
        for r in conn.execute(
            "select pg_get_constraintdef(oid) from pg_constraint "
            "where conrelid = ('public.' || %s)::regclass and contype = 'c'",
            (table,),
        ).fetchall()
    ]


# ---------------------------------------------------------------------------
# jobs
# ---------------------------------------------------------------------------

def test_jobs_shape(db_conn):
    cols = _columns(db_conn, "jobs")
    expected = [
        "stage", "version", "kind", "payload", "state",
        "requires_approval", "approved", "approved_by", "approved_at",
        "cost_estimate_cents", "cost_actual_cents", "max_cost_cents",
        "progress", "error_code", "worker_id",
        "last_heartbeat", "created_by", "created_at", "started_at",
        "finished_at",
        # explicit-runs additions
        "llm_provider", "llm_model", "apply_mode",
    ]
    for c in expected:
        assert c in cols, f"jobs missing column {c!r}"
    # batch_id folded away with job_batches.
    assert "batch_id" not in cols

    # state is the job_state enum.
    assert cols["state"][0] == "USER-DEFINED"
    udt = db_conn.execute(
        "select udt_name from information_schema.columns "
        "where table_schema = 'public' and table_name = 'jobs' "
        "and column_name = 'state'"
    ).fetchone()[0]
    assert udt == "job_state"
    labels = {
        r[0]
        for r in db_conn.execute(
            "select e.enumlabel from pg_enum e "
            "join pg_type t on t.oid = e.enumtypid "
            "where t.typname = 'job_state'"
        ).fetchall()
    }
    assert {
        "queued", "awaiting_approval", "running", "succeeded", "failed",
        "draft", "done",
    } <= labels

    # kind CHECK(run,reset,reconcile).
    kind_checks = [c for c in _checks(db_conn, "jobs") if "kind" in c]
    assert any(
        "'run'" in c and "'reset'" in c and "'reconcile'" in c for c in kind_checks
    ), f"no kind CHECK found in {kind_checks}"

    # progress jsonb default '{}'.
    assert cols["progress"][0] == "jsonb"
    prog_default = db_conn.execute(
        "select column_default from information_schema.columns "
        "where table_schema = 'public' and table_name = 'jobs' "
        "and column_name = 'progress'"
    ).fetchone()[0]
    assert prog_default is not None and "{}" in prog_default

    assert cols["payload"][0] == "jsonb"

    # Partial claimable index over created_at.
    idx = db_conn.execute(
        "select indexdef from pg_indexes "
        "where schemaname = 'public' and indexname = 'jobs_claimable_idx'"
    ).fetchone()
    assert idx is not None, "jobs_claimable_idx missing"
    d = idx[0].lower()
    assert "created_at" in d
    assert "state = 'queued'" in d
    assert "requires_approval" in d and "approved" in d

    # apply_mode CHECK(auto,hold).
    am_checks = [c for c in _checks(db_conn, "jobs") if "apply_mode" in c]
    assert any(
        "'auto'" in c and "'hold'" in c for c in am_checks
    ), f"no apply_mode CHECK found in {am_checks}"


def test_jobs_rls_and_realtime(db_conn):
    # RLS enabled.
    assert db_conn.execute(
        "select relrowsecurity from pg_class where oid = 'public.jobs'::regclass"
    ).fetchone()[0] is True

    # An admin SELECT policy exists.
    assert db_conn.execute(
        "select count(*) from pg_policies "
        "where schemaname = 'public' and tablename = 'jobs' and cmd = 'SELECT'"
    ).fetchone()[0] >= 1

    # jobs is a member of the supabase_realtime publication.
    assert db_conn.execute(
        "select count(*) from pg_publication_tables "
        "where pubname = 'supabase_realtime' "
        "and schemaname = 'public' and tablename = 'jobs'"
    ).fetchone()[0] == 1

    # anon cannot select jobs directly (no table grant -> permission denied).
    db_conn.execute("set role anon")
    try:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            db_conn.execute("select * from jobs").fetchall()
    finally:
        db_conn.execute("reset role")

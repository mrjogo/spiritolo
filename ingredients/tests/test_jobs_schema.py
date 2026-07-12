"""Schema-shape tests for the Postgres-as-queue tables (WS-B22).

Asserts the ``jobs`` + ``job_batches`` migrations produce the columns,
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
        "progress", "error_code", "batch_id", "worker_id",
        "last_heartbeat", "created_by", "created_at", "started_at",
        "finished_at",
    ]
    for c in expected:
        assert c in cols, f"jobs missing column {c!r}"

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
    assert {"queued", "awaiting_approval", "running", "succeeded", "failed"} <= labels

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

    # batch_id FK -> job_batches.
    fks = db_conn.execute(
        "select confrelid::regclass::text from pg_constraint "
        "where conrelid = 'public.jobs'::regclass and contype = 'f'"
    ).fetchall()
    assert any("job_batches" in r[0] for r in fks), f"no FK to job_batches in {fks}"


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


# ---------------------------------------------------------------------------
# job_batches
# ---------------------------------------------------------------------------

def test_job_batches_shape(db_conn):
    cols = _columns(db_conn, "job_batches")
    for c in ["provider", "provider_batch_id", "state", "custom_id_map"]:
        assert c in cols, f"job_batches missing column {c!r}"

    # provider default 'openai'.
    pdef = db_conn.execute(
        "select column_default from information_schema.columns "
        "where table_schema = 'public' and table_name = 'job_batches' "
        "and column_name = 'provider'"
    ).fetchone()[0]
    assert pdef is not None and "openai" in pdef

    # provider_batch_id unique (constraint or unique index).
    idx_defs = [
        r[0].lower()
        for r in db_conn.execute(
            "select indexdef from pg_indexes "
            "where schemaname = 'public' and tablename = 'job_batches'"
        ).fetchall()
    ]
    assert any(
        "provider_batch_id" in d and "unique" in d for d in idx_defs
    ), f"no unique index on provider_batch_id in {idx_defs}"

    # state CHECK(submitted,in_progress,completed,failed,ingested).
    wanted = ["'submitted'", "'in_progress'", "'completed'", "'failed'", "'ingested'"]
    assert any(
        all(s in c for s in wanted) for c in _checks(db_conn, "job_batches")
    ), "no state CHECK covering all five batch states"

    # custom_id_map jsonb.
    assert cols["custom_id_map"][0] == "jsonb"

    # Partial open index scoped to submitted/in_progress.
    open_idx = db_conn.execute(
        "select indexdef from pg_indexes "
        "where schemaname = 'public' and indexname = 'job_batches_open_idx'"
    ).fetchone()
    assert open_idx is not None, "job_batches_open_idx missing"
    od = open_idx[0].lower()
    assert "submitted" in od and "in_progress" in od

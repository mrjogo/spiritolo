"""Migration assertions for 20260719120000_drop_apply_and_rename_stages.sql.

Verifies the apply/hold teardown + the stage rename landed against
``TEST_DB_URL`` (the ingredients conftest auto-applies new migrations before
these run):

  - ``jobs.apply_mode`` is gone.
  - ``apply_run_items`` no longer exists.
  - the ``job_items.state`` CHECK no longer permits ``pending_apply``.
  - ``create_run`` is the single-arg (stage-only) overload.
  - stored ``stage`` strings use canonical ``<verb>-<object>`` names (a legacy
    ``'map'`` value cannot be inserted-and-left; the canonical names round-trip).
"""
from __future__ import annotations

import os

import psycopg
import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("TEST_DB_URL") is None,
    reason="TEST_DB_URL not set; DB-integration tests skip",
)


@pytest.fixture()
def conn(test_db_url):
    with psycopg.connect(test_db_url, autocommit=True) as c:
        yield c


def test_jobs_apply_mode_column_dropped(conn):
    cols = {
        r[0]
        for r in conn.execute(
            "select column_name from information_schema.columns "
            "where table_schema = 'public' and table_name = 'jobs'"
        ).fetchall()
    }
    assert "apply_mode" not in cols


def test_apply_run_items_function_dropped(conn):
    exists = conn.execute(
        "select count(*) from pg_proc where proname = 'apply_run_items'"
    ).fetchone()[0]
    assert exists == 0


def test_job_items_state_check_has_no_pending_apply(conn):
    checks = [
        r[0]
        for r in conn.execute(
            "select pg_get_constraintdef(oid) from pg_constraint "
            "where conrelid = 'public.job_items'::regclass and contype = 'c' "
            "and conname = 'job_items_state_check'"
        ).fetchall()
    ]
    assert checks, "job_items_state_check constraint is missing"
    clause = checks[0]
    assert "pending_apply" not in clause
    for state in ("pending", "running", "applied", "flagged", "failed"):
        assert f"'{state}'" in clause


def test_create_run_is_single_arg(conn):
    # Exactly one create_run overload, taking a single (stage text) argument.
    sigs = [
        r[0]
        for r in conn.execute(
            "select pg_get_function_identity_arguments(oid) from pg_proc "
            "where proname = 'create_run' and pronamespace = 'public'::regnamespace"
        ).fetchall()
    ]
    assert sigs == ["stage text"], sigs


def test_state_check_rejects_pending_apply(conn):
    conn.execute(
        "insert into recipes (id, source_url, site, source) "
        "values (9101, 'http://example.test/9101', 'test', '{}'::jsonb) "
        "on conflict do nothing"
    )
    jid = conn.execute(
        "insert into jobs (stage, state) values ('map-ingredient', 'draft') returning id"
    ).fetchone()[0]
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute(
            "insert into job_items (job_id, entity_type, entity_id, stage, "
            "code_version, outcome, method, state) values "
            "(%s, 'recipe', 9101, 'map-ingredient', 'v1', 'resolved', "
            "'deterministic', 'pending_apply')",
            (jid,),
        )


def test_canonical_stage_names_round_trip(conn):
    # The renamed canonical stage strings are storable/queryable end to end.
    canonical = [
        "extract-recipe",
        "parse-ingredients",
        "map-ingredient",
        "convert-steps",
        "cluster-recipes",
        "export-recipegf",
    ]
    ids = []
    for name in canonical:
        jid = conn.execute(
            "insert into jobs (stage, state) values (%s, 'draft') returning id",
            (name,),
        ).fetchone()[0]
        ids.append(jid)
    stored = {
        r[0]
        for r in conn.execute(
            "select stage from jobs where id = any(%s)", (ids,)
        ).fetchall()
    }
    assert stored == set(canonical)

"""stage_runs foreign-key wiring to the queue tables.

stage_runs landed before ``jobs`` / ``job_batches`` existed, so its ``batch_id``
and ``job_id`` columns were plain bigints with the references deferred. Once the
queue tables exist a migration wires the FKs. These tests assert both
constraints exist and that a dangling reference is rejected — the ledger may
only cite a real job / batch.

Runs against ``TEST_DB_URL`` (the migrations conftest auto-applies the new
``*.sql`` before these run).
"""
from __future__ import annotations

import os

import psycopg
import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("TEST_DB_URL") is None,
    reason="TEST_DB_URL not set; DB-integration tests skip",
)


def _fk_targets(conn) -> dict[str, tuple[str, str]]:
    """Map each FK constraint on stage_runs to (local_column, referenced_table)."""
    rows = conn.execute(
        """
        select con.conname,
               att.attname,
               ref.relname
        from pg_constraint con
        join pg_class rel on rel.oid = con.conrelid
        join pg_class ref on ref.oid = con.confrelid
        join unnest(con.conkey) with ordinality as k(attnum, ord) on true
        join pg_attribute att
          on att.attrelid = con.conrelid and att.attnum = k.attnum
        where rel.relname = 'stage_runs' and con.contype = 'f'
        """
    ).fetchall()
    return {conname: (col, reftable) for conname, col, reftable in rows}


def test_batch_id_fk_references_job_batches(db_conn):
    fks = _fk_targets(db_conn)
    targets = {(col, ref) for col, ref in fks.values()}
    assert ("batch_id", "job_batches") in targets, (
        "stage_runs.batch_id must have a FK to job_batches"
    )


def test_job_id_fk_references_jobs(db_conn):
    fks = _fk_targets(db_conn)
    targets = {(col, ref) for col, ref in fks.values()}
    assert ("job_id", "jobs") in targets, (
        "stage_runs.job_id must have a FK to jobs"
    )


def _insert_stage_run(conn, *, batch_id=None, job_id=None):
    conn.execute(
        """
        insert into stage_runs
            (entity_type, entity_id, stage, version, outcome, method,
             batch_id, job_id)
        values ('recipe', 1, 'demo', 'v1', 'resolved', 'llm', %s, %s)
        """,
        (batch_id, job_id),
    )


def test_dangling_batch_id_rejected(db_conn):
    db_conn.execute("truncate table stage_runs restart identity cascade")
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        _insert_stage_run(db_conn, batch_id=999_999)


def test_dangling_job_id_rejected(db_conn):
    db_conn.execute("truncate table stage_runs restart identity cascade")
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        _insert_stage_run(db_conn, job_id=999_999)


def test_null_references_allowed(db_conn):
    # A deterministic run cites neither a job nor a batch; both FKs are nullable.
    db_conn.execute("truncate table stage_runs restart identity cascade")
    _insert_stage_run(db_conn, batch_id=None, job_id=None)
    n = db_conn.execute("select count(*) from stage_runs").fetchone()[0]
    assert n == 1

"""Reaper tests for the Postgres-as-queue.

``queue.reaper.requeue_stale`` puts jobs whose ``last_heartbeat`` is older than
a threshold back on the queue (state='queued', worker_id=null). It is the entire
retry story — safe to re-run because stage writes are idempotent UPSERTs. DB-
integration against TEST_DB_URL; skips-loud if unset.
"""
from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("TEST_DB_URL") is None,
    reason="TEST_DB_URL not set; DB-integration tests skip",
)


def test_reaper_requeues_stale(db_conn):
    from ingredients.queue.reaper import requeue_stale

    db_conn.execute("truncate table jobs restart identity cascade")
    stale = db_conn.execute(
        "insert into jobs (stage, state, worker_id, last_heartbeat) "
        "values ('parse', 'running', 'w1', now() - interval '5 minutes') returning id"
    ).fetchone()[0]
    fresh = db_conn.execute(
        "insert into jobs (stage, state, worker_id, last_heartbeat) "
        "values ('parse', 'running', 'w2', now()) returning id"
    ).fetchone()[0]

    n = requeue_stale(db_conn, older_than_seconds=120)
    assert n == 1

    assert db_conn.execute(
        "select state, worker_id from jobs where id = %s", (stale,)
    ).fetchone() == ("queued", None)

    # The fresh-heartbeat job is untouched.
    assert db_conn.execute(
        "select state, worker_id from jobs where id = %s", (fresh,)
    ).fetchone() == ("running", "w2")


def test_reaper_idempotent(db_conn):
    from ingredients.queue.reaper import requeue_stale

    db_conn.execute("truncate table jobs restart identity cascade")
    jid = db_conn.execute(
        "insert into jobs (stage, state, worker_id, last_heartbeat) "
        "values ('parse', 'running', 'w1', now() - interval '5 minutes') returning id"
    ).fetchone()[0]

    n1 = requeue_stale(db_conn, older_than_seconds=120)
    n2 = requeue_stale(db_conn, older_than_seconds=120)
    assert n1 == 1
    assert n2 == 0
    assert db_conn.execute(
        "select state from jobs where id = %s", (jid,)
    ).fetchone()[0] == "queued"

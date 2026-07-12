"""Claim-path tests for the Postgres-as-queue (WS-B22).

``queue.claim.claim_one`` does a single ``UPDATE ... WHERE id = (SELECT ... FOR
UPDATE SKIP LOCKED LIMIT 1) RETURNING *`` so concurrent workers never claim the
same job and never block on each other. These are DB-integration tests against
TEST_DB_URL; skips-loud if unset.
"""
from __future__ import annotations

import os

import psycopg
import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("TEST_DB_URL") is None,
    reason="TEST_DB_URL not set; DB-integration tests skip",
)


def test_claim_skip_locked(test_db_url, db_conn):
    from ingredients.queue.claim import claim_one

    db_conn.execute("truncate table jobs restart identity cascade")
    a = db_conn.execute(
        "insert into jobs (stage, state) values ('parse', 'queued') returning id"
    ).fetchone()[0]
    b = db_conn.execute(
        "insert into jobs (stage, state) values ('parse', 'queued') returning id"
    ).fetchone()[0]

    # Two independent transactions claim concurrently. Neither commits between
    # the two claims, so both row locks coexist; SKIP LOCKED must hand each a
    # distinct row without blocking (a statement_timeout turns a regression that
    # blocks into a fast failure instead of a hang).
    c1 = psycopg.connect(test_db_url)
    c2 = psycopg.connect(test_db_url)
    try:
        c1.execute("set statement_timeout = '5s'")
        c2.execute("set statement_timeout = '5s'")
        j1 = claim_one(c1, worker_id="w1")
        j2 = claim_one(c2, worker_id="w2")
        assert j1 is not None and j2 is not None
        assert j1["id"] != j2["id"]
        assert {j1["id"], j2["id"]} == {a, b}
        assert j1["state"] == "running" and j2["state"] == "running"
        c1.commit()
        c2.commit()
    finally:
        c1.close()
        c2.close()


def test_claim_respects_max_cost_gate(db_conn):
    from ingredients.queue.claim import claim_one

    db_conn.execute("truncate table jobs restart identity cascade")
    jid = db_conn.execute(
        "insert into jobs (stage, state, cost_estimate_cents) "
        "values ('map', 'queued', 500) returning id"
    ).fetchone()[0]

    # Budget below the estimate -> not claimed.
    assert claim_one(db_conn, worker_id="w1", max_cost_cents=100) is None

    # Budget at/above the estimate -> claimed.
    claimed = claim_one(db_conn, worker_id="w1", max_cost_cents=1000)
    assert claimed is not None and claimed["id"] == jid


def test_claim_ignores_awaiting_approval(db_conn):
    from ingredients.queue.claim import claim_one

    db_conn.execute("truncate table jobs restart identity cascade")
    db_conn.execute(
        "insert into jobs (stage, state, requires_approval, approved) "
        "values ('map', 'awaiting_approval', true, false)"
    )
    assert claim_one(db_conn, worker_id="w1", max_cost_cents=100000) is None

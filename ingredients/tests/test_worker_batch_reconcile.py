"""Boot-time reconciliation of open ``job_batches``.

The worker submits big metered stage runs to a hosted provider's async Batch
API (half price, ~24h SLA) and records each as a ``job_batches`` row whose
``custom_id_map`` ties every request's opaque ``custom_id`` back to the entity +
stage the answer belongs to. On boot the worker polls each open batch through an
injected provider client; a completed batch is ingested into the ``stage_runs``
ledger (one UPSERT per resolved ``custom_id``) and flipped to ``ingested``.

DB-integration against ``TEST_DB_URL``; the provider client is a fake — never a
live model, never network.
"""
from __future__ import annotations

import os
import threading

import psycopg
import pytest
from psycopg.types.json import Json

from ingredients.worker.batches import (
    BatchItemResult,
    BatchPoll,
    build_reconcile_hook,
    reconcile,
)
from ingredients.worker.loop import serve

pytestmark = pytest.mark.skipif(
    os.environ.get("TEST_DB_URL") is None,
    reason="TEST_DB_URL not set; DB-integration tests skip",
)


class FakeBatchClient:
    """Returns a canned ``BatchPoll`` per provider_batch_id and records which
    ids were polled — so a test can assert the reconciler polls open batches
    only."""

    def __init__(self, polls: dict[str, BatchPoll]) -> None:
        self.polls = polls
        self.calls: list[str] = []

    def get_batch(self, provider_batch_id: str) -> BatchPoll:
        self.calls.append(provider_batch_id)
        return self.polls[provider_batch_id]


def _reset(db_conn) -> None:
    db_conn.execute("truncate table stage_runs restart identity cascade")
    db_conn.execute("truncate table jobs restart identity cascade")
    db_conn.execute("truncate table job_batches restart identity cascade")


def _seed_batch(db_conn, *, provider_batch_id, state, custom_id_map) -> int:
    return db_conn.execute(
        "insert into job_batches (provider_batch_id, state, custom_id_map) "
        "values (%s, %s, %s) returning id",
        (provider_batch_id, state, Json(custom_id_map)),
    ).fetchone()[0]


def _desc(entity_id, *, stage="map", version="v1"):
    return {"entity_type": "recipe", "entity_id": entity_id,
            "stage": stage, "version": version}


def _stage_runs(db_conn, *, stage="map"):
    return {
        r[0]: r
        for r in db_conn.execute(
            "select entity_id, outcome, method, batch_id from stage_runs "
            "where stage=%s order by entity_id",
            (stage,),
        ).fetchall()
    }


def test_reconcile_open_only(db_conn):
    _reset(db_conn)
    open_a = _seed_batch(db_conn, provider_batch_id="pa", state="submitted",
                         custom_id_map={})
    open_b = _seed_batch(db_conn, provider_batch_id="pb", state="in_progress",
                         custom_id_map={})
    _seed_batch(db_conn, provider_batch_id="pi", state="ingested", custom_id_map={})
    _seed_batch(db_conn, provider_batch_id="pf", state="failed", custom_id_map={})

    client = FakeBatchClient({
        "pa": BatchPoll(state="in_progress"),
        "pb": BatchPoll(state="in_progress"),
    })
    reconcile(db_conn, client)

    # Only the two open batches were polled; terminal rows are never re-polled.
    assert sorted(client.calls) == ["pa", "pb"]


def test_completed_batch_ingested(db_conn):
    _reset(db_conn)
    cmap = {"c1": _desc(101), "c2": _desc(102)}
    bid = _seed_batch(db_conn, provider_batch_id="pb", state="submitted",
                      custom_id_map=cmap)
    client = FakeBatchClient({
        "pb": BatchPoll(state="completed", results=[
            BatchItemResult(custom_id="c1", output={"node": "gin"}),
            BatchItemResult(custom_id="c2", output={"node": "rum"}),
        ]),
    })

    summary = reconcile(db_conn, client)

    runs = _stage_runs(db_conn)
    assert set(runs) == {101, 102}
    assert runs[101][1:] == ("resolved", "llm", bid)  # outcome, method, batch_id
    assert runs[102][3] == bid
    assert db_conn.execute(
        "select state from job_batches where id=%s", (bid,)
    ).fetchone()[0] == "ingested"
    assert summary.runs_written == 2
    assert summary.parked == 0


def test_in_progress_left_open(db_conn):
    _reset(db_conn)
    bid = _seed_batch(db_conn, provider_batch_id="pb", state="submitted",
                      custom_id_map={"c1": _desc(201)})
    client = FakeBatchClient({"pb": BatchPoll(state="in_progress")})

    summary = reconcile(db_conn, client)

    assert db_conn.execute("select count(*) from stage_runs").fetchone()[0] == 0
    assert db_conn.execute(
        "select state from job_batches where id=%s", (bid,)
    ).fetchone()[0] == "in_progress"
    assert summary.runs_written == 0


def test_ingest_idempotent(db_conn):
    _reset(db_conn)
    bid = _seed_batch(db_conn, provider_batch_id="pb", state="submitted",
                      custom_id_map={"c1": _desc(301), "c2": _desc(302)})
    client = FakeBatchClient({
        "pb": BatchPoll(state="completed", results=[
            BatchItemResult(custom_id="c1", output={"x": 1}),
            BatchItemResult(custom_id="c2", output={"x": 2}),
        ]),
    })

    reconcile(db_conn, client)
    assert db_conn.execute("select count(*) from stage_runs").fetchone()[0] == 2

    client.calls.clear()
    reconcile(db_conn, client)

    # The batch is now 'ingested' — a second reconcile never re-polls it.
    assert client.calls == []
    assert db_conn.execute("select count(*) from stage_runs").fetchone()[0] == 2
    assert db_conn.execute(
        "select state from job_batches where id=%s", (bid,)
    ).fetchone()[0] == "ingested"


def test_partial_batch_parks_failures(db_conn):
    _reset(db_conn)
    cmap = {"c1": _desc(401), "c2": _desc(402), "c3": _desc(403)}
    bid = _seed_batch(db_conn, provider_batch_id="pb", state="submitted",
                      custom_id_map=cmap)
    client = FakeBatchClient({
        "pb": BatchPoll(state="completed", results=[
            BatchItemResult(custom_id="c1", output={"ok": True}),   # resolved
            BatchItemResult(custom_id="c2", output=None, error="rate_limited"),  # errored
            # c3 absent from results entirely -> dropped
        ]),
    })

    summary = reconcile(db_conn, client)

    runs = _stage_runs(db_conn)
    assert set(runs) == {401}, "only the resolved custom_id gets a ledger row"
    assert summary.runs_written == 1
    assert summary.parked == 2, "errored + dropped custom_ids are parked"
    # The batch still reaches a terminal state so it isn't re-polled forever.
    assert db_conn.execute(
        "select state from job_batches where id=%s", (bid,)
    ).fetchone()[0] == "ingested"


def test_boot_calls_reconcile_before_claim(test_db_url, db_conn):
    _reset(db_conn)
    # A completed batch whose result becomes the 'map' run for entity 501.
    _seed_batch(db_conn, provider_batch_id="pb", state="submitted",
                custom_id_map={"c1": _desc(501)})
    client = FakeBatchClient({
        "pb": BatchPoll(state="completed", results=[
            BatchItemResult(custom_id="c1", output={"node": "vodka"}),
        ]),
    })
    # A queued job whose stage_fn checks whether the batch's row already exists
    # by the time it is claimed — proving reconcile ran on boot, before claim.
    db_conn.execute("insert into jobs (stage, state) values ('check', 'queued')")

    seen: dict[str, bool] = {}
    stop = threading.Event()

    def check_fn(job, conn, providers):
        row = conn.execute(
            "select 1 from stage_runs where entity_type='recipe' "
            "and entity_id=501 and stage='map'"
        ).fetchone()
        seen["row_before_claim"] = row is not None
        stop.set()

    conn = psycopg.connect(test_db_url)
    try:
        serve(
            conn,
            stage_fns={"check": check_fn},
            reconcile_hook=build_reconcile_hook(client),
            reaper_older_than_seconds=1,
            stop_event=stop,
            poll_interval=0.01,
        )
    finally:
        conn.close()

    assert seen.get("row_before_claim") is True

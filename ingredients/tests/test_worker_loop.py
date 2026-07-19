"""Worker loop: claim -> dispatch -> heartbeat -> finalize.

One loop ``tick`` claims the oldest runnable job (reusing the queue claim),
dispatches it to its ``stage_fn`` while a background thread heartbeats, then sets
the terminal state + progress and rolls cost up from ``job_items``. ``boot``
runs the reaper once (Railway-restart safety) and leaves a seam where the B24
batch reconciler will hook in.

DB-integration against TEST_DB_URL; fake stage_fns only, never a live model.
"""
from __future__ import annotations

import time

import psycopg
from psycopg.types.json import Json

from ingredients.pipeline.ledger import record_run
from ingredients.worker.loop import boot, tick


def _seed_job(db_conn, *, stage, payload=None, **cols):
    columns = ["stage", "state"]
    values = [stage, cols.pop("state", "queued")]
    if payload is not None:
        columns.append("payload")
        values.append(Json(payload))
    for k, v in cols.items():
        columns.append(k)
        values.append(v)
    placeholders = ", ".join(["%s"] * len(values))
    return db_conn.execute(
        f"insert into jobs ({', '.join(columns)}) values ({placeholders}) returning id",
        values,
    ).fetchone()[0]


def test_claim_run_finish(test_db_url, db_conn):
    db_conn.execute("truncate table jobs restart identity cascade")
    db_conn.execute("truncate table job_items restart identity cascade")
    payload = {"entity_ids": [101], "entity_type": "recipe", "version": "vtest"}
    jid = _seed_job(db_conn, stage="demo", payload=payload)

    def demo_fn(job, conn, providers):
        p = job["payload"]
        for eid in p["entity_ids"]:
            record_run(
                conn, entity_type=p["entity_type"], entity_id=eid,
                stage=job["stage"], version=p["version"], outcome="resolved",
                method="deterministic", cost_cents=0, job_id=job["id"],
            )
        return {"processed": len(p["entity_ids"])}

    conn = psycopg.connect(test_db_url)
    try:
        ran = tick(conn, stage_fns={"demo": demo_fn})
    finally:
        conn.close()

    assert ran is True
    state, started, finished, progress = db_conn.execute(
        "select state, started_at, finished_at, progress from jobs where id=%s",
        (jid,),
    ).fetchone()
    assert state == "succeeded"
    assert started is not None and finished is not None
    assert progress == {"processed": 1}

    sr = db_conn.execute(
        "select outcome, job_id from job_items where entity_type='recipe' "
        "and entity_id=101 and stage='demo'"
    ).fetchone()
    assert sr == ("resolved", jid)


def test_heartbeat_updates_during_run(test_db_url, db_conn):
    db_conn.execute("truncate table jobs restart identity cascade")
    db_conn.execute("truncate table job_items restart identity cascade")
    jid = _seed_job(
        db_conn, stage="hb",
        payload={"entity_ids": [201], "entity_type": "recipe", "version": "vt"},
    )

    observed = {}

    def hb_fn(job, conn, providers):
        # Watch last_heartbeat from an independent connection until the
        # background heartbeat thread advances it past the claim baseline.
        probe = psycopg.connect(test_db_url, autocommit=True)
        try:
            baseline = probe.execute(
                "select last_heartbeat from jobs where id=%s", (job["id"],)
            ).fetchone()[0]
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                cur = probe.execute(
                    "select last_heartbeat from jobs where id=%s", (job["id"],)
                ).fetchone()[0]
                if baseline is not None and cur is not None and cur > baseline:
                    observed["advanced"] = True
                    break
                time.sleep(0.02)
        finally:
            probe.close()
        record_run(
            conn, entity_type="recipe", entity_id=201, stage=job["stage"],
            version="vt", outcome="resolved", method="deterministic",
            job_id=job["id"],
        )

    conn = psycopg.connect(test_db_url)
    try:
        tick(
            conn,
            stage_fns={"hb": hb_fn},
            conn_factory=lambda: psycopg.connect(test_db_url, autocommit=True),
            heartbeat_interval=0.05,
        )
    finally:
        conn.close()

    assert observed.get("advanced") is True, "heartbeat must advance mid-run"


def test_empty_queue_no_op(test_db_url, db_conn):
    db_conn.execute("truncate table jobs restart identity cascade")
    db_conn.execute("truncate table job_items restart identity cascade")

    conn = psycopg.connect(test_db_url)
    try:
        ran = tick(conn, stage_fns={})
    finally:
        conn.close()

    assert ran is False, "no claimable job -> tick is a no-op"
    assert db_conn.execute("select count(*) from job_items").fetchone()[0] == 0


def test_reaper_on_boot(test_db_url, db_conn):
    db_conn.execute("truncate table jobs restart identity cascade")
    jid = _seed_job(
        db_conn, stage="parse", state="running", worker_id="dead-worker",
    )
    db_conn.execute(
        "update jobs set last_heartbeat = now() - interval '10 minutes' where id=%s",
        (jid,),
    )

    conn = psycopg.connect(test_db_url)
    try:
        n = boot(conn, reaper_older_than_seconds=1)
    finally:
        conn.close()

    assert n == 1, "boot must run the reaper once and requeue the stale job"
    assert db_conn.execute(
        "select state, worker_id from jobs where id=%s", (jid,)
    ).fetchone() == ("queued", None)


def test_boot_runs_reconcile_hook_before_reaper(test_db_url, db_conn):
    # The B24 batch reconciler hooks in here; B23 only guarantees the seam is
    # invoked on boot (before the claim loop). No batch logic yet.
    db_conn.execute("truncate table jobs restart identity cascade")
    calls = []

    conn = psycopg.connect(test_db_url)
    try:
        boot(conn, reaper_older_than_seconds=1, reconcile_hook=lambda c: calls.append(c))
    finally:
        conn.close()

    assert len(calls) == 1, "boot must invoke the reconcile seam exactly once"

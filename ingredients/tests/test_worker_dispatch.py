"""stage_fn dispatch (registry + failure + idempotency).

``dispatch.run`` maps ``job.stage`` to a registered ``stage_fn(job, conn,
providers)``. An unknown stage is a typed ``UnknownStage`` at the dispatch seam,
which the loop converts to a ``failed`` job with an ``error_code`` — never a
crash. Re-running the same job is idempotent: each stage writes a latest-only
``stage_run`` UPSERT, so a rerun keeps one row per (entity, stage) and cost is
not double-counted.

Pure dispatch tests need no DB; the failure/idempotency tests drive one loop
tick against TEST_DB_URL with a fake stage_fn (never a live model).
"""
from __future__ import annotations

import pytest
from common.db import jdump as Json

from ingredients.pipeline.ledger import record_run
from ingredients.worker.dispatch import STAGE_FNS, UnknownStage, register, run
from ingredients.worker.runner import run_next as tick


# --------------------------------------------------------------------------
# Pure — the dispatch registry + lookup
# --------------------------------------------------------------------------

def test_run_dispatches_to_registered_fn():
    seen = {}

    def fn(job, conn, providers):
        seen["job"] = job
        seen["providers"] = providers
        return {"ok": True}

    out = run({"stage": "x"}, conn="CONN", providers="PROV", stage_fns={"x": fn})
    assert seen["job"]["stage"] == "x"
    assert seen["providers"] == "PROV"
    assert out == {"ok": True}


def test_unknown_stage_raises():
    with pytest.raises(UnknownStage):
        run({"stage": "nope"}, conn=None, providers=None, stage_fns={})


def test_register_adds_to_global_registry():
    def fn(job, conn, providers):
        return None

    try:
        register("regtest_stage", fn)
        assert STAGE_FNS.get("regtest_stage") is fn
    finally:
        STAGE_FNS.pop("regtest_stage", None)


# --------------------------------------------------------------------------
# DB — unknown stage -> failed, and idempotent rerun
# --------------------------------------------------------------------------

def test_stage_fn_lookup_unknown_marks_failed(conn_factory, db_conn):
    db_conn.execute("delete from jobs")
    db_conn.execute("delete from job_items")
    jid = db_conn.execute(
        "insert into jobs (stage, state) values ('does_not_exist', 'queued') "
        "returning id"
    ).fetchone()[0]

    ran = tick(conn_factory(), stage_fns={})  # empty registry -> unknown stage

    assert ran is True, "the job was claimed and handled (not skipped)"
    state, error_code = db_conn.execute(
        "select state, error_code from jobs where id = ?", (jid,)
    ).fetchone()
    assert state == "failed"
    assert error_code == "unknown_stage"
    assert db_conn.execute("select count(*) from job_items").fetchone()[0] == 0


def test_idempotent_rerun(conn_factory, db_conn):
    db_conn.execute("delete from jobs")
    db_conn.execute("delete from job_items")
    payload = {"entity_ids": [301], "entity_type": "recipe", "version": "vt"}
    jid = db_conn.execute(
        "insert into jobs (stage, payload, state) values "
        "('demo', ?, 'queued') returning id",
        (Json(payload),),
    ).fetchone()[0]
    # The run's member row pre-exists (as add_run_items would have created it);
    # the stage_fn UPDATEs it in place, so a re-run cannot duplicate it.
    db_conn.execute(
        "insert into job_items (entity_type, entity_id, stage, code_version, "
        "outcome, method, state, job_id) "
        "values ('recipe', 301, 'demo', '', 'pending', 'deterministic', 'pending', ?)",
        (jid,),
    )

    def fn(job, conn, providers):
        for eid in job["payload"]["entity_ids"]:
            record_run(
                conn, entity_type="recipe", entity_id=eid, stage=job["stage"],
                version="vt", outcome="resolved", method="deterministic",
                cost_cents=3, job_id=job["id"],
            )
        return {"processed": 1}

    conn = conn_factory()
    if True:
        tick(conn, stage_fns={"demo": fn})
        # Requeue the SAME job and run it again.
        db_conn.execute(
            "update jobs set state='queued', worker_id=null, started_at=null, "
            "finished_at=null where id=?",
            (jid,),
        )
        tick(conn, stage_fns={"demo": fn})

    n_rows = db_conn.execute(
        "select count(*) from job_items where entity_type='recipe' "
        "and entity_id=301 and stage='demo'"
    ).fetchone()[0]
    assert n_rows == 1, "the member row is UPDATEd in place, not duplicated"

    cost_actual = db_conn.execute(
        "select cost_actual_cents from jobs where id=?", (jid,)
    ).fetchone()[0]
    assert cost_actual == 3, "cost_actual reflects the single run, not doubled"

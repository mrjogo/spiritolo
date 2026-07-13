"""WS-B23 — hard cost cap + free-stage exemption.

A metered stage accumulates per-item spend against ``jobs.max_cost_cents``. Once
the next item would breach the cap the worker hard-aborts (``CostCapExceeded``):
the breaching item is left unprocessed (no ``stage_run``, no double count), the
job is marked ``failed`` with a ``cost_cap_exceeded`` error_code, and
``cost_actual_cents`` equals the sum of the ``stage_runs.cost_cents`` actually
written. A free / deterministic chain never consults the cap at all.

Fake providers only; the abort test drives one loop tick against TEST_DB_URL.
"""
from __future__ import annotations

import psycopg
from psycopg.types.json import Json

from common.providers import DeterministicProvider, FakeProvider, Item
from common.providers.config import StageChainConfig

from ingredients.pipeline.ledger import record_run
from ingredients.worker.cost import CostMeter
from ingredients.worker.loop import tick
from ingredients.worker.providers import ProviderChain


def test_free_stage_no_cap_check():
    # A deterministic chain under a ZERO budget still resolves everything — free
    # work never inspects the cap.
    det = DeterministicProvider(
        resolve_fn=lambda items: {it.id: f"ok:{it.id}" for it in items}
    )
    meter = CostMeter(cap_cents=0)
    chain = ProviderChain(
        config=StageChainConfig(stage="map", provider_ids=("det",), pack_size=1),
        providers={"det": det},
        meter=meter,
    )

    r = chain.resolve([Item("1"), Item("2"), Item("3")])

    assert r.resolved == {"1": "ok:1", "2": "ok:2", "3": "ok:3"}
    assert r.cost_cents == 0
    assert meter.spent_cents == 0
    assert meter.consultations == 0, "a free chain must never consult the cap"


def test_aborts_past_max_cost(test_db_url, db_conn):
    db_conn.execute("truncate table jobs restart identity cascade")
    db_conn.execute("truncate table stage_runs restart identity cascade")

    # Metered fake: 2c per call, pack_size 1 -> 2c per item. Budget is 5c, so
    # item #3 (which would reach 6c) must abort.
    provider_impls = {
        "llm": FakeProvider(
            canned_map={"401": "A", "402": "B", "403": "C", "404": "D"},
            cost_per_call=2,
        )
    }
    configs = {"metered": StageChainConfig("metered", ("llm",), 1)}
    payload = {
        "entity_ids": [401, 402, 403, 404],
        "entity_type": "recipe",
        "version": "vt",
    }
    jid = db_conn.execute(
        "insert into jobs (stage, payload, state, max_cost_cents) values "
        "('metered', %s, 'queued', 5) returning id",
        (Json(payload),),
    ).fetchone()[0]

    def metered_fn(job, conn, providers):
        for eid in job["payload"]["entity_ids"]:
            res = providers.resolve([Item(str(eid))])  # may raise CostCapExceeded
            record_run(
                conn, entity_type="recipe", entity_id=eid, stage=job["stage"],
                version="vt", outcome="resolved", method="llm",
                cost_cents=res.cost_cents, model_id="fake-model",
                job_id=job["id"],
            )
            conn.commit()  # persist each paid-for item so an abort keeps it
        return {"processed": len(job["payload"]["entity_ids"])}

    conn = psycopg.connect(test_db_url)
    try:
        ran = tick(
            conn, stage_fns={"metered": metered_fn},
            configs=configs, provider_impls=provider_impls,
        )
    finally:
        conn.close()

    assert ran is True
    rows = db_conn.execute(
        "select entity_id, cost_cents from stage_runs where stage='metered' "
        "order by entity_id"
    ).fetchall()
    assert [r[0] for r in rows] == [401, 402], "items 3 and 4 left unprocessed"
    assert sum(int(r[1]) for r in rows) == 4

    state, error_code, cost_actual = db_conn.execute(
        "select state, error_code, cost_actual_cents from jobs where id=%s", (jid,)
    ).fetchone()
    assert state == "failed"
    assert error_code == "cost_cap_exceeded"
    assert cost_actual == 4, "no double count on the aborted item"

    assert db_conn.execute(
        "select count(*) from stage_runs where entity_id=403"
    ).fetchone()[0] == 0, "the aborted item never got a stage_run"

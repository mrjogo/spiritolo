"""Hard cost cap + free-stage exemption.

A metered stage accumulates per-item spend against ``jobs.max_cost_cents``. Once
the next item would breach the cap the worker hard-aborts (``CostCapExceeded``):
the breaching item is left unprocessed (no ``stage_run``, no double count), the
job is marked ``failed`` with a ``cost_cap_exceeded`` error_code, and
``cost_actual_cents`` equals the sum of the ``job_items.cost_cents`` actually
written. A free / deterministic chain never consults the cap at all.

Fake providers only; the abort test drives one loop tick against TEST_DB_URL.
"""
from __future__ import annotations

import psycopg
from psycopg.types.json import Json

from dataclasses import dataclass
from typing import Any
from collections.abc import Callable

from common.providers import FakeProvider, Item

from ingredients.pipeline.ledger import record_run
from ingredients.worker.cost import CostMeter
from ingredients.worker.loop import tick
from ingredients.worker.providers import ProviderChain


@dataclass
class _Deterministic:
    """A pure resolver as a chain tier (exposes ``resolve_items``)."""

    resolve_fn: Callable[[list[Item]], dict[str, Any]]

    def resolve_items(self, items: list[Item]) -> dict[str, Any]:
        return self.resolve_fn(items)


def test_free_stage_no_cap_check():
    # A deterministic chain under a ZERO budget still resolves everything — free
    # work never inspects the cap.
    det = _Deterministic(
        resolve_fn=lambda items: {it.id: f"ok:{it.id}" for it in items}
    )
    meter = CostMeter(cap_cents=0)
    chain = ProviderChain(tiers=[("det", det)], pack_size=1, meter=meter)

    r = chain.resolve([Item("1"), Item("2"), Item("3")])

    assert r.resolved == {"1": "ok:1", "2": "ok:2", "3": "ok:3"}
    assert r.cost_cents == 0
    assert meter.spent_cents == 0
    assert meter.consultations == 0, "a free chain must never consult the cap"


def test_aborts_past_max_cost(test_db_url, db_conn):
    db_conn.execute("truncate table jobs restart identity cascade")
    db_conn.execute("truncate table job_items restart identity cascade")

    # Metered fake: 2c per call, pack_size 1 -> 2c per item. Budget is 5c, so
    # item #3 (which would reach 6c) must abort.
    fake = FakeProvider(
        canned_map={"401": "A", "402": "B", "403": "C", "404": "D"},
        cost_per_call=2,
    )
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
    # The four members pre-exist (as add_run_items would create them); the
    # metered stage UPDATEs each as it pays for it, and the abort leaves the
    # unreached members pending.
    for eid in (401, 402, 403, 404):
        db_conn.execute(
            "insert into job_items (entity_type, entity_id, stage, code_version, "
            "outcome, method, state, job_id) "
            "values ('recipe', %s, 'metered', '', 'pending', 'deterministic', 'pending', %s)",
            (eid, jid),
        )

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

    def build_metered_chain(job):
        # Stand in for _build_providers: a single metered LLM tier at pack_size 1,
        # bound to the job's own cost cap.
        return ProviderChain(
            tiers=[("llm", fake)],
            pack_size=1,
            meter=CostMeter(job.get("max_cost_cents")),
        )

    conn = psycopg.connect(test_db_url)
    try:
        ran = tick(
            conn, stage_fns={"metered": metered_fn},
            providers_builder=build_metered_chain,
        )
    finally:
        conn.close()

    assert ran is True
    # Only the paid-for members were UPDATEd to a terminal state; the abort left
    # 403/404 as pending members (they never reached record_run).
    processed = db_conn.execute(
        "select entity_id, cost_cents from job_items "
        "where stage='metered' and state <> 'pending' order by entity_id"
    ).fetchall()
    assert [r[0] for r in processed] == [401, 402], "items 3 and 4 left unprocessed"
    assert sum(int(r[1]) for r in processed) == 4

    state, error_code, cost_actual = db_conn.execute(
        "select state, error_code, cost_actual_cents from jobs where id=%s", (jid,)
    ).fetchone()
    assert state == "failed"
    assert error_code == "cost_cap_exceeded"
    assert cost_actual == 4, "no double count on the aborted item"

    assert db_conn.execute(
        "select state from job_items where entity_id=403"
    ).fetchone()[0] == "pending", "the aborted item was never processed"

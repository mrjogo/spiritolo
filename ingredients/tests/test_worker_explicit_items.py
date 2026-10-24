"""The worker processes a run's explicit `job_items`.

When a job carries an id (a real run), a stage_fn resolves its work queue from
that job's *pending* members — not the version NOT-EXISTS predicate — and moves
each member to a terminal state (application is always immediate):
  resolved -> applied
  failed   -> failed
  parked (pending/abstain/proposes_new) -> flagged
Non-member entities are never touched. The CLI cold-build path (job id None)
still uses the predicate queue + the append-versioned ledger upsert.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from ingredients import runs
from ingredients.pipeline.stages import base
from ingredients.pipeline.stages.map import MAPPER_VERSION, map_stage_fn


class _FakeChain:
    def __init__(self, mapping=None):
        self.mapping = mapping or {}

    def resolve(self, items, **_kw):
        return SimpleNamespace(
            resolved={it.id: self.mapping[it.id] for it in items if it.id in self.mapping}
        )


@pytest.fixture()
def conn(db_conn):
    if (c := db_conn) is not None:
        for t in ("recipes", "job_items", "jobs", "ingredient_resolutions", "taxonomy_nodes"):
            c.execute(f"delete from {t}")
        nid = c.execute(
            "insert into taxonomy_nodes (slug, display_name, default_role) "
            "values ('bourbon', 'Bourbon', 'base_spirit') returning id"
        ).fetchone()[0]
        c.execute("insert into taxonomy_aliases (node_id, alias) values (?, 'bourbon')", (nid,))
        yield c


def _recipe(conn, names):
    rid = conn.execute(
        "insert into recipes (source_url, site, source) "
        "values (?, 'ex', '{}') returning id",
        (f"https://x/{uuid.uuid4()}",),
    ).fetchone()[0]
    for pos, name in enumerate(names):
        conn.execute(
            "insert into recipe_ingredients (recipe_id, position, name, raw_text) "
            "values (?, ?, ?, ?)",
            (rid, pos, name, f"{name} raw"),
        )
    return rid


def _job(conn, jid):
    return runs.get_run(conn, jid)


def _start(conn, jid, recipe_ids):
    runs.add_run_items(conn, jid, "recipe", list(recipe_ids))
    runs.start_run(conn, jid, None)


def _states(conn, jid):
    return dict(
        conn.execute(
            "select entity_id, state from job_items where job_id = ?", (jid,)
        ).fetchall()
    )


# ---------------------------------------------------------------------------
def test_run_item_ids_returns_pending_members(conn):
    r1, r2 = _recipe(conn, ["bourbon"]), _recipe(conn, ["bourbon"])
    jid = runs.create_run(conn, "map-ingredient")
    _start(conn, jid, [r1, r2])
    assert sorted(base.run_item_ids(conn, job_id=jid, stage="map-ingredient")) == sorted([r1, r2])


def test_auto_run_applies_only_its_members(conn):
    r1, r2, r3 = (_recipe(conn, ["bourbon"]) for _ in range(3))
    jid = runs.create_run(conn, "map-ingredient")
    _start(conn, jid, [r1, r2])  # r3 not a member
    map_stage_fn(_job(conn, jid), conn, _FakeChain())
    assert _states(conn, jid) == {r1: "applied", r2: "applied"}
    # r3 was never processed — no job_item exists for it at all.
    assert conn.execute(
        "select count(*) from job_items where entity_id = ?", (r3,)
    ).fetchone()[0] == 0


def test_unresolved_member_is_flagged(conn):
    # An un-slugifiable name can't mint a node, so it abstains -> the recipe stays
    # pending -> the member is flagged. (A slugifiable miss would instead mint a
    # provisional node and resolve.)
    r1 = _recipe(conn, ["!!!"])  # no alias, no LLM, no valid slug -> parked
    jid = runs.create_run(conn, "map-ingredient")
    _start(conn, jid, [r1])
    map_stage_fn(_job(conn, jid), conn, None)  # providers None -> LLM tier skipped
    assert _states(conn, jid) == {r1: "flagged"}


def test_member_row_updated_not_duplicated(conn):
    r1 = _recipe(conn, ["bourbon"])
    jid = runs.create_run(conn, "map-ingredient")
    _start(conn, jid, [r1])
    map_stage_fn(_job(conn, jid), conn, _FakeChain())
    # Exactly one job_item for the member (the pending row was updated in place),
    # stamped at the stage's code version and keeping its why_added.
    rows = conn.execute(
        "select code_version, state, outcome_payload from job_items where job_id = ?", (jid,)
    ).fetchall()
    assert len(rows) == 1
    assert rows[0][0] == MAPPER_VERSION
    assert rows[0][1] == "applied"
    assert rows[0][2]["why_added"] == "never_run"


def test_item_state_mapping():
    assert base.item_state("resolved") == "applied"
    assert base.item_state("failed") == "failed"
    assert base.item_state("pending") == "flagged"
    assert base.item_state("abstain") == "flagged"
    assert base.item_state("proposes_new") == "flagged"

"""combine-nodes stage_fn: merge duplicate taxonomy nodes.

Runs against TEST_DB_URL. The LLM tier is a fake chain (a stub with
``resolve(items, system_prompt) -> .resolved {id: answer}``), mirroring the map
stage's tests. The merge write goes through the real ``combine_merge`` SQL
function, so these exercise the resolution/edge repoint + node delete end to end.
"""

from __future__ import annotations

from types import SimpleNamespace

import psycopg
import pytest

from ingredients.pipeline.stages.combine import (
    COMBINE_VERSION,
    combine_stage_fn,
)


class _FakeChain:
    """ProviderChain stand-in: resolve(items, system_prompt=...) -> a result with
    ``.resolved`` plus the per-item telemetry maps a real ChainResult carries.

    ``mapping`` is keyed by the item id (str(node_id)); records whether resolve
    was called so a test can assert the LLM tier was skipped entirely. Optional
    ``tokens`` / ``cost`` / ``model`` maps (id -> value) let a test pin the
    telemetry a resolved node's job_item should persist."""

    def __init__(
        self,
        mapping: dict[str, dict],
        *,
        tokens: dict[str, tuple[int | None, int | None]] | None = None,
        cost: dict[str, int] | None = None,
        model: dict[str, str] | None = None,
    ):
        self.mapping = mapping
        self.tokens = tokens or {}
        self.cost = cost or {}
        self.model = model or {}
        self.called = False

    def resolve(self, items, **_kw):
        self.called = True
        ids = [it.id for it in items if it.id in self.mapping]
        return SimpleNamespace(
            resolved={i: self.mapping[i] for i in ids},
            per_item_tokens={i: self.tokens.get(i, (None, None)) for i in ids},
            per_item_cost={i: self.cost[i] for i in ids if i in self.cost},
            per_item_model={i: self.model[i] for i in ids if i in self.model},
        )


@pytest.fixture()
def conn(test_db_url: str):
    with psycopg.connect(test_db_url, autocommit=True) as c:
        for t in ("job_items", "human_reviews", "ingredient_resolutions",
                  "taxonomy_aliases", "taxonomy_edges", "taxonomy_provenance",
                  "taxonomy_nodes"):
            c.execute(f"truncate {t} restart identity cascade")
        yield c
        for t in ("job_items", "human_reviews", "ingredient_resolutions",
                  "taxonomy_aliases", "taxonomy_edges", "taxonomy_provenance",
                  "taxonomy_nodes"):
            c.execute(f"truncate {t} restart identity cascade")


def _node(conn, slug, display_name, status):
    return conn.execute(
        "insert into taxonomy_nodes (slug, display_name, status) "
        "values (%s, %s, %s) returning id",
        (slug, display_name, status),
    ).fetchone()[0]


def _resolution(conn, name, slug):
    conn.execute(
        "insert into ingredient_resolutions (normalized_name, taxonomy_slug, method, version) "
        "values (%s, %s, 'provisional', %s)",
        (name, slug, COMBINE_VERSION),
    )


def _job():
    return {"id": None, "payload": {}}


def _job_item(conn, node_id):
    row = conn.execute(
        "select outcome, state from job_items "
        "where entity_type = 'taxonomy_node' and entity_id = %s and stage = 'combine-nodes'",
        (node_id,),
    ).fetchone()
    return row  # (outcome, state) or None


def test_merge_absorbs_provisional_into_live(conn):
    live = _node(conn, "lime-juice", "Lime Juice", "live")
    prov = _node(conn, "juice-of-1-lime", "juice of 1 lime", "provisional")
    # A shared resolution points at the provisional slug; the merge must repoint it.
    _resolution(conn, "juice of 1 lime", "juice-of-1-lime")

    chain = _FakeChain({str(prov): {"action": "merge", "survivor_slug": "lime-juice"}})
    counts = combine_stage_fn(_job(), conn, chain)

    assert counts["merged"] == 1
    # Absorbed provisional node is gone; the live survivor remains.
    assert conn.execute(
        "select count(*) from taxonomy_nodes where slug = 'juice-of-1-lime'"
    ).fetchone()[0] == 0
    assert conn.execute(
        "select count(*) from taxonomy_nodes where id = %s", (live,)
    ).fetchone()[0] == 1
    # Resolution repointed from absorbed slug to survivor slug.
    assert conn.execute(
        "select taxonomy_slug from ingredient_resolutions where normalized_name = 'juice of 1 lime'"
    ).fetchone()[0] == "lime-juice"
    # The absorbed node's job_item is terminal-applied.
    assert _job_item(conn, prov) == ("resolved", "applied")


def test_distinct_keeps_node(conn):
    # 'lime' shares the token 'lime' with the live 'Lime Juice', so it surfaces as
    # a candidate — but they are NOT the same substance; the LLM says distinct.
    _node(conn, "lime-juice", "Lime Juice", "live")
    prov = _node(conn, "lime", "lime", "provisional")

    chain = _FakeChain({str(prov): {"action": "distinct"}})
    counts = combine_stage_fn(_job(), conn, chain)

    assert counts == {"merged": 0, "distinct": 1, "pending": 0}
    # Node kept.
    assert conn.execute(
        "select count(*) from taxonomy_nodes where id = %s", (prov,)
    ).fetchone()[0] == 1
    assert _job_item(conn, prov) == ("resolved", "applied")
    # No review opened.
    assert conn.execute("select count(*) from human_reviews").fetchone()[0] == 0


def test_no_llm_opens_review(conn):
    # Candidate exists but no LLM is available -> the node parks for a curator.
    _node(conn, "lime-juice", "Lime Juice", "live")
    prov = _node(conn, "fresh-lime-juice", "fresh lime juice", "provisional")

    counts = combine_stage_fn(_job(), conn, None)

    assert counts == {"merged": 0, "distinct": 0, "pending": 1}
    # Parked: flagged terminal state, pending outcome, node untouched.
    assert _job_item(conn, prov) == ("pending", "flagged")
    assert conn.execute(
        "select count(*) from taxonomy_nodes where id = %s", (prov,)
    ).fetchone()[0] == 1
    # A combine-nodes machine_proposal review is open, keyed by the node id.
    review = conn.execute(
        "select origin, state, payload from human_reviews "
        "where stage = 'combine-nodes' and entity_kind = 'taxonomy_node' and entity_id = %s",
        (str(prov),),
    ).fetchone()
    assert review is not None
    origin, state, payload = review
    assert (origin, state) == ("machine_proposal", "open")
    assert payload["candidates"][0]["slug"] == "lime-juice"


def _run_member(conn, node_id, job_id):
    conn.execute(
        "insert into job_items (job_id, entity_type, entity_id, stage, code_version, "
        "outcome, method, state) "
        "values (%s, 'taxonomy_node', %s, 'combine-nodes', '', 'pending', 'deterministic', 'pending')",
        (job_id, node_id),
    )


def test_resolved_node_persists_tokens_cost_model_and_rolls_up(conn):
    # Two provisional nodes the LLM judges 'distinct', run as members of a job.
    # Each carries its own tokens/cost/model onto its job_item, and the job-level
    # SUM (what finalize rolls up) equals the total across the two.
    _node(conn, "lime-juice", "Lime Juice", "live")
    a = _node(conn, "lime", "lime", "provisional")
    b = _node(conn, "limes", "limes", "provisional")

    job_id = conn.execute(
        "insert into jobs (stage, state) values ('combine-nodes', 'running') returning id"
    ).fetchone()[0]
    _run_member(conn, a, job_id)
    _run_member(conn, b, job_id)

    chain = _FakeChain(
        {str(a): {"action": "distinct"}, str(b): {"action": "distinct"}},
        tokens={str(a): (80, 20), str(b): (40, 10)},
        cost={str(a): 2, str(b): 1},
        model={str(a): "claude-haiku-4-5", str(b): "claude-haiku-4-5"},
    )
    counts = combine_stage_fn({"id": job_id, "payload": {}}, conn, chain)
    assert counts["distinct"] == 2

    rows = dict(
        (r[0], r[1:])
        for r in conn.execute(
            "select entity_id, prompt_tokens, completion_tokens, cost_cents, model_id "
            "from job_items where job_id = %s and stage = 'combine-nodes'",
            (job_id,),
        ).fetchall()
    )
    assert rows[a] == (80, 20, 2, "claude-haiku-4-5")
    assert rows[b] == (40, 10, 1, "claude-haiku-4-5")

    rollup = conn.execute(
        "select sum(prompt_tokens), sum(completion_tokens), sum(cost_cents) "
        "from job_items where job_id = %s",
        (job_id,),
    ).fetchone()
    assert rollup == (120, 30, 3)


def test_no_candidates_resolved_without_llm_call(conn):
    # The only node in the taxonomy shares no lexical signal with anything, so it
    # has no candidates: trivially distinct, recorded deterministically, no LLM.
    prov = _node(conn, "xyzzy-cordial", "xyzzy cordial", "provisional")

    chain = _FakeChain({})  # should never be called
    counts = combine_stage_fn(_job(), conn, chain)

    assert counts == {"merged": 0, "distinct": 1, "pending": 0}
    assert chain.called is False
    assert _job_item(conn, prov) == ("resolved", "applied")
    assert conn.execute("select count(*) from human_reviews").fetchone()[0] == 0
    method = conn.execute(
        "select method from job_items where entity_id = %s and stage = 'combine-nodes'",
        (prov,),
    ).fetchone()[0]
    assert method == "deterministic"

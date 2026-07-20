"""connect-nodes stage_fn: place a provisional taxonomy node in the DAG + promote.

Runs against TEST_DB_URL; the LLM tier is a fake chain returning a preset
``{node_id: answer}`` map (the exact JSON contract the real provider decodes).
"""

from __future__ import annotations

from types import SimpleNamespace

import psycopg
import pytest

from ingredients.pipeline.stages.connect import CONNECT_VERSION, connect_stage_fn


class _FakeChain:
    """Stands in for a ProviderChain: resolve(items) -> .resolved {id: answer}."""

    def __init__(self, mapping: dict[str, object]):
        self.mapping = mapping

    def resolve(self, items, **_kw):
        return SimpleNamespace(
            resolved={it.id: self.mapping[it.id] for it in items if it.id in self.mapping}
        )


@pytest.fixture()
def conn(test_db_url: str):
    tables = (
        "job_items",
        "human_reviews",
        "taxonomy_edges",
        "taxonomy_aliases",
        "taxonomy_nodes",
    )
    with psycopg.connect(test_db_url, autocommit=True) as c:
        for t in tables:
            c.execute(f"truncate {t} restart identity cascade")
        yield c
        for t in tables:
            c.execute(f"truncate {t} restart identity cascade")


def _job():
    return {"id": None, "payload": {}}


def _node(conn, slug, name, *, status, is_cluster_node=False, node_kind=None):
    return conn.execute(
        "insert into taxonomy_nodes (slug, display_name, status, node_kind, is_cluster_node) "
        "values (%s, %s, %s, %s, %s) returning id",
        (slug, name, status, node_kind, is_cluster_node),
    ).fetchone()[0]


def _edge(conn, parent_id, child_id):
    conn.execute(
        "insert into taxonomy_edges (parent_id, child_id) values (%s, %s)",
        (parent_id, child_id),
    )


def _job_item(conn, node_id):
    return conn.execute(
        "select outcome, state from job_items "
        "where entity_id = %s and stage = 'connect-nodes'",
        (node_id,),
    ).fetchone()


def _open_review(conn, node_id):
    return conn.execute(
        "select payload from human_reviews "
        "where entity_kind = 'taxonomy_node' and entity_id = %s "
        "and stage = 'connect-nodes' and state = 'open'",
        (str(node_id),),
    ).fetchone()


def test_places_node_under_parent_and_promotes(conn):
    parent = _node(conn, "citrus", "Citrus", status="live")
    # A live "lime" so the deterministic candidate generator has something to find.
    _node(conn, "lime", "Lime", status="live")
    node = _node(conn, "lime-juice", "lime juice", status="provisional")

    chain = _FakeChain(
        {str(node): {"node_kind": None, "parent_slugs": ["citrus"], "is_cluster_node": False}}
    )
    counts = connect_stage_fn(_job(), conn, chain)

    assert counts == {"connected": 1, "pending": 0}
    # Edge created under the chosen parent.
    assert conn.execute(
        "select 1 from taxonomy_edges where parent_id = %s and child_id = %s",
        (parent, node),
    ).fetchone()
    # node_kind + is_cluster_node set; promoted to live.
    assert conn.execute(
        "select node_kind, status, is_cluster_node from taxonomy_nodes where id = %s",
        (node,),
    ).fetchone() == (None, "live", False)
    # Outcome resolved -> applied; no review opened.
    assert _job_item(conn, node) == ("resolved", "applied")
    assert _open_review(conn, node) is None


def test_unknown_parent_slug_parks_for_review(conn):
    node = _node(conn, "mystery-cordial", "mystery cordial", status="provisional")
    chain = _FakeChain(
        {str(node): {"node_kind": None, "parent_slugs": ["does-not-exist"], "is_cluster_node": False}}
    )
    counts = connect_stage_fn(_job(), conn, chain)

    assert counts == {"connected": 0, "pending": 1}
    # connect_place raised -> node untouched, still provisional, no edge.
    assert conn.execute(
        "select status from taxonomy_nodes where id = %s", (node,)
    ).fetchone()[0] == "provisional"
    assert conn.execute(
        "select count(*) from taxonomy_edges where child_id = %s", (node,)
    ).fetchone()[0] == 0
    # A connect-nodes review is opened carrying the proposed placement.
    review = _open_review(conn, node)
    assert review is not None
    assert review[0]["proposed"]["parent_slugs"] == ["does-not-exist"]
    assert _job_item(conn, node) == ("pending", "flagged")


def test_no_providers_parks_for_review(conn):
    node = _node(conn, "orphan-syrup", "orphan syrup", status="provisional")
    counts = connect_stage_fn(_job(), conn, None)

    assert counts == {"connected": 0, "pending": 1}
    assert conn.execute(
        "select status from taxonomy_nodes where id = %s", (node,)
    ).fetchone()[0] == "provisional"
    assert _open_review(conn, node) is not None
    assert _job_item(conn, node) == ("pending", "flagged")


def test_uncertain_answer_parks_for_review(conn):
    node = _node(conn, "puzzle-liqueur", "puzzle liqueur", status="provisional")
    chain = _FakeChain({str(node): {"action": "uncertain"}})
    counts = connect_stage_fn(_job(), conn, chain)

    assert counts == {"connected": 0, "pending": 1}
    assert conn.execute(
        "select status from taxonomy_nodes where id = %s", (node,)
    ).fetchone()[0] == "provisional"
    assert _open_review(conn, node) is not None
    assert _job_item(conn, node) == ("pending", "flagged")


def test_antichain_violation_parks_for_review(conn):
    # A cluster-node ancestor: placing a cluster node beneath it violates the
    # antichain invariant, so connect_place RAISES and the node parks.
    ancestor = _node(conn, "spirits", "Spirits", status="live", is_cluster_node=True)
    mid = _node(conn, "brandy-family", "brandy family", status="live")
    _edge(conn, ancestor, mid)
    node = _node(conn, "fancy-brandy", "fancy brandy", status="provisional")

    chain = _FakeChain(
        {str(node): {"node_kind": None, "parent_slugs": ["brandy-family"], "is_cluster_node": True}}
    )
    counts = connect_stage_fn(_job(), conn, chain)

    assert counts == {"connected": 0, "pending": 1}
    # Savepoint rolled back: no edge persisted, node still provisional.
    assert conn.execute(
        "select count(*) from taxonomy_edges where child_id = %s", (node,)
    ).fetchone()[0] == 0
    assert conn.execute(
        "select status from taxonomy_nodes where id = %s", (node,)
    ).fetchone()[0] == "provisional"
    assert _open_review(conn, node) is not None
    assert _job_item(conn, node) == ("pending", "flagged")


def test_candidate_parents_surface_in_uncertain_review(conn):
    # The deterministic generator finds a live node sharing a token with the
    # provisional node's name and surfaces it to the (uncertain) review.
    _node(conn, "lime", "Lime", status="live")
    node = _node(conn, "lime-cordial", "lime cordial", status="provisional")
    chain = _FakeChain({str(node): {"action": "uncertain"}})

    connect_stage_fn(_job(), conn, chain)

    review = _open_review(conn, node)
    assert review is not None
    slugs = {c["slug"] for c in review[0]["candidate_parents"]}
    assert "lime" in slugs

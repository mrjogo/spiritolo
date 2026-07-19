"""map stage LLM tier: propose_brand auto-create + propose_form review queue.

The deterministic tiers resolve a name to a taxonomy slug. The LLM tier answers
with a richer action: choose a slug, propose a brand/expression (auto-created
when its parent already exists), propose a new form node (queued for human
review), or abstain. These tests pin the DB writes each action makes, plus the
review path that turns an approved form proposal into a resolution.

Runs against TEST_DB_URL; the LLM tier is a fake chain emitting action objects.
"""

from __future__ import annotations

from types import SimpleNamespace

import psycopg
import pytest

from ingredients.mapping.eval_fixture import seed
from ingredients.mapping.proposals import (
    approve_form_proposal,
    fetch_pending_form_proposals,
)
from ingredients.pipeline.stages.map import map_stage_fn
from ingredients.reviews.model import insert_review


class _FakeChain:
    """Stands in for a ProviderChain: resolve(items) -> .resolved {id: answer}.

    Each answer is the map stage's LLM-tier action object (or a bare slug).
    """

    def __init__(self, mapping: dict):
        self.mapping = mapping

    def resolve(self, items, **_kw):
        return SimpleNamespace(
            resolved={it.id: self.mapping[it.id] for it in items if it.id in self.mapping}
        )


@pytest.fixture()
def conn(test_db_url: str):
    with psycopg.connect(test_db_url, autocommit=True) as c:
        _truncate(c)
        ids = seed(c)  # citrus/lemon/gin/london-dry-gin/tanqueray/bourbon
        yield c, ids
        _truncate(c)


def _truncate(c: psycopg.Connection) -> None:
    for t in (
        "recipes",
        "human_reviews",
        "job_items",
        "ingredient_resolutions",
        "taxonomy_provenance",
        "taxonomy_aliases",
        "taxonomy_edges",
        "taxonomy_nodes",
    ):
        c.execute(f"truncate {t} restart identity cascade")


def _recipe(c, url, ingredient_names):
    rid = c.execute(
        "insert into recipes (source_url, site, source) values (%s, 'ex', '{}'::jsonb) returning id",
        (url,),
    ).fetchone()[0]
    for pos, name in enumerate(ingredient_names):
        c.execute(
            "insert into recipe_ingredients (recipe_id, position, name, raw_text) "
            "values (%s, %s, %s, %s)",
            (rid, pos, name, f"{name} raw"),
        )
    return rid


def _job():
    return {"id": None, "payload": {}}


def test_propose_brand_auto_creates_node_edge_provenance_resolution(conn):
    c, ids = conn
    _recipe(c, "https://ex.test/b", ["Nolet Silver"])
    chain = _FakeChain(
        {
            "nolet silver": {
                "action": "propose_brand",
                "slug": "nolet-silver",
                "display_name": "Nolet Silver",
                "parent_slug": "london-dry-gin",
                "node_kind": "expression",
            }
        }
    )
    counts = map_stage_fn(_job(), c, chain)
    assert counts["resolved"] == 1

    node = c.execute(
        "select id, node_kind, is_cluster_node from taxonomy_nodes where slug = 'nolet-silver'"
    ).fetchone()
    assert node is not None
    new_id, node_kind, is_cluster = node
    assert node_kind == "expression"
    assert is_cluster is False

    edge = c.execute(
        "select 1 from taxonomy_edges where parent_id = %s and child_id = %s",
        (ids["london-dry-gin"], new_id),
    ).fetchone()
    assert edge is not None

    prov = c.execute(
        "select source from taxonomy_provenance where node_id = %s", (new_id,)
    ).fetchone()
    assert prov == ("llm-mapper",)

    res = c.execute(
        "select taxonomy_slug, method from ingredient_resolutions "
        "where normalized_name = 'nolet silver'"
    ).fetchone()
    assert res == ("nolet-silver", "llm")


def test_propose_brand_with_missing_parent_abstains(conn):
    c, _ = conn
    _recipe(c, "https://ex.test/np", ["Ghost Amaro"])
    chain = _FakeChain(
        {
            "ghost amaro": {
                "action": "propose_brand",
                "slug": "ghost-amaro",
                "display_name": "Ghost Amaro",
                "parent_slug": "no-such-parent",
                "node_kind": "brand",
            }
        }
    )
    counts = map_stage_fn(_job(), c, chain)
    assert counts["pending"] == 1
    assert (
        c.execute("select 1 from taxonomy_nodes where slug = 'ghost-amaro'").fetchone()
        is None
    )
    res = c.execute(
        "select taxonomy_slug, method from ingredient_resolutions "
        "where normalized_name = 'ghost amaro'"
    ).fetchone()
    assert res == (None, "abstain")


def test_propose_form_queues_proposal_and_parks(conn):
    c, ids = conn
    rid = _recipe(c, "https://ex.test/f", ["Lemon Zest"])
    chain = _FakeChain(
        {
            "lemon zest": {
                "action": "propose_form",
                "slug": "lemon-zest",
                "display_name": "Lemon Zest",
                "parent_slug": "lemon",
            }
        }
    )
    counts = map_stage_fn(_job(), c, chain)
    assert counts["pending"] == 1

    prop = c.execute(
        "select entity_id, stage, origin, state, "
        "payload->>'proposed_slug', (payload->>'proposed_parent_id')::bigint "
        "from human_reviews where entity_id = 'lemon zest' and stage = 'map'"
    ).fetchone()
    assert prop == ("lemon zest", "map", "machine_proposal", "open",
                    "lemon-zest", ids["lemon"])

    # Parked: no taxonomy node yet, no non-null resolution for the name.
    assert (
        c.execute("select 1 from taxonomy_nodes where slug = 'lemon-zest'").fetchone()
        is None
    )
    slug = c.execute(
        "select taxonomy_slug from ingredient_resolutions where normalized_name = 'lemon zest'"
    ).fetchone()
    assert slug is None or slug[0] is None

    outcome = c.execute(
        "select outcome from job_items where entity_id = %s and stage = 'map'", (rid,)
    ).fetchone()[0]
    assert outcome == "pending"


def test_review_proposals_path_resolves(conn):
    c, ids = conn
    insert_review(
        c,
        entity_kind="ingredient_name",
        entity_id="lemon zest",
        stage="map",
        origin="machine_proposal",
        payload={
            "kind": "form",
            "proposed_slug": "lemon-zest",
            "proposed_display_name": "Lemon Zest",
            "proposed_parent_id": ids["lemon"],
            "candidates": [],
        },
        origin_version="v1",
    )
    [proposal] = fetch_pending_form_proposals(c)
    assert proposal["raw_string"] == "lemon zest"

    new_id = approve_form_proposal(c, proposal=proposal, decided_by="alice", version="v1")

    node = c.execute(
        "select slug from taxonomy_nodes where id = %s", (new_id,)
    ).fetchone()
    assert node == ("lemon-zest",)
    edge = c.execute(
        "select 1 from taxonomy_edges where parent_id = %s and child_id = %s",
        (ids["lemon"], new_id),
    ).fetchone()
    assert edge is not None
    alias = c.execute(
        "select 1 from taxonomy_aliases where alias = 'lemon zest' and node_id = %s",
        (new_id,),
    ).fetchone()
    assert alias is not None

    res = c.execute(
        "select taxonomy_slug from ingredient_resolutions where normalized_name = 'lemon zest'"
    ).fetchone()
    assert res == ("lemon-zest",)

    state = c.execute(
        "select state from human_reviews where id = %s", (proposal["id"],)
    ).fetchone()[0]
    assert state == "resolved"

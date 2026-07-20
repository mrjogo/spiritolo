"""map stage LLM tier: attach-to-existing-node or abstain (then mint).

The deterministic tiers resolve a name to a taxonomy slug. The LLM tier may only
attach a name to an *existing* node (``chose_slug``) or abstain — it no longer
proposes or auto-creates taxonomy structure. Any name the LLM abstains on falls
through to the deterministic mint pass, which mints a provisional node. These
tests pin the DB writes for both LLM outcomes.

Runs against TEST_DB_URL; the LLM tier is a fake chain emitting action objects.
"""

from __future__ import annotations

from types import SimpleNamespace

import psycopg
import pytest

from ingredients.mapping.eval_fixture import seed
from ingredients.pipeline.stages.map import map_stage_fn


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


def test_chose_slug_resolves_to_existing_node(conn):
    c, _ = conn
    _recipe(c, "https://ex.test/c", ["Dry Gin"])
    chain = _FakeChain({"dry gin": {"action": "chose_slug", "slug": "gin"}})
    counts = map_stage_fn(_job(), c, chain)
    assert counts["resolved"] == 1

    res = c.execute(
        "select taxonomy_slug, method from ingredient_resolutions "
        "where normalized_name = 'dry gin'"
    ).fetchone()
    assert res == ("gin", "llm")
    # No new node was created — it attached to the existing 'gin' node.
    assert (
        c.execute(
            "select count(*) from taxonomy_nodes where status = 'provisional'"
        ).fetchone()[0]
        == 0
    )


def test_bare_slug_answer_resolves(conn):
    c, _ = conn
    _recipe(c, "https://ex.test/b", ["Fancy Bourbon"])
    chain = _FakeChain({"fancy bourbon": "bourbon"})
    counts = map_stage_fn(_job(), c, chain)
    assert counts["resolved"] == 1
    res = c.execute(
        "select taxonomy_slug, method from ingredient_resolutions "
        "where normalized_name = 'fancy bourbon'"
    ).fetchone()
    assert res == ("bourbon", "llm")


def test_llm_abstain_falls_through_to_mint(conn):
    c, _ = conn
    _recipe(c, "https://ex.test/a", ["Nolet Silver"])
    chain = _FakeChain({"nolet silver": {"action": "abstain"}})
    counts = map_stage_fn(_job(), c, chain)
    # An LLM abstain no longer parks the name: it mints a provisional node.
    assert counts["resolved"] == 1

    node = c.execute(
        "select node_kind, status, is_cluster_node from taxonomy_nodes "
        "where slug = 'nolet-silver'"
    ).fetchone()
    assert node == (None, "provisional", False)

    res = c.execute(
        "select taxonomy_slug, method from ingredient_resolutions "
        "where normalized_name = 'nolet silver'"
    ).fetchone()
    assert res == ("nolet-silver", "provisional")


def test_llm_unknown_action_falls_through_to_mint(conn):
    c, _ = conn
    _recipe(c, "https://ex.test/x", ["Weird Thing"])
    # A malformed / removed action object is treated as abstain -> mint.
    chain = _FakeChain({"weird thing": {"action": "propose_brand", "slug": "x"}})
    counts = map_stage_fn(_job(), c, chain)
    assert counts["resolved"] == 1
    res = c.execute(
        "select taxonomy_slug, method from ingredient_resolutions "
        "where normalized_name = 'weird thing'"
    ).fetchone()
    assert res == ("weird-thing", "provisional")

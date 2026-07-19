"""map stage_fn: shared, name-keyed ingredient_resolutions.

The headline behaviour: a name resolves ONCE and every recipe that uses it
follows. Runs against TEST_DB_URL; the LLM tier is a fake chain.
"""

from __future__ import annotations

from types import SimpleNamespace

import psycopg
import pytest

from ingredients.pipeline.stages.map import MAPPER_VERSION, map_stage_fn


class _FakeChain:
    """Stands in for a ProviderChain: resolve(items) -> .resolved {id: slug}."""

    def __init__(self, mapping: dict[str, str]):
        self.mapping = mapping

    def resolve(self, items, **_kw):
        return SimpleNamespace(
            resolved={it.id: self.mapping[it.id] for it in items if it.id in self.mapping}
        )


@pytest.fixture()
def conn(test_db_url: str):
    with psycopg.connect(test_db_url, autocommit=True) as c:
        for t in ("recipes", "job_items", "ingredient_resolutions", "taxonomy_nodes"):
            c.execute(f"truncate {t} restart identity cascade")
        nid = c.execute(
            "insert into taxonomy_nodes (slug, display_name, default_role) "
            "values ('bourbon', 'Bourbon', 'base_spirit') returning id"
        ).fetchone()[0]
        c.execute("insert into taxonomy_aliases (node_id, alias) values (%s, 'bourbon')", (nid,))
        yield c
        for t in ("recipes", "job_items", "ingredient_resolutions", "taxonomy_nodes"):
            c.execute(f"truncate {t} restart identity cascade")


def _recipe(conn, url, ingredient_names):
    rid = conn.execute(
        "insert into recipes (source_url, site, source) values (%s, 'ex', '{}'::jsonb) returning id",
        (url,),
    ).fetchone()[0]
    for pos, name in enumerate(ingredient_names):
        conn.execute(
            "insert into recipe_ingredients (recipe_id, position, name, raw_text) "
            "values (%s, %s, %s, %s)",
            (rid, pos, name, f"{name} raw"),
        )
    return rid


def _job():
    return {"id": None, "payload": {}}


def test_resolution_is_shared_across_recipes(conn):
    a = _recipe(conn, "https://ex.test/a", ["Bourbon"])
    b = _recipe(conn, "https://ex.test/b", ["Bourbon"])
    counts = map_stage_fn(_job(), conn, None)
    assert counts["resolved"] == 2

    # Exactly ONE shared resolution row for the name, keyed normalized.
    rows = conn.execute(
        "select normalized_name, taxonomy_slug, method from ingredient_resolutions"
    ).fetchall()
    assert rows == [("bourbon", "bourbon", "alias")]

    for rid in (a, b):
        outcome = conn.execute(
            "select outcome from job_items where entity_id=%s and stage='map-ingredient'", (rid,)
        ).fetchone()[0]
        assert outcome == "resolved"


def test_unresolved_name_records_pending(conn):
    rid = _recipe(conn, "https://ex.test/u", ["Unobtanium"])
    counts = map_stage_fn(_job(), conn, None)
    assert counts["pending"] == 1
    row = conn.execute(
        "select taxonomy_slug, method from ingredient_resolutions where normalized_name='unobtanium'"
    ).fetchone()
    assert row == (None, "abstain")
    outcome = conn.execute(
        "select outcome from job_items where entity_id=%s and stage='map-ingredient'", (rid,)
    ).fetchone()[0]
    assert outcome == "pending"


def test_llm_tier_resolves_misses(conn):
    rid = _recipe(conn, "https://ex.test/l", ["Fancy Amaro"])
    chain = _FakeChain({"fancy amaro": "amaro"})
    counts = map_stage_fn(_job(), conn, chain)
    assert counts["resolved"] == 1
    row = conn.execute(
        "select taxonomy_slug, method from ingredient_resolutions where normalized_name='fancy amaro'"
    ).fetchone()
    assert row == ("amaro", "llm")


def test_map_is_idempotent_via_ledger(conn):
    _recipe(conn, "https://ex.test/i", ["Bourbon"])
    assert map_stage_fn(_job(), conn, None)["resolved"] == 1
    assert map_stage_fn(_job(), conn, None) == {"resolved": 0, "pending": 0}


def test_chunk_boundary_matches_single_chunk(conn):
    # Several recipes spanning multiple chunk_size=2 chunks; mix of resolvable
    # (bourbon alias) and unresolvable names, plus a shared name across recipes.
    specs = [
        ("https://ex.test/c0", ["Bourbon"]),
        ("https://ex.test/c1", ["Unobtanium"]),
        ("https://ex.test/c2", ["Bourbon", "Unobtanium"]),
        ("https://ex.test/c3", ["Bourbon"]),
        ("https://ex.test/c4", ["Unobtanium"]),
    ]
    rids = [_recipe(conn, url, names) for url, names in specs]

    counts = map_stage_fn(_job(), conn, None, chunk_size=2)

    # c0 + c3 resolve (bourbon); c1, c2, c4 pending (unobtanium unresolved).
    assert counts == {"resolved": 2, "pending": 3}

    outcomes = {
        rid: conn.execute(
            "select outcome from job_items where entity_id=%s and stage='map-ingredient'", (rid,)
        ).fetchone()[0]
        for rid in rids
    }
    assert outcomes == {
        rids[0]: "resolved",
        rids[1]: "pending",
        rids[2]: "pending",
        rids[3]: "resolved",
        rids[4]: "pending",
    }

    # Shared, name-keyed: exactly one row per distinct name regardless of chunking.
    rows = conn.execute(
        "select normalized_name, taxonomy_slug, method from ingredient_resolutions "
        "order by normalized_name"
    ).fetchall()
    assert rows == [
        ("bourbon", "bourbon", "alias"),
        ("unobtanium", None, "abstain"),
    ]

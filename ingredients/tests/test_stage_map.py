"""map stage_fn: shared, name-keyed ingredient_resolutions.

The headline behaviour: a name resolves ONCE and every recipe that uses it
follows. Runs against TEST_DB_URL; the LLM tier is a fake chain.
"""

from __future__ import annotations

from types import SimpleNamespace

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
def conn(db_conn):
    if (c := db_conn) is not None:
        for t in ("recipes", "job_items", "ingredient_resolutions", "taxonomy_nodes"):
            c.execute(f"delete from {t}")
        nid = c.execute(
            "insert into taxonomy_nodes (slug, display_name, default_role) "
            "values ('bourbon', 'Bourbon', 'base_spirit') returning id"
        ).fetchone()[0]
        c.execute("insert into taxonomy_aliases (node_id, alias) values (?, 'bourbon')", (nid,))
        yield c
        for t in ("recipes", "job_items", "ingredient_resolutions", "taxonomy_nodes"):
            c.execute(f"delete from {t}")


def _recipe(conn, url, ingredient_names):
    rid = conn.execute(
        "insert into recipes (source_url, site, source) values (?, 'ex', '{}') returning id",
        (url,),
    ).fetchone()[0]
    for pos, name in enumerate(ingredient_names):
        conn.execute(
            "insert into recipe_ingredients (recipe_id, position, name, raw_text) "
            "values (?, ?, ?, ?)",
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
            "select outcome from job_items where entity_id=? and stage='map-ingredient'", (rid,)
        ).fetchone()[0]
        assert outcome == "resolved"


def test_unresolved_name_mints_provisional_node(conn):
    # No live match and no providers (CLI cold-build): the name is mechanically
    # minted as a provisional node and resolved to it.
    rid = _recipe(conn, "https://ex.test/u", ["Unobtanium"])
    counts = map_stage_fn(_job(), conn, None)
    assert counts["resolved"] == 1
    row = conn.execute(
        "select taxonomy_slug, method from ingredient_resolutions where normalized_name='unobtanium'"
    ).fetchone()
    assert row == ("unobtanium", "provisional")
    node = conn.execute(
        "select node_kind, status, is_cluster_node from taxonomy_nodes where slug='unobtanium'"
    ).fetchone()
    assert node == (None, "provisional", False)
    outcome = conn.execute(
        "select outcome from job_items where entity_id=? and stage='map-ingredient'", (rid,)
    ).fetchone()[0]
    assert outcome == "resolved"


def _amaro(conn):
    """A live 'amaro' node under a 'liqueur' parent, so 'fancy amaro' has a
    candidate the lexical tier won't accept on its own."""
    parent = conn.execute(
        "insert into taxonomy_nodes (slug, display_name) values ('liqueur', 'Liqueur') "
        "returning id"
    ).fetchone()[0]
    child = conn.execute(
        "insert into taxonomy_nodes (slug, display_name) values ('amaro', 'Amaro') "
        "returning id"
    ).fetchone()[0]
    conn.execute(
        "insert into taxonomy_edges (parent_id, child_id) values (?, ?)", (parent, child)
    )


def test_llm_tier_resolves_misses(conn):
    _amaro(conn)
    rid = _recipe(conn, "https://ex.test/l", ["Fancy Amaro"])
    chain = _FakeChain({"fancy amaro": "amaro"})
    counts = map_stage_fn(_job(), conn, chain)
    assert counts["resolved"] == 1
    row = conn.execute(
        "select taxonomy_slug, method from ingredient_resolutions where normalized_name='fancy amaro'"
    ).fetchone()
    assert row == ("amaro", "llm")
    method = conn.execute(
        "select method from job_items where entity_id=? and stage='map-ingredient'", (rid,)
    ).fetchone()[0]
    assert method == "llm"


class _RecordingChain(_FakeChain):
    def __init__(self, mapping):
        super().__init__(mapping)
        self.calls: list[dict] = []

    def resolve(self, items, **kw):
        self.calls.append({"items": list(items), **kw})
        return super().resolve(items, **kw)


def test_llm_items_carry_candidates_and_the_mapping_prompt(conn):
    from ingredients.mapping.prompt import MAP_ANSWER_SCHEMA, SYSTEM_PROMPT

    _amaro(conn)
    rid = _recipe(conn, "https://ex.test/p", ["Fancy Amaro"])
    conn.execute("update recipe_ingredients set unit = 'oz' where recipe_id = ?", (rid,))
    chain = _RecordingChain({})
    map_stage_fn(_job(), conn, chain)

    (call,) = chain.calls
    assert call["system_prompt"] == SYSTEM_PROMPT
    assert call["answer_schema"] == MAP_ANSWER_SCHEMA
    (item,) = call["items"]
    assert item.id == "fancy amaro"
    assert item.payload["name"] == "fancy amaro"
    assert item.payload["parser_unit"] == "oz"
    assert item.payload["site"] == "ex"
    amaro = next(c for c in item.payload["candidates"] if c["slug"] == "amaro")
    assert amaro["parents"] == ["Liqueur"]
    assert amaro["display_name"] == "Amaro"


def test_llm_skips_names_with_no_live_candidate(conn):
    chain = _RecordingChain({})
    _recipe(conn, "https://ex.test/z", ["Xyzzyq"])
    map_stage_fn(_job(), conn, chain)
    assert chain.calls == []  # nothing to choose from -> no paid call, straight to mint


def test_chose_slug_outside_candidates_is_abstain(conn):
    _amaro(conn)
    _recipe(conn, "https://ex.test/o", ["Fancy Amaro"])
    chain = _FakeChain({"fancy amaro": {"action": "chose_slug", "slug": "bourbon"}})
    map_stage_fn(_job(), conn, chain)
    row = conn.execute(
        "select taxonomy_slug, method from ingredient_resolutions where normalized_name='fancy amaro'"
    ).fetchone()
    assert row == ("fancy-amaro", "provisional")  # abstained, then minted


def test_map_is_idempotent_via_ledger(conn):
    _recipe(conn, "https://ex.test/i", ["Bourbon"])
    assert map_stage_fn(_job(), conn, None)["resolved"] == 1
    assert map_stage_fn(_job(), conn, None) == {"resolved": 0, "pending": 0}


def test_chunk_boundary_matches_single_chunk(conn):
    # Several recipes spanning multiple chunk_size=2 chunks; mix of alias-resolved
    # (bourbon) and mint-resolved (unobtanium) names, plus a shared name across
    # recipes and across a chunk boundary.
    specs = [
        ("https://ex.test/c0", ["Bourbon"]),
        ("https://ex.test/c1", ["Unobtanium"]),
        ("https://ex.test/c2", ["Bourbon", "Unobtanium"]),
        ("https://ex.test/c3", ["Bourbon"]),
        ("https://ex.test/c4", ["Unobtanium"]),
    ]
    rids = [_recipe(conn, url, names) for url, names in specs]

    counts = map_stage_fn(_job(), conn, None, chunk_size=2)

    # Every name resolves now: bourbon by alias, unobtanium by mint.
    assert counts == {"resolved": 5, "pending": 0}

    outcomes = {
        rid: conn.execute(
            "select outcome from job_items where entity_id=? and stage='map-ingredient'", (rid,)
        ).fetchone()[0]
        for rid in rids
    }
    assert all(o == "resolved" for o in outcomes.values())

    # Shared, name-keyed: exactly one row per distinct name regardless of chunking;
    # 'unobtanium' minted once even though it spans two chunks (c1 then c2/c4).
    rows = conn.execute(
        "select normalized_name, taxonomy_slug, method from ingredient_resolutions "
        "order by normalized_name"
    ).fetchall()
    assert rows == [
        ("bourbon", "bourbon", "alias"),
        ("unobtanium", "unobtanium", "provisional"),
    ]
    # Exactly one provisional node for the shared unobtanium name.
    assert (
        conn.execute(
            "select count(*) from taxonomy_nodes where slug='unobtanium'"
        ).fetchone()[0]
        == 1
    )

"""convert stage_fn: verb-frame steps + equipment, or a routed non-result."""

from __future__ import annotations

import psycopg
import pytest

from ingredients.pipeline.stages.convert import convert_stage_fn
from ingredients.recipegf.version import CONVERTER_VERSION


@pytest.fixture()
def conn(test_db_url: str):
    with psycopg.connect(test_db_url, autocommit=True) as c:
        for t in ("recipes", "stage_runs", "ingredient_resolutions",
                  "taxonomy_nodes", "cocktail_aliases"):
            c.execute(f"truncate {t} restart identity cascade")
        for slug, role in [("bourbon", "base_spirit"), ("simple-syrup", "sweetener"),
                           ("angostura-bitters", "bitters")]:
            c.execute(
                "insert into taxonomy_nodes (slug, display_name, default_role) values (%s,%s,%s)",
                (slug, slug, role),
            )
        for name, slug in [("bourbon", "bourbon"), ("simple syrup", "simple-syrup"),
                           ("angostura bitters", "angostura-bitters")]:
            c.execute(
                "insert into ingredient_resolutions (normalized_name, taxonomy_slug, method, version) "
                "values (%s,%s,'alias','v1')",
                (name, slug),
            )
        yield c
        for t in ("recipes", "stage_runs", "ingredient_resolutions",
                  "taxonomy_nodes", "cocktail_aliases"):
            c.execute(f"truncate {t} restart identity cascade")


def _old_fashioned(conn, resolve_all=True, url="https://ex.test/of"):
    rid = conn.execute(
        """
        insert into recipes (source_url, site, source, title, canonical_name)
        values (%s, 'ex',
                '{"recipeInstructions":"Stir with ice and strain into a rocks glass."}'::jsonb,
                'Old Fashioned', 'old fashioned')
        returning id
        """,
        (url,),
    ).fetchone()[0]
    ings = [("Bourbon", 2.0, "oz"), ("Simple Syrup", 0.25, "oz"),
            ("Angostura Bitters", 2.0, "dash")]
    for pos, (name, amt, unit) in enumerate(ings):
        conn.execute(
            "insert into recipe_ingredients (recipe_id, position, name, amount, unit, raw_text) "
            "values (%s,%s,%s,%s,%s,%s)",
            (rid, pos, name, amt, unit, f"{name} raw"),
        )
    if not resolve_all:
        conn.execute("delete from ingredient_resolutions where taxonomy_slug='bourbon'")
    return rid


def _job():
    return {"id": None, "payload": {}}


def test_convert_writes_steps_and_equipment(conn):
    rid = _old_fashioned(conn)
    counts = convert_stage_fn(_job(), conn, None)
    assert counts["converted"] == 1

    steps = conn.execute(
        "select verb from recipe_steps where recipe_id=%s order by step_index", (rid,)
    ).fetchall()
    assert [s[0] for s in steps] == ["add", "stir", "strain"]
    equipment = conn.execute("select equipment, recipe_slug from recipes where id=%s", (rid,)).fetchone()
    assert "mixing_glass" in equipment[0]
    assert equipment[1] == "old-fashioned"

    run = conn.execute(
        "select outcome, version from stage_runs where entity_id=%s and stage='convert'", (rid,)
    ).fetchone()
    assert run == ("resolved", CONVERTER_VERSION)


def test_convert_batches_across_chunk_boundary(conn):
    # Three resolvable recipes. With chunk_size=2 the queue spans two chunks
    # ([r1, r2], [r3]); the batched result must match a single chunk's.
    # (ingredient_resolutions is shared/name-keyed, so all three resolve.)
    rids = [_old_fashioned(conn, url=f"https://ex.test/of/{i}") for i in range(3)]

    counts = convert_stage_fn(_job(), conn, None, chunk_size=2)
    assert counts == {"converted": 3, "pending": 0, "proposes_new": 0}

    for rid in rids:
        verbs = conn.execute(
            "select verb from recipe_steps where recipe_id=%s order by step_index", (rid,)
        ).fetchall()
        assert [v[0] for v in verbs] == ["add", "stir", "strain"]
        equip = conn.execute(
            "select equipment, recipe_slug from recipes where id=%s", (rid,)
        ).fetchone()
        assert "mixing_glass" in equip[0]
        assert equip[1] == "old-fashioned"
        assert conn.execute(
            "select outcome from stage_runs where entity_id=%s and stage='convert'", (rid,)
        ).fetchone()[0] == "resolved"


def test_convert_pending_when_ingredient_unresolved(conn):
    rid = _old_fashioned(conn, resolve_all=False)
    counts = convert_stage_fn(_job(), conn, None)
    assert counts["pending"] == 1
    assert conn.execute("select count(*) from recipe_steps where recipe_id=%s", (rid,)).fetchone()[0] == 0
    outcome = conn.execute(
        "select outcome from stage_runs where entity_id=%s and stage='convert'", (rid,)
    ).fetchone()[0]
    assert outcome == "pending"

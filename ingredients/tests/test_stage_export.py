"""export stage_fn: generate the bundle on demand and freeze it + ledger.

Runs against TEST_DB_URL. Deterministic, so `providers` is None.
"""

from __future__ import annotations

import json

import psycopg
import pytest
from recipegf import parse_recipe_id

from ingredients.pipeline.stages.export import export_stage_fn
from ingredients.recipegf.version import CONVERTER_VERSION


@pytest.fixture()
def conn(test_db_url: str):
    with psycopg.connect(test_db_url, autocommit=True) as c:
        c.execute("truncate recipes restart identity cascade")
        c.execute("truncate ingredient_resolutions restart identity cascade")
        c.execute("truncate job_items restart identity cascade")
        c.execute("truncate recipe_exports restart identity cascade")
        yield c
        c.execute("truncate recipes restart identity cascade")
        c.execute("truncate ingredient_resolutions restart identity cascade")
        c.execute("truncate job_items restart identity cascade")
        c.execute("truncate recipe_exports restart identity cascade")


def _resolve(conn, name, slug):
    conn.execute(
        "insert into ingredient_resolutions (normalized_name, taxonomy_slug, method, version) "
        "values (%s, %s, 'alias', 'v1') on conflict (normalized_name) do nothing",
        (name, slug),
    )


def _seed_ready_recipe(conn, suffix: str = "") -> int:
    rid = conn.execute(
        """
        insert into recipes (source_url, site, source, title, canonical_name,
                             equipment)
        values (%s, 'ex', '{}'::jsonb, 'Old Fashioned',
                'old fashioned', array['mixing_glass','bar_spoon','rocks_glass'])
        returning id
        """,
        (f"https://ex.test/of{suffix}",),
    ).fetchone()[0]
    ings = [
        (0, "Bourbon", 2.0, "oz", "bourbon"),
        (1, "Simple Syrup", 0.25, "oz", "simple-syrup"),
        (2, "Angostura Bitters", 2.0, "dash", "angostura-bitters"),
    ]
    for pos, name, amt, unit, slug in ings:
        conn.execute(
            "insert into recipe_ingredients (recipe_id, position, name, amount, unit, raw_text) "
            "values (%s,%s,%s,%s,%s,%s)",
            (rid, pos, name, amt, unit, f"{name} raw"),
        )
        _resolve(conn, name.lower(), slug)
    steps = [
        (0, "add", {"input": ["bourbon", "simple-syrup", "angostura-bitters"],
                    "to": "mixing_glass"}, "combined"),
        (1, "stir", {"input": "combined", "using": "bar_spoon"}, "stirred"),
        (2, "strain", {"input": "stirred", "to": "rocks_glass", "using": "bar_spoon"}, "poured"),
    ]
    for idx, verb, roles, result in steps:
        conn.execute(
            "insert into recipe_steps (recipe_id, step_index, verb, roles, result) "
            "values (%s,%s,%s,%s::jsonb,%s)",
            (rid, idx, verb, json.dumps(roles), result),
        )
    return rid


def _job():
    return {"id": None, "payload": {}}


def test_export_freezes_bundle_and_records_resolved(conn):
    rid = _seed_ready_recipe(conn)
    counts = export_stage_fn(_job(), conn, None)
    assert counts["exported"] == 1

    exp = conn.execute(
        "select recipe_slug, recipe_ref, converter_version, bundle from recipe_exports "
        "where recipe_id=%s",
        (rid,),
    ).fetchone()
    assert exp[0] == "old-fashioned"
    assert parse_recipe_id(exp[1]).slug == "old-fashioned"
    assert exp[2] == CONVERTER_VERSION
    assert exp[3]["meta"]["slug"] == "old-fashioned"

    # Slug pinned back onto the recipe.
    assert conn.execute("select recipe_slug from recipes where id=%s", (rid,)).fetchone()[0] == "old-fashioned"

    outcome = conn.execute(
        "select outcome from job_items where entity_id=%s and stage='export'", (rid,)
    ).fetchone()[0]
    assert outcome == "resolved"


def test_export_pending_when_ingredient_unresolved(conn):
    rid = _seed_ready_recipe(conn)
    # Drop one resolution so the bundle can't be minted yet.
    conn.execute("delete from ingredient_resolutions where taxonomy_slug='bourbon'")
    counts = export_stage_fn(_job(), conn, None)
    assert counts["pending"] == 1
    assert conn.execute("select count(*) from recipe_exports").fetchone()[0] == 0
    outcome = conn.execute(
        "select outcome from job_items where entity_id=%s and stage='export'", (rid,)
    ).fetchone()[0]
    assert outcome == "pending"


def test_export_is_idempotent_via_ledger(conn):
    _seed_ready_recipe(conn)
    assert export_stage_fn(_job(), conn, None)["exported"] == 1
    counts = export_stage_fn(_job(), conn, None)
    assert counts["exported"] == 0


def test_export_batches_across_chunk_boundary(conn):
    # Seed several ready recipes so a small chunk_size forces >1 chunk. Two share
    # the same canonical name (→ same slug) to exercise the slug UPDATE guard.
    rids = [_seed_ready_recipe(conn, suffix=str(i)) for i in range(5)]

    counts = export_stage_fn(_job(), conn, None, chunk_size=2)

    # Same counts a single chunk would produce.
    assert counts == {"exported": 5, "pending": 0, "failed": 0}

    # Every recipe frozen + slug pinned + ledger 'resolved'.
    assert conn.execute("select count(*) from recipe_exports").fetchone()[0] == 5
    for rid in rids:
        exp = conn.execute(
            "select recipe_slug, converter_version from recipe_exports where recipe_id=%s",
            (rid,),
        ).fetchone()
        assert exp[0] == "old-fashioned"
        assert exp[1] == CONVERTER_VERSION
        assert (
            conn.execute("select recipe_slug from recipes where id=%s", (rid,)).fetchone()[0]
            == "old-fashioned"
        )
        outcome = conn.execute(
            "select outcome from job_items where entity_id=%s and stage='export'", (rid,)
        ).fetchone()[0]
        assert outcome == "resolved"

"""parse stage_fn: source JSON-LD ingredients -> recipe_ingredients + ledger.

Runs against TEST_DB_URL. The stage is deterministic, so `providers` is None.
"""

from __future__ import annotations

import json

import psycopg
import pytest
from psycopg.types.json import Json

from ingredients.parser import PARSER_VERSION
from ingredients.pipeline.stages.parse import parse_stage_fn


@pytest.fixture()
def conn(test_db_url: str):
    with psycopg.connect(test_db_url, autocommit=True) as c:
        c.execute("truncate recipes restart identity cascade")
        c.execute("truncate job_items restart identity cascade")
        yield c
        c.execute("truncate recipes restart identity cascade")
        c.execute("truncate job_items restart identity cascade")


def _seed_recipe(conn, url, ingredients):
    return conn.execute(
        "insert into recipes (source_url, site, source) values (%s, 'punch', %s) returning id",
        (url, Json({"recipeIngredient": ingredients})),
    ).fetchone()[0]


def _job(site=None, limit=None):
    return {"id": None, "payload": {"site": site, "limit": limit}}


def test_parse_writes_recipe_ingredients(conn):
    rid = _seed_recipe(conn, "https://ex.test/a", ["2 oz gin", "0.5 oz lime juice"])
    counts = parse_stage_fn(_job(), conn, None)
    assert counts["parsed"] == 1

    rows = conn.execute(
        "select position, name, amount, unit from recipe_ingredients "
        "where recipe_id = %s order by position",
        (rid,),
    ).fetchall()
    assert rows[0] == (0, "gin", 2, "oz")
    assert rows[1][1] == "lime juice"

    run = conn.execute(
        "select stage, code_version, outcome, method from job_items "
        "where entity_type='recipe' and entity_id=%s and stage='parse-ingredients'",
        (rid,),
    ).fetchone()
    assert run == ("parse-ingredients", PARSER_VERSION, "resolved", "deterministic")


def test_parse_is_idempotent_via_ledger(conn):
    _seed_recipe(conn, "https://ex.test/b", ["2 oz rum"])
    assert parse_stage_fn(_job(), conn, None)["parsed"] == 1
    # Second run: the recipe already has a run at PARSER_VERSION, so the queue
    # is empty and nothing is reprocessed.
    counts = parse_stage_fn(_job(), conn, None)
    assert counts == {"parsed": 0, "empty": 0}


def test_parse_stores_unparseable_row_but_abstains(conn):
    rid = _seed_recipe(conn, "https://ex.test/c", ["???"])
    counts = parse_stage_fn(_job(), conn, None)
    assert counts["empty"] == 1
    # The raw text is preserved even though nothing structured out of it.
    row = conn.execute(
        "select name, raw_text from recipe_ingredients where recipe_id=%s", (rid,)
    ).fetchone()
    assert row[0] is None and row[1] == "???"
    outcome = conn.execute(
        "select outcome from job_items where entity_id=%s and stage='parse-ingredients'", (rid,)
    ).fetchone()[0]
    assert outcome == "abstain"


def test_parse_batches_across_chunk_boundary(conn):
    # Five recipes with chunk_size=2 → chunks of [2, 2, 1]. The batched writes
    # must produce the SAME counts and DB rows as a single-chunk run.
    specs = [
        ("https://ex.test/c1", ["2 oz gin", "0.5 oz lime juice"]),
        ("https://ex.test/c2", ["1 oz rum"]),
        ("https://ex.test/c3", ["???"]),
        ("https://ex.test/c4", ["1.5 oz vodka", "0.75 oz triple sec"]),
        ("https://ex.test/c5", ["3 dashes bitters"]),
    ]
    rids = [_seed_recipe(conn, url, ings) for url, ings in specs]

    counts = parse_stage_fn(_job(), conn, None, chunk_size=2)
    # c3 (???) abstains → empty; the other four structure at least one row.
    assert counts == {"parsed": 4, "empty": 1}

    # Every recipe got its ingredient rows and exactly one job_items row.
    for rid, (_, ings) in zip(rids, specs):
        n_rows = conn.execute(
            "select count(*) from recipe_ingredients where recipe_id=%s", (rid,)
        ).fetchone()[0]
        assert n_rows == len(ings)
    total_runs = conn.execute(
        "select count(*) from job_items where stage='parse-ingredients'"
    ).fetchone()[0]
    assert total_runs == len(rids)

    # Spot-check one structured row and one abstain outcome survived batching.
    row = conn.execute(
        "select name, amount, unit from recipe_ingredients "
        "where recipe_id=%s order by position",
        (rids[3],),
    ).fetchall()
    assert row[0] == ("vodka", 1.5, "oz")
    abstain = conn.execute(
        "select outcome from job_items where entity_id=%s and stage='parse-ingredients'",
        (rids[2],),
    ).fetchone()[0]
    assert abstain == "abstain"


def test_parse_scopes_by_site(conn):
    a = _seed_recipe(conn, "https://ex.test/d", ["1 oz gin"])
    conn.execute("update recipes set site='other' where id=%s", (a,))
    _seed_recipe(conn, "https://ex.test/e", ["1 oz vodka"])
    parse_stage_fn(_job(site="punch"), conn, None)
    # Only the punch recipe was parsed.
    n = conn.execute(
        "select count(*) from job_items where stage='parse-ingredients'"
    ).fetchone()[0]
    assert n == 1

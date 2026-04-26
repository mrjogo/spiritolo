import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

requires_supabase = pytest.mark.skipif(
    not os.environ.get("SUPABASE_DB_URL"),
    reason="SUPABASE_DB_URL not set; skipping integration test",
)

PARSER_VERSION_TEST = "v-test"


@pytest.fixture
def isolated_db():
    """Truncate recipes + recipe_ingredients, yield a Database, clean up after."""
    from ingredients.db import IngredientsDatabase
    db = IngredientsDatabase()
    db.conn.execute("truncate table recipe_ingredients cascade")
    db.conn.execute("truncate table recipes cascade")
    db.conn.commit()
    yield db
    db.conn.execute("truncate table recipe_ingredients cascade")
    db.conn.execute("truncate table recipes cascade")
    db.conn.commit()
    db.close()


def _seed_recipe(db, *, source_url, site, jsonld):
    import json
    db.conn.execute(
        """
        insert into recipes (source_url, site, name, jsonld, fetched_at)
        values (%s, %s, %s, %s::jsonb, '2026-04-25T00:00:00Z')
        returning id
        """,
        (source_url, site, "test", json.dumps(jsonld)),
    )
    db.conn.commit()
    return db.conn.execute(
        "select id from recipes where source_url = %s", (source_url,)
    ).fetchone()[0]


@requires_supabase
def test_work_queue_returns_recipes_lacking_current_version_parse(isolated_db):
    db = isolated_db
    rid = _seed_recipe(db, source_url="https://example.com/r1", site="punch",
                       jsonld={"recipeIngredient": ["2 oz gin", "1 oz lime"]})

    queue = db.fetch_work_queue(parser_version=PARSER_VERSION_TEST)
    assert len(queue) == 1
    assert queue[0]["id"] == rid
    assert queue[0]["site"] == "punch"
    assert queue[0]["recipe_ingredient"] == ["2 oz gin", "1 oz lime"]


@requires_supabase
def test_work_queue_skips_recipes_with_current_version_parse(isolated_db):
    db = isolated_db
    rid = _seed_recipe(db, source_url="https://example.com/r2", site="punch",
                       jsonld={"recipeIngredient": ["2 oz gin"]})
    db.write_recipe_parses(
        recipe_id=rid,
        rows=[{
            "position": 0, "raw_text": "2 oz gin",
            "amount": 2.0, "amount_max": None, "unit": "oz", "name": "gin",
            "modifier": None, "parse_status": "parsed", "parser_rule": "qty_unit",
        }],
        parser_version=PARSER_VERSION_TEST,
    )
    queue = db.fetch_work_queue(parser_version=PARSER_VERSION_TEST)
    assert queue == []


@requires_supabase
def test_work_queue_returns_recipe_with_old_version_parse(isolated_db):
    db = isolated_db
    rid = _seed_recipe(db, source_url="https://example.com/r3", site="punch",
                       jsonld={"recipeIngredient": ["2 oz gin"]})
    db.write_recipe_parses(
        recipe_id=rid,
        rows=[{
            "position": 0, "raw_text": "2 oz gin",
            "amount": 2.0, "amount_max": None, "unit": "oz", "name": "gin",
            "modifier": None, "parse_status": "parsed", "parser_rule": "qty_unit",
        }],
        parser_version="v0",
    )
    queue = db.fetch_work_queue(parser_version=PARSER_VERSION_TEST)
    assert len(queue) == 1
    assert queue[0]["id"] == rid


@requires_supabase
def test_write_replaces_existing_rows_for_recipe(isolated_db):
    db = isolated_db
    rid = _seed_recipe(db, source_url="https://example.com/r4", site="punch",
                       jsonld={"recipeIngredient": ["2 oz gin"]})
    db.write_recipe_parses(
        recipe_id=rid,
        rows=[{
            "position": 0, "raw_text": "old", "amount": 1.0, "amount_max": None,
            "unit": "oz", "name": "old", "modifier": None,
            "parse_status": "parsed", "parser_rule": "qty_unit",
        }],
        parser_version="v0",
    )
    db.write_recipe_parses(
        recipe_id=rid,
        rows=[{
            "position": 0, "raw_text": "new", "amount": 2.0, "amount_max": None,
            "unit": "oz", "name": "new", "modifier": None,
            "parse_status": "parsed", "parser_rule": "qty_unit",
        }],
        parser_version=PARSER_VERSION_TEST,
    )
    rows = db.conn.execute(
        "select raw_text, parser_version from recipe_ingredients where recipe_id = %s",
        (rid,),
    ).fetchall()
    assert rows == [("new", PARSER_VERSION_TEST)]


@requires_supabase
def test_count_eval_rows_filters(isolated_db):
    db = isolated_db
    rid = _seed_recipe(db, source_url="https://example.com/r5", site="punch",
                       jsonld={"recipeIngredient": ["2 oz gin"]})
    db.write_recipe_parses(
        recipe_id=rid,
        rows=[{
            "position": 0, "raw_text": "x", "amount": 1.0, "amount_max": None,
            "unit": "oz", "name": "x", "modifier": None,
            "parse_status": "parsed", "parser_rule": "qty_unit",
        }],
        parser_version="v0",
    )
    assert db.count_eval_rows(site=None, except_version=None, older_than=None) == 1
    assert db.count_eval_rows(site="punch", except_version=None, older_than=None) == 1
    assert db.count_eval_rows(site="liquor", except_version=None, older_than=None) == 0
    assert db.count_eval_rows(site=None, except_version="v0", older_than=None) == 0
    assert db.count_eval_rows(site=None, except_version="v1", older_than=None) == 1


@requires_supabase
def test_clear_eval_rows_returns_deleted_count(isolated_db):
    db = isolated_db
    rid = _seed_recipe(db, source_url="https://example.com/r6", site="punch",
                       jsonld={"recipeIngredient": ["2 oz gin"]})
    db.write_recipe_parses(
        recipe_id=rid,
        rows=[{
            "position": 0, "raw_text": "x", "amount": 1.0, "amount_max": None,
            "unit": "oz", "name": "x", "modifier": None,
            "parse_status": "parsed", "parser_rule": "qty_unit",
        }],
        parser_version="v0",
    )
    n = db.clear_eval_rows(site=None, except_version=None, older_than=None)
    assert n == 1

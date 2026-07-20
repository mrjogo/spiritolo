"""Unit tests for pipeline.stages.base helpers. Runs against TEST_DB_URL."""

from __future__ import annotations

import psycopg
import pytest

from ingredients.pipeline.stages import base


@pytest.fixture()
def conn(test_db_url: str):
    with psycopg.connect(test_db_url, autocommit=True) as c:
        for t in ("recipes", "recipe_ingredients", "ingredient_resolutions",
                  "taxonomy_nodes"):
            c.execute(f"truncate {t} restart identity cascade")
        yield c
        for t in ("recipes", "recipe_ingredients", "ingredient_resolutions",
                  "taxonomy_nodes"):
            c.execute(f"truncate {t} restart identity cascade")


def _recipe(conn, url, ingredients):
    rid = conn.execute(
        "insert into recipes (source_url, site, source, title) "
        "values (%s, 'ex', '{}'::jsonb, 't') returning id",
        (url,),
    ).fetchone()[0]
    for pos, name in enumerate(ingredients):
        conn.execute(
            "insert into recipe_ingredients (recipe_id, position, name, raw_text) "
            "values (%s, %s, %s, 'x')",
            (rid, pos, name),
        )
    return rid


def test_recipes_with_provisional_ingredients_returns_right_subset(conn):
    # gin -> live, elderflower -> provisional.
    for slug, status in [("gin", "live"), ("elderflower-liqueur", "provisional")]:
        conn.execute(
            "insert into taxonomy_nodes (slug, display_name, status) values (%s,%s,%s)",
            (slug, slug, status),
        )
    for name, slug in [("gin", "gin"), ("elderflower liqueur", "elderflower-liqueur")]:
        conn.execute(
            "insert into ingredient_resolutions (normalized_name, taxonomy_slug, method, version) "
            "values (%s,%s,'alias','v1')",
            (name, slug),
        )

    all_live = _recipe(conn, "https://ex.test/a", ["Gin"])
    has_provisional = _recipe(conn, "https://ex.test/b", ["Gin", "Elderflower Liqueur"])
    unresolved = _recipe(conn, "https://ex.test/c", ["Mystery Cordial"])

    got = base.recipes_with_provisional_ingredients(
        conn, [all_live, has_provisional, unresolved]
    )
    assert got == {has_provisional}


def test_recipes_with_provisional_ingredients_empty_input(conn):
    assert base.recipes_with_provisional_ingredients(conn, []) == set()

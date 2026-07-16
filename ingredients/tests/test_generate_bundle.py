"""generate_bundle assembles a valid pin-2 bundle from the relational rows.

Seeds one recipe (header + RecipeGF ingredient rows + shared resolutions +
verb-frame steps) and asserts the on-demand bundle: is structurally valid under
core ∪ spiritolo/, mints the reverse-DNS id + ingredient refs from the shared
resolution, embeds only the spiritolo/ verb-defs its steps use, and round-trips
byte-for-byte (deterministic) and through RecipeGF's own models. Runs against
TEST_DB_URL.
"""

from __future__ import annotations

import json

import psycopg
import pytest
from recipegf import RecipeDocument, parse_ingredient_ref, parse_recipe_id

from ingredients.recipegf.bundle import BundleError, validate_bundle
from ingredients.recipegf.generate import (
    UnresolvedIngredient,
    generate_bundle,
    generate_bundles,
)


@pytest.fixture()
def conn(test_db_url: str):
    with psycopg.connect(test_db_url, autocommit=True) as c:
        c.execute("truncate recipes restart identity cascade")
        c.execute("truncate ingredient_resolutions restart identity cascade")
        yield c
        c.execute("truncate recipes restart identity cascade")
        c.execute("truncate ingredient_resolutions restart identity cascade")


def _seed_resolution(conn, normalized_name, slug):
    conn.execute(
        "insert into ingredient_resolutions (normalized_name, taxonomy_slug, method, version) "
        "values (%s, %s, 'alias', 'v1') on conflict (normalized_name) do update "
        "set taxonomy_slug = excluded.taxonomy_slug",
        (normalized_name, slug),
    )


def _seed_stirred_old_fashioned(conn) -> int:
    recipe_id = conn.execute(
        """
        insert into recipes (source_url, site, source, title, canonical_name,
                             recipe_slug, equipment)
        values ('https://ex.test/of', 'ex', '{}'::jsonb, 'Old Fashioned',
                'old fashioned', 'old-fashioned',
                array['mixing_glass','bar_spoon','rocks_glass'])
        returning id
        """
    ).fetchone()[0]

    ings = [
        (0, "Bourbon", 2.0, None, "oz", "bourbon"),
        (1, "Simple Syrup", 0.25, None, "oz", "simple-syrup"),
        (2, "Angostura Bitters", 2.0, None, "dash", "angostura-bitters"),
    ]
    for pos, name, amount, amount_max, unit, slug in ings:
        conn.execute(
            "insert into recipe_ingredients (recipe_id, position, name, amount, "
            "amount_max, unit, raw_text) values (%s, %s, %s, %s, %s, %s, %s)",
            (recipe_id, pos, name, amount, amount_max, unit, f"{name} raw"),
        )
        _seed_resolution(conn, name.lower().strip(), slug)

    steps = [
        (0, "add", {"input": ["bourbon", "simple-syrup", "angostura-bitters"],
                    "to": "mixing_glass"}, "combined"),
        (1, "stir", {"input": "combined", "using": "bar_spoon"}, "stirred"),
        (2, "strain", {"input": "stirred", "to": "rocks_glass", "using": "bar_spoon"},
         "poured"),
    ]
    for idx, verb, roles, result in steps:
        conn.execute(
            "insert into recipe_steps (recipe_id, step_index, verb, roles, result) "
            "values (%s, %s, %s, %s::jsonb, %s)",
            (recipe_id, idx, verb, json.dumps(roles), result),
        )
    return recipe_id


def test_generate_bundle_is_valid_and_governed(conn):
    recipe_id = _seed_stirred_old_fashioned(conn)
    bundle = generate_bundle(conn, recipe_id, imported_at="2026-07-12T00:00:00+00:00")
    assert bundle is not None

    # Structurally valid under core ∪ spiritolo/ with only what it carries.
    assert validate_bundle(bundle).valid

    recipe = bundle["recipe"]
    parsed = parse_recipe_id(recipe["id"])
    assert parsed.authority == "com.spiritolo"
    assert parsed.slug == "old-fashioned"
    assert bundle["meta"]["slug"] == parsed.slug

    # Every ingredient carries its portable ref, resolved from the SHARED map.
    refs = [parse_ingredient_ref(i["ref"]) for i in recipe["ingredients"]]
    assert [r.slug for r in refs] == ["bourbon", "simple-syrup", "angostura-bitters"]
    assert all(r.authority == "com.spiritolo" for r in refs)

    # A stirred drink uses no spiritolo/ verbs, so the bundle embeds none.
    assert bundle["verbs"] == []


def test_generate_bundle_roundtrips(conn):
    recipe_id = _seed_stirred_old_fashioned(conn)
    a = generate_bundle(conn, recipe_id, imported_at="2026-07-12T00:00:00+00:00")
    b = generate_bundle(conn, recipe_id, imported_at="2026-07-12T00:00:00+00:00")
    # Deterministic: same rows + same imported_at -> byte-identical bundle.
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)

    # Round-trips through RecipeGF's own models without loss.
    doc = RecipeDocument.from_doc({"recipe": a["recipe"]})
    reserialized = doc.model_dump(by_alias=True, exclude_none=True)["recipe"]
    assert reserialized["schema"] == a["recipe"]["schema"]
    assert reserialized["id"] == a["recipe"]["id"]
    assert [i["ref"] for i in reserialized["ingredients"]] == [
        i["ref"] for i in a["recipe"]["ingredients"]
    ]


def test_generate_bundle_missing_recipe_returns_none(conn):
    assert generate_bundle(conn, 999999, imported_at="2026-07-12T00:00:00+00:00") is None


def test_generate_bundle_unresolved_ingredient_raises(conn):
    recipe_id = conn.execute(
        """
        insert into recipes (source_url, site, source, title, canonical_name,
                             recipe_slug, equipment)
        values ('https://ex.test/u', 'ex', '{}'::jsonb, 'Mystery', 'mystery',
                'mystery', array[]::text[])
        returning id
        """
    ).fetchone()[0]
    conn.execute(
        "insert into recipe_ingredients (recipe_id, position, name, amount, unit, "
        "raw_text) values (%s, 0, 'Unobtanium', 1, 'oz', '1 oz unobtanium')",
        (recipe_id,),
    )
    with pytest.raises(UnresolvedIngredient):
        generate_bundle(conn, recipe_id, imported_at="2026-07-12T00:00:00+00:00")


def test_generate_bundles_matches_per_recipe(conn):
    # A chunk spanning every outcome: a valid bundle, an unresolved ingredient,
    # a slug-less recipe (BundleError), and a vanished id.
    ok_id = _seed_stirred_old_fashioned(conn)
    unresolved_id = conn.execute(
        "insert into recipes (source_url, site, source, title, canonical_name, "
        "recipe_slug, equipment) values ('https://ex.test/u2','ex','{}'::jsonb,"
        "'Mystery','mystery','mystery', array[]::text[]) returning id"
    ).fetchone()[0]
    conn.execute(
        "insert into recipe_ingredients (recipe_id, position, name, amount, unit, "
        "raw_text) values (%s, 0, 'Unobtanium', 1, 'oz', '1 oz unobtanium')",
        (unresolved_id,),
    )
    noslug_id = conn.execute(
        "insert into recipes (source_url, site, source, title, canonical_name, "
        "recipe_slug, equipment) values ('https://ex.test/n', 'ex', '{}'::jsonb, "
        "NULL, NULL, NULL, array[]::text[]) returning id"
    ).fetchone()[0]
    ids = [ok_id, unresolved_id, noslug_id, 999999]

    at = "2026-07-12T00:00:00+00:00"
    results = generate_bundles(conn, ids, imported_at=at)

    # Order + coverage preserved (one entry per input id, in order).
    assert [rid for rid, _ in results] == ids
    by_id = dict(results)
    # Valid recipe: byte-identical to the per-recipe call.
    single = generate_bundle(conn, ok_id, imported_at=at)
    assert json.dumps(by_id[ok_id], sort_keys=True) == json.dumps(single, sort_keys=True)
    # Unresolved / slug-less: the exceptions are returned (caught), not raised.
    assert isinstance(by_id[unresolved_id], UnresolvedIngredient)
    assert isinstance(by_id[noslug_id], BundleError)
    # Vanished recipe: None, same as generate_bundle.
    assert by_id[999999] is None

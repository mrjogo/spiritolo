"""DB-integration test for the RecipeGF export stage against real Postgres
(TEST_DB_URL — a local Supabase/Docker cluster or any reachable Postgres; the
suite skips-loud if unset). Verifies the relational schema + db.py + run_export,
including that the pin-2 bundle generated from the stored rows is identical to
what the converter produced (the "store, then project" contract).
"""

from __future__ import annotations

import json
from datetime import datetime

import pytest

from ingredients.recipegf import db as export_db
from ingredients.recipegf.bundle import validate_bundle
from ingredients.recipegf.converter import (
    Ok,
    SourceIngredient,
    SourceRecipe,
    convert_recipe,
)
from ingredients.recipegf.verbs import verb_defs_for
from ingredients.recipegf.version import CONVERTER_VERSION

_IMPORTED_AT = "2026-07-11T00:00:00+00:00"

# The exportable drink, as a SourceRecipe — we both seed the DB from it and
# convert it in-memory, so the stored rows and the "expected" bundle share one
# source of truth (slug=None everywhere → the converter slugifies the name).
_OF = SourceRecipe(
    canonical_name="Old Fashioned", source_url="https://ex/of",
    jsonld={"recipeInstructions": "Stir with ice and strain over a large cube. "
                                  "Garnish with an orange twist."},
    ingredients=[
        SourceIngredient(position=0, raw_text="2 oz bourbon", name="bourbon",
                         slug=None, amount=2, unit="oz", role="base_spirit"),
        SourceIngredient(position=1, raw_text="1 cube ice", name="ice",
                         slug=None, amount=1, unit="cube", role="ice"),
        SourceIngredient(position=2, raw_text="orange twist", name="orange twist",
                         slug=None, amount=None, unit=None, role="garnish"),
    ],
)

_MOJ = SourceRecipe(
    canonical_name="Mojito", source_url="https://ex/moj",
    jsonld={"recipeInstructions": "Muddle mint, add rum, stir and top with soda."},
    ingredients=[
        SourceIngredient(position=0, raw_text="2 oz rum", name="rum",
                         slug=None, amount=2, unit="oz", role="base_spirit"),
    ],
)


def _insert_recipe(conn, src: SourceRecipe) -> int:
    rid = conn.execute(
        "insert into recipes (site, source_url, jsonld, fetched_at) "
        "values ('test', %s, %s::jsonb, now()) returning id",
        (src.source_url, json.dumps(src.jsonld)),
    ).fetchone()[0]
    for ing in src.ingredients:
        conn.execute(
            "insert into recipe_ingredients "
            "(recipe_id, position, raw_text, name, amount, unit, role, "
            " parse_status, parser_version) "
            "values (%s,%s,%s,%s,%s,%s,%s,'parsed','v1')",
            (rid, ing.position, ing.raw_text, ing.name, ing.amount, ing.unit, ing.role),
        )
    return rid


def _insert_cluster(conn, *, key, name, rep_id) -> int:
    return conn.execute(
        "insert into recipe_clusters "
        "(cluster_key, canonical_name, ingredient_set, dedup_version, "
        " representative_recipe_id) "
        "values (%s,%s,'[]'::jsonb,'v1',%s) returning id",
        (key, name, rep_id),
    ).fetchone()[0]


@pytest.fixture
def export_scenario(db_conn):
    conn = db_conn
    conn.execute(
        "truncate table recipegf_proposals, recipegf_recipes, recipe_clusters, "
        "recipe_ingredients, recipes restart identity cascade"
    )
    of_rid = _insert_recipe(conn, _OF)
    of_cluster = _insert_cluster(conn, key="k-of", name=_OF.canonical_name, rep_id=of_rid)
    moj_rid = _insert_recipe(conn, _MOJ)
    moj_cluster = _insert_cluster(conn, key="k-moj", name=_MOJ.canonical_name, rep_id=moj_rid)
    return conn, of_cluster, moj_cluster


def test_export_persists_relationally_and_parks_uncertain(export_scenario):
    conn, of_cluster, moj_cluster = export_scenario

    counts = _run(conn)
    assert counts["exported"] == 1
    assert counts["muddle_unsupported"] == 1

    # Exported drink: a header row + ingredient rows + step rows (relational,
    # not a blob).
    header = conn.execute(
        "select status, slug, recipe_id, technique, equipment, converter_version "
        "from recipegf_recipes where cluster_id = %s", (of_cluster,),
    ).fetchone()
    status, slug, recipe_id, technique, equipment, version = header
    assert status == "exported"
    assert slug == "old-fashioned"
    assert recipe_id == "com.spiritolo/old-fashioned:v1"
    assert technique == "stir"
    assert "mixing_glass" in equipment
    assert version == CONVERTER_VERSION

    n_ing = conn.execute(
        "select count(*) from recipegf_ingredients ri "
        "join recipegf_recipes rr on rr.id = ri.recipegf_recipe_id "
        "where rr.cluster_id = %s", (of_cluster,),
    ).fetchone()[0]
    n_steps = conn.execute(
        "select count(*) from recipegf_steps rs "
        "join recipegf_recipes rr on rr.id = rs.recipegf_recipe_id "
        "where rr.cluster_id = %s", (of_cluster,),
    ).fetchone()[0]
    assert n_ing == 3 and n_steps == 5

    # Uncertain drink: a parking header (no children) + a proposal.
    moj_header = conn.execute(
        "select status, slug from recipegf_recipes where cluster_id = %s", (moj_cluster,),
    ).fetchone()
    assert moj_header == ("uncertain", None)
    assert conn.execute(
        "select count(*) from recipegf_ingredients ri "
        "join recipegf_recipes rr on rr.id = ri.recipegf_recipe_id "
        "where rr.cluster_id = %s", (moj_cluster,),
    ).fetchone()[0] == 0
    proposal = conn.execute(
        "select reason, status from recipegf_proposals where cluster_id = %s",
        (moj_cluster,),
    ).fetchone()
    assert proposal == ("muddle_unsupported", "pending")


def test_generated_bundle_matches_converter_output(export_scenario):
    conn, of_cluster, _moj = export_scenario
    _run(conn)

    generated = export_db.generate_bundle(
        conn, cluster_id=of_cluster, converter_version=CONVERTER_VERSION
    )
    assert generated is not None
    assert validate_bundle(generated).valid

    # The store projection must reproduce exactly what the converter produced.
    expected = convert_recipe(_OF)
    assert isinstance(expected, Ok)
    assert generated["recipe"] == expected.recipe
    assert generated["verbs"] == verb_defs_for(expected.spiritolo_verbs)
    assert generated["meta"]["slug"] == expected.slug == "old-fashioned"
    assert generated["meta"]["source"] == _OF.source_url
    # imported_at is the row's exported_at — a real, parseable timestamp.
    datetime.fromisoformat(generated["meta"]["imported_at"])


def test_export_is_idempotent(export_scenario):
    conn, _of, _moj = export_scenario
    _run(conn)
    again = _run(conn)
    assert sum(again.values()) == 0


def test_reset_requeues(export_scenario):
    conn, _of, _moj = export_scenario
    _run(conn)
    # Two headers: one 'exported', one parked 'uncertain' — reset clears both.
    assert export_db.count_recipe_headers(conn) == 2
    cleared = export_db.clear_recipe_headers(conn)
    assert cleared == 2
    counts = _run(conn)
    assert counts["exported"] == 1 and counts["muddle_unsupported"] == 1


def test_dry_run_does_not_write(export_scenario):
    conn, _of, _moj = export_scenario
    _run(conn, dry_run=True)
    assert conn.execute("select count(*) from recipegf_recipes").fetchone()[0] == 0
    assert conn.execute("select count(*) from recipegf_proposals").fetchone()[0] == 0


def _run(conn, **kw):
    from ingredients.recipegf.export import run_export
    return run_export(conn, imported_at=_IMPORTED_AT, **kw)

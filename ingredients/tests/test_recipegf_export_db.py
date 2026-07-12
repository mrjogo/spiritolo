"""DB-integration test for the RecipeGF export stage against real Postgres
(TEST_DB_URL — a local Supabase/Docker cluster or any reachable Postgres; the
suite skips-loud if unset). Verifies the relational schema + db.py + run_export,
including that the pin-2 bundle generated from the stored rows is identical to
what the converter produced (the "store, then project" contract).
"""

from __future__ import annotations

import json
from datetime import datetime

import psycopg
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
# source of truth. Ingredients carry *registered* taxonomy slugs (bourbon / ice
# / orange): D6 governance means the converter never slugifies a parsed name,
# so an exportable fixture must supply resolved slugs (a null-slug ingredient
# would abstain, like _MOJ's muddle does for a different reason).
_OF = SourceRecipe(
    canonical_name="Old Fashioned", source_url="https://ex/of",
    jsonld={"recipeInstructions": "Stir with ice and strain over a large cube. "
                                  "Garnish with an orange twist."},
    ingredients=[
        SourceIngredient(position=0, raw_text="2 oz bourbon", name="bourbon",
                         slug="bourbon", amount=2, unit="oz", role="base_spirit"),
        SourceIngredient(position=1, raw_text="1 cube ice", name="ice",
                         slug="ice", amount=1, unit="cube", role="ice"),
        SourceIngredient(position=2, raw_text="orange twist", name="orange twist",
                         slug="orange", amount=None, unit=None, role="garnish"),
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

# A blend drink — exercises the spiritolo/blend extension verb, so its bundle's
# `verbs` array is non-empty (the RPC's verb-def-from-cache path).
_FD = SourceRecipe(
    canonical_name="Frozen Daiquiri", source_url="https://ex/fd",
    jsonld={"recipeInstructions": "Combine rum, lime juice, simple syrup and ice "
                                  "in a blender. Blend until smooth."},
    ingredients=[
        SourceIngredient(position=0, raw_text="2 oz white rum", name="white rum",
                         slug="white-rum", amount=2, unit="oz", role="base_spirit"),
        SourceIngredient(position=1, raw_text="1 oz lime juice", name="lime juice",
                         slug="lime-juice", amount=1, unit="oz", role="citrus"),
        SourceIngredient(position=2, raw_text="0.5 oz simple syrup", name="simple syrup",
                         slug="simple-syrup", amount=0.5, unit="oz", role="sweetener"),
        SourceIngredient(position=3, raw_text="1 cup ice", name="ice",
                         slug="ice", amount=1, unit="cup", role="ice"),
    ],
)


def _ensure_node(conn, slug: str) -> int:
    """Register a taxonomy node for ``slug`` (idempotent), returning its id.

    The converter reads the *registered* slug via the taxonomy_nodes join in
    ``fetch_source_ingredients`` — there is no name-slugify fallback — so an
    exportable seed must actually register its ingredient slugs here."""
    row = conn.execute(
        "insert into taxonomy_nodes (slug, display_name) values (%s, %s) "
        "on conflict (slug) do update set slug = excluded.slug returning id",
        (slug, slug),
    ).fetchone()
    return row[0]


def _insert_recipe(conn, src: SourceRecipe) -> int:
    rid = conn.execute(
        "insert into recipes (site, source_url, jsonld, fetched_at) "
        "values ('test', %s, %s::jsonb, now()) returning id",
        (src.source_url, json.dumps(src.jsonld)),
    ).fetchone()[0]
    for ing in src.ingredients:
        node_id = _ensure_node(conn, ing.slug) if ing.slug else None
        conn.execute(
            "insert into recipe_ingredients "
            "(recipe_id, position, raw_text, name, amount, unit, role, "
            " taxonomy_node_id, parse_status, parser_version) "
            "values (%s,%s,%s,%s,%s,%s,%s,%s,'parsed','v1')",
            (rid, ing.position, ing.raw_text, ing.name, ing.amount, ing.unit,
             ing.role, node_id),
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
        "truncate table recipegf_proposals, recipegf_recipes, recipegf_verb_defs, "
        "recipe_clusters, recipe_ingredients, recipes, taxonomy_nodes "
        "restart identity cascade"
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


# --------------------------------------------------------------------------
# P3 read surface: slug-keyed pull, verb-def sync, catalog + bundle RPCs
# --------------------------------------------------------------------------


def test_generate_bundle_by_slug_matches_cluster_pull(export_scenario):
    conn, of_cluster, _moj = export_scenario
    _run(conn)

    by_slug = export_db.generate_bundle_by_slug(
        conn, slug="old-fashioned", converter_version=CONVERTER_VERSION
    )
    by_cluster = export_db.generate_bundle(
        conn, cluster_id=of_cluster, converter_version=CONVERTER_VERSION
    )
    assert by_slug is not None
    assert by_slug == by_cluster
    assert validate_bundle(by_slug).valid


def test_generate_bundle_by_slug_unknown_is_none(export_scenario):
    conn, _of, _moj = export_scenario
    _run(conn)
    assert export_db.generate_bundle_by_slug(
        conn, slug="does-not-exist", converter_version=CONVERTER_VERSION
    ) is None
    # A parked-uncertain drink has no exported row → no slug-keyed bundle.
    assert export_db.generate_bundle_by_slug(
        conn, slug="mojito", converter_version=CONVERTER_VERSION
    ) is None


def test_slug_is_unique_per_converter_version(export_scenario):
    conn, of_cluster, _moj = export_scenario
    _run(conn)
    # A second exported row with the same (slug, converter_version) is rejected
    # by the partial unique index — the guarantee Barbot's slug join relies on.
    with pytest.raises(psycopg.errors.UniqueViolation):
        conn.execute(
            "insert into recipegf_recipes "
            "(cluster_id, status, slug, recipe_id, converter_version) "
            "values (%s, 'exported', 'old-fashioned', 'com.spiritolo/old-fashioned:v1', %s)",
            (of_cluster, CONVERTER_VERSION),
        )


def test_verb_defs_synced_from_repo(export_scenario):
    from ingredients.recipegf.verbs import spiritolo_verb_defs

    conn, _of, _moj = export_scenario
    _run(conn)
    rows = conn.execute(
        "select verb, definition from recipegf_verb_defs order by verb"
    ).fetchall()
    synced = {verb: definition for verb, definition in rows}
    assert synced == spiritolo_verb_defs()


def test_rpc_catalog_lists_only_exported(export_scenario):
    conn, _of, _moj = export_scenario
    of_rid = _insert_recipe(conn, _FD)
    _insert_cluster(conn, key="k-fd", name=_FD.canonical_name, rep_id=of_rid)
    _run(conn)

    rows = conn.execute(
        "select slug, title, technique from recipegf_catalog(%s) order by slug",
        (CONVERTER_VERSION,),
    ).fetchall()
    slugs = [r[0] for r in rows]
    assert slugs == ["frozen-daiquiri", "old-fashioned"]   # sorted; mojito parked-out
    by_slug = {r[0]: (r[1], r[2]) for r in rows}
    assert by_slug["old-fashioned"] == ("Old Fashioned", "stir")
    assert by_slug["frozen-daiquiri"] == ("Frozen Daiquiri", "blend")

    # Version filter: a bogus version yields nothing.
    assert conn.execute(
        "select count(*) from recipegf_catalog('vX')"
    ).fetchone()[0] == 0


def test_rpc_bundle_matches_python_projection(export_scenario):
    """The recipegf_bundle RPC (SQL) and generate_bundle_by_slug (Python) are
    two projections of the same rows — they must agree byte-for-byte (modulo the
    imported_at timestamp rendering, which is instant-equal)."""
    conn, _of, _moj = export_scenario
    fd_rid = _insert_recipe(conn, _FD)
    _insert_cluster(conn, key="k-fd", name=_FD.canonical_name, rep_id=fd_rid)
    _run(conn)

    for slug, expect_verbs in [("old-fashioned", []), ("frozen-daiquiri", ["spiritolo/blend"])]:
        rpc = conn.execute(
            "select recipegf_bundle(%s, %s)", (slug, CONVERTER_VERSION)
        ).fetchone()[0]
        py = export_db.generate_bundle_by_slug(
            conn, slug=slug, converter_version=CONVERTER_VERSION
        )
        assert rpc is not None and py is not None

        # The RPC bundle is self-contained + valid exactly as Barbot validates it.
        assert validate_bundle(rpc).valid
        assert [d["verb"] for d in rpc["verbs"]] == expect_verbs

        # recipe + verbs + meta.slug/source identical; imported_at same instant.
        assert rpc["recipe"] == py["recipe"]
        assert rpc["verbs"] == py["verbs"]
        assert rpc["meta"]["slug"] == py["meta"]["slug"]
        assert rpc["meta"]["source"] == py["meta"]["source"]
        assert datetime.fromisoformat(rpc["meta"]["imported_at"]) == \
            datetime.fromisoformat(py["meta"]["imported_at"])


def test_rpc_bundle_unknown_slug_is_null(export_scenario):
    conn, _of, _moj = export_scenario
    _run(conn)
    assert conn.execute(
        "select recipegf_bundle('nope', %s)", (CONVERTER_VERSION,)
    ).fetchone()[0] is None

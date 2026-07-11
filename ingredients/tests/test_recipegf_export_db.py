"""DB-integration test for the RecipeGF export stage. Needs TEST_DB_URL
(runs in CI / on a host with the local Postgres; skips-loud otherwise, like the
rest of the DB suite). Verifies the migration columns + db.py + run_export
against real Postgres.
"""

from __future__ import annotations

import json

import psycopg
import pytest

from ingredients.recipegf import db as export_db
from ingredients.recipegf.bundle import validate_bundle
from ingredients.recipegf.export import run_export
from ingredients.recipegf.version import CONVERTER_VERSION

_IMPORTED_AT = "2026-07-11T00:00:00+00:00"


def _insert_recipe(conn, *, url, instructions):
    return conn.execute(
        "insert into recipes (site, source_url, jsonld, fetched_at) "
        "values ('test', %s, %s::jsonb, now()) returning id",
        (url, json.dumps({"recipeInstructions": instructions})),
    ).fetchone()[0]


def _insert_ingredient(conn, *, recipe_id, pos, raw, name, amount, unit, role):
    conn.execute(
        "insert into recipe_ingredients "
        "(recipe_id, position, raw_text, name, amount, unit, role, "
        " parse_status, parser_version) "
        "values (%s,%s,%s,%s,%s,%s,%s,'parsed','v1')",
        (recipe_id, pos, raw, name, amount, unit, role),
    )


def _insert_cluster(conn, *, key, name, rep_id):
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
        "truncate table recipegf_proposals, recipe_clusters, "
        "recipe_ingredients, recipes restart identity cascade"
    )
    # Exportable stirred drink.
    of = _insert_recipe(conn, url="https://ex/of",
                        instructions="Stir with ice and strain over a large cube.")
    _insert_ingredient(conn, recipe_id=of, pos=0, raw="2 oz bourbon",
                       name="bourbon", amount=2, unit="oz", role="base_spirit")
    _insert_ingredient(conn, recipe_id=of, pos=1, raw="1 cube ice",
                       name="ice", amount=1, unit="cube", role="ice")
    of_cluster = _insert_cluster(conn, key="k-of", name="Old Fashioned", rep_id=of)

    # Muddled drink → propose→review.
    moj = _insert_recipe(conn, url="https://ex/moj",
                         instructions="Muddle mint, add rum, stir and top with soda.")
    _insert_ingredient(conn, recipe_id=moj, pos=0, raw="2 oz rum",
                       name="rum", amount=2, unit="oz", role="base_spirit")
    moj_cluster = _insert_cluster(conn, key="k-moj", name="Mojito", rep_id=moj)
    return conn, of_cluster, moj_cluster


def test_export_persists_bundle_and_parks_uncertain(export_scenario):
    conn, of_cluster, moj_cluster = export_scenario

    counts = run_export(conn, imported_at=_IMPORTED_AT)
    assert counts["exported"] == 1
    assert counts["muddle_unsupported"] == 1

    # Exported cluster carries a validated bundle stamped at the current version.
    row = conn.execute(
        "select recipegf_slug, recipegf_bundle, recipegf_version, recipegf_status "
        "from recipe_clusters where id = %s", (of_cluster,),
    ).fetchone()
    slug, bundle, version, status = row
    assert slug == "old-fashioned"
    assert status == "exported"
    assert version == CONVERTER_VERSION
    assert bundle["recipe"]["id"] == "com.spiritolo/old-fashioned:v1"
    assert bundle["meta"] == {"slug": "old-fashioned", "source": "https://ex/of",
                              "imported_at": _IMPORTED_AT}
    assert validate_bundle(bundle).valid

    # Uncertain cluster is parked with no bundle + a proposal enqueued.
    prow = conn.execute(
        "select recipegf_bundle, recipegf_version, recipegf_status "
        "from recipe_clusters where id = %s", (moj_cluster,),
    ).fetchone()
    assert prow[0] is None and prow[1] == CONVERTER_VERSION and prow[2] == "uncertain"
    proposal = conn.execute(
        "select reason, status, cluster_id from recipegf_proposals where cluster_id = %s",
        (moj_cluster,),
    ).fetchone()
    assert proposal == ("muddle_unsupported", "pending", moj_cluster)


def test_export_is_idempotent(export_scenario):
    conn, _of, _moj = export_scenario
    run_export(conn, imported_at=_IMPORTED_AT)
    # Both clusters now stamped at the current version → queue is empty.
    again = run_export(conn, imported_at=_IMPORTED_AT)
    assert sum(again.values()) == 0


def test_reset_requeues(export_scenario):
    conn, _of, _moj = export_scenario
    run_export(conn, imported_at=_IMPORTED_AT)
    assert export_db.count_exported_rows(conn) == 2
    cleared = export_db.clear_exported_rows(conn)
    assert cleared == 2
    # A fresh run finds both clusters again.
    counts = run_export(conn, imported_at=_IMPORTED_AT)
    assert counts["exported"] == 1 and counts["muddle_unsupported"] == 1


def test_dry_run_does_not_write(export_scenario):
    conn, of_cluster, _moj = export_scenario
    run_export(conn, imported_at=_IMPORTED_AT, dry_run=True)
    row = conn.execute(
        "select recipegf_version from recipe_clusters where id = %s", (of_cluster,),
    ).fetchone()
    assert row[0] is None
    assert conn.execute("select count(*) from recipegf_proposals").fetchone()[0] == 0

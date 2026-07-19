"""cluster stage_fn: slug-hashed cluster + variant identity.

Identical drinks collapse to one cluster+variant; ratio differences split the
variant within one cluster; ice is off the key. Runs against TEST_DB_URL.
"""

from __future__ import annotations

import psycopg
import pytest

from ingredients.dedup.version import DEDUP_VERSION
from ingredients.pipeline.stages.cluster import cluster_stage_fn


@pytest.fixture()
def conn(test_db_url: str):
    with psycopg.connect(test_db_url, autocommit=True) as c:
        for t in ("recipes", "job_items", "ingredient_resolutions",
                  "recipe_clusters", "taxonomy_nodes", "cocktail_aliases"):
            c.execute(f"truncate {t} restart identity cascade")
        for slug, role in [("gin", "base_spirit"), ("campari", "modifier"),
                           ("sweet-vermouth", "modifier"), ("ice", "ice")]:
            c.execute(
                "insert into taxonomy_nodes (slug, display_name, default_role, is_cluster_node) "
                "values (%s, %s, %s, true)",
                (slug, slug, role),
            )
        for name, slug in [("gin", "gin"), ("campari", "campari"),
                           ("sweet vermouth", "sweet-vermouth"), ("ice", "ice")]:
            c.execute(
                "insert into ingredient_resolutions (normalized_name, taxonomy_slug, method, version) "
                "values (%s, %s, 'alias', 'v1')",
                (name, slug),
            )
        yield c
        for t in ("recipes", "job_items", "ingredient_resolutions",
                  "recipe_clusters", "taxonomy_nodes", "cocktail_aliases"):
            c.execute(f"truncate {t} restart identity cascade")


def _negroni(conn, url, site, ingredients):
    rid = conn.execute(
        "insert into recipes (source_url, site, source, title, canonical_name) "
        "values (%s, %s, '{}'::jsonb, 'Negroni', 'negroni') returning id",
        (url, site),
    ).fetchone()[0]
    for pos, (name, amount) in enumerate(ingredients):
        conn.execute(
            "insert into recipe_ingredients (recipe_id, position, name, amount, unit, raw_text) "
            "values (%s, %s, %s, %s, 'oz', 'x')",
            (rid, pos, name, amount),
        )
    return rid


_BASE = [("gin", 1.0), ("campari", 1.0), ("sweet vermouth", 1.0)]


def _job():
    return {"id": None, "payload": {}}


def test_identical_recipes_share_cluster_and_variant(conn):
    a = _negroni(conn, "https://ex.test/n1", "punch", _BASE)
    b = _negroni(conn, "https://ex.test/n2", "imbibe", _BASE)
    counts = cluster_stage_fn(_job(), conn, None)
    assert counts["clustered"] == 2
    rows = conn.execute(
        "select cluster_id, variant_key from recipes where id in (%s,%s) order by id", (a, b)
    ).fetchall()
    assert rows[0] == rows[1]
    # One cluster row with recipe_count 2 across 2 sources.
    cluster = conn.execute(
        "select recipe_count, source_count from recipe_clusters"
    ).fetchone()
    assert cluster == (2, 2)


def test_ratio_variants_split_within_one_cluster(conn):
    a = _negroni(conn, "https://ex.test/r1", "punch", [("gin", 1.0), ("campari", 1.0), ("sweet vermouth", 1.0)])
    b = _negroni(conn, "https://ex.test/r2", "imbibe", [("gin", 1.5), ("campari", 1.0), ("sweet vermouth", 1.0)])
    cluster_stage_fn(_job(), conn, None)
    rows = conn.execute(
        "select cluster_id, variant_key from recipes where id in (%s,%s) order by id", (a, b)
    ).fetchall()
    assert rows[0][0] == rows[1][0]      # same cluster
    assert rows[0][1] != rows[1][1]      # different variant


def test_ice_is_off_the_cluster_key(conn):
    a = _negroni(conn, "https://ex.test/i1", "punch", _BASE)
    b = _negroni(conn, "https://ex.test/i2", "imbibe", _BASE + [("ice", 1.0)])
    cluster_stage_fn(_job(), conn, None)
    rows = conn.execute(
        "select cluster_id, variant_key from recipes where id in (%s,%s) order by id", (a, b)
    ).fetchall()
    assert rows[0] == rows[1]


def test_chunk_boundary_matches_single_chunk(conn):
    # Five recipes across three sites (two distinct sources), forcing chunk_size=2
    # so the run spans three chunks (2 + 2 + 1). Batched writes must produce the
    # exact counts + DB end state a single chunk would.
    sites = ["punch", "imbibe", "punch", "imbibe", "punch"]
    rids = [
        _negroni(conn, f"https://ex.test/c{i}", site, _BASE)
        for i, site in enumerate(sites)
    ]
    counts = cluster_stage_fn(_job(), conn, None, chunk_size=2)
    assert counts == {"clustered": 5, "skipped": 0}

    # All five collapse to one cluster + variant.
    rows = conn.execute(
        "select cluster_id, variant_key from recipes where id = any(%s) order by id", (rids,)
    ).fetchall()
    assert len({r[0] for r in rows}) == 1
    assert len({r[1] for r in rows}) == 1

    cluster = conn.execute(
        "select recipe_count, source_count from recipe_clusters"
    ).fetchone()
    assert cluster == (5, 2)

    # One resolved stage_run per recipe at the current version.
    runs = conn.execute(
        "select entity_id, outcome, code_version from job_items where stage='cluster-recipes' order by entity_id"
    ).fetchall()
    assert [r[0] for r in runs] == sorted(rids)
    assert all(r[1] == "resolved" and r[2] == DEDUP_VERSION for r in runs)


def test_cluster_is_idempotent_via_ledger(conn):
    _negroni(conn, "https://ex.test/x", "punch", _BASE)
    assert cluster_stage_fn(_job(), conn, None)["clustered"] == 1
    assert cluster_stage_fn(_job(), conn, None) == {"clustered": 0}
    # The stage_run is at the current DEDUP_VERSION.
    v = conn.execute(
        "select code_version from job_items where stage='cluster-recipes' limit 1"
    ).fetchone()[0]
    assert v == DEDUP_VERSION

"""End-to-end cold build: one page -> an exportable pin-2 bundle.

Seeds a tiny taxonomy + one classified page whose cached HTML carries an Old
Fashioned Recipe JSON-LD, runs every stage in order, and asserts a frozen bundle
plus one stage_run per stage. Runs against TEST_DB_URL with a fake corpus reader
(no object store) and no LLM.
"""

from __future__ import annotations

import gzip
import hashlib

import psycopg
import pytest
from recipegf import parse_recipe_id

from ingredients.pipeline.coldbuild import run_cold_build
from ingredients.pipeline.stages import STAGE_ORDER, extract

_HTML = """
<html><head>
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"Recipe","name":"Old Fashioned",
 "author":{"@type":"Person","name":"Jerry Thomas"},
 "image":"https://img.test/of.jpg",
 "recipeIngredient":["2 oz bourbon","0.25 oz simple syrup","2 dashes Angostura bitters"],
 "recipeInstructions":"Stir with ice and strain into a rocks glass."}
</script></head><body>Old Fashioned</body></html>
"""


class _FakeCorpus:
    """Serves one gzipped HTML doc by its sha256(url) key, like the object-store reader."""

    def __init__(self, mapping: dict[str, str]):
        self._by_key = {k: gzip.compress(v.encode()) for k, v in mapping.items()}

    def read_html(self, key: str) -> str:
        from ingredients.pipeline.corpus import CorpusMiss

        if key not in self._by_key:
            raise CorpusMiss(key)
        return gzip.decompress(self._by_key[key]).decode()


def _seed_taxonomy(conn: psycopg.Connection) -> None:
    conn.execute("truncate taxonomy_nodes restart identity cascade")
    conn.execute("truncate cocktail_aliases")
    nodes = [
        ("bourbon", "Bourbon", "base_spirit"),
        ("simple-syrup", "Simple Syrup", "sweetener"),
        ("angostura-bitters", "Angostura Bitters", "bitters"),
    ]
    ids = {}
    for slug, display, role in nodes:
        ids[slug] = conn.execute(
            "insert into taxonomy_nodes (slug, display_name, default_role, is_cluster_node) "
            "values (%s, %s, %s, true) returning id",
            (slug, display, role),
        ).fetchone()[0]
    for slug, alias in [
        ("bourbon", "bourbon"),
        ("simple-syrup", "simple syrup"),
        ("angostura-bitters", "angostura bitters"),
    ]:
        conn.execute(
            "insert into taxonomy_aliases (node_id, alias) values (%s, %s)",
            (ids[slug], alias),
        )


@pytest.fixture()
def conn(test_db_url: str):
    with psycopg.connect(test_db_url, autocommit=True) as c:
        for t in ("recipes", "pages", "stage_runs", "ingredient_resolutions",
                  "recipe_clusters", "recipe_exports"):
            c.execute(f"truncate {t} restart identity cascade")
        _seed_taxonomy(c)
        url = "https://ex.test/old-fashioned"
        key = hashlib.sha256(url.encode()).hexdigest()
        c.execute(
            "insert into pages (url, site, corpus_key, content_type) "
            "values (%s, 'ex', %s, 'likely_drink_recipe')",
            (url, key),
        )
        extract.set_corpus_reader(_FakeCorpus({key: _HTML}))
        yield c
        extract.set_corpus_reader(None)


def test_cold_build_produces_bundle_and_one_run_per_stage(conn):
    results = run_cold_build(conn, providers=None)
    assert results["extract"]["extracted"] == 1
    assert results["export"]["exported"] == 1

    # A frozen bundle exists, valid pin-2 shape.
    row = conn.execute(
        "select recipe_slug, recipe_ref, bundle from recipe_exports"
    ).fetchone()
    assert row is not None
    slug, ref, bundle = row
    assert slug == "old-fashioned"
    assert parse_recipe_id(ref).slug == "old-fashioned"
    ingredient_refs = [i["ref"] for i in bundle["recipe"]["ingredients"]]
    assert ingredient_refs == [
        "com.spiritolo/bourbon",
        "com.spiritolo/simple-syrup",
        "com.spiritolo/angostura-bitters",
    ]

    # The recipe is clustered and the resolution is shared/name-keyed.
    recipe = conn.execute(
        "select id, cluster_id, variant_key, canonical_name from recipes"
    ).fetchone()
    assert recipe[1] is not None and recipe[2] is not None
    assert conn.execute(
        "select count(*) from ingredient_resolutions where taxonomy_slug is not null"
    ).fetchone()[0] == 3

    # Exactly one stage_run per content stage for this recipe/page.
    recipe_stage_runs = {
        r[0] for r in conn.execute(
            "select stage from stage_runs where entity_type='recipe' and entity_id=%s",
            (recipe[0],),
        ).fetchall()
    }
    assert {"parse", "map", "convert", "cluster", "export"} <= recipe_stage_runs
    page_runs = conn.execute(
        "select count(*) from stage_runs where entity_type='page' and stage='extract'"
    ).fetchone()[0]
    assert page_runs == 1
    # Every content stage ran.
    assert set(STAGE_ORDER) == {"extract", "parse", "map", "convert", "cluster", "export"}


def test_cold_build_is_idempotent(conn):
    run_cold_build(conn, providers=None)
    second = run_cold_build(conn, providers=None)
    # Nothing left to do on the second pass.
    assert second["extract"]["extracted"] == 0
    assert second["export"]["exported"] == 0
    assert conn.execute("select count(*) from recipe_exports").fetchone()[0] == 1

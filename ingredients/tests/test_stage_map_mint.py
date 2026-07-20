"""map stage mint pass: mechanically mint provisional nodes for unresolved names.

After alias / lexical / LLM, any name still without a live match is minted as a
``status='provisional'`` node (``node_kind`` NULL, not a cluster node), with a
``map-mint`` provenance row and a ``provisional`` resolution. The mint is fully
deterministic (no LLM), idempotent, and — via get-or-create by slug — attaches to
an existing live node rather than duplicating it. Un-slugifiable garbage abstains
instead of minting a bad node.

Runs against TEST_DB_URL.
"""

from __future__ import annotations

import psycopg
import pytest

from ingredients.mapping.mint import mint_provisional_node
from ingredients.pipeline.stages.map import MAPPER_VERSION, map_stage_fn


@pytest.fixture()
def conn(test_db_url: str):
    with psycopg.connect(test_db_url, autocommit=True) as c:
        _truncate(c)
        yield c
        _truncate(c)


def _truncate(c: psycopg.Connection) -> None:
    for t in (
        "recipes",
        "job_items",
        "ingredient_resolutions",
        "taxonomy_provenance",
        "taxonomy_aliases",
        "taxonomy_edges",
        "taxonomy_nodes",
    ):
        c.execute(f"truncate {t} restart identity cascade")


def _recipe(c, url, ingredient_names):
    rid = c.execute(
        "insert into recipes (source_url, site, source) values (%s, 'ex', '{}'::jsonb) returning id",
        (url,),
    ).fetchone()[0]
    for pos, name in enumerate(ingredient_names):
        c.execute(
            "insert into recipe_ingredients (recipe_id, position, name, raw_text) "
            "values (%s, %s, %s, %s)",
            (rid, pos, name, f"{name} raw"),
        )
    return rid


def _job():
    return {"id": None, "payload": {}}


def test_unresolved_name_mints_one_provisional_node_idempotently(conn):
    # (a) an unresolved name mints exactly one provisional node, idempotent.
    _recipe(conn, "https://ex.test/1", ["Elderflower Cordial"])
    map_stage_fn(_job(), conn, None)

    nodes = conn.execute(
        "select node_kind, status, is_cluster_node from taxonomy_nodes "
        "where slug='elderflower-cordial'"
    ).fetchall()
    assert nodes == [(None, "provisional", False)]

    # Re-run: no duplicate node, still exactly one.
    _recipe(conn, "https://ex.test/2", ["Elderflower Cordial"])
    map_stage_fn(_job(), conn, None)
    count = conn.execute(
        "select count(*) from taxonomy_nodes where slug='elderflower-cordial'"
    ).fetchone()[0]
    assert count == 1


def test_mint_resolution_and_provenance(conn):
    # (b) resolution method='provisional' pointing at the minted slug;
    # (c) a taxonomy_provenance row with source='map-mint' exists.
    _recipe(conn, "https://ex.test/3", ["Amaro Nonino"])
    map_stage_fn(_job(), conn, None)

    res = conn.execute(
        "select taxonomy_slug, method, version from ingredient_resolutions "
        "where normalized_name='amaro nonino'"
    ).fetchone()
    assert res == ("amaro-nonino", "provisional", MAPPER_VERSION)

    node_id = conn.execute(
        "select id from taxonomy_nodes where slug='amaro-nonino'"
    ).fetchone()[0]
    prov = conn.execute(
        "select source, mapper_version, raw_string from taxonomy_provenance where node_id=%s",
        (node_id,),
    ).fetchone()
    assert prov == ("map-mint", MAPPER_VERSION, "amaro nonino")


def test_unslugifiable_name_abstains_without_creating_a_node(conn):
    # (d) an un-slugifiable name abstains; no node created.
    _recipe(conn, "https://ex.test/4", ["!!!"])
    counts = map_stage_fn(_job(), conn, None)
    assert counts["pending"] == 1

    res = conn.execute(
        "select taxonomy_slug, method from ingredient_resolutions where normalized_name='!!!'"
    ).fetchone()
    assert res == (None, "abstain")
    assert conn.execute("select count(*) from taxonomy_nodes").fetchone()[0] == 0


def test_mint_attaches_to_existing_live_node_when_slug_exists(conn):
    # (e) if the slug already exists as a LIVE node, mint attaches the resolution
    # to it instead of duplicating (and does not downgrade it to provisional).
    conn.execute(
        "insert into taxonomy_nodes (slug, display_name, node_kind) "
        "values ('campari', 'Campari', 'brand')"
    )
    slug = mint_provisional_node(conn, normalized_name="campari", version=MAPPER_VERSION)
    assert slug == "campari"

    nodes = conn.execute(
        "select node_kind, status from taxonomy_nodes where slug='campari'"
    ).fetchall()
    # Still exactly one node, still live, node_kind untouched.
    assert nodes == [("brand", "live")]

    res = conn.execute(
        "select taxonomy_slug, method from ingredient_resolutions where normalized_name='campari'"
    ).fetchone()
    assert res == ("campari", "provisional")

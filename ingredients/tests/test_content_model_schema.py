"""Schema shape of the relational content model.

Pins the cutover migration: the legacy per-cluster RecipeGF trio and the old
parser-output columns are gone, and the new `recipes` / `recipe_ingredients` /
`recipe_steps` / `ingredient_resolutions` / `recipe_clusters` / `recipe_exports`
tables exist with the columns the pipeline and the bundle generator read. Runs
against TEST_DB_URL (auto-migrated by conftest).
"""

from __future__ import annotations

import psycopg
import pytest


@pytest.fixture()
def conn(test_db_url: str):
    with psycopg.connect(test_db_url, autocommit=True) as c:
        yield c


def _columns(conn: psycopg.Connection, table: str) -> dict[str, str]:
    rows = conn.execute(
        """
        select column_name, data_type
        from information_schema.columns
        where table_schema = 'public' and table_name = %s
        """,
        (table,),
    ).fetchall()
    return {name: dtype for name, dtype in rows}


def _table_exists(conn: psycopg.Connection, table: str) -> bool:
    return (
        conn.execute(
            "select to_regclass(%s) is not null", (f"public.{table}",)
        ).fetchone()[0]
        is True
    )


def test_legacy_tables_are_dropped(conn):
    for gone in (
        "recipegf_recipes",
        "recipegf_ingredients",
        "recipegf_steps",
        "recipegf_proposals",
        "recipegf_verb_defs",
        "recipe_variants",
    ):
        assert not _table_exists(conn, gone), f"{gone} should be dropped"


def test_recipes_columns(conn):
    cols = _columns(conn, "recipes")
    for expected in (
        "id", "source_url", "site", "source", "title", "author", "image_url",
        "equipment", "canonical_name", "cluster_id", "variant_key",
        "recipe_slug", "created_at", "updated_at",
    ):
        assert expected in cols, f"recipes.{expected} missing"
    # The old shape kept the full JSON-LD under `jsonld`; the new column is
    # `source`. Guard the rename so nothing silently reads a dropped column.
    assert "jsonld" not in cols
    assert cols["source"] == "jsonb"


def test_recipe_ingredients_shape(conn):
    cols = _columns(conn, "recipe_ingredients")
    for expected in (
        "id", "recipe_id", "position", "name", "amount", "amount_max",
        "unit", "modifiers", "raw_text",
    ):
        assert expected in cols, f"recipe_ingredients.{expected} missing"
    # Resolution is shared/name-keyed now, not a per-row taxonomy id + status.
    assert "taxonomy_node_id" not in cols
    assert "parse_status" not in cols
    assert cols["modifiers"] == "ARRAY"


def test_recipe_steps_shape(conn):
    cols = _columns(conn, "recipe_steps")
    for expected in (
        "id", "recipe_id", "step_index", "verb", "roles", "modifiers", "result",
    ):
        assert expected in cols, f"recipe_steps.{expected} missing"
    assert cols["roles"] == "jsonb"
    assert cols["modifiers"] == "ARRAY"


def test_ingredient_resolutions_is_name_keyed(conn):
    cols = _columns(conn, "ingredient_resolutions")
    for expected in ("normalized_name", "taxonomy_slug", "method", "version"):
        assert expected in cols
    # normalized_name is the unique shared key.
    uniques = conn.execute(
        """
        select a.attname
        from pg_constraint con
        join pg_class rel on rel.oid = con.conrelid
        join lateral unnest(con.conkey) as k(attnum) on true
        join pg_attribute a on a.attrelid = rel.oid and a.attnum = k.attnum
        where rel.relname = 'ingredient_resolutions' and con.contype = 'u'
        """
    ).fetchall()
    assert ("normalized_name",) in uniques


def test_recipe_clusters_keyed_by_cluster_key(conn):
    cols = _columns(conn, "recipe_clusters")
    for expected in (
        "cluster_key", "canonical_name", "ingredient_set",
        "representative_recipe_id", "recipe_count", "source_count",
    ):
        assert expected in cols
    pk = conn.execute(
        """
        select a.attname
        from pg_constraint con
        join pg_class rel on rel.oid = con.conrelid
        join lateral unnest(con.conkey) as k(attnum) on true
        join pg_attribute a on a.attrelid = rel.oid and a.attnum = k.attnum
        where rel.relname = 'recipe_clusters' and con.contype = 'p'
        """
    ).fetchall()
    assert pk == [("cluster_key",)]


def test_recipe_exports_freeze_target(conn):
    cols = _columns(conn, "recipe_exports")
    for expected in (
        "recipe_id", "recipe_slug", "recipe_ref", "converter_version",
        "bundle", "exported_at",
    ):
        assert expected in cols
    assert cols["bundle"] == "jsonb"


def test_recipes_public_contract_preserved(conn):
    cols = _columns(conn, "recipes_public")
    for expected in (
        "id", "source_url", "site", "name", "author", "image_url",
        "jsonld", "cluster_id", "variant_key",
    ):
        assert expected in cols, f"recipes_public.{expected} missing"


def test_recipes_public_reads_new_columns(conn):
    conn.execute(
        """
        insert into recipes (source_url, site, source, title, author, image_url)
        values ('https://x.test/a', 'x', '{"k":1}'::jsonb, 'Old Fashioned',
                'Someone', 'https://img.test/a.jpg')
        """
    )
    row = conn.execute(
        "select name, jsonld from recipes_public where source_url = 'https://x.test/a'"
    ).fetchone()
    assert row[0] == "Old Fashioned"       # title exposed as name
    assert row[1] == {"k": 1}              # source exposed as jsonld
    conn.execute("delete from recipes where source_url = 'https://x.test/a'")

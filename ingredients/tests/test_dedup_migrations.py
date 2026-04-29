"""Schema-level integration tests for E's migrations.

Tests run against TEST_DB_URL with all migrations applied (the
ingredients conftest auto-applies new ones). Each test asserts a
column or table exists with the expected shape.
"""

from __future__ import annotations

import pytest
import psycopg


def test_taxonomy_nodes_has_is_cluster_node_column(db_conn):
    row = db_conn.execute(
        """
        select column_name, data_type, is_nullable, column_default
        from information_schema.columns
        where table_name = 'taxonomy_nodes' and column_name = 'is_cluster_node'
        """
    ).fetchone()
    assert row is not None, "is_cluster_node column missing"
    name, dtype, nullable, default = row
    assert dtype == "boolean"
    assert nullable == "NO"
    assert "false" in (default or "").lower()


def test_taxonomy_nodes_has_role_default_column(db_conn):
    row = db_conn.execute(
        """
        select data_type, is_nullable
        from information_schema.columns
        where table_name = 'taxonomy_nodes' and column_name = 'role_default'
        """
    ).fetchone()
    assert row is not None, "role_default column missing"
    dtype, nullable = row
    assert dtype == "text"
    assert nullable == "YES"


def test_taxonomy_nodes_has_is_defining_garnish_column(db_conn):
    row = db_conn.execute(
        """
        select data_type, is_nullable, column_default
        from information_schema.columns
        where table_name = 'taxonomy_nodes' and column_name = 'is_defining_garnish'
        """
    ).fetchone()
    assert row is not None, "is_defining_garnish column missing"
    dtype, nullable, default = row
    assert dtype == "boolean"
    assert nullable == "NO"
    assert "false" in (default or "").lower()


def test_recipe_ingredients_has_role_columns(db_conn):
    cols = {
        row[0]: (row[1], row[2])
        for row in db_conn.execute(
            """
            select column_name, data_type, is_nullable
            from information_schema.columns
            where table_name = 'recipe_ingredients'
              and column_name in ('role', 'role_source')
            """
        ).fetchall()
    }
    assert "role" in cols
    assert cols["role"] == ("text", "YES")
    assert "role_source" in cols
    assert cols["role_source"] == ("text", "YES")


def test_recipe_ingredients_role_check_constraint_rejects_unknown(db_conn):
    # Seed a valid recipe so the FK on recipe_ingredients.recipe_id is satisfied;
    # without this, the FK violation fires before the role CHECK.
    recipe_id = db_conn.execute(
        """
        insert into recipes (source_url, site, name, jsonld, fetched_at)
        values ('http://test/role-check', 'test', 'X', '{}'::jsonb, now())
        on conflict (source_url) do update set name = excluded.name
        returning id
        """
    ).fetchone()[0]
    with pytest.raises(psycopg.errors.CheckViolation):
        db_conn.execute(
            """
            insert into recipe_ingredients
                (recipe_id, position, raw_text, parse_status, parser_version, role)
            values (%s, 1, 'x', 'parsed', 'v1', 'not_a_real_role')
            """,
            (recipe_id,),
        )


def test_recipe_ingredients_role_source_check_constraint_rejects_unknown(db_conn):
    recipe_id = db_conn.execute(
        """
        insert into recipes (source_url, site, name, jsonld, fetched_at)
        values ('http://test/role-source-check', 'test', 'X', '{}'::jsonb, now())
        on conflict (source_url) do update set name = excluded.name
        returning id
        """
    ).fetchone()[0]
    with pytest.raises(psycopg.errors.CheckViolation):
        db_conn.execute(
            """
            insert into recipe_ingredients
                (recipe_id, position, raw_text, parse_status, parser_version, role_source)
            values (%s, 1, 'x', 'parsed', 'v1', 'banana')
            """,
            (recipe_id,),
        )


def test_recipes_has_normalize_columns(db_conn):
    cols = {
        row[0]: row[1]
        for row in db_conn.execute(
            """
            select column_name, data_type
            from information_schema.columns
            where table_name = 'recipes'
              and column_name in (
                'canonical_name', 'canonical_name_source',
                'normalizer_version', 'normalized_at'
              )
            """
        ).fetchall()
    }
    assert cols.get("canonical_name") == "text"
    assert cols.get("canonical_name_source") == "text"
    assert cols.get("normalizer_version") == "text"
    assert cols.get("normalized_at") == "timestamp with time zone"


def test_recipes_canonical_name_source_check_constraint_rejects_unknown(db_conn):
    # Insert a real recipe, then attempt to update it with an out-of-vocabulary
    # source. The CHECK fires only on a real row mutation; a `where false`
    # update would silently no-op, so we need an actual row.
    recipe_id = db_conn.execute(
        """
        insert into recipes (source_url, site, name, jsonld, fetched_at)
        values ('http://test/canonical-source-check', 'test', 'X', '{}'::jsonb, now())
        on conflict (source_url) do update set name = excluded.name
        returning id
        """
    ).fetchone()[0]
    with pytest.raises(psycopg.errors.CheckViolation):
        db_conn.execute(
            "update recipes set canonical_name_source = 'bogus' where id = %s",
            (recipe_id,),
        )

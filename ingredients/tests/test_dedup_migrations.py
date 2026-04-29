"""Schema-level integration tests for E's migrations.

Tests run against TEST_DB_URL with all migrations applied (the
ingredients conftest auto-applies new ones). Each test asserts a
column or table exists with the expected shape.
"""

from __future__ import annotations


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

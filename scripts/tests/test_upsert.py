"""UPSERT and sequence-resync SQL generation."""
from __future__ import annotations

import psycopg

from upload_to_staging.tables import OWNED_TABLES, OwnedTable
from upload_to_staging.upsert import build_upsert_sql, resync_sequence_sql


_RECIPES = next(t for t in OWNED_TABLES if t.name == "recipes")
_TAXEDGES = next(t for t in OWNED_TABLES if t.name == "taxonomy_edges")


def test_upsert_sql_single_pk():
    sql = build_upsert_sql(_RECIPES, columns=["id", "name", "updated_at"])
    rendered = sql.as_string(None)
    assert "insert into" in rendered.lower()
    assert '"recipes"' in rendered
    assert "on conflict (\"id\")" in rendered.lower() or 'on conflict ("id")' in rendered
    assert 'do update set "name" = excluded."name"' in rendered.lower() \
        or '"name" = excluded."name"' in rendered.lower()
    # PK column never appears in the SET list.
    set_clause = rendered.lower().split("do update set", 1)[1]
    assert '"id"' not in set_clause


def test_upsert_sql_composite_pk():
    sql = build_upsert_sql(
        _TAXEDGES,
        columns=["parent_id", "child_id", "rank", "updated_at"],
    )
    rendered = sql.as_string(None)
    assert "(\"parent_id\", \"child_id\")" in rendered.lower() \
        or '("parent_id", "child_id")' in rendered.lower()


def test_resync_sequence_sql_for_serial_table():
    sql = resync_sequence_sql(_RECIPES)
    assert sql is not None
    rendered = sql.as_string(None)
    assert "setval" in rendered.lower()
    assert "recipes_id_seq" in rendered
    assert "max(\"id\")" in rendered.lower() or 'max("id")' in rendered.lower()


def test_resync_sequence_sql_returns_none_for_composite_pk_table():
    assert resync_sequence_sql(_TAXEDGES) is None

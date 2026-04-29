import psycopg
import pytest

from ingredients.mapping.db import (
    fetch_unique_pending_names, write_resolution, write_pending,
)


def _seed_recipes_and_ingredients(conn: psycopg.Connection) -> dict[str, int]:
    """Two recipes, with overlapping ingredient names so we can verify
    the unique-names query collapses duplicates and the batch UPDATE
    flips every row sharing a name."""
    conn.execute("truncate table recipe_ingredients, recipes restart identity cascade")
    rid1 = conn.execute(
        "insert into recipes (site, source_url, jsonld, fetched_at) values ('punch', 'https://example.com/a', '{}'::jsonb, now()) returning id"
    ).fetchone()[0]
    rid2 = conn.execute(
        "insert into recipes (site, source_url, jsonld, fetched_at) values ('punch', 'https://example.com/b', '{}'::jsonb, now()) returning id"
    ).fetchone()[0]
    rows = [
        (rid1, 0, "2 oz gin",          "gin",          "parsed", "qty_unit"),
        (rid1, 1, "1 oz lemon juice",  "lemon juice",  "parsed", "qty_unit"),
        (rid2, 0, "2 oz gin",          "gin",          "parsed", "qty_unit"),
        (rid2, 1, "0.5 oz simple syrup", "simple syrup", "parsed", "qty_unit"),
    ]
    for r in rows:
        conn.execute(
            "insert into recipe_ingredients "
            "(recipe_id, position, raw_text, name, parse_status, parser_rule, parser_version) "
            "values (%s,%s,%s,%s,%s,%s,'v1')",
            r,
        )
    conn.commit()
    return {"recipe1": rid1, "recipe2": rid2}


def test_fetch_unique_pending_names_collapses_duplicates(fixture_taxonomy):
    conn, _ = fixture_taxonomy
    _seed_recipes_and_ingredients(conn)
    names = fetch_unique_pending_names(conn, mapper_version="v1")
    # 'gin' appears in both recipes but should be deduped.
    assert sorted(names) == ["gin", "lemon juice", "simple syrup"]


def test_write_resolution_updates_every_row_sharing_name(fixture_taxonomy):
    conn, ids = fixture_taxonomy
    _seed_recipes_and_ingredients(conn)
    write_resolution(
        conn, normalized_name="gin", taxonomy_node_id=ids["gin"],
        source="alias", mapper_version="v1",
    )
    rows = conn.execute(
        "select taxonomy_node_id, mapper_source, mapper_version "
        "from recipe_ingredients where lower(trim(name)) = 'gin' order by id"
    ).fetchall()
    assert len(rows) == 2
    for r in rows:
        assert r == (ids["gin"], "alias", "v1")


def test_write_pending_marks_rows_pending_llm(fixture_taxonomy):
    conn, _ = fixture_taxonomy
    _seed_recipes_and_ingredients(conn)
    write_pending(conn, normalized_name="simple syrup", mapper_version="v1")
    row = conn.execute(
        "select taxonomy_node_id, mapper_source, mapper_version "
        "from recipe_ingredients where lower(trim(name)) = 'simple syrup'"
    ).fetchone()
    assert row == (None, "pending_llm", "v1")


def test_fetch_skips_already_mapped_at_current_version(fixture_taxonomy):
    conn, ids = fixture_taxonomy
    _seed_recipes_and_ingredients(conn)
    write_resolution(
        conn, normalized_name="gin", taxonomy_node_id=ids["gin"],
        source="alias", mapper_version="v1",
    )
    names = fetch_unique_pending_names(conn, mapper_version="v1")
    assert "gin" not in names
    assert sorted(names) == ["lemon juice", "simple syrup"]

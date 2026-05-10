"""DB-integration tests for park_attempted_names / unpark_failures.
Runs against TEST_DB_URL (the conftest fixture provides `db_conn`)."""

from __future__ import annotations

import pytest

from ingredients.mapping.db import (
    park_attempted_names, unpark_failures,
)


def _truncate(conn):
    conn.execute("truncate table recipe_ingredients, recipes restart identity cascade")
    conn.commit()


def _seed_recipe_ingredient(conn, *, name, mapper_source, mapper_version):
    """Insert a recipe + a single recipe_ingredients row at the requested
    state. Returns the recipe_ingredients id."""
    rec_id = conn.execute(
        """
        insert into recipes (source_url, site, name, jsonld, fetched_at)
        values (%s, 'test', %s, '{}'::jsonb, now())
        returning id
        """,
        (f"test://{name}/{mapper_version}/{mapper_source}", name),
    ).fetchone()[0]
    ri_id = conn.execute(
        """
        insert into recipe_ingredients
            (recipe_id, position, raw_text, name,
             parse_status, parser_version,
             mapper_source, mapper_version, mapper_at)
        values (%s, 0, %s, %s, 'parsed', 'v1', %s, %s, now())
        returning id
        """,
        (rec_id, name, name, mapper_source, mapper_version),
    ).fetchone()[0]
    conn.commit()
    return ri_id


def test_park_flips_pending_to_pending_tried(db_conn):
    """A row at mapper_source='pending_llm' for the given version flips
    to 'pending_llm_tried' when its name is in the parking list."""
    _truncate(db_conn)
    rid = _seed_recipe_ingredient(
        db_conn, name="lemon juice",
        mapper_source="pending_llm", mapper_version="v1",
    )

    n = park_attempted_names(
        db_conn, mapper_version="v1", names=["lemon juice"],
    )
    db_conn.commit()
    assert n == 1

    src = db_conn.execute(
        "select mapper_source from recipe_ingredients where id = %s", (rid,),
    ).fetchone()[0]
    assert src == "pending_llm_tried"


def test_park_skips_already_resolved(db_conn):
    """A row that has been moved off pending_llm (e.g. to 'llm' or
    'abstain') by the ingest is not touched by parking, even if its
    normalized name appears in the parking list."""
    _truncate(db_conn)
    rid = _seed_recipe_ingredient(
        db_conn, name="dry vermouth",
        mapper_source="llm", mapper_version="v1",
    )

    park_attempted_names(db_conn, mapper_version="v1", names=["dry vermouth"])
    db_conn.commit()

    src = db_conn.execute(
        "select mapper_source from recipe_ingredients where id = %s", (rid,),
    ).fetchone()[0]
    assert src == "llm"


def test_park_respects_version(db_conn):
    """A row at pending_llm but at a *different* mapper_version is not
    touched."""
    _truncate(db_conn)
    rid = _seed_recipe_ingredient(
        db_conn, name="campari",
        mapper_source="pending_llm", mapper_version="v0",
    )
    park_attempted_names(db_conn, mapper_version="v1", names=["campari"])
    db_conn.commit()
    src = db_conn.execute(
        "select mapper_source from recipe_ingredients where id = %s", (rid,),
    ).fetchone()[0]
    assert src == "pending_llm"


def test_park_handles_empty_names(db_conn):
    """Empty names list is a no-op, returns 0, does not touch the DB."""
    _truncate(db_conn)
    n = park_attempted_names(db_conn, mapper_version="v1", names=[])
    assert n == 0


def test_unpark_flips_back(db_conn):
    """unpark_failures flips pending_llm_tried rows at the given version
    back to pending_llm."""
    _truncate(db_conn)
    rid = _seed_recipe_ingredient(
        db_conn, name="orgeat",
        mapper_source="pending_llm_tried", mapper_version="v1",
    )
    n = unpark_failures(db_conn, mapper_version="v1")
    db_conn.commit()
    assert n == 1
    src = db_conn.execute(
        "select mapper_source from recipe_ingredients where id = %s", (rid,),
    ).fetchone()[0]
    assert src == "pending_llm"


def test_unpark_respects_version(db_conn):
    """unpark_failures does not touch rows at a different mapper_version."""
    _truncate(db_conn)
    rid = _seed_recipe_ingredient(
        db_conn, name="falernum",
        mapper_source="pending_llm_tried", mapper_version="v0",
    )
    n = unpark_failures(db_conn, mapper_version="v1")
    db_conn.commit()
    assert n == 0
    src = db_conn.execute(
        "select mapper_source from recipe_ingredients where id = %s", (rid,),
    ).fetchone()[0]
    assert src == "pending_llm_tried"


def test_unpark_with_limit(db_conn):
    """unpark_failures(limit=N) flips at most N rows."""
    _truncate(db_conn)
    for n in ("a-name", "b-name", "c-name"):
        _seed_recipe_ingredient(
            db_conn, name=n,
            mapper_source="pending_llm_tried", mapper_version="v1",
        )
    rc = unpark_failures(db_conn, mapper_version="v1", limit=2)
    db_conn.commit()
    assert rc == 2
    remaining = db_conn.execute(
        "select count(*) from recipe_ingredients "
        "where mapper_source = 'pending_llm_tried' and mapper_version = %s",
        ("v1",),
    ).fetchone()[0]
    assert remaining == 1

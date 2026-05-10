"""DB-integration tests for dedup park_attempted_names / unpark_failures.
Runs against TEST_DB_URL (the conftest fixture provides `db_conn`)."""

from __future__ import annotations

import pytest

from ingredients.dedup.db import (
    park_attempted_names, unpark_failures,
)


def _truncate(conn):
    conn.execute("truncate table recipe_ingredients, recipes restart identity cascade")
    conn.commit()


def _seed_recipe(conn, *, name, source, version):
    """Insert a recipes row at the requested canonical_name_source state.
    Returns the recipes id."""
    rec_id = conn.execute(
        """
        insert into recipes (source_url, site, name, jsonld, fetched_at,
                             canonical_name_source, normalizer_version,
                             normalized_at)
        values (%s, 'test', %s, '{}'::jsonb, now(), %s, %s, now())
        returning id
        """,
        (f"test://{name}/{version}/{source}", name, source, version),
    ).fetchone()[0]
    conn.commit()
    return rec_id


def test_park_flips_pending_to_pending_tried(db_conn):
    """A row at canonical_name_source='pending_llm' for the given version
    flips to 'pending_llm_tried' when its name is in the parking list."""
    _truncate(db_conn)
    rid = _seed_recipe(
        db_conn, name="Margarita",
        source="pending_llm", version="v1",
    )

    n = park_attempted_names(
        db_conn, normalizer_version="v1", names=["Margarita"],
    )
    db_conn.commit()
    assert n == 1

    src = db_conn.execute(
        "select canonical_name_source from recipes where id = %s", (rid,),
    ).fetchone()[0]
    assert src == "pending_llm_tried"


def test_park_skips_already_resolved(db_conn):
    """A row that has been moved off pending_llm (e.g. to 'llm' or
    'abstain') by the ingest is not touched by parking, even if its
    name appears in the parking list."""
    _truncate(db_conn)
    rid = _seed_recipe(
        db_conn, name="Old Fashioned",
        source="llm", version="v1",
    )

    park_attempted_names(db_conn, normalizer_version="v1", names=["Old Fashioned"])
    db_conn.commit()

    src = db_conn.execute(
        "select canonical_name_source from recipes where id = %s", (rid,),
    ).fetchone()[0]
    assert src == "llm"


def test_park_respects_version(db_conn):
    """A row at pending_llm but at a *different* normalizer_version is not
    touched."""
    _truncate(db_conn)
    rid = _seed_recipe(
        db_conn, name="Negroni",
        source="pending_llm", version="v0",
    )
    park_attempted_names(db_conn, normalizer_version="v1", names=["Negroni"])
    db_conn.commit()
    src = db_conn.execute(
        "select canonical_name_source from recipes where id = %s", (rid,),
    ).fetchone()[0]
    assert src == "pending_llm"


def test_park_handles_empty_names(db_conn):
    """Empty names list is a no-op, returns 0, does not touch the DB."""
    _truncate(db_conn)
    n = park_attempted_names(db_conn, normalizer_version="v1", names=[])
    assert n == 0


def test_unpark_flips_back(db_conn):
    """unpark_failures flips pending_llm_tried rows at the given version
    back to pending_llm."""
    _truncate(db_conn)
    rid = _seed_recipe(
        db_conn, name="Daiquiri",
        source="pending_llm_tried", version="v1",
    )
    n = unpark_failures(db_conn, normalizer_version="v1")
    db_conn.commit()
    assert n == 1
    src = db_conn.execute(
        "select canonical_name_source from recipes where id = %s", (rid,),
    ).fetchone()[0]
    assert src == "pending_llm"


def test_unpark_respects_version(db_conn):
    """unpark_failures does not touch rows at a different normalizer_version."""
    _truncate(db_conn)
    rid = _seed_recipe(
        db_conn, name="Gimlet",
        source="pending_llm_tried", version="v0",
    )
    n = unpark_failures(db_conn, normalizer_version="v1")
    db_conn.commit()
    assert n == 0
    src = db_conn.execute(
        "select canonical_name_source from recipes where id = %s", (rid,),
    ).fetchone()[0]
    assert src == "pending_llm_tried"


def test_unpark_with_limit(db_conn):
    """unpark_failures(limit=N) flips at most N rows."""
    _truncate(db_conn)
    for n in ("Sidecar", "Aviation", "Bee's Knees"):
        _seed_recipe(
            db_conn, name=n,
            source="pending_llm_tried", version="v1",
        )
    rc = unpark_failures(db_conn, normalizer_version="v1", limit=2)
    db_conn.commit()
    assert rc == 2
    remaining = db_conn.execute(
        "select count(*) from recipes "
        "where canonical_name_source = 'pending_llm_tried' and normalizer_version = %s",
        ("v1",),
    ).fetchone()[0]
    assert remaining == 1

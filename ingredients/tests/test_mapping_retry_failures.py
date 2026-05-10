"""Integration test for `map retry-failures`. Hits TEST_DB_URL via the
db_conn fixture; constructs argparse.Namespace by hand to bypass parser."""

from __future__ import annotations

import argparse
from unittest.mock import patch


def _truncate(conn):
    conn.execute("truncate table recipe_ingredients, recipes restart identity cascade")
    conn.commit()


def _seed_parked(conn, *, name, mapper_version):
    rec_id = conn.execute(
        """
        insert into recipes (source_url, site, name, jsonld, fetched_at)
        values (%s, 'test', %s, '{}'::jsonb, now()) returning id
        """,
        (f"test://{name}/{mapper_version}", name),
    ).fetchone()[0]
    conn.execute(
        """
        insert into recipe_ingredients
            (recipe_id, position, raw_text, name, parse_status,
             parser_version, mapper_source, mapper_version, mapper_at)
        values (%s, 0, %s, %s, 'parsed', 'v1', 'pending_llm_tried', %s, now())
        """,
        (rec_id, name, name, mapper_version),
    )
    conn.commit()


def test_retry_failures_unparks_at_current_version(db_conn, monkeypatch):
    from ingredients.cli import run_map_retry_failures
    from ingredients.mapping.mapper import MAPPER_VERSION

    _truncate(db_conn)
    _seed_parked(db_conn, name="pisco", mapper_version=MAPPER_VERSION)
    _seed_parked(db_conn, name="batavia arrack", mapper_version=MAPPER_VERSION)

    # Stub IngredientsDatabase to use the test connection.
    class _StubDB:
        def __init__(self):
            self.conn = db_conn
        def close(self):
            pass
    monkeypatch.setattr("ingredients.cli.IngredientsDatabase", _StubDB)

    args = argparse.Namespace(map_cmd="retry-failures", limit=None, yes=True)
    rc = run_map_retry_failures(args)
    assert rc == 0

    n_remaining = db_conn.execute(
        "select count(*) from recipe_ingredients "
        "where mapper_source = 'pending_llm_tried' and mapper_version = %s",
        (MAPPER_VERSION,),
    ).fetchone()[0]
    assert n_remaining == 0
    n_pending = db_conn.execute(
        "select count(*) from recipe_ingredients "
        "where mapper_source = 'pending_llm' and mapper_version = %s "
        "and name in ('pisco', 'batavia arrack')",
        (MAPPER_VERSION,),
    ).fetchone()[0]
    assert n_pending == 2


def test_retry_failures_empty_returns_zero(db_conn, monkeypatch):
    from ingredients.cli import run_map_retry_failures

    _truncate(db_conn)

    class _StubDB:
        def __init__(self):
            self.conn = db_conn
        def close(self):
            pass
    monkeypatch.setattr("ingredients.cli.IngredientsDatabase", _StubDB)

    args = argparse.Namespace(map_cmd="retry-failures", limit=None, yes=True)
    rc = run_map_retry_failures(args)
    assert rc == 0


def test_retry_failures_respects_limit(db_conn, monkeypatch):
    from ingredients.cli import run_map_retry_failures
    from ingredients.mapping.mapper import MAPPER_VERSION

    _truncate(db_conn)
    for n in ("a-rum", "b-rum", "c-rum"):
        _seed_parked(db_conn, name=n, mapper_version=MAPPER_VERSION)

    class _StubDB:
        def __init__(self):
            self.conn = db_conn
        def close(self):
            pass
    monkeypatch.setattr("ingredients.cli.IngredientsDatabase", _StubDB)

    args = argparse.Namespace(map_cmd="retry-failures", limit=2, yes=True)
    rc = run_map_retry_failures(args)
    assert rc == 0

    remaining = db_conn.execute(
        "select count(*) from recipe_ingredients "
        "where mapper_source = 'pending_llm_tried' and mapper_version = %s",
        (MAPPER_VERSION,),
    ).fetchone()[0]
    assert remaining == 1

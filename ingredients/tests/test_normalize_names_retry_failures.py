"""Integration test for `normalize-names retry-failures`. Hits TEST_DB_URL via
the db_conn fixture; constructs argparse.Namespace by hand to bypass parser."""

from __future__ import annotations

import argparse


def _truncate(conn):
    conn.execute("truncate table recipe_ingredients, recipes restart identity cascade")
    conn.commit()


def _seed_parked(conn, *, name, normalizer_version):
    conn.execute(
        """
        insert into recipes
            (source_url, site, name, jsonld, fetched_at,
             canonical_name_source, normalizer_version, normalized_at)
        values (%s, 'test', %s, '{}'::jsonb, now(),
                'pending_llm_tried', %s, now())
        """,
        (f"test://{name}/{normalizer_version}", name, normalizer_version),
    )
    conn.commit()


def test_retry_failures_unparks(db_conn, monkeypatch):
    from ingredients.cli import run_normalize_names_retry_failures
    from ingredients.dedup.version import NORMALIZER_VERSION

    _truncate(db_conn)
    _seed_parked(db_conn, name="garibaldi", normalizer_version=NORMALIZER_VERSION)
    _seed_parked(db_conn, name="americano", normalizer_version=NORMALIZER_VERSION)

    class _StubDB:
        def __init__(self):
            self.conn = db_conn
        def close(self):
            pass
    monkeypatch.setattr("ingredients.cli.IngredientsDatabase", _StubDB)

    args = argparse.Namespace(
        normalize_cmd="retry-failures", limit=None, yes=True,
    )
    rc = run_normalize_names_retry_failures(args)
    assert rc == 0

    n_remaining = db_conn.execute(
        "select count(*) from recipes "
        "where canonical_name_source = 'pending_llm_tried' "
        "and normalizer_version = %s",
        (NORMALIZER_VERSION,),
    ).fetchone()[0]
    assert n_remaining == 0

    n_pending = db_conn.execute(
        "select count(*) from recipes "
        "where canonical_name_source = 'pending_llm' "
        "and normalizer_version = %s "
        "and name in ('garibaldi', 'americano')",
        (NORMALIZER_VERSION,),
    ).fetchone()[0]
    assert n_pending == 2


def test_retry_failures_empty_returns_zero(db_conn, monkeypatch):
    from ingredients.cli import run_normalize_names_retry_failures

    _truncate(db_conn)

    class _StubDB:
        def __init__(self):
            self.conn = db_conn
        def close(self):
            pass
    monkeypatch.setattr("ingredients.cli.IngredientsDatabase", _StubDB)

    args = argparse.Namespace(
        normalize_cmd="retry-failures", limit=None, yes=True,
    )
    rc = run_normalize_names_retry_failures(args)
    assert rc == 0


def test_retry_failures_respects_limit(db_conn, monkeypatch):
    from ingredients.cli import run_normalize_names_retry_failures
    from ingredients.dedup.version import NORMALIZER_VERSION

    _truncate(db_conn)
    for n in ("a-tail", "b-tail", "c-tail"):
        _seed_parked(db_conn, name=n, normalizer_version=NORMALIZER_VERSION)

    class _StubDB:
        def __init__(self):
            self.conn = db_conn
        def close(self):
            pass
    monkeypatch.setattr("ingredients.cli.IngredientsDatabase", _StubDB)

    args = argparse.Namespace(
        normalize_cmd="retry-failures", limit=2, yes=True,
    )
    rc = run_normalize_names_retry_failures(args)
    assert rc == 0

    remaining = db_conn.execute(
        "select count(*) from recipes "
        "where canonical_name_source = 'pending_llm_tried' "
        "and normalizer_version = %s",
        (NORMALIZER_VERSION,),
    ).fetchone()[0]
    assert remaining == 1

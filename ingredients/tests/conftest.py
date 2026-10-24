"""Pytest configuration for spiritolo-ingredients.

DB-integration tests run against a throwaway SQLite database: a fresh file per
test under pytest's ``tmp_path`` (or in-memory), with the repo's migrations
applied by ``common.db.open_database``. There is no external database to set up
and nothing shared between tests, so the fixtures below need no truncation
ritual — each test starts from an empty, fully migrated schema.
"""
from __future__ import annotations

import os
import pathlib

import pytest

from common.db import Connection, open_database

# Defensive: nothing in the test suite may touch a real database file. Point the
# app/CLI default somewhere that cannot exist so an accidental fall-back fails
# loudly instead of writing into a developer's data directory.
os.environ["SPIRITOLO_DB"] = "/nonexistent/SPIRITOLO_DB_must_not_be_used_in_tests.db"


@pytest.fixture
def db_path(tmp_path: pathlib.Path) -> pathlib.Path:
    """Path of a fresh, not-yet-created SQLite file for this test."""
    return tmp_path / "test.db"


@pytest.fixture
def db_conn(db_path: pathlib.Path):
    """A migrated, audit-enabled connection to a fresh per-test database."""
    conn = open_database(db_path, actor=("system", None, "test"))
    yield conn
    conn.close()


@pytest.fixture
def conn_factory(db_path: pathlib.Path, db_conn: Connection):
    """Open additional connections to the same per-test database (for tests that
    exercise concurrent access or a second actor context)."""
    opened: list[Connection] = []

    def factory(**kwargs) -> Connection:
        c = open_database(db_path, migrate=False, **kwargs)
        opened.append(c)
        return c

    yield factory
    for c in opened:
        c.close()


@pytest.fixture
def fixture_taxonomy(db_conn: Connection):
    """Yield (conn, slug->id dict) with the taxonomy seeded from
    ingredients.mapping.eval_fixture."""
    from ingredients.mapping.eval_fixture import seed

    ids = seed(db_conn)
    return db_conn, ids


@pytest.fixture
def dedup_fixture(db_conn: Connection):
    """Seed the dedup fixture taxonomy + cocktail_aliases. Yields (conn, ids)."""
    from ingredients.dedup.eval_fixture import seed_dedup_fixture

    ids = seed_dedup_fixture(db_conn)
    return db_conn, ids

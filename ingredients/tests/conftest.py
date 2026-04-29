"""Pytest configuration for spiritolo-ingredients.

DB-integration tests run against ``TEST_DB_URL`` — a *separate* Postgres
database from ``SUPABASE_DB_URL`` — to avoid wiping the dev DB. The
session-scoped autouse fixture below auto-creates the test DB if missing
and applies any new ``supabase/migrations/*.sql`` files before tests run,
so there's no manual setup ritual.

Convention: ``TEST_DB_URL`` should point at a database named
``spiritolo_test`` (or similar) on the same local Postgres cluster as
``SUPABASE_DB_URL``. The conftest refuses to run if the two URLs are
equal or if the test URL points at the default ``postgres`` database.

If ``TEST_DB_URL`` isn't set, DB-integration tests skip; pure-Python
tests still run.
"""
from __future__ import annotations

import os
import pathlib
from urllib.parse import urlparse, urlunparse

import psycopg
import pytest
from dotenv import load_dotenv


load_dotenv(pathlib.Path(__file__).resolve().parent.parent.parent / ".env")

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
_MIGRATIONS_DIR = _REPO_ROOT / "supabase" / "migrations"


def _db_name(url: str) -> str:
    return urlparse(url).path.lstrip("/")


def _admin_url(test_url: str) -> str:
    """Same connection as ``test_url`` but addressed at the cluster's
    default ``postgres`` DB. Needed because ``CREATE DATABASE`` can't run
    inside a transaction or while connected to the target DB."""
    return urlunparse(urlparse(test_url)._replace(path="/postgres"))


def _validate_test_db_url() -> str | None:
    """Return ``TEST_DB_URL`` if set and safe; ``None`` to signal skip.

    Fails loudly (no skip) if the URL is set but unsafe — equal to
    ``SUPABASE_DB_URL``, pointing at the default ``postgres`` DB, or
    using a non-alphanumeric DB name we'd refuse to ``CREATE``.
    """
    test_url = os.environ.get("TEST_DB_URL")
    if not test_url:
        return None

    sup_url = os.environ.get("SUPABASE_DB_URL")
    if sup_url and test_url == sup_url:
        pytest.fail(
            "TEST_DB_URL must not equal SUPABASE_DB_URL — refuse to truncate "
            "the dev database. Configure a separate test DB.",
            pytrace=False,
        )

    name = _db_name(test_url)
    if name in ("", "postgres"):
        pytest.fail(
            f"TEST_DB_URL must point at a non-default database (got {name!r}); "
            "convention is `spiritolo_test` on the same local cluster.",
            pytrace=False,
        )
    if not name.replace("_", "").isalnum():
        pytest.fail(
            f"TEST_DB_URL database name {name!r} contains characters we won't "
            "quote into a CREATE DATABASE statement; pick a [A-Za-z0-9_] name.",
            pytrace=False,
        )
    return test_url


@pytest.fixture(scope="session")
def test_db_url() -> str:
    """Validated TEST_DB_URL. Tests requesting it fail when unset.

    DB-integration tests must fail loud rather than skip — silent skips
    hide gaps in coverage and let CI claim a green run that exercised
    nothing. Pure-Python tests don't take this fixture and are unaffected.
    """
    url = _validate_test_db_url()
    if url is None:
        pytest.fail(
            "TEST_DB_URL is not set. DB-integration tests require a separate "
            "test database; see CLAUDE.md for the one-line .env setup.",
            pytrace=False,
        )
    return url


@pytest.fixture(scope="session", autouse=True)
def _ensure_test_db_migrated() -> None:
    """Create the test DB if missing; apply any new migrations.

    Runs once per pytest session. Re-applies only migration files not yet
    recorded in the ``_test_db_migrations`` manifest table — so adding a
    new migration just causes the next test run to pick it up. Replacing
    or editing an existing migration is *not* detected; if you need a
    clean rebuild, drop the test DB and re-run pytest.
    """
    test_url = _validate_test_db_url()
    if test_url is None:
        return

    name = _db_name(test_url)

    with psycopg.connect(_admin_url(test_url), autocommit=True) as admin:
        if admin.execute(
            "select 1 from pg_database where datname = %s", (name,)
        ).fetchone() is None:
            admin.execute(f'create database "{name}"')

    with psycopg.connect(test_url, autocommit=True) as conn:
        conn.execute(
            """
            create table if not exists _test_db_migrations (
                filename text primary key,
                applied_at timestamptz not null default now()
            )
            """
        )
        applied = {
            row[0] for row in conn.execute(
                "select filename from _test_db_migrations"
            ).fetchall()
        }
        for path in sorted(_MIGRATIONS_DIR.glob("*.sql")):
            if path.name in applied:
                continue
            sql = path.read_text()
            with conn.transaction():
                conn.execute(sql)
                conn.execute(
                    "insert into _test_db_migrations (filename) values (%s)",
                    (path.name,),
                )


@pytest.fixture
def isolated_db(test_db_url: str):
    """Truncate ``recipes`` + ``recipe_ingredients`` in the test DB
    before and after the test; yield a connected ``IngredientsDatabase``.

    The fixture only ever connects to ``TEST_DB_URL``, never to
    ``SUPABASE_DB_URL``.
    """
    from ingredients.db import IngredientsDatabase

    db = IngredientsDatabase(db_url=test_db_url)
    db.conn.execute("truncate table recipe_ingredients cascade")
    db.conn.execute("truncate table recipes cascade")
    db.conn.commit()
    yield db
    db.conn.execute("truncate table recipe_ingredients cascade")
    db.conn.execute("truncate table recipes cascade")
    db.conn.commit()
    db.close()


@pytest.fixture
def db_conn(test_db_url: str):
    """Raw psycopg connection to the test DB. Closed after each test.

    Use this for schema-level assertions (information_schema queries) and
    other tests that don't need the IngredientsDatabase wrapper.
    """
    conn = psycopg.connect(test_db_url, autocommit=True)
    yield conn
    conn.close()


@pytest.fixture
def fixture_taxonomy(test_db_url: str):
    """Yield (psycopg conn, slug->id dict) with taxonomy_* truncated and
    seeded from ingredients.mapping.eval_fixture. Truncates on teardown."""
    from ingredients.mapping.eval_fixture import seed

    conn = psycopg.connect(test_db_url)
    ids = seed(conn)
    yield conn, ids
    conn.execute("truncate table taxonomy_aliases, taxonomy_edges, taxonomy_nodes restart identity cascade")
    conn.commit()
    conn.close()

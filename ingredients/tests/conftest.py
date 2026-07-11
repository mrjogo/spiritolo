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

# Capture the REAL dev DB URL before we clobber it below, so the safety checks
# in _validate_test_db_url can compare against it (otherwise they'd only ever
# see the sentinel and the "don't nuke the dev DB" guard would be dead).
_REAL_SUPABASE_DB_URL = os.environ.get("SUPABASE_DB_URL")

# Defensive: any test that accidentally connects via SUPABASE_DB_URL
# (e.g. SupabaseClient() with no explicit url) silently wipes the dev DB.
# Override with an invalid sentinel after .env loads so any such fall-back
# fails loudly. Tests that need a real Postgres must use TEST_DB_URL.
os.environ["SUPABASE_DB_URL"] = (
    "postgresql://invalid:invalid@127.0.0.1:1/SUPABASE_DB_URL_must_not_be_used_in_tests"
)

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
_MIGRATIONS_DIR = _REPO_ROOT / "supabase" / "migrations"


def _db_name(url: str) -> str:
    return urlparse(url).path.lstrip("/")


def _conn_target(url: str) -> tuple:
    """(host, port, dbname) — the physical database a URL addresses. Used to
    catch a TEST_DB_URL that points at the dev DB via a differently-spelled URL
    (different creds/params, same server + database)."""
    p = urlparse(url)
    return (p.hostname, p.port, p.path.lstrip("/"))


def _admin_url(test_url: str) -> str:
    """Same connection as ``test_url`` but addressed at the cluster's
    default ``postgres`` DB. Needed because ``CREATE DATABASE`` can't run
    inside a transaction or while connected to the target DB."""
    return urlunparse(urlparse(test_url)._replace(path="/postgres"))


def _validate_test_db_url() -> str | None:
    """Return ``TEST_DB_URL`` if set and safe; ``None`` to signal skip.

    The session wipes this database wholesale (every public table is truncated),
    so the checks here are load-bearing safety, not cosmetics. Fails loudly (no
    skip) if the URL is set but unsafe — the same physical database as the dev
    ``SUPABASE_DB_URL``, the default ``postgres`` DB, a name we can't safely
    quote, or a name that isn't marked as a disposable test DB.
    """
    test_url = os.environ.get("TEST_DB_URL")
    if not test_url:
        return None

    # Never operate on the dev/staging database. Compare the physical target
    # (host, port, dbname), so a differently-spelled URL for the same DB is
    # still caught. (`_REAL_SUPABASE_DB_URL` is captured before the sentinel
    # override, so this actually compares against the real dev URL.)
    if _REAL_SUPABASE_DB_URL and _conn_target(test_url) == _conn_target(_REAL_SUPABASE_DB_URL):
        pytest.fail(
            "TEST_DB_URL points at the same database as SUPABASE_DB_URL — refuse "
            "to truncate the dev database. Configure a separate test DB.",
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
    # Hard stop for the wholesale truncate: the database name must mark it as a
    # throwaway test DB. Cheap insurance that a misconfigured TEST_DB_URL can't
    # nuke a real database whose name happens to pass the checks above.
    if "test" not in name.lower():
        pytest.fail(
            f"TEST_DB_URL database {name!r} is not marked as a test DB (its name "
            "must contain 'test') — the suite truncates it wholesale each run. "
            "Use e.g. `spiritolo_test`.",
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
    """Create the test DB if missing; apply any new migrations; truncate all
    data so each session starts clean.

    Runs once per pytest session. Re-applies only migration files not yet
    recorded in the ``_test_db_migrations`` manifest table — so adding a
    new migration just causes the next test run to pick it up. Then truncates
    every public table (except the migration ledger) with RESTART IDENTITY, so
    state cannot accumulate across runs of the persistent test DB.

    Replacing or editing an existing migration's *SQL* is still not detected
    (only its data is wiped, not its schema); for a schema rebuild after editing
    a migration in place, drop the test DB and re-run pytest.
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
        # Stub the Supabase auth surface our migrations reference. The
        # real auth schema is provisioned by GoTrue (cloud) or by
        # `supabase start` (host); the test DB is bare Postgres, so we
        # create just enough for FK references and `auth.uid()` calls
        # to compile. Tests don't exercise actual auth flows.
        conn.execute("create schema if not exists auth")
        conn.execute(
            """
            create table if not exists auth.users (
                id uuid primary key default gen_random_uuid(),
                email text
            )
            """
        )
        conn.execute(
            """
            create or replace function auth.uid() returns uuid
            language sql stable as 'select null::uuid'
            """
        )
        # `extensions` schema exists by default on Supabase; create it
        # locally so migrations that move extensions into it
        # (`alter extension ... set schema extensions`) succeed.
        conn.execute("create schema if not exists extensions")

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

        # Start every session from a clean slate. The test DB is persistent
        # (created once, migrations applied incrementally), so without this,
        # data written by one run leaks into the next — a fixture that inserts
        # explicit ids then collides with leftovers, etc. Truncating all public
        # tables (except the migration ledger) with RESTART IDENTITY resets both
        # rows and sequences, so runs can't accumulate state. Per-test fixtures
        # still handle within-run isolation.
        #
        # Belt-and-suspenders: re-assert we're on a disposable test DB right
        # before the wholesale truncate, independent of _validate_test_db_url,
        # so this destructive op can never touch the dev/staging database.
        if "test" not in name.lower() or name == "postgres":
            pytest.fail(
                f"refusing to truncate {name!r}: not a disposable test DB", pytrace=False
            )
        data_tables = [
            row[0] for row in conn.execute(
                "select tablename from pg_tables "
                "where schemaname = 'public' and tablename <> '_test_db_migrations'"
            ).fetchall()
        ]
        if data_tables:
            conn.execute(
                "truncate table "
                + ", ".join(f'public."{t}"' for t in data_tables)
                + " restart identity cascade"
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


@pytest.fixture
def dedup_fixture(db_conn):
    """Seed the dedup fixture taxonomy + cocktail_aliases into TEST_DB_URL.
    Truncates recipes + cocktail_aliases before seeding so each test starts
    from a known state regardless of prior runs. Yields (conn, ids)."""
    from ingredients.dedup.eval_fixture import seed_dedup_fixture
    db_conn.execute("truncate table recipes cascade")
    db_conn.execute("truncate table cocktail_aliases restart identity cascade")
    ids = seed_dedup_fixture(db_conn)
    return db_conn, ids

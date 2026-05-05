"""Test fixtures for the uploader.

Spins up two ephemeral databases on the local Postgres cluster derived
from TEST_DB_URL. They simulate the uploader's "local" and "staging"
inputs end-to-end.

If TEST_DB_URL is unset, DB-backed tests skip cleanly.
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


def _base_url() -> str | None:
    return os.environ.get("TEST_DB_URL")


def _db_name(url: str) -> str:
    return urlparse(url).path.lstrip("/")


def _with_db(url: str, name: str) -> str:
    return urlunparse(urlparse(url)._replace(path=f"/{name}"))


def _admin_url(url: str) -> str:
    return _with_db(url, "postgres")


def _ensure_db(admin_url: str, name: str) -> None:
    with psycopg.connect(admin_url, autocommit=True) as conn:
        existed = conn.execute(
            "select 1 from pg_database where datname = %s", (name,)
        ).fetchone() is not None
        if existed:
            # Drop and recreate to guarantee clean state per session.
            # Disconnect any clients first.
            conn.execute(
                "select pg_terminate_backend(pid) from pg_stat_activity "
                "where datname = %s and pid <> pg_backend_pid()",
                (name,),
            )
            conn.execute(f'drop database "{name}"')
        conn.execute(f'create database "{name}"')


def _bootstrap_supabase_stubs(conn: psycopg.Connection) -> None:
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
        "create or replace function auth.uid() returns uuid "
        "language sql stable as 'select null::uuid'"
    )
    conn.execute("create schema if not exists extensions")
    conn.execute(
        "create schema if not exists supabase_migrations"
    )
    conn.execute(
        """
        create table if not exists
            supabase_migrations.schema_migrations (
            version text primary key,
            name text,
            statements text[]
        )
        """
    )


def _apply_migrations(url: str) -> list[str]:
    versions: list[str] = []
    with psycopg.connect(url, autocommit=True) as conn:
        _bootstrap_supabase_stubs(conn)
        for path in sorted(_MIGRATIONS_DIR.glob("*.sql")):
            sql = path.read_text()
            with conn.transaction():
                conn.execute(sql)
                version = path.stem.split("_", 1)[0]
                conn.execute(
                    "insert into supabase_migrations.schema_migrations "
                    "(version, name) values (%s, %s) on conflict do nothing",
                    (version, path.stem),
                )
                versions.append(version)
    return versions


@pytest.fixture(scope="session")
def db_pair():
    """Yield (local_url, staging_url) for two freshly-migrated DBs.
    Skips the test if TEST_DB_URL is unset."""
    base = _base_url()
    if not base:
        pytest.skip("TEST_DB_URL not set; skipping DB-backed test")

    base_name = _db_name(base)
    local_name = f"{base_name}_upload_local"
    staging_name = f"{base_name}_upload_staging"

    admin = _admin_url(base)
    _ensure_db(admin, local_name)
    _ensure_db(admin, staging_name)

    local_url = _with_db(base, local_name)
    staging_url = _with_db(base, staging_name)
    _apply_migrations(local_url)
    _apply_migrations(staging_url)

    yield local_url, staging_url


@pytest.fixture
def fresh_db_pair(db_pair):
    """Truncate every owned table in both DBs before yielding."""
    from upload_to_staging.tables import OWNED_TABLES
    local_url, staging_url = db_pair
    table_list = ", ".join(t.name for t in OWNED_TABLES)
    for url in (local_url, staging_url):
        with psycopg.connect(url, autocommit=True) as conn:
            conn.execute(f"truncate {table_list} restart identity cascade")
    yield local_url, staging_url

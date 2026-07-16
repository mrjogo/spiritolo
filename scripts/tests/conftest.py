"""Fixtures for the pages-migration tooling tests.

``pg_conn`` connects to a throwaway Postgres derived from ``TEST_DB_URL``
(database ``<base>_scripts``) with the ``pages`` migration applied; DB-backed
tests skip cleanly when ``TEST_DB_URL`` is unset. ``sqlite_pages`` is an
in-memory SQLite carrying the scraper's ``pages`` schema.
"""
from __future__ import annotations

import os
import pathlib
import sqlite3
from urllib.parse import urlparse, urlunparse

import psycopg
import pytest
from dotenv import load_dotenv

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
load_dotenv(_REPO_ROOT / ".env")

# The pages table, then the rename that gives it its current column name —
# applied in order so the scripts test DB matches production's `pages`
# (corpus_key, not r2_key). Extend this if a later migration reshapes `pages`.
_PAGES_MIGRATIONS = (
    _REPO_ROOT / "supabase" / "migrations" / "20260715090000_pages.sql",
    _REPO_ROOT / "supabase" / "migrations"
    / "20260722090000_rename_pages_r2_key_to_corpus_key.sql",
)

# Defensive: any code path that falls back to SUPABASE_DB_URL must fail loudly
# rather than touch the dev DB. Mirrors ingredients/tests/conftest.py.
os.environ["SUPABASE_DB_URL"] = (
    "postgresql://invalid:invalid@127.0.0.1:1/SUPABASE_DB_URL_must_not_be_used_in_tests"
)

# The scraper's SQLite pages schema (scraper/src/scraper/db.py).
_SQLITE_PAGES_DDL = """
create table pages (
    id integer primary key autoincrement,
    site text not null,
    url text not null unique,
    status text not null default 'pending',
    content_type text,
    sitemap_source text,
    attempts integer not null default 0,
    discovered_at text not null,
    fetched_at text,
    fetch_error text,
    html_path text,
    disabled_reason text
)
"""


def _scripts_db_url() -> str | None:
    base = os.environ.get("TEST_DB_URL")
    if not base:
        return None
    p = urlparse(base)
    return urlunparse(p._replace(path=f"/{p.path.lstrip('/')}_scripts"))


@pytest.fixture(scope="session")
def _scripts_db() -> str:
    url = _scripts_db_url()
    if not url:
        pytest.skip("TEST_DB_URL not set; DB-integration tests skip")
    name = urlparse(url).path.lstrip("/")
    if "test" not in name.lower() or name == "postgres":
        pytest.fail(f"refusing non-test DB {name!r}", pytrace=False)
    admin = urlunparse(urlparse(url)._replace(path="/postgres"))
    with psycopg.connect(admin, autocommit=True) as conn:
        if not conn.execute(
            "select 1 from pg_database where datname = %s", (name,)
        ).fetchone():
            conn.execute(f'create database "{name}"')
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("drop table if exists pages cascade")
        for migration in _PAGES_MIGRATIONS:
            conn.execute(migration.read_text())
    return url


@pytest.fixture
def pg_conn(_scripts_db):
    conn = psycopg.connect(_scripts_db, autocommit=True)
    conn.execute("truncate table pages restart identity cascade")
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture
def sqlite_pages():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(_SQLITE_PAGES_DDL)
    yield conn
    conn.close()

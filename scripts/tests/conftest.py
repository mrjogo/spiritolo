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

_PAGES_MIGRATION = _REPO_ROOT / "supabase" / "migrations" / "20260715090000_pages.sql"

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
        conn.execute(_PAGES_MIGRATION.read_text())
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

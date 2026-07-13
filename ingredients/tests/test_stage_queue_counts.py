"""stage_queue_counts(): real per-stage content-queue depth.

Covers the reference table (stage_queue_versions — pinned against the live
Python version constants so a bump can't silently drift the SQL mirror out
of sync), the admin gate, and the NOT-EXISTS qualifying predicate for both a
`pages`-backed stage (extract) and a `recipes`-backed stage (parse/map/
convert/cluster/export all qualify every row, gated only by the run itself).

Note on the migration's seed rows: the auto-migrate conftest TRUNCATEs every
public table immediately after applying migrations, every session (see
test_stage_config.py), so the DB tests below can never observe the
migration's INSERT surviving into a test and re-seed stage_queue_versions
themselves. The seed values are instead pinned by a separate, non-DB test
that reads the migration file's text directly.

Runs against TEST_DB_URL (skips-loud if unset); the ingredients conftest
auto-applies the new migration before these run.
"""
from __future__ import annotations

import os
import re
import uuid
from pathlib import Path

import psycopg
import pytest

pytestmark_db = pytest.mark.skipif(
    os.environ.get("TEST_DB_URL") is None,
    reason="TEST_DB_URL not set; DB-integration tests skip",
)

_MIGRATION = (
    Path(__file__).resolve().parent.parent.parent
    / "supabase" / "migrations" / "20260721090000_stage_queue_counts.sql"
)


def _become(conn: psycopg.Connection, *, admin: bool) -> uuid.UUID:
    uid = uuid.uuid4()
    conn.execute("insert into auth.users (id, email) values (%s, %s)", (uid, f"{uid}@test"))
    conn.execute("update profiles set is_admin = %s where id = %s", (admin, uid))
    conn.execute(
        f"create or replace function auth.uid() returns uuid "
        f"language sql stable as $$ select '{uid}'::uuid $$"
    )
    conn.commit()
    return uid


# ---------------------------------------------------------------------------
# Seed values — pinned from the migration text itself (no DB needed; the
# auto-migrate conftest's clean-slate TRUNCATE means the DB tests below
# never see the seed rows survive into a test).
# ---------------------------------------------------------------------------

def test_migration_seeds_match_live_python_version_constants():
    from ingredients.dedup.version import DEDUP_VERSION
    from ingredients.pipeline.stages.extract import EXTRACTOR_VERSION
    from ingredients.pipeline.stages.map import MAPPER_VERSION
    from ingredients.parser import PARSER_VERSION
    from ingredients.recipegf.version import CONVERTER_VERSION

    sql = _MIGRATION.read_text()
    seeded = {
        stage: version
        for stage, version, _table in re.findall(
            r"\('([\w-]+)',\s*'([\w.]+)',\s*'(\w+)'\)", sql,
        )
    }
    assert seeded == {
        "extract": EXTRACTOR_VERSION,
        "parse": PARSER_VERSION,
        "map": MAPPER_VERSION,
        "convert": CONVERTER_VERSION,
        "cluster": DEDUP_VERSION,
        "export": CONVERTER_VERSION,
    }


# ---------------------------------------------------------------------------
# Shape + boundary — against TEST_DB_URL (post-truncate, so self-seeding).
# ---------------------------------------------------------------------------

@pytest.fixture
def clean(db_conn):
    db_conn.execute("truncate table pages restart identity cascade")
    db_conn.execute("truncate table recipes restart identity cascade")
    db_conn.execute("truncate table stage_runs restart identity cascade")
    db_conn.execute("truncate table stage_queue_versions restart identity cascade")
    db_conn.execute("delete from profiles")
    db_conn.execute("delete from auth.users")
    db_conn.execute(
        "insert into stage_queue_versions (stage, version, content_table) values "
        "('extract', 'v1', 'pages'), ('parse', 'v10', 'recipes'), "
        "('export', 'v1', 'recipes')"
    )
    yield db_conn
    db_conn.execute("truncate table pages restart identity cascade")
    db_conn.execute("truncate table recipes restart identity cascade")
    db_conn.execute("truncate table stage_runs restart identity cascade")
    db_conn.execute("truncate table stage_queue_versions restart identity cascade")
    db_conn.execute("delete from profiles")
    db_conn.execute("delete from auth.users")


def _insert_recipe(conn, source_url: str) -> int:
    return conn.execute(
        "insert into recipes (source_url, site, source) values (%s, 'ex', '{}'::jsonb) "
        "returning id",
        (source_url,),
    ).fetchone()[0]


def _insert_page(conn, url: str, *, content_type: str | None, r2_key: str | None) -> int:
    return conn.execute(
        "insert into pages (url, site, content_type, r2_key) values (%s, 'ex', %s, %s) "
        "returning id",
        (url, content_type, r2_key),
    ).fetchone()[0]


def _insert_run(conn, entity_type: str, entity_id: int, stage: str, version: str) -> None:
    conn.execute(
        "insert into stage_runs (entity_type, entity_id, stage, version, outcome, method) "
        "values (%s, %s, %s, %s, 'resolved', 'deterministic')",
        (entity_type, entity_id, stage, version),
    )


@pytestmark_db
def test_rejects_anonymous(clean):
    conn = clean
    conn.execute(
        "create or replace function auth.uid() returns uuid "
        "language sql stable as $$ select null::uuid $$"
    )
    conn.commit()
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute("select * from stage_queue_counts()")


@pytestmark_db
def test_rejects_non_admin(clean):
    _become(clean, admin=False)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        clean.execute("select * from stage_queue_counts()")


@pytestmark_db
def test_recipes_backed_stage_counts_rows_with_no_run_at_current_version(clean):
    conn = clean
    _become(conn, admin=True)
    r1 = _insert_recipe(conn, "https://ex.test/1")
    r2 = _insert_recipe(conn, "https://ex.test/2")
    _insert_recipe(conn, "https://ex.test/3")
    # r1 already parsed at the current version -> drops off the queue.
    _insert_run(conn, "recipe", r1, "parse", "v10")
    # r2 has a run, but at a stale version -> still queued.
    _insert_run(conn, "recipe", r2, "parse", "v9")
    conn.commit()

    rows = dict(conn.execute("select stage, queue_depth from stage_queue_counts()").fetchall())
    assert rows["parse"] == 2  # r2 (stale version) + r3 (never run)


@pytestmark_db
def test_pages_backed_stage_requires_recipe_content_type_and_corpus_key(clean):
    conn = clean
    _become(conn, admin=True)
    _insert_page(conn, "https://ex.test/a", content_type="likely_drink_recipe", r2_key="k1")
    _insert_page(conn, "https://ex.test/b", content_type="confirmed_drink", r2_key=None)
    _insert_page(conn, "https://ex.test/c", content_type="likely_drink_article", r2_key="k3")
    conn.commit()

    rows = dict(conn.execute("select stage, queue_depth from stage_queue_counts()").fetchall())
    # Only the classified-as-recipe page with a corpus key qualifies.
    assert rows["extract"] == 1


@pytestmark_db
def test_untracked_stage_is_omitted_not_zero(clean):
    conn = clean
    _become(conn, admin=True)
    conn.commit()

    rows = dict(conn.execute("select stage, queue_depth from stage_queue_counts()").fetchall())
    assert "discover" not in rows
    assert "classify" not in rows
    assert "fetch" not in rows
    assert "role" not in rows
    # Configured stages with no qualifying content are explicitly zero, not omitted.
    assert rows["extract"] == 0
    assert rows["parse"] == 0
    assert rows["export"] == 0


@pytestmark_db
def test_recipes_backed_stage_is_zero_when_fully_caught_up(clean):
    conn = clean
    _become(conn, admin=True)
    r1 = _insert_recipe(conn, "https://ex.test/only")
    _insert_run(conn, "recipe", r1, "export", "v1")
    conn.commit()

    rows = dict(conn.execute("select stage, queue_depth from stage_queue_counts()").fetchall())
    assert rows["export"] == 0

"""Actor-derivation tests for the audit log.

The whole point of the audit log is the human-vs-worker-vs-system
distinction, and it must fall out of ``auth.uid()`` + the ``app.job_id`` /
``app.source`` GUCs with no bolted-on side channel:

- worker  → no JWT, ``SET LOCAL app.job_id`` set  → actor_kind='worker'
- human   → user JWT (auth.uid non-null)          → actor_kind='human'
- system  → neither                               → actor_kind='system'

Plus: INSERT/UPDATE/DELETE all captured with the right op + before/after.
Runs against ``TEST_DB_URL``.
"""
from __future__ import annotations

import os
import uuid

import psycopg
import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("TEST_DB_URL") is None,
    reason="TEST_DB_URL not set; DB-integration tests skip",
)

_COLS = ["op", "actor_kind", "actor_id", "source", "before", "after", "changed_keys"]


def _latest_audit(conn, table_name: str, pk) -> dict | None:
    r = conn.execute(
        f"select {', '.join(_COLS)} from audit.log "
        "where table_name = %s and pk = %s order by ts desc, id desc limit 1",
        (table_name, str(pk)),
    ).fetchone()
    return dict(zip(_COLS, r)) if r else None


@pytest.fixture
def clean(db_conn):
    """Reset auth.uid() to the null stub, empty audit.log + taxonomy_nodes so
    each test starts from a known state. auth.uid()=null is the default a
    worker/system path relies on; the human test rewires it via ``as_user``."""
    db_conn.execute(
        "create or replace function auth.uid() returns uuid "
        "language sql stable as $$ select null::uuid $$"
    )
    db_conn.execute("truncate table audit.log restart identity")
    db_conn.execute("delete from taxonomy_nodes")
    return db_conn


@pytest.fixture
def as_user(db_conn):
    """Rewire auth.uid() to a supplied uuid (simulating a user JWT); restore
    the null stub on teardown so later worker/system tests see auth.uid=null."""
    def _set(uid: str) -> None:
        db_conn.execute(
            f"create or replace function auth.uid() returns uuid "
            f"language sql stable as $$ select '{uid}'::uuid $$"
        )
    yield _set
    db_conn.execute(
        "create or replace function auth.uid() returns uuid "
        "language sql stable as $$ select null::uuid $$"
    )


def _insert_node(conn, slug: str = "gin", name: str = "Gin") -> int:
    return conn.execute(
        "insert into taxonomy_nodes (slug, display_name) values (%s, %s) returning id",
        (slug, name),
    ).fetchone()[0]


# ---------------------------------------------------------------------------
# worker / human / system
# ---------------------------------------------------------------------------

def test_worker_actor_from_app_job_id(clean):
    conn = clean
    nid = _insert_node(conn)
    conn.execute("truncate table audit.log restart identity")  # drop the insert row

    with conn.transaction():
        conn.execute("set local app.job_id = '42'")
        conn.execute("set local app.source = 'job:parse'")
        conn.execute(
            "update taxonomy_nodes set display_name = 'Gin 2' where id = %s", (nid,)
        )

    row = _latest_audit(conn, "taxonomy_nodes", nid)
    assert row is not None
    assert row["op"] == "U"
    assert row["actor_kind"] == "worker"
    assert row["actor_id"] == "42"
    assert row["source"] == "job:parse"


def test_human_actor_from_auth_uid(clean, as_user):
    conn = clean
    nid = _insert_node(conn)
    conn.execute("truncate table audit.log restart identity")

    uid = str(uuid.uuid4())
    as_user(uid)
    with conn.transaction():
        conn.execute("set local app.source = 'manual-ui-edit'")
        conn.execute(
            "update taxonomy_nodes set display_name = 'Edited' where id = %s", (nid,)
        )

    row = _latest_audit(conn, "taxonomy_nodes", nid)
    assert row is not None
    assert row["actor_kind"] == "human"
    assert row["actor_id"] == uid
    assert row["source"] == "manual-ui-edit"


def test_system_actor_when_no_context(clean):
    conn = clean
    # Bare autocommit statement: no JWT, no app.job_id GUC (migration/reaper/seed).
    nid = _insert_node(conn, slug="rum", name="Rum")

    row = _latest_audit(conn, "taxonomy_nodes", nid)
    assert row is not None
    assert row["op"] == "I"
    assert row["actor_kind"] == "system"
    assert row["actor_id"] is None
    assert row["source"]  # NOT NULL — coalesced to 'unknown' when app.source unset


# ---------------------------------------------------------------------------
# insert / delete capture
# ---------------------------------------------------------------------------

def test_insert_and_delete_captured(clean):
    conn = clean
    nid = _insert_node(conn, slug="vodka", name="Vodka")

    ins = _latest_audit(conn, "taxonomy_nodes", nid)
    assert ins["op"] == "I"
    assert ins["before"] is None
    assert ins["after"] is not None and ins["after"]["slug"] == "vodka"

    conn.execute("delete from taxonomy_nodes where id = %s", (nid,))

    dele = _latest_audit(conn, "taxonomy_nodes", nid)
    assert dele["op"] == "D"
    assert dele["before"] is not None and dele["before"]["slug"] == "vodka"
    assert dele["after"] is None

"""changed_keys + single-writer tests for the audit log.

- ``changed_keys`` lists only the keys whose value actually changed (jsonb
  is-distinct-from), not a stored full-diff blob.
- The trigger is the SOLE audit writer: a hand-SQL UPDATE, a worker UPDATE
  (app.job_id set via actor_context.set_job_context), and an admin-RPC UPDATE
  (auth.uid set) each produce EXACTLY ONE audit row with the correct
  actor_kind — no path double-logs.

Runs against ``TEST_DB_URL``.
"""
from __future__ import annotations

import os
import uuid

import psycopg
import pytest

from ingredients.worker.actor_context import set_job_context

pytestmark = pytest.mark.skipif(
    os.environ.get("TEST_DB_URL") is None,
    reason="TEST_DB_URL not set; DB-integration tests skip",
)


def _audit_count(conn, table_name: str, pk) -> int:
    return conn.execute(
        "select count(*) from audit.log where table_name = %s and pk = %s",
        (table_name, str(pk)),
    ).fetchone()[0]


def _latest_kind(conn, table_name: str, pk) -> str:
    return conn.execute(
        "select actor_kind from audit.log "
        "where table_name = %s and pk = %s order by ts desc, id desc limit 1",
        (table_name, str(pk)),
    ).fetchone()[0]


@pytest.fixture
def clean(db_conn):
    db_conn.execute(
        "create or replace function auth.uid() returns uuid "
        "language sql stable as $$ select null::uuid $$"
    )
    db_conn.execute("truncate table audit.log restart identity")
    db_conn.execute("delete from taxonomy_nodes")
    db_conn.execute("delete from profiles")
    db_conn.execute("delete from auth.users")
    return db_conn


def _insert_node(conn, slug: str = "gin", name: str = "Gin") -> int:
    nid = conn.execute(
        "insert into taxonomy_nodes (slug, display_name) values (%s, %s) returning id",
        (slug, name),
    ).fetchone()[0]
    return nid


# ---------------------------------------------------------------------------
# changed_keys
# ---------------------------------------------------------------------------

def test_changed_keys_on_update(clean):
    conn = clean
    nid = _insert_node(conn)
    conn.execute("truncate table audit.log restart identity")

    # Separate (autocommit) txn so now() advances → the set_updated_at BEFORE
    # trigger bumps updated_at, and only display_name + updated_at differ.
    conn.execute(
        "update taxonomy_nodes set display_name = 'Genever' where id = %s", (nid,)
    )

    row = conn.execute(
        "select op, changed_keys from audit.log "
        "where table_name = 'taxonomy_nodes' and pk = %s order by ts desc limit 1",
        (str(nid),),
    ).fetchone()
    assert row[0] == "U"
    # Only the keys whose value is distinct — slug/created_at/id untouched.
    assert set(row[1]) == {"display_name", "updated_at"}, row[1]


# ---------------------------------------------------------------------------
# single writer across all three paths
# ---------------------------------------------------------------------------

def test_single_writer_all_paths(clean):
    conn = clean
    nid = _insert_node(conn)

    # --- 1. hand-SQL UPDATE: no context → system, exactly one row.
    conn.execute("truncate table audit.log restart identity")
    conn.execute(
        "update taxonomy_nodes set display_name = 'Hand' where id = %s", (nid,)
    )
    assert _audit_count(conn, "taxonomy_nodes", nid) == 1
    assert _latest_kind(conn, "taxonomy_nodes", nid) == "system"

    # --- 2. worker UPDATE: app.job_id set via set_job_context → worker, one row.
    conn.execute("truncate table audit.log restart identity")
    with conn.transaction():
        set_job_context(conn, 42, "job:map")
        conn.execute(
            "update taxonomy_nodes set display_name = 'Worker' where id = %s", (nid,)
        )
    assert _audit_count(conn, "taxonomy_nodes", nid) == 1
    kind = _latest_kind(conn, "taxonomy_nodes", nid)
    assert kind == "worker"

    # --- 3. admin-RPC UPDATE: runs under a user JWT → human, one row.
    uid = uuid.uuid4()
    conn.execute("insert into auth.users (id, email) values (%s, %s)", (uid, f"{uid}@t"))
    conn.execute("update profiles set is_admin = true where id = %s", (uid,))
    conn.execute(
        f"create or replace function auth.uid() returns uuid "
        f"language sql stable as $$ select '{uid}'::uuid $$"
    )
    conn.execute("truncate table audit.log restart identity")
    with conn.transaction():
        conn.execute("set local app.source = 'manual-ui-edit'")
        conn.execute(
            "select update_taxonomy_node(%s, %s::jsonb)",
            (nid, '{"display_name": "Rpc"}'),
        )
    assert _audit_count(conn, "taxonomy_nodes", nid) == 1
    assert _latest_kind(conn, "taxonomy_nodes", nid) == "human"

    # Restore the null stub so ordering can't leak this uid into later tests.
    conn.execute(
        "create or replace function auth.uid() returns uuid "
        "language sql stable as $$ select null::uuid $$"
    )

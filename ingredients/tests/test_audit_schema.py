"""Constraint + RLS + trigger-attachment tests for the audit log.

Each test here asserts something the DDL does not already state on its own:
that the op / actor_kind domains are actually enforced, that the log is
admin-read-only with no write policy (so no client role can forge history),
that the generic ``audit.log_change`` trigger is attached to exactly the
curated tables that exist today, and that composite-PK reference tables are
deliberately NOT row-audited (node-level audit is the meaningful unit).

Deliberately absent: column-name/type and index-presence assertions. Those
restate the migration, so they can only fail when the schema is changed on
purpose — at which point they are rewritten to match and have taught nothing.
Payload behaviour lives in test_audit_payload_shape.py.

Runs against ``TEST_DB_URL`` (skips-loud if unset; the migrations conftest
auto-applies the new ``*.sql`` files before these run).
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


def _audited_tables(conn) -> set[str]:
    """Bare table names carrying the audit.log_change AFTER trigger."""
    return {
        r[0].split(".")[-1]
        for r in conn.execute(
            "select t.tgrelid::regclass::text from pg_trigger t "
            "join pg_proc p on p.oid = t.tgfoid "
            "join pg_namespace n on n.oid = p.pronamespace "
            "where p.proname = 'log_change' and n.nspname = 'audit' "
            "and not t.tgisinternal"
        ).fetchall()
    }


# ---------------------------------------------------------------------------
# audit.log shape
# ---------------------------------------------------------------------------

def test_audit_log_rejects_ops_and_actor_kinds_outside_their_domains(db_conn):
    """Every consumer switches exhaustively on `op` and `actor_kind` — the
    /ops browser's op labels and actor pills, and the reconstruction walk in
    test_audit_payload_shape.py. The CHECKs are what stop a future writer from
    inventing a fourth value that those consumers would silently mishandle."""
    with pytest.raises(psycopg.errors.CheckViolation):
        db_conn.execute(
            "insert into audit.log (table_name, pk, op, actor_kind, source) "
            "values ('taxonomy_nodes', '1', 'X', 'worker', 'job:map')"
        )
    with pytest.raises(psycopg.errors.CheckViolation):
        db_conn.execute(
            "insert into audit.log (table_name, pk, op, actor_kind, source) "
            "values ('taxonomy_nodes', '1', 'U', 'robot', 'job:map')"
        )


# ---------------------------------------------------------------------------
# RLS: admin read only, no write policy (append is trigger-only)
# ---------------------------------------------------------------------------

def test_audit_log_rls_admin_read_only(db_conn):
    # RLS enabled.
    assert db_conn.execute(
        "select relrowsecurity from pg_class where oid = 'audit.log'::regclass"
    ).fetchone()[0] is True

    pols = db_conn.execute(
        "select cmd, qual from pg_policies "
        "where schemaname = 'audit' and tablename = 'log'"
    ).fetchall()
    # Exactly one policy: SELECT gated on is_admin(). No write policy exists —
    # the trigger (SECURITY DEFINER) + service_role (BYPASSRLS) are the only
    # writers, so no client role can forge or mutate history.
    assert [p[0] for p in pols] == ["SELECT"], f"expected one SELECT policy, got {pols}"
    assert "is_admin" in (pols[0][1] or ""), f"SELECT policy not gated on is_admin: {pols}"

    # authenticated has a table SELECT grant (so the policy can gate rows).
    assert db_conn.execute(
        "select has_table_privilege('authenticated', 'audit.log', 'SELECT')"
    ).fetchone()[0] is True


def test_audit_log_rls_denies_non_admin(db_conn):
    # A non-admin authenticated user sees zero rows even though rows exist.
    db_conn.execute(
        "create or replace function auth.uid() returns uuid "
        "language sql stable as $$ select null::uuid $$"
    )
    nid = db_conn.execute(
        "insert into taxonomy_nodes (slug, display_name) "
        "values (%s, 'X') returning id",
        (f"rls-{uuid.uuid4().hex[:8]}",),
    ).fetchone()[0]
    # A row was audited by the trigger.
    assert db_conn.execute(
        "select count(*) from audit.log where table_name = 'taxonomy_nodes' and pk = %s",
        (str(nid),),
    ).fetchone()[0] >= 1

    db_conn.execute("set role authenticated")
    try:
        # is_admin() is false (auth.uid null → no profile), so RLS filters all rows.
        assert db_conn.execute("select count(*) from audit.log").fetchone()[0] == 0
    finally:
        db_conn.execute("reset role")


# ---------------------------------------------------------------------------
# Trigger attachment
# ---------------------------------------------------------------------------

def test_trigger_attached_to_curated_tables(db_conn):
    tables = _audited_tables(db_conn)
    assert {
        "taxonomy_nodes", "human_reviews",
        "recipes", "recipe_ingredients", "recipe_steps", "ingredient_resolutions",
    } <= tables


def test_composite_pk_tables_not_audited(db_conn):
    # taxonomy_edges/aliases + cocktail_aliases have composite / non-node PKs;
    # node-level audit is the meaningful unit, so they carry no row trigger.
    tables = _audited_tables(db_conn)
    for t in ("taxonomy_edges", "taxonomy_aliases", "cocktail_aliases"):
        assert t not in tables, f"{t} should not be row-audited"

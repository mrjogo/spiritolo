"""Schema-shape + RLS + trigger-attachment tests for the audit log.

Asserts the ``audit.log`` migration produces the columns, CHECKs, indexes,
and admin-read-only RLS the /ops surface depends on, that the generic
``audit.log_change`` trigger is attached to exactly the curated tables that
exist today, and that composite-PK reference tables are NOT row-audited
(node-level audit is the meaningful unit).

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


def _columns(conn, schema: str, table: str) -> dict[str, tuple[str, str]]:
    return {
        r[0]: (r[1], r[2])
        for r in conn.execute(
            "select column_name, data_type, is_nullable "
            "from information_schema.columns "
            "where table_schema = %s and table_name = %s",
            (schema, table),
        ).fetchall()
    }


def _checks(conn, relname: str) -> list[str]:
    return [
        r[0]
        for r in conn.execute(
            "select pg_get_constraintdef(oid) from pg_constraint "
            "where conrelid = %s::regclass and contype = 'c'",
            (relname,),
        ).fetchall()
    ]


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

def test_audit_log_shape(db_conn):
    cols = _columns(db_conn, "audit", "log")
    for c in (
        "ts", "table_name", "pk", "op", "actor_kind", "actor_id",
        "source", "before", "after", "changed_keys",
    ):
        assert c in cols, f"audit.log missing column {c!r}"

    assert cols["ts"] == ("timestamp with time zone", "NO")
    assert cols["table_name"] == ("text", "NO")
    assert cols["pk"] == ("text", "NO")
    assert cols["op"][0] == "character"          # char(1)
    assert cols["op"][1] == "NO"
    assert cols["actor_kind"] == ("text", "NO")
    assert cols["actor_id"][1] == "YES"          # nullable (system → null)
    assert cols["source"][1] == "NO"
    assert cols["before"][0] == "jsonb"
    assert cols["after"][0] == "jsonb"
    assert cols["changed_keys"][0] == "ARRAY"    # text[]

    checks = _checks(db_conn, "audit.log")
    assert any(
        "op" in c and "'I'" in c and "'U'" in c and "'D'" in c for c in checks
    ), f"no op CHECK(I,U,D) in {checks}"
    assert any(
        "actor_kind" in c and "'human'" in c and "'worker'" in c and "'system'" in c
        for c in checks
    ), f"no actor_kind CHECK(human,worker,system) in {checks}"


def test_audit_log_indexes(db_conn):
    idx = {
        r[0]: r[1].lower()
        for r in db_conn.execute(
            "select indexname, indexdef from pg_indexes "
            "where schemaname = 'audit' and tablename = 'log'"
        ).fetchall()
    }
    tbl_pk = idx.get("audit_log_table_pk_idx")
    assert tbl_pk is not None, "audit_log_table_pk_idx missing"
    assert "table_name" in tbl_pk and "pk" in tbl_pk and "ts desc" in tbl_pk

    actor = idx.get("audit_log_actor_idx")
    assert actor is not None, "audit_log_actor_idx missing"
    assert "actor_kind" in actor and "ts desc" in actor


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
        "taxonomy_nodes", "stage_reviews",
        "recipes", "recipe_ingredients", "recipe_steps", "ingredient_resolutions",
    } <= tables


def test_composite_pk_tables_not_audited(db_conn):
    # taxonomy_edges/aliases + cocktail_aliases have composite / non-node PKs;
    # node-level audit is the meaningful unit, so they carry no row trigger.
    tables = _audited_tables(db_conn)
    for t in ("taxonomy_edges", "taxonomy_aliases", "cocktail_aliases"):
        assert t not in tables, f"{t} should not be row-audited"

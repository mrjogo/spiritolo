"""DB-side tests for the explicit-run RPC surface (Task 3).

These are the SECURITY DEFINER functions the queue-selection UI calls: the run
lifecycle (create_run / add_run_items[_by_filter] / remove_run_items /
set_run_llm / start_run / apply_run_items), the browsing surfaces
(eligible_pool[_facets] / run_items[_facets]), and the `runs` read view.

Every function guards on ``public.is_admin()`` (reads profiles.is_admin filtered
by ``auth.uid()``); the fixture rewires ``auth.uid()`` to a freshly-inserted
admin user, exactly like test_job_rpcs. The argument NAMES are load-bearing —
the committed web hooks (web/src/ui/runs/*.ts) call these RPCs with named args
via supabase.rpc, so a couple of tests pin the exact names with `=>` notation.
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


@pytest.fixture
def conn(db_conn):
    """Autocommit connection with the run tables + auth surface cleaned, and an
    admin session wired up (auth.uid() -> an is_admin profile)."""
    db_conn.execute("reset role")
    for t in ("job_items", "jobs", "recipes", "pages"):
        db_conn.execute(f"truncate table {t} restart identity cascade")
    db_conn.execute("delete from profiles")
    db_conn.execute("delete from auth.users")
    _become(db_conn, admin=True)
    yield db_conn
    db_conn.execute("reset role")


def _become(conn, *, admin: bool) -> uuid.UUID:
    uid = uuid.uuid4()
    conn.execute("insert into auth.users (id, email) values (%s, %s)", (uid, f"{uid}@test"))
    conn.execute("update profiles set is_admin = %s where id = %s", (admin, uid))
    conn.execute(
        f"create or replace function auth.uid() returns uuid "
        f"language sql stable as $$ select '{uid}'::uuid $$"
    )
    return uid


def _recipe(conn, *, site="diffordsguide", title="A Drink") -> int:
    return conn.execute(
        "insert into recipes (source_url, site, source, title) "
        "values (%s, %s, '{}'::jsonb, %s) returning id",
        (f"https://x/{uuid.uuid4()}", site, title),
    ).fetchone()[0]


def _terminal_item(conn, *, recipe_id, stage="map", state="flagged", code_version="v1"):
    """A completed job_item that gives an entity a stage status in the pool."""
    conn.execute(
        "insert into job_items (entity_type, entity_id, stage, code_version, "
        "outcome, method, state) values ('recipe', %s, %s, %s, %s, 'deterministic', %s)",
        (recipe_id, stage, code_version, "resolved" if state == "applied" else "pending", state),
    )


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------
def test_run_lifecycle(conn):
    r1, r2 = _recipe(conn), _recipe(conn)
    jid = conn.execute("select create_run('map','hold')").fetchone()[0]
    assert isinstance(jid, int)
    assert conn.execute("select state, apply_mode from jobs where id=%s", (jid,)).fetchone() == (
        "draft",
        "hold",
    )

    n = conn.execute("select add_run_items(%s,'recipe', array[%s,%s])", (jid, r1, r2)).fetchone()[0]
    assert n == 2
    assert conn.execute(
        "select count(*) from job_items where job_id=%s and state='pending'", (jid,)
    ).fetchone()[0] == 2

    # Idempotent add: re-adding the same ids does not duplicate members.
    again = conn.execute("select add_run_items(%s,'recipe', array[%s])", (jid, r1)).fetchone()[0]
    assert again == 0
    assert conn.execute(
        "select count(*) from job_items where job_id=%s", (jid,)
    ).fetchone()[0] == 2

    conn.execute("select set_run_llm(%s,'deepseek','deepseek-chat')", (jid,))
    assert conn.execute(
        "select llm_provider, llm_model from jobs where id=%s", (jid,)
    ).fetchone() == ("deepseek", "deepseek-chat")

    conn.execute("select start_run(%s, 500)", (jid,))
    row = conn.execute(
        "select state, max_cost_cents, cost_estimate_cents, approved from jobs where id=%s", (jid,)
    ).fetchone()
    assert row[0] == "queued"
    assert row[1] == 500
    assert row[2] is not None  # estimate stamped
    assert row[3] is True


def test_named_args_match_web_hooks(conn):
    """The web hooks call these RPCs with named args; pin the exact names."""
    r1 = _recipe(conn)
    jid = conn.execute("select create_run(stage => 'map', apply_mode => 'auto')").fetchone()[0]
    conn.execute(
        "select add_run_items(job_id => %s, entity_type => 'recipe', entity_ids => array[%s])",
        (jid, r1),
    )
    conn.execute("select set_run_llm(job_id => %s, provider => 'openai', model => 'gpt')", (jid,))
    conn.execute("select start_run(job_id => %s, max_cost_cents => 100)", (jid,))
    assert conn.execute("select state from jobs where id=%s", (jid,)).fetchone()[0] == "queued"


def test_remove_run_items_draft_only(conn):
    r1, r2 = _recipe(conn), _recipe(conn)
    jid = conn.execute("select create_run('map','auto')").fetchone()[0]
    conn.execute("select add_run_items(%s,'recipe', array[%s,%s])", (jid, r1, r2))
    ids = [
        r[0]
        for r in conn.execute("select id from job_items where job_id=%s order by entity_id", (jid,)).fetchall()
    ]
    removed = conn.execute("select remove_run_items(%s, array[%s])", (jid, ids[0])).fetchone()[0]
    assert removed == 1
    assert conn.execute("select count(*) from job_items where job_id=%s", (jid,)).fetchone()[0] == 1


def test_apply_run_items_flips_pending_apply(conn):
    r1 = _recipe(conn)
    jid = conn.execute("select create_run('map','hold')").fetchone()[0]
    conn.execute("select add_run_items(%s,'recipe', array[%s])", (jid, r1))
    # Simulate a hold-run worker outcome: the member is held for apply.
    conn.execute("update job_items set state='pending_apply' where job_id=%s", (jid,))
    n = conn.execute("select apply_run_items(%s, null)", (jid,)).fetchone()[0]
    assert n == 1
    assert conn.execute(
        "select state from job_items where job_id=%s", (jid,)
    ).fetchone()[0] == "applied"


# ---------------------------------------------------------------------------
# runs read view
# ---------------------------------------------------------------------------
def test_runs_view_shape_and_rollups(conn):
    r1, r2, r3 = _recipe(conn), _recipe(conn), _recipe(conn)
    # r1 flagged, r2 failed at the stage; r3 never run.
    _terminal_item(conn, recipe_id=r1, state="flagged")
    _terminal_item(conn, recipe_id=r2, state="failed")
    jid = conn.execute("select create_run('map','auto')").fetchone()[0]
    conn.execute("select add_run_items(%s,'recipe', array[%s,%s,%s])", (jid, r1, r2, r3))

    row = conn.execute(
        "select id, stage, state, apply_mode, llm_provider, llm_model, task_count, "
        "flagged_count, never_run_count, failed_count, cost_estimate_cents, "
        "max_cost_cents, created_at, created_by from runs where id=%s",
        (jid,),
    ).fetchone()
    assert row[0] == jid
    assert row[1] == "map"
    assert row[2] == "draft"
    assert row[3] == "auto"
    assert row[6] == 3  # task_count
    assert row[7] == 1  # flagged_count
    assert row[8] == 1  # never_run_count
    assert row[9] == 1  # failed_count


# ---------------------------------------------------------------------------
# eligible_pool + facets
# ---------------------------------------------------------------------------
def test_eligible_pool_filter_and_facets(conn):
    r1 = _recipe(conn, site="diffordsguide")
    r2 = _recipe(conn, site="diffordsguide")
    r3 = _recipe(conn, site="punch")
    _recipe(conn, site="diffordsguide")  # r4: never_run
    _terminal_item(conn, recipe_id=r1, state="flagged")
    _terminal_item(conn, recipe_id=r2, state="failed")
    _terminal_item(conn, recipe_id=r3, state="flagged")

    # AND across keys, OR within a key: (flagged OR failed) AND source=diffordsguide.
    rows = conn.execute(
        "select * from eligible_pool('map', %s, 'last_run_desc', 50, 0)",
        ('{"status":["flagged","failed"],"source":["diffordsguide"]}',),
    ).fetchall()
    ids = {r[0] for r in rows}
    assert ids == {str(r1), str(r2)}
    # total_count window column is stamped on every row.
    assert all(r[-1] == 2 for r in rows)

    facets = conn.execute("select eligible_pool_facets('map','{}')").fetchone()[0]
    assert facets["status"]["flagged"] == 2
    assert facets["status"]["failed"] == 1
    assert facets["status"]["never_run"] == 1
    assert facets["source"]["diffordsguide"] == 3


def test_add_run_items_by_filter(conn):
    r1 = _recipe(conn, site="diffordsguide")
    r2 = _recipe(conn, site="punch")
    _terminal_item(conn, recipe_id=r1, state="flagged")
    _terminal_item(conn, recipe_id=r2, state="flagged")
    jid = conn.execute("select create_run('map','auto')").fetchone()[0]
    n = conn.execute(
        "select add_run_items_by_filter(%s, %s)",
        (jid, '{"status":["flagged"],"source":["diffordsguide"]}'),
    ).fetchone()[0]
    assert n == 1
    members = [
        r[0]
        for r in conn.execute(
            "select entity_id from job_items where job_id=%s", (jid,)
        ).fetchall()
    ]
    assert members == [r1]


# ---------------------------------------------------------------------------
# run_items + facets
# ---------------------------------------------------------------------------
def test_run_items_and_facets(conn):
    r1, r2 = _recipe(conn, title="Negroni"), _recipe(conn, title="Martini")
    _terminal_item(conn, recipe_id=r1, state="flagged")  # why_added flagged
    jid = conn.execute("select create_run('map','auto')").fetchone()[0]
    conn.execute("select add_run_items(%s,'recipe', array[%s,%s])", (jid, r1, r2))

    rows = conn.execute(
        "select * from run_items(%s, '{}'::jsonb, 'title_asc', 50, 0)", (jid,)
    ).fetchall()
    assert len(rows) == 2
    # columns: item_id, entity_id, title, source, why_added, task_state, total_count
    by_entity = {r[1]: r for r in rows}
    assert by_entity[str(r1)][4] == "flagged"  # why_added
    assert by_entity[str(r2)][4] == "never_run"
    assert by_entity[str(r1)][5] == "pending"  # task_state
    assert all(r[-1] == 2 for r in rows)  # total_count window

    facets = conn.execute("select run_items_facets(%s, '{}'::jsonb)", (jid,)).fetchone()[0]
    assert facets["status"]["pending"] == 2

    # status filter on run_items narrows by task_state.
    conn.execute("update job_items set state='applied' where job_id=%s and entity_id=%s", (jid, r1))
    filtered = conn.execute(
        "select * from run_items(%s, %s, 'title_asc', 50, 0)", (jid, '{"status":["applied"]}')
    ).fetchall()
    assert [r[1] for r in filtered] == [str(r1)]


# ---------------------------------------------------------------------------
# admin gate
# ---------------------------------------------------------------------------
def test_create_run_admin_only(conn):
    _become(conn, admin=False)
    conn.execute("set role authenticated")
    try:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("select create_run('map','auto')")
    finally:
        conn.execute("reset role")


def test_estimate_cents_token_based(conn):
    """_estimate_cents prices ~1200 input + 200 output tokens per item at each
    provider's published $/1M rate (matches web estimateRunCents); ollama free."""

    def est(provider, items):
        return conn.execute(
            "select _estimate_cents(%s::text, null::text, %s::int)", (provider, items)
        ).fetchone()[0]

    assert est("ollama", 1000) == 0
    assert est("deepseek", 1000) == 22    # 1000 * (1200*0.14 + 200*0.28)/1e4
    assert est("openai", 1000) == 180     # 1000 * (1200*0.75 + 200*4.50)/1e4
    assert est("anthropic", 1000) == 220  # 1000 * (1200*1.00 + 200*5.00)/1e4
    assert est(None, 1000) == 0           # unknown / no provider -> free


def test_estimate_run_cents_rpc(conn):
    """The public estimate_run_cents RPC (the draft-UI preview) returns the same
    values start_run stamps via _estimate_cents — one source of truth for cost."""

    def rpc(provider, items):
        return conn.execute(
            "select estimate_run_cents(%s::text, null::text, %s::int)", (provider, items)
        ).fetchone()[0]

    assert rpc("ollama", 1000) == 0
    assert rpc("deepseek", 1000) == 22
    assert rpc("openai", 1000) == 180
    assert rpc("anthropic", 1000) == 220

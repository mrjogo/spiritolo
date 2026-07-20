"""DB-side tests for the explicit-run RPC surface (Task 3).

These are the SECURITY DEFINER functions the queue-selection UI calls: the run
lifecycle (create_run / add_run_items[_by_filter] / remove_run_items /
set_run_llm / start_run), the browsing surfaces
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


def _terminal_item(conn, *, recipe_id, stage="map-ingredient", state="flagged", code_version="v1"):
    """A completed job_item that gives an entity a stage status in the pool."""
    conn.execute(
        "insert into job_items (entity_type, entity_id, stage, code_version, "
        "outcome, method, state) values ('recipe', %s, %s, %s, %s, 'deterministic', %s)",
        (recipe_id, stage, code_version, "resolved" if state == "applied" else "pending", state),
    )


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------
def test_cancel_run_draft_and_queued_go_cancelled(conn):
    # A run no worker has claimed is cancelled outright.
    jid = conn.execute("select create_run('map-ingredient')").fetchone()[0]  # draft
    conn.execute("select cancel_run(%s)", (jid,))
    assert conn.execute("select state from jobs where id=%s", (jid,)).fetchone()[0] == "cancelled"

    qid = conn.execute(
        "insert into jobs (stage, state) values ('map-ingredient', 'queued') returning id"
    ).fetchone()[0]
    conn.execute("select cancel_run(%s)", (qid,))
    assert conn.execute("select state from jobs where id=%s", (qid,)).fetchone()[0] == "cancelled"


def test_cancel_run_running_requests_cooperative_stop(conn):
    # An in-flight run is asked to stop ('cancelling'); the worker turns that into
    # terminal 'cancelled' once the stage bails.
    rid = conn.execute(
        "insert into jobs (stage, state) values ('map-ingredient', 'running') returning id"
    ).fetchone()[0]
    conn.execute("select cancel_run(%s)", (rid,))
    assert conn.execute("select state from jobs where id=%s", (rid,)).fetchone()[0] == "cancelling"


def test_cancel_run_missing_raises(conn):
    with pytest.raises(psycopg.errors.ForeignKeyViolation):  # 23503, per start_run
        conn.execute("select cancel_run(999999)")


def test_retry_run_requeues_residue(conn):
    # A failed run with applied + failed + pending items: retry resets failed ->
    # pending, re-queues the job, and clears the error.
    r_ok, r_bad, r_todo = _recipe(conn), _recipe(conn), _recipe(conn)
    jid = conn.execute(
        "insert into jobs (stage, state, error_code, error_detail, cost_actual_cents) "
        "values ('map-ingredient', 'failed', 'provider_unavailable', 'boom', 5) returning id"
    ).fetchone()[0]
    for rid, st in [(r_ok, "applied"), (r_bad, "failed"), (r_todo, "pending")]:
        conn.execute(
            "insert into job_items (entity_type, entity_id, stage, code_version, "
            "outcome, method, state, job_id) "
            "values ('recipe', %s, 'map-ingredient', 'v1', 'resolved', 'deterministic', %s, %s)",
            (rid, st, jid),
        )

    conn.execute("select retry_run(%s)", (jid,))

    state, ec, ed = conn.execute(
        "select state, error_code, error_detail from jobs where id=%s", (jid,)
    ).fetchone()
    assert state == "queued"
    assert ec is None and ed is None
    counts = dict(
        conn.execute(
            "select state, count(*) from job_items where job_id=%s group by state", (jid,)
        ).fetchall()
    )
    assert counts.get("pending") == 2  # r_todo + the reset r_bad
    assert counts.get("applied") == 1
    assert counts.get("failed", 0) == 0


def test_retry_run_rejects_a_running_run(conn):
    jid = conn.execute(
        "insert into jobs (stage, state) values ('map-ingredient', 'running') returning id"
    ).fetchone()[0]
    with pytest.raises(psycopg.errors.InvalidParameterValue):  # 22023 not finished
        conn.execute("select retry_run(%s)", (jid,))


def test_runs_view_exposes_cockpit_fields(conn):
    jid = conn.execute(
        "insert into jobs (stage, state, worker_id, cost_actual_cents, error_detail) "
        "values ('map-ingredient', 'failed', 'w1', 7, 'boom') returning id"
    ).fetchone()[0]
    r = _recipe(conn)
    conn.execute(
        "insert into job_items (entity_type, entity_id, stage, code_version, "
        "outcome, method, state, job_id) "
        "values ('recipe', %s, 'map-ingredient', 'v1', 'resolved', 'deterministic', 'applied', %s)",
        (r, jid),
    )
    state, cost_actual, detail, worker_id, applied = conn.execute(
        "select state, cost_actual_cents, error_detail, worker_id, items_applied "
        "from runs where id=%s",
        (jid,),
    ).fetchone()
    assert state == "failed"
    assert cost_actual == 7 and detail == "boom" and worker_id == "w1"
    assert applied == 1


def test_run_lifecycle(conn):
    r1, r2 = _recipe(conn), _recipe(conn)
    jid = conn.execute("select create_run('map-ingredient')").fetchone()[0]
    assert isinstance(jid, int)
    assert conn.execute("select state from jobs where id=%s", (jid,)).fetchone() == ("draft",)

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
    jid = conn.execute("select create_run(stage => 'map-ingredient')").fetchone()[0]
    conn.execute(
        "select add_run_items(job_id => %s, entity_type => 'recipe', entity_ids => array[%s])",
        (jid, r1),
    )
    conn.execute("select set_run_llm(job_id => %s, provider => 'openai', model => 'gpt')", (jid,))
    conn.execute("select start_run(job_id => %s, max_cost_cents => 100)", (jid,))
    assert conn.execute("select state from jobs where id=%s", (jid,)).fetchone()[0] == "queued"


def test_remove_run_items_draft_only(conn):
    r1, r2 = _recipe(conn), _recipe(conn)
    jid = conn.execute("select create_run('map-ingredient')").fetchone()[0]
    conn.execute("select add_run_items(%s,'recipe', array[%s,%s])", (jid, r1, r2))
    ids = [
        r[0]
        for r in conn.execute("select id from job_items where job_id=%s order by entity_id", (jid,)).fetchall()
    ]
    removed = conn.execute("select remove_run_items(%s, array[%s])", (jid, ids[0])).fetchone()[0]
    assert removed == 1
    assert conn.execute("select count(*) from job_items where job_id=%s", (jid,)).fetchone()[0] == 1


# ---------------------------------------------------------------------------
# runs read view
# ---------------------------------------------------------------------------
def test_runs_view_shape_and_rollups(conn):
    r1, r2, r3 = _recipe(conn), _recipe(conn), _recipe(conn)
    # r1 flagged, r2 failed at the stage; r3 never run.
    _terminal_item(conn, recipe_id=r1, state="flagged")
    _terminal_item(conn, recipe_id=r2, state="failed")
    jid = conn.execute("select create_run('map-ingredient')").fetchone()[0]
    conn.execute("select add_run_items(%s,'recipe', array[%s,%s,%s])", (jid, r1, r2, r3))

    row = conn.execute(
        "select id, stage, state, llm_provider, llm_model, task_count, "
        "flagged_count, never_run_count, failed_count, cost_estimate_cents, "
        "max_cost_cents, created_at, created_by from runs where id=%s",
        (jid,),
    ).fetchone()
    assert row[0] == jid
    assert row[1] == "map-ingredient"
    assert row[2] == "draft"
    assert row[5] == 3  # task_count
    assert row[6] == 1  # flagged_count
    assert row[7] == 1  # never_run_count
    assert row[8] == 1  # failed_count


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
        "select * from eligible_pool('map-ingredient', %s, 'last_run_desc', 50, 0)",
        ('{"status":["flagged","failed"],"source":["diffordsguide"]}',),
    ).fetchall()
    ids = {r[0] for r in rows}
    assert ids == {str(r1), str(r2)}
    # total_count window column is stamped on every row.
    assert all(r[-1] == 2 for r in rows)

    facets = conn.execute("select eligible_pool_facets('map-ingredient','{}')").fetchone()[0]
    assert facets["status"]["flagged"] == 2
    assert facets["status"]["failed"] == 1
    assert facets["status"]["never_run"] == 1
    assert facets["source"]["diffordsguide"] == 3


def test_add_run_items_by_filter(conn):
    r1 = _recipe(conn, site="diffordsguide")
    r2 = _recipe(conn, site="punch")
    _terminal_item(conn, recipe_id=r1, state="flagged")
    _terminal_item(conn, recipe_id=r2, state="flagged")
    jid = conn.execute("select create_run('map-ingredient')").fetchone()[0]
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


def _page(conn, *, content_type=None, corpus_key=None, site="diffordsguide") -> int:
    return conn.execute(
        "insert into pages (url, site, content_type, corpus_key) "
        "values (%s, %s, %s, %s) returning id",
        (f"https://x/{uuid.uuid4()}", site, content_type, corpus_key),
    ).fetchone()[0]


def test_extract_universe_only_fetched_recipe_pages(conn):
    """The extract-recipe run universe is exactly what the stage can process —
    recipe-classified pages with cached HTML (a corpus key). Non-recipe or
    unfetched pages must not inflate the 'never run' facet (the ~484k artifact)."""
    good = _page(conn, content_type="likely_drink_recipe", corpus_key="k1")
    confirmed = _page(conn, content_type="confirmed_drink", corpus_key="k2")
    _page(conn, content_type="likely_drink_recipe", corpus_key=None)  # not fetched
    _page(conn, content_type="article", corpus_key="k3")              # not a recipe
    _page(conn, content_type=None, corpus_key="k4")                   # unclassified

    rows = conn.execute(
        "select entity_id from _eligible_base('extract-recipe', '{}'::jsonb)"
    ).fetchall()
    assert {r[0] for r in rows} == {good, confirmed}

    facets = conn.execute("select eligible_pool_facets('extract-recipe','{}')").fetchone()[0]
    assert facets["status"]["never_run"] == 2  # only the two eligible pages


# ---------------------------------------------------------------------------
# node run universe (combine-nodes / connect-nodes)
# ---------------------------------------------------------------------------
def _node(conn, *, display_name, status="provisional") -> int:
    """A taxonomy node with the given harmonization status."""
    slug = f"n-{uuid.uuid4().hex[:12]}"
    return conn.execute(
        "insert into taxonomy_nodes (slug, display_name, status) "
        "values (%s, %s, %s) returning id",
        (slug, display_name, status),
    ).fetchone()[0]


def test_eligible_pool_node_universe(conn):
    """combine-nodes/connect-nodes browse the taxonomy_nodes universe, with the
    node's status mapped onto the `source` column so the source facet becomes a
    live/provisional filter."""
    conn.execute("truncate table taxonomy_nodes cascade")
    prov = _node(conn, display_name="Provisional Amaro", status="provisional")
    live = _node(conn, display_name="Live Gin", status="live")

    rows = conn.execute(
        "select entity_id, title, source from "
        "_eligible_base('combine-nodes', '{}'::jsonb) order by title"
    ).fetchall()
    by_id = {r[0]: r for r in rows}
    assert set(by_id) == {prov, live}
    # status is surfaced as the `source` facet value.
    assert by_id[prov][2] == "provisional"
    assert by_id[live][2] == "live"
    assert by_id[prov][1] == "Provisional Amaro"

    # A source filter of ['provisional'] narrows to just the provisional node —
    # the default "residue" view the operator starts from.
    narrowed = conn.execute(
        "select entity_id from _eligible_base('combine-nodes', %s)",
        ('{"source":["provisional"]}',),
    ).fetchall()
    assert [r[0] for r in narrowed] == [prov]


def test_add_run_items_by_filter_node_stage(conn):
    """add_run_items_by_filter for a node stage inserts job_items keyed to
    taxonomy_node entities."""
    conn.execute("truncate table taxonomy_nodes cascade")
    prov = _node(conn, display_name="Provisional Amaro", status="provisional")
    _node(conn, display_name="Live Gin", status="live")

    jid = conn.execute("select create_run('combine-nodes')").fetchone()[0]
    n = conn.execute(
        "select add_run_items_by_filter(%s, %s)", (jid, '{"source":["provisional"]}')
    ).fetchone()[0]
    assert n == 1
    rows = conn.execute(
        "select entity_type, entity_id from job_items where job_id=%s", (jid,)
    ).fetchall()
    assert rows == [("taxonomy_node", prov)]


# ---------------------------------------------------------------------------
# run_items + facets
# ---------------------------------------------------------------------------
def test_run_items_and_facets(conn):
    r1, r2 = _recipe(conn, title="Negroni"), _recipe(conn, title="Martini")
    _terminal_item(conn, recipe_id=r1, state="flagged")  # why_added flagged
    jid = conn.execute("select create_run('map-ingredient')").fetchone()[0]
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
            conn.execute("select create_run('map-ingredient')")
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

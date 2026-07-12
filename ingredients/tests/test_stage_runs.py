"""Schema + behavior + boundary tests for the stage_runs run-ledger (B4).

stage_runs is ONE polymorphic latest-only ledger generalizing every per-stage
*_runs table: (entity_type, entity_id, stage) is unique, a re-run UPSERTs, the
work queue is "content qualifies AND NOT EXISTS a run at the current version",
and --reset deletes runs (optionally below a version / scoped) to re-queue the
entity. ledger.py wraps the UPSERT / queue / reset SQL.

Runs against TEST_DB_URL with all migrations applied (the ingredients conftest
auto-applies 20260712_020000_stage_runs.sql). recipe_docs (B2) supplies the
content rows the recipe_doc queue joins against; stage_runs carries NO per-entity
FK, so page-entity rows need no pages table.
"""

from __future__ import annotations

import psycopg
import pytest
from psycopg.types.json import Json

from ingredients.pipeline import ledger


def _seed_doc(conn, source_url: str, *, state: str = "extracted") -> int:
    return conn.execute(
        "insert into recipe_docs (source_url, doc, state) values (%s, %s, %s) "
        "returning id",
        (source_url, Json({"title": "X", "_x": {}}), state),
    ).fetchone()[0]


def _reset_tables(conn) -> None:
    conn.execute("truncate table stage_runs restart identity cascade")
    conn.execute("truncate table recipe_docs restart identity cascade")


# --------------------------------------------------------------------------
# Shape
# --------------------------------------------------------------------------

def test_schema_shape(db_conn):
    cols = {
        r[0]: (r[1], r[2])
        for r in db_conn.execute(
            """
            select column_name, data_type, is_nullable
            from information_schema.columns
            where table_name = 'stage_runs'
            """
        ).fetchall()
    }
    assert cols["entity_type"] == ("text", "NO")
    assert cols["entity_id"] == ("bigint", "NO")
    assert cols["stage"] == ("text", "NO")
    assert cols["version"] == ("text", "NO")
    assert cols["outcome"] == ("text", "NO")
    assert cols["method"] == ("text", "NO")
    assert cols["confidence"][0] == "real"
    assert cols["model_id"][0] == "text"
    assert cols["cost_cents"][0] == "numeric"
    assert cols["error_code"][0] == "text"
    assert cols["batch_id"][0] == "bigint"
    assert cols["job_id"][0] == "bigint"
    assert cols["payload"][0] == "jsonb"
    assert cols["started_at"][0] == "timestamp with time zone"
    assert cols["finished_at"][0] == "timestamp with time zone"

    # CHECK constraints enumerate the allowed values.
    checks = " ".join(
        r[0]
        for r in db_conn.execute(
            """
            select cc.check_clause
            from information_schema.check_constraints cc
            join information_schema.constraint_column_usage ccu
              on cc.constraint_name = ccu.constraint_name
            where ccu.table_name = 'stage_runs'
            """
        ).fetchall()
    )
    for v in ("page", "recipe_doc"):
        assert v in checks, f"entity_type CHECK missing {v}"
    for v in ("resolved", "abstain", "pending", "failed", "proposes_new"):
        assert v in checks, f"outcome CHECK missing {v}"
    for v in ("deterministic", "llm", "manual"):
        assert v in checks, f"method CHECK missing {v}"

    # UNIQUE(entity_type, entity_id, stage) — the latest-only key.
    uniq = {}
    for r in db_conn.execute(
        """
        select tc.constraint_name, kcu.column_name, kcu.ordinal_position
        from information_schema.table_constraints tc
        join information_schema.key_column_usage kcu
          on tc.constraint_name = kcu.constraint_name
        where tc.table_name = 'stage_runs' and tc.constraint_type = 'UNIQUE'
        """
    ).fetchall():
        uniq.setdefault(r[0], []).append((r[2], r[1]))
    assert any(
        [c for _, c in sorted(members)] == ["entity_type", "entity_id", "stage"]
        for members in uniq.values()
    ), f"missing UNIQUE(entity_type, entity_id, stage); have {uniq}"


def test_entity_type_check_rejects_unknown(db_conn):
    _reset_tables(db_conn)
    with pytest.raises(psycopg.errors.CheckViolation):
        db_conn.execute(
            "insert into stage_runs (entity_type, entity_id, stage, version, "
            "outcome, method) values ('widget', 1, 'parse', 'v1', 'resolved', "
            "'deterministic')"
        )


# --------------------------------------------------------------------------
# Behavior — latest-only UPSERT
# --------------------------------------------------------------------------

def test_upsert_is_latest_only(db_conn):
    _reset_tables(db_conn)
    doc_id = _seed_doc(db_conn, "https://ex/upsert")

    ledger.record_run(
        db_conn, entity_type="recipe_doc", entity_id=doc_id, stage="parse",
        version="v1", outcome="pending", method="deterministic",
        payload={"n": 1},
    )
    ledger.record_run(
        db_conn, entity_type="recipe_doc", entity_id=doc_id, stage="parse",
        version="v2", outcome="resolved", method="llm", confidence=0.9,
        model_id="gpt-5-mini", payload={"n": 2},
    )

    rows = db_conn.execute(
        "select version, outcome, method, confidence, model_id, payload "
        "from stage_runs where entity_type = 'recipe_doc' and entity_id = %s "
        "and stage = 'parse'",
        (doc_id,),
    ).fetchall()
    assert len(rows) == 1, "UPSERT must keep exactly one row per (entity, stage)"
    version, outcome, method, confidence, model_id, payload = rows[0]
    assert (version, outcome, method) == ("v2", "resolved", "llm")
    assert confidence == pytest.approx(0.9)
    assert model_id == "gpt-5-mini"
    assert payload == {"n": 2}


# --------------------------------------------------------------------------
# Behavior — work queue (NOT EXISTS at current version)
# --------------------------------------------------------------------------

def test_work_queue_not_exists_predicate(db_conn):
    _reset_tables(db_conn)
    a = _seed_doc(db_conn, "https://ex/wq-a")
    b = _seed_doc(db_conn, "https://ex/wq-b")
    c = _seed_doc(db_conn, "https://ex/wq-c")

    # a has been parsed at the current version; b and c have not.
    ledger.record_run(
        db_conn, entity_type="recipe_doc", entity_id=a, stage="parse",
        version="v1", outcome="resolved", method="deterministic",
    )
    q = ledger.work_queue(
        db_conn, entity_type="recipe_doc", stage="parse", version="v1",
        state="extracted",
    )
    assert set(q) == {b, c}

    # A doc left at an OLDER version re-appears in the current-version queue —
    # the unique constraint guarantees ≤1 row per (entity, stage), so a stale
    # version is automatically re-queued with no history filtering.
    ledger.record_run(
        db_conn, entity_type="recipe_doc", entity_id=b, stage="parse",
        version="v0", outcome="resolved", method="deterministic",
    )
    q2 = ledger.work_queue(
        db_conn, entity_type="recipe_doc", stage="parse", version="v1",
        state="extracted",
    )
    assert set(q2) == {b, c}, "parse@v0 doc must re-appear in the v1 queue"


def test_truncate_stage_runs_requeues_everything(db_conn):
    # stage_runs is prunable derived state: TRUNCATE + re-run reproduces it.
    _reset_tables(db_conn)
    a = _seed_doc(db_conn, "https://ex/tr-a")
    ledger.record_run(
        db_conn, entity_type="recipe_doc", entity_id=a, stage="parse",
        version="v1", outcome="resolved", method="deterministic",
    )
    assert ledger.work_queue(
        db_conn, entity_type="recipe_doc", stage="parse", version="v1",
        state="extracted",
    ) == []

    db_conn.execute("truncate table stage_runs")
    assert ledger.work_queue(
        db_conn, entity_type="recipe_doc", stage="parse", version="v1",
        state="extracted",
    ) == [a]


# --------------------------------------------------------------------------
# Behavior — reset
# --------------------------------------------------------------------------

def test_reset_requeues_below_version(db_conn):
    _reset_tables(db_conn)
    a = _seed_doc(db_conn, "https://ex/rs-a")
    b = _seed_doc(db_conn, "https://ex/rs-b")
    ledger.record_run(
        db_conn, entity_type="recipe_doc", entity_id=a, stage="parse",
        version="v1", outcome="resolved", method="deterministic",
    )
    ledger.record_run(
        db_conn, entity_type="recipe_doc", entity_id=b, stage="parse",
        version="v2", outcome="resolved", method="deterministic",
    )

    deleted = ledger.reset(
        db_conn, stage="parse", except_version="v2", entity_type="recipe_doc",
    )
    assert deleted == 1

    surviving = db_conn.execute(
        "select entity_id, version from stage_runs where stage = 'parse'"
    ).fetchall()
    assert surviving == [(b, "v2")], "only the v2 row survives"

    # A re-queues at v2; B (already v2) does not.
    q = ledger.work_queue(
        db_conn, entity_type="recipe_doc", stage="parse", version="v2",
        state="extracted",
    )
    assert set(q) == {a}


def test_reset_nulls_gating_cursor_atomically(db_conn):
    # classify's queue gates on a denormalized cursor (pages.content_type IS
    # NULL), so its reset must delete the run row AND null the cursor in ONE
    # transaction. stage_runs has no FK to the gated table, so we exercise the
    # generic gating mechanism against a throwaway stand-in for `pages`.
    _reset_tables(db_conn)
    db_conn.execute("drop table if exists _ledger_gating_pages")
    db_conn.execute(
        "create table _ledger_gating_pages (id bigint primary key, "
        "content_type text)"
    )
    try:
        db_conn.execute(
            "insert into _ledger_gating_pages (id, content_type) "
            "values (1, 'drink_recipe')"
        )
        ledger.record_run(
            db_conn, entity_type="page", entity_id=1, stage="classify",
            version="v1", outcome="resolved", method="llm",
        )

        ledger.reset(
            db_conn, stage="classify", entity_type="page",
            gating=("_ledger_gating_pages", "content_type"),
        )
        # Both effects landed: run row gone, cursor nulled.
        assert db_conn.execute(
            "select count(*) from stage_runs where stage = 'classify'"
        ).fetchone()[0] == 0
        assert db_conn.execute(
            "select content_type from _ledger_gating_pages where id = 1"
        ).fetchone()[0] is None

        # Atomicity: a gating update that fails rolls back the delete too, so an
        # entity is never stranded out of both the queue and the ledger.
        db_conn.execute(
            "update _ledger_gating_pages set content_type = 'drink_recipe' "
            "where id = 1"
        )
        ledger.record_run(
            db_conn, entity_type="page", entity_id=1, stage="classify",
            version="v1", outcome="resolved", method="llm",
        )
        with pytest.raises(psycopg.errors.Error):
            ledger.reset(
                db_conn, stage="classify", entity_type="page",
                gating=("_ledger_gating_pages", "no_such_column"),
            )
        # The delete rolled back — the run row is still there.
        assert db_conn.execute(
            "select count(*) from stage_runs where stage = 'classify'"
        ).fetchone()[0] == 1
    finally:
        db_conn.execute("drop table if exists _ledger_gating_pages")


# --------------------------------------------------------------------------
# Boundary — RLS keeps the ledger admin/pipeline-only
# --------------------------------------------------------------------------

def test_anon_cannot_read_stage_runs(db_conn):
    db_conn.execute("set role anon")
    try:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            db_conn.execute("select * from stage_runs limit 1")
    finally:
        db_conn.execute("reset role")

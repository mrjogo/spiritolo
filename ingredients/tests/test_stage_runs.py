"""Schema + behavior + boundary tests for the job_items run-ledger.

job_items is ONE polymorphic latest-only ledger generalizing every per-stage
*_runs table: (entity_type, entity_id, stage) is unique, a re-run UPSERTs, the
work queue is "content qualifies AND NOT EXISTS a run at the current version",
and its `reset()` operation deletes runs (optionally below a version / scoped)
to re-queue the entity. ledger.py wraps the UPSERT / queue / reset SQL.

Runs against TEST_DB_URL with all migrations applied (the ingredients conftest
auto-applies 20260712_020000_job_items.sql). The ledger is content-agnostic and
carries NO per-entity FK, so these tests drive it against a small throwaway
stand-in content table (`_ledger_content`) rather than any real content table —
the ledger is decoupled from the `recipes` schema and already speaks the
`recipe` entity_type without depending on it.
"""

from __future__ import annotations

import psycopg
import pytest

from ingredients.pipeline import ledger

_CONTENT = "_ledger_content"


@pytest.fixture
def content_table(db_conn):
    """A throwaway stand-in for a content table: (id, state, site). Stands in for
    the real `recipes`/`pages` content the ledger's work_queue joins against,
    keeping the ledger tests independent of any particular content schema."""
    db_conn.execute("truncate table job_items restart identity cascade")
    db_conn.execute(f"drop table if exists {_CONTENT}")
    db_conn.execute(
        f"create table {_CONTENT} (id bigint primary key, state text, site text)"
    )
    yield _CONTENT
    db_conn.execute(f"drop table if exists {_CONTENT}")


def _seed_content(conn, table, id_, *, state="extracted", site=None):
    conn.execute(
        f"insert into {table} (id, state, site) values (%s, %s, %s)",
        (id_, state, site),
    )
    return id_


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
            where table_name = 'job_items'
            """
        ).fetchall()
    }
    assert cols["entity_type"] == ("text", "NO")
    assert cols["entity_id"] == ("bigint", "NO")
    assert cols["stage"] == ("text", "NO")
    assert cols["code_version"] == ("text", "NO")
    assert cols["outcome"] == ("text", "NO")
    assert cols["method"] == ("text", "NO")
    assert cols["confidence"][0] == "real"
    assert cols["model_id"][0] == "text"
    assert cols["cost_cents"][0] == "numeric"
    assert cols["error_code"][0] == "text"
    assert cols["job_id"][0] == "bigint"
    assert cols["state"][0] == "text"
    assert cols["outcome_payload"][0] == "jsonb"
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
            where ccu.table_name = 'job_items'
            """
        ).fetchall()
    )
    for v in ("page", "recipe"):
        assert v in checks, f"entity_type CHECK missing {v}"
    assert "recipe_doc" not in checks, "entity_type must be 'recipe', not 'recipe_doc'"
    for v in ("resolved", "abstain", "pending", "failed", "proposes_new"):
        assert v in checks, f"outcome CHECK missing {v}"
    for v in ("deterministic", "llm", "manual"):
        assert v in checks, f"method CHECK missing {v}"

    # Append-versioned uniqueness is now a PARTIAL unique index scoped to the
    # cold-build ledger rows (job_id IS NULL). Run-member rows (job_id NOT NULL)
    # are deliberately unconstrained — the same entity can be a member of many
    # runs over time, and the add_run_items RPC dedups membership instead.
    idxdef = db_conn.execute(
        "select indexdef from pg_indexes "
        "where tablename = 'job_items' and indexname = 'job_items_ledger_key'"
    ).fetchone()
    assert idxdef is not None, "missing job_items_ledger_key partial unique index"
    definition = idxdef[0].lower()
    assert "unique" in definition
    for col in ("entity_type", "entity_id", "stage", "code_version"):
        assert col in definition, f"ledger key missing {col}: {definition}"
    assert "job_id is null" in definition, definition


def test_entity_type_check_rejects_unknown(db_conn):
    db_conn.execute("truncate table job_items restart identity cascade")
    with pytest.raises(psycopg.errors.CheckViolation):
        db_conn.execute(
            "insert into job_items (entity_type, entity_id, stage, code_version, "
            "outcome, method) values ('widget', 1, 'parse', 'v1', 'resolved', "
            "'deterministic')"
        )


# --------------------------------------------------------------------------
# Behavior — latest-only UPSERT
# --------------------------------------------------------------------------

def test_upsert_appends_versions(db_conn):
    # Append-versioned: one row per (entity, stage, VERSION); a bump keeps the
    # prior version's decision. A re-run at the SAME version overwrites in place.
    db_conn.execute("truncate table job_items restart identity cascade")

    ledger.record_run(
        db_conn, entity_type="recipe", entity_id=1, stage="parse",
        version="v1", outcome="pending", method="deterministic",
        payload={"n": 1},
    )
    ledger.record_run(
        db_conn, entity_type="recipe", entity_id=1, stage="parse",
        version="v2", outcome="resolved", method="llm", confidence=0.9,
        model_id="gpt-5-mini", payload={"n": 2},
    )

    rows = db_conn.execute(
        "select code_version, outcome from job_items "
        "where entity_type = 'recipe' and entity_id = 1 and stage = 'parse' "
        "order by code_version"
    ).fetchall()
    assert rows == [("v1", "pending"), ("v2", "resolved")], (
        "append-versioned: one row per version, history kept"
    )

    # Same-version re-run overwrites that version's row in place.
    ledger.record_run(
        db_conn, entity_type="recipe", entity_id=1, stage="parse",
        version="v2", outcome="failed", method="llm", payload={"n": 3},
    )
    v2 = db_conn.execute(
        "select outcome, payload from job_items "
        "where entity_id = 1 and stage = 'parse' and code_version = 'v2'"
    ).fetchall()
    assert v2 == [("failed", {"n": 3})]


# --------------------------------------------------------------------------
# Behavior — work queue (NOT EXISTS at current version)
# --------------------------------------------------------------------------

def test_work_queue_not_exists_predicate(db_conn, content_table):
    a = _seed_content(db_conn, content_table, 1)
    b = _seed_content(db_conn, content_table, 2)
    c = _seed_content(db_conn, content_table, 3)

    # a has been parsed at the current version; b and c have not.
    ledger.record_run(
        db_conn, entity_type="recipe", entity_id=a, stage="parse",
        version="v1", outcome="resolved", method="deterministic",
    )
    q = ledger.work_queue(
        db_conn, content_table=content_table, entity_type="recipe",
        stage="parse", version="v1", where="c.state = %s", params=("extracted",),
    )
    assert set(q) == {b, c}

    # A doc left at an OLDER version re-appears in the current-version queue —
    # the unique constraint guarantees ≤1 row per (entity, stage), so a stale
    # version is automatically re-queued with no history filtering.
    ledger.record_run(
        db_conn, entity_type="recipe", entity_id=b, stage="parse",
        version="v0", outcome="resolved", method="deterministic",
    )
    q2 = ledger.work_queue(
        db_conn, content_table=content_table, entity_type="recipe",
        stage="parse", version="v1", where="c.state = %s", params=("extracted",),
    )
    assert set(q2) == {b, c}, "parse@v0 entity must re-appear in the v1 queue"


def test_truncate_job_items_requeues_everything(db_conn, content_table):
    # job_items is prunable derived state: TRUNCATE + re-run reproduces it.
    a = _seed_content(db_conn, content_table, 1)
    ledger.record_run(
        db_conn, entity_type="recipe", entity_id=a, stage="parse",
        version="v1", outcome="resolved", method="deterministic",
    )
    assert ledger.work_queue(
        db_conn, content_table=content_table, entity_type="recipe",
        stage="parse", version="v1",
    ) == []

    db_conn.execute("truncate table job_items")
    assert ledger.work_queue(
        db_conn, content_table=content_table, entity_type="recipe",
        stage="parse", version="v1",
    ) == [a]


# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
# Boundary — RLS keeps the ledger admin/pipeline-only
# --------------------------------------------------------------------------

def test_anon_cannot_read_job_items(db_conn):
    db_conn.execute("set role anon")
    try:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            db_conn.execute("select * from job_items limit 1")
    finally:
        db_conn.execute("reset role")

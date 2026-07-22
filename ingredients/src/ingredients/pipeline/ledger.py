"""job_items run-ledger access.

One polymorphic latest-only ledger for every pipeline stage. Three operations,
mirroring the per-stage ``record_*`` / ``get_pending_*`` / ``clear_*`` helpers
in ``scraper/db.py`` that this generalizes:

- ``record_run``  — UPSERT on the (entity_type, entity_id, stage) unique key, so
  a re-run overwrites the prior row (latest-only, no history).
- ``work_queue``  — "content qualifies AND NOT EXISTS a run at the current
  version": entities with no run row, or a row left at an older version, appear.
- ``reset``       — delete the stage's rows (optionally below a version / scoped
  by site / older-than) to re-queue their entities; for a stage that also gates
  on a denormalized cursor (classify → pages.content_type), null that cursor in
  the SAME transaction so a crash can't strand an entity out of both queue and
  ledger.

The ledger is deliberately decoupled from any particular content table. It never
hardcodes a table name or a gating column: ``work_queue`` takes the content
table + an optional prefilter, ``reset`` takes the content table for site
scoping, and the gating cursor is passed explicitly. So the same ledger serves
`page` entities today and `recipe` entities once a relational `recipes` schema
exists — no change here.

All functions take a psycopg connection and do not commit (the caller owns the
transaction boundary); ``reset`` opens its own transaction for atomicity, which
composes correctly whether the connection is autocommit or not.
"""

from __future__ import annotations

from typing import Any, Sequence

from psycopg.types.json import Json


# Cold-build ledger upsert (job_id IS NULL). Append-versioned: keyed on the
# partial unique index over (entity_type, entity_id, stage, code_version) that
# covers only the ledger rows; run-member rows (job_id NOT NULL) take the UPDATE
# path below instead.
_UPSERT_LEDGER_SQL = """
    insert into job_items (
        entity_type, entity_id, stage, code_version, outcome, method,
        confidence, model_id, cost_cents, error_code, job_id, state,
        payload, finished_at
    )
    values (
        %s, %s, %s, %s, %s, %s,
        %s, %s, %s, %s, %s, %s,
        %s, coalesce(%s, now())
    )
    on conflict (entity_type, entity_id, stage, code_version) where job_id is null
    do update set
        outcome     = excluded.outcome,
        method      = excluded.method,
        confidence  = excluded.confidence,
        model_id    = excluded.model_id,
        cost_cents  = excluded.cost_cents,
        error_code  = excluded.error_code,
        job_id      = excluded.job_id,
        state       = excluded.state,
        payload     = excluded.payload,
        started_at  = now(),
        finished_at = excluded.finished_at
"""

# Run-member UPDATE (job_id IS NOT NULL). The member row was inserted 'pending'
# by add_run_items; the worker fills in the outcome + terminal state in place,
# keyed on membership (job_id, entity, stage), NOT on code_version — so it never
# collides with a prior run's row for the same entity. outcome_payload (carrying
# why_added) is deliberately left untouched.
_UPDATE_MEMBER_SQL = """
    update job_items set
        code_version = %s,
        outcome      = %s,
        method       = %s,
        confidence   = %s,
        model_id     = %s,
        cost_cents   = %s,
        error_code   = %s,
        state        = %s,
        payload      = %s,
        started_at   = now(),
        finished_at  = coalesce(%s, now())
    where job_id = %s and entity_type = %s and entity_id = %s and stage = %s
"""


def _default_state(outcome: str) -> str:
    """The auto-mode terminal state for an outcome (used when a caller does not
    pass an explicit ``state``)."""
    if outcome == "resolved":
        return "applied"
    if outcome == "failed":
        return "failed"
    return "flagged"


def _upsert_params(
    *,
    entity_type: str,
    entity_id: int,
    stage: str,
    version: str,
    outcome: str,
    method: str,
    state: str | None = None,
    confidence: float | None = None,
    model_id: str | None = None,
    cost_cents: float | None = None,
    error_code: str | None = None,
    job_id: int | None = None,
    payload: Any | None = None,
    finished_at: Any | None = None,
) -> tuple:
    return (
        entity_type, entity_id, stage, version, outcome, method,
        confidence, model_id, cost_cents, error_code, job_id,
        state or _default_state(outcome),
        Json(payload) if payload is not None else None, finished_at,
    )


def _member_params(
    *,
    entity_type: str,
    entity_id: int,
    stage: str,
    version: str,
    outcome: str,
    method: str,
    state: str | None = None,
    confidence: float | None = None,
    model_id: str | None = None,
    cost_cents: float | None = None,
    error_code: str | None = None,
    job_id: int | None = None,
    payload: Any | None = None,
    finished_at: Any | None = None,
) -> tuple:
    return (
        version, outcome, method, confidence, model_id, cost_cents, error_code,
        state or _default_state(outcome),
        Json(payload) if payload is not None else None, finished_at,
        job_id, entity_type, entity_id, stage,
    )


def record_run(conn, **kwargs) -> None:
    """Record one stage outcome for an entity.

    When ``job_id`` is set the entity is a run MEMBER (added by add_run_items);
    the member row is UPDATEd in place with the outcome + terminal ``state``.
    When ``job_id`` is None (the CLI cold-build) the row is UPSERTed into the
    append-versioned ledger. ``finished_at`` defaults to now() when not supplied.
    """
    if kwargs.get("job_id") is not None:
        conn.execute(_UPDATE_MEMBER_SQL, _member_params(**kwargs))
    else:
        conn.execute(_UPSERT_LEDGER_SQL, _upsert_params(**kwargs))


def record_runs(conn, rows: Sequence[dict[str, Any]]) -> None:
    """Batch form of ``record_run``: one round-trip per SQL shape. Rows with a
    ``job_id`` UPDATE their member row; rows without one UPSERT the cold-build
    ledger. Each group is a single ``executemany`` (psycopg pipelines the batch).
    The caller owns the transaction (wrap a chunk in ``conn.transaction()``)."""
    members = [r for r in rows if r.get("job_id") is not None]
    ledger_rows = [r for r in rows if r.get("job_id") is None]
    with conn.cursor() as cur:
        if members:
            cur.executemany(_UPDATE_MEMBER_SQL, [_member_params(**r) for r in members])
        if ledger_rows:
            cur.executemany(_UPSERT_LEDGER_SQL, [_upsert_params(**r) for r in ledger_rows])


def work_queue(
    conn,
    *,
    content_table: str,
    entity_type: str,
    stage: str,
    version: str,
    where: str | None = None,
    params: Sequence[Any] = (),
    limit: int | None = None,
) -> list[int]:
    """Ids from ``content_table`` that qualify for ``stage`` but have no run at
    ``version``.

    The NOT-EXISTS predicate is the generalization of every ``get_pending_*``
    query: an entity is queued when no job_items row exists for it at the
    current version. The ledger is append-versioned (≤1 row per (entity, stage,
    version), history kept), so an entity whose only rows are at older versions
    still qualifies — the predicate keys on the current version, so prior-version
    history rows don't mask it.

    The ledger stays content-agnostic: the caller supplies ``content_table`` and
    an optional ``where``/``params`` prefilter over the content row (aliased
    ``c``) — e.g. ``where="c.state = %s", params=("extracted",)`` or a site
    scope. No content column is hardcoded here.
    """
    sql = f"""
        select c.id
        from {content_table} c
        where not exists (
            select 1 from job_items r
            where r.entity_type = %s
              and r.entity_id   = c.id
              and r.stage       = %s
              and r.code_version = %s
        )
    """
    qparams: list[Any] = [entity_type, stage, version]
    if where:
        sql += f" and ({where})"
        qparams.extend(params)
    sql += " order by c.id"
    if limit is not None:
        sql += " limit %s"
        qparams.append(limit)
    return [r[0] for r in conn.execute(sql, qparams).fetchall()]



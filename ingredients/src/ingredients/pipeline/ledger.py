"""job_items run-ledger access.

One polymorphic ledger for every pipeline stage, in two modes:

- **run member** (``job_id`` set): the row was inserted ``pending`` when the
  operator loaded the run; the stage fills in the outcome + terminal ``state``
  in place, keyed on membership ``(job_id, entity, stage)``.
- **cold-build ledger** (``job_id`` None): the CLI path UPSERTs one row per
  ``(entity_type, entity_id, stage, code_version)`` — append-versioned, so an
  entity re-qualifies for ``work_queue`` only after a version bump.

All functions take a :class:`common.db.Connection` and do not commit on their
own; the caller owns the transaction boundary (statements outside a
``transaction()`` block autocommit).
"""

from __future__ import annotations

from typing import Any, Sequence

from common.db import jdump, jlist

_NOW = "strftime('%Y-%m-%dT%H:%M:%fZ','now')"

_UPSERT_LEDGER_SQL = f"""
    insert into job_items (
        entity_type, entity_id, stage, code_version, outcome, method,
        confidence, model_id, cost_cents, error_code, job_id, state,
        payload, finished_at
    )
    values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, coalesce(?, {_NOW}))
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
        started_at  = {_NOW},
        finished_at = excluded.finished_at
"""

_UPDATE_MEMBER_SQL = f"""
    update job_items set
        code_version = ?,
        outcome      = ?,
        method       = ?,
        confidence   = ?,
        model_id     = ?,
        cost_cents   = ?,
        error_code   = ?,
        state        = ?,
        payload      = ?,
        started_at   = {_NOW},
        finished_at  = coalesce(?, {_NOW})
    where job_id = ? and entity_type = ? and entity_id = ? and stage = ?
"""


def _default_state(outcome: str) -> str:
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
        jdump(payload), finished_at,
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
        jdump(payload), finished_at,
        job_id, entity_type, entity_id, stage,
    )


def record_run(conn, **kwargs) -> None:
    """Record one stage outcome for an entity (member UPDATE when ``job_id`` is
    set, ledger UPSERT otherwise). ``finished_at`` defaults to now."""
    if kwargs.get("job_id") is not None:
        conn.execute(_UPDATE_MEMBER_SQL, _member_params(**kwargs))
    else:
        conn.execute(_UPSERT_LEDGER_SQL, _upsert_params(**kwargs))


def record_runs(conn, rows: Sequence[dict[str, Any]]) -> None:
    """Batch form of ``record_run``: one ``executemany`` per SQL shape."""
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
    """Ids from ``content_table`` (aliased ``c``) that have no run at
    ``version`` for ``stage`` — the cold-build NOT-EXISTS queue. ``where`` is an
    optional extra predicate over ``c`` with ``?`` placeholders."""
    sql = f"""
        select c.id
        from {content_table} c
        where not exists (
            select 1 from job_items r
            where r.entity_type = ?
              and r.entity_id   = c.id
              and r.stage       = ?
              and r.code_version = ?
        )
    """
    qparams: list[Any] = [entity_type, stage, version]
    if where:
        sql += f" and ({where})"
        qparams.extend(params)
    sql += " order by c.id"
    if limit is not None:
        sql += " limit ?"
        qparams.append(limit)
    return [r[0] for r in conn.execute(sql, qparams).fetchall()]


def latest_status(conn, *, stage: str, entity_ids: Sequence[int]) -> dict[int, str]:
    """The most recent terminal ``state`` per entity for ``stage``
    (``applied`` / ``flagged`` / ``failed``); entities with no terminal row are
    absent. This is the derived "current status of X at stage Y" index."""
    if not entity_ids:
        return {}
    rows = conn.execute(
        """
        select entity_id, state from (
            select entity_id, state,
                   row_number() over (partition by entity_id order by id desc) as rn
            from job_items
            where stage = ? and state in ('applied', 'flagged', 'failed')
              and entity_id in (select value from json_each(?))
        ) where rn = 1
        """,
        (stage, jlist(entity_ids)),
    ).fetchall()
    return {r[0]: r[1] for r in rows}

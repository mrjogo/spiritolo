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


_RECORD_RUN_SQL = """
    insert into job_items (
        entity_type, entity_id, stage, code_version, outcome, method,
        confidence, model_id, cost_cents, error_code, job_id,
        payload, finished_at
    )
    values (
        %s, %s, %s, %s, %s, %s,
        %s, %s, %s, %s, %s,
        %s, coalesce(%s, now())
    )
    on conflict (entity_type, entity_id, stage, code_version) do update set
        outcome     = excluded.outcome,
        method      = excluded.method,
        confidence  = excluded.confidence,
        model_id    = excluded.model_id,
        cost_cents  = excluded.cost_cents,
        error_code  = excluded.error_code,
        job_id      = excluded.job_id,
        payload     = excluded.payload,
        started_at  = now(),
        finished_at = excluded.finished_at
"""


def _record_run_params(
    *,
    entity_type: str,
    entity_id: int,
    stage: str,
    version: str,
    outcome: str,
    method: str,
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
        Json(payload) if payload is not None else None, finished_at,
    )


def record_run(conn, **kwargs) -> None:
    """UPSERT the run for ``(entity_type, entity_id, stage, version)``.

    Append-versioned: re-running at the SAME version overwrites that version's
    row in place, but a NEW version inserts a new row — so a bump keeps the prior
    version's decision (in ``payload``) instead of destroying it. ``finished_at``
    defaults to now() when not supplied. See ``_record_run_params`` for keywords.
    """
    conn.execute(_RECORD_RUN_SQL, _record_run_params(**kwargs))


def record_runs(conn, rows: Sequence[dict[str, Any]]) -> None:
    """Batch form of ``record_run``: UPSERT one job_items row per dict in
    ``rows`` (each dict is the keyword set ``record_run`` takes) in a single
    ``executemany``. psycopg pipelines the batch, so a chunk of N recipes is one
    round-trip's worth of latency instead of N — the whole point of chunking a
    stage's ledger writes. The caller owns the transaction (wrap a chunk in
    ``conn.transaction()`` so it commits once)."""
    params = [_record_run_params(**row) for row in rows]
    if not params:
        return
    with conn.cursor() as cur:
        cur.executemany(_RECORD_RUN_SQL, params)


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


def reset(
    conn,
    *,
    stage: str,
    except_version: str | None = None,
    entity_type: str | None = None,
    site: str | None = None,
    content_table: str | None = None,
    older_than: str | None = None,
    gating: tuple[str, str] | None = None,
) -> int:
    """Delete ``stage`` run rows (re-queuing their entities); return the count.

    Filters (all optional, ANDed): ``except_version`` keeps rows at that version,
    ``entity_type`` scopes to one entity kind, ``site`` scopes to one source (via
    ``content_table``, which must be given when ``site`` is), ``older_than`` keeps
    rows finished on/after the cutoff. When ``gating=(table, column)`` is given
    (e.g. ('pages', 'content_type') for classify), that cursor is nulled in the
    SAME transaction as the delete — so a failure in either half rolls back both
    and an entity is never stranded out of both the queue and the ledger.
    """
    with conn.transaction():
        clauses = ["stage = %s"]
        params: list[Any] = [stage]
        if except_version is not None:
            clauses.append("code_version <> %s")
            params.append(except_version)
        if entity_type is not None:
            clauses.append("entity_type = %s")
            params.append(entity_type)
        if older_than is not None:
            clauses.append("finished_at < %s::timestamptz")
            params.append(older_than)
        if site is not None:
            if content_table is None:
                raise ValueError("site scope requires content_table")
            clauses.append(
                f"entity_id in (select id from {content_table} where site = %s)"
            )
            params.append(site)

        cur = conn.execute(
            f"delete from job_items where {' and '.join(clauses)}", params
        )
        deleted = cur.rowcount

        if gating is not None:
            gtable, gcolumn = gating
            gparams: list[Any] = []
            gwhere = ""
            if site is not None:
                gwhere = " where site = %s"
                gparams.append(site)
            conn.execute(f"update {gtable} set {gcolumn} = null{gwhere}", gparams)

    return deleted

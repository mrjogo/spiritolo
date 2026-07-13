"""stage_runs run-ledger access.

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


def record_run(
    conn,
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
    batch_id: int | None = None,
    job_id: int | None = None,
    payload: Any | None = None,
    finished_at: Any | None = None,
) -> None:
    """UPSERT the latest run for ``(entity_type, entity_id, stage)``.

    On conflict the row is overwritten in place (version/outcome/method/… all
    take the new values), so exactly one row per (entity, stage) ever exists.
    ``finished_at`` defaults to now() when not supplied — a recorded run is a
    completed run.
    """
    conn.execute(
        """
        insert into stage_runs (
            entity_type, entity_id, stage, version, outcome, method,
            confidence, model_id, cost_cents, error_code, batch_id, job_id,
            payload, finished_at
        )
        values (
            %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s,
            %s, coalesce(%s, now())
        )
        on conflict (entity_type, entity_id, stage) do update set
            version     = excluded.version,
            outcome     = excluded.outcome,
            method      = excluded.method,
            confidence  = excluded.confidence,
            model_id    = excluded.model_id,
            cost_cents  = excluded.cost_cents,
            error_code  = excluded.error_code,
            batch_id    = excluded.batch_id,
            job_id      = excluded.job_id,
            payload     = excluded.payload,
            started_at  = now(),
            finished_at = excluded.finished_at
        """,
        (
            entity_type, entity_id, stage, version, outcome, method,
            confidence, model_id, cost_cents, error_code, batch_id, job_id,
            Json(payload) if payload is not None else None, finished_at,
        ),
    )


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
    query: an entity is queued when no stage_runs row exists for it at the
    current version. Because the unique key guarantees ≤1 row per (entity,
    stage), an entity whose row is left at an older version is automatically
    included — no history rows to filter.

    The ledger stays content-agnostic: the caller supplies ``content_table`` and
    an optional ``where``/``params`` prefilter over the content row (aliased
    ``c``) — e.g. ``where="c.state = %s", params=("extracted",)`` or a site
    scope. No content column is hardcoded here.
    """
    sql = f"""
        select c.id
        from {content_table} c
        where not exists (
            select 1 from stage_runs r
            where r.entity_type = %s
              and r.entity_id   = c.id
              and r.stage       = %s
              and r.version     = %s
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
            clauses.append("version <> %s")
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
            f"delete from stage_runs where {' and '.join(clauses)}", params
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

"""Shared plumbing for the pipeline stages.

A stage_fn resolves its work queue from the ledger, processes each entity, and
records exactly one `stage_runs` row per entity (latest-only UPSERT). `scope`
pulls the `{site, limit}` filter a job carries in its payload; `queue` is the
NOT-EXISTS-a-run-at-this-version predicate over a content table.
"""

from __future__ import annotations

from typing import Any

import psycopg

from ingredients.pipeline import ledger

ENTITY_RECIPE = "recipe"


def scope(job: dict[str, Any]) -> tuple[str | None, int | None]:
    """(site, limit) from a job's payload; both optional."""
    payload = job.get("payload") or {}
    return payload.get("site"), payload.get("limit")


def recipe_queue(
    conn: psycopg.Connection,
    *,
    stage: str,
    version: str,
    site: str | None,
    limit: int | None,
    extra_where: str | None = None,
    extra_params: tuple[Any, ...] = (),
) -> list[int]:
    """Recipe ids with no `stage_runs` row for (stage, version), optionally
    scoped by site and an extra content predicate over the `c` alias."""
    where = None
    params: list[Any] = []
    clauses: list[str] = []
    if site is not None:
        clauses.append("c.site = %s")
        params.append(site)
    if extra_where:
        clauses.append(extra_where)
        params.extend(extra_params)
    if clauses:
        where = " and ".join(clauses)
    return ledger.work_queue(
        conn,
        content_table="recipes",
        entity_type=ENTITY_RECIPE,
        stage=stage,
        version=version,
        where=where,
        params=tuple(params),
        limit=limit,
    )


def record(
    conn: psycopg.Connection,
    *,
    recipe_id: int,
    stage: str,
    version: str,
    outcome: str,
    method: str,
    job_id: int | None = None,
    cost_cents: float | None = None,
    model_id: str | None = None,
    error_code: str | None = None,
    payload: Any | None = None,
) -> None:
    """UPSERT the recipe's `stage_runs` row for this stage/version."""
    ledger.record_run(
        conn,
        entity_type=ENTITY_RECIPE,
        entity_id=recipe_id,
        stage=stage,
        version=version,
        outcome=outcome,
        method=method,
        job_id=job_id,
        cost_cents=cost_cents,
        model_id=model_id,
        error_code=error_code,
        payload=payload,
    )

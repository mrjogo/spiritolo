"""Shared plumbing for the pipeline stages.

A stage_fn resolves its work queue from the ledger, processes each entity, and
records exactly one `job_items` row per entity (latest-only UPSERT). `scope`
pulls the `{site, limit}` filter a job carries in its payload; `queue` is the
NOT-EXISTS-a-run-at-this-version predicate over a content table.
"""

from __future__ import annotations

from typing import Any, Iterable, Iterator, Sequence

import psycopg

from ingredients.pipeline import ledger

ENTITY_RECIPE = "recipe"

# Recipes per transaction/batch. A stage collects a chunk's writes, flushes them
# with bulk statements + one ledger executemany, and commits once — turning ~N
# per-recipe round-trips into ~a handful per chunk over the remote pooler.
CHUNK_SIZE = 200


def chunked(seq: Sequence[Any], size: int = CHUNK_SIZE) -> Iterator[list[Any]]:
    """Yield ``seq`` in lists of at most ``size``."""
    for i in range(0, len(seq), size):
        yield list(seq[i : i + size])


def scope(job: dict[str, Any]) -> tuple[str | None, int | None]:
    """(site, limit) from a job's payload; both optional."""
    payload = job.get("payload") or {}
    return payload.get("site"), payload.get("limit")


def run_item_ids(conn: psycopg.Connection, *, job_id: int, stage: str) -> list[int]:
    """The entity ids of a run's *pending* members for ``stage``.

    This is the explicit-run queue: when a stage_fn is dispatched for a real job
    it processes exactly the entities the operator loaded into that run (added by
    the add_run_items RPC as 'pending' job_items), instead of re-deriving a
    version NOT-EXISTS predicate over the whole content table. Ordered by
    entity_id for stable chunking."""
    rows = conn.execute(
        "select entity_id from job_items "
        "where job_id = %s and stage = %s and state = 'pending' "
        "order by entity_id",
        (job_id, stage),
    ).fetchall()
    return [r[0] for r in rows]


def item_state(outcome: str, apply_mode: str = "auto") -> str:
    """The terminal job_item ``state`` for a stage outcome under a run's
    apply_mode.

    - ``resolved`` -> ``applied`` for an auto run, ``pending_apply`` for a hold
      run (the result is computed but held for a human to bulk-apply).
    - ``failed``   -> ``failed``.
    - anything parked (``pending`` / ``abstain`` / ``proposes_new``) -> ``flagged``
      (no content written; needs an LLM or human pass)."""
    if outcome == "resolved":
        return "applied" if apply_mode == "auto" else "pending_apply"
    if outcome == "failed":
        return "failed"
    return "flagged"


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
    """Recipe ids with no `job_items` row for (stage, version), optionally
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
    apply_mode: str = "auto",
    job_id: int | None = None,
    cost_cents: float | None = None,
    model_id: str | None = None,
    error_code: str | None = None,
    payload: Any | None = None,
) -> None:
    """Record the recipe's `job_items` outcome for this stage/version.

    For a run member (``job_id`` set) the pending member row is UPDATEd to its
    terminal ``state`` (per ``apply_mode``); for the cold-build (``job_id`` None)
    the append-versioned ledger row is UPSERTed."""
    ledger.record_run(
        conn,
        entity_type=ENTITY_RECIPE,
        entity_id=recipe_id,
        stage=stage,
        version=version,
        outcome=outcome,
        method=method,
        state=item_state(outcome, apply_mode),
        job_id=job_id,
        cost_cents=cost_cents,
        model_id=model_id,
        error_code=error_code,
        payload=payload,
    )


def finalize_run(
    conn: psycopg.Connection, *, stage: str, version: str, ids: Sequence[str]
) -> None:
    """Close out a stage run over ``ids`` (touched entities, at the stage's review
    grain — recipe-id-strings for recipe stages, names for map).

    The one uniform post-run step: re-apply any resolved human overrides the
    auto-compute may have clobbered (pin survives rerun). ``reapply`` only touches
    *resolved* overrides, so freshly-opened machine proposals for the same
    entities are untouched. Superseding stale proposals is a resolution-aware,
    per-stage concern (see ``reviews.reapply.supersede_stale``) and is invoked
    explicitly by a stage over the ids it actually resolved, not blanket-applied
    here.
    """
    from ingredients.reviews.reapply import reapply_overrides

    reapply_overrides(conn, stage=stage, ids=ids)


def record_many(
    conn: psycopg.Connection,
    records: Iterable[dict[str, Any]],
    *,
    apply_mode: str = "auto",
) -> None:
    """Batch form of ``record`` for a chunk of recipes. Each dict carries
    ``recipe_id`` plus the same keywords ``record`` takes (stage, version,
    outcome, method, and optional job_id/payload/error_code/…). Member rows
    (``job_id`` set) UPDATE their pending row to the terminal ``state`` derived
    from the outcome + ``apply_mode``; cold-build rows UPSERT the ledger. Wrap the
    chunk in ``conn.transaction()`` to commit once."""
    ledger.record_runs(
        conn,
        [
            {
                "entity_type": ENTITY_RECIPE,
                "entity_id": r["recipe_id"],
                "state": item_state(r["outcome"], apply_mode),
                **{k: v for k, v in r.items() if k != "recipe_id"},
            }
            for r in records
        ],
    )

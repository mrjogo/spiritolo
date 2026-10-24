"""Shared plumbing for the pipeline stages.

A stage_fn resolves its work queue (the run's pending members, or the cold-build
NOT-EXISTS queue), processes each entity, and records exactly one `job_items`
row per entity. `scope` pulls the `{site, limit}` filter a job carries in its
payload.
"""

from __future__ import annotations

from typing import Any, Iterable, Iterator, Sequence

from common.db import Connection, jlist

from ingredients.pipeline import ledger

ENTITY_RECIPE = "recipe"
ENTITY_TAXONOMY_NODE = "taxonomy_node"

# Recipes per transaction/batch. Local SQLite has no round-trip cost to amortize,
# but one commit per chunk still bounds the transaction size and keeps a cancel
# responsive.
CHUNK_SIZE = 200


def chunked(seq: Sequence[Any], size: int = CHUNK_SIZE) -> Iterator[list[Any]]:
    """Yield ``seq`` in lists of at most ``size``."""
    for i in range(0, len(seq), size):
        yield list(seq[i : i + size])


def scope(job: dict[str, Any]) -> tuple[str | None, int | None]:
    """(site, limit) from a job's payload; both optional."""
    payload = job.get("payload") or {}
    if isinstance(payload, str):  # a raw row's JSON text
        from common.db import jload
        payload = jload(payload, {})
    return payload.get("site"), payload.get("limit")


def run_item_ids(conn: Connection, *, job_id: int, stage: str) -> list[int]:
    """The entity ids of a run's *pending* members for ``stage`` — the explicit
    run queue, ordered by entity_id for stable chunking."""
    rows = conn.execute(
        "select entity_id from job_items "
        "where job_id = ? and stage = ? and state = 'pending' "
        "order by entity_id",
        (job_id, stage),
    ).fetchall()
    return [r[0] for r in rows]


def item_state(outcome: str) -> str:
    """The terminal job_item ``state`` for a stage outcome: ``resolved`` ->
    ``applied``, ``failed`` -> ``failed``, anything parked -> ``flagged``."""
    if outcome == "resolved":
        return "applied"
    if outcome == "failed":
        return "failed"
    return "flagged"


def recipe_queue(
    conn: Connection,
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
        clauses.append("c.site = ?")
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


def node_queue(
    conn: Connection,
    *,
    stage: str,
    version: str,
    broad: bool = False,
    limit: int | None = None,
) -> list[int]:
    """taxonomy_node ids with no `job_items` row for (stage, version). By
    default the provisional residue; ``broad=True`` covers the live set too."""
    where = None if broad else "c.status = 'provisional'"
    return ledger.work_queue(
        conn,
        content_table="taxonomy_nodes",
        entity_type=ENTITY_TAXONOMY_NODE,
        stage=stage,
        version=version,
        where=where,
        limit=limit,
    )


def recipes_with_provisional_ingredients(
    conn: Connection, recipe_ids: list[int]
) -> set[int]:
    """The subset of ``recipe_ids`` with at least one ingredient resolved to a
    ``status='provisional'`` node — not yet eligible for cluster/convert/export."""
    if not recipe_ids:
        return set()
    rows = conn.execute(
        "select distinct ri.recipe_id "
        "from recipe_ingredients ri "
        "join ingredient_resolutions ir "
        "  on lower(trim(ri.name)) = ir.normalized_name "
        "join taxonomy_nodes n on n.slug = ir.taxonomy_slug "
        "where ri.recipe_id in (select value from json_each(?)) and n.status = 'provisional'",
        (jlist(recipe_ids),),
    ).fetchall()
    return {r[0] for r in rows}


def record(
    conn: Connection,
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
    """Record the recipe's `job_items` outcome for this stage/version."""
    ledger.record_run(
        conn,
        entity_type=ENTITY_RECIPE,
        entity_id=recipe_id,
        stage=stage,
        version=version,
        outcome=outcome,
        method=method,
        state=item_state(outcome),
        job_id=job_id,
        cost_cents=cost_cents,
        model_id=model_id,
        error_code=error_code,
        payload=payload,
    )


def record_node(
    conn: Connection,
    *,
    node_id: int,
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
    """Record a taxonomy node's `job_items` outcome for this stage/version."""
    ledger.record_run(
        conn,
        entity_type=ENTITY_TAXONOMY_NODE,
        entity_id=node_id,
        stage=stage,
        version=version,
        outcome=outcome,
        method=method,
        state=item_state(outcome),
        job_id=job_id,
        cost_cents=cost_cents,
        model_id=model_id,
        error_code=error_code,
        payload=payload,
    )


def finalize_run(
    conn: Connection, *, stage: str, version: str, ids: Sequence[str]
) -> None:
    """Close out a stage run over ``ids``: re-apply any resolved human
    overrides the auto-compute may have clobbered (the pin survives a rerun)."""
    from ingredients.reviews.reapply import reapply_overrides

    reapply_overrides(conn, stage=stage, ids=ids)


def record_many(
    conn: Connection,
    records: Iterable[dict[str, Any]],
) -> None:
    """Batch form of ``record`` for a chunk of recipes."""
    ledger.record_runs(
        conn,
        [
            {
                "entity_type": ENTITY_RECIPE,
                "entity_id": r["recipe_id"],
                "state": item_state(r["outcome"]),
                **{k: v for k, v in r.items() if k != "recipe_id"},
            }
            for r in records
        ],
    )

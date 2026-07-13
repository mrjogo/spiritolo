"""Claim the next runnable job.

``claim_one`` is a single ``UPDATE ... WHERE id = (SELECT ... FOR UPDATE SKIP
LOCKED LIMIT 1) RETURNING *``: two workers running it concurrently each get a
distinct row and neither blocks on the other. It is a pure function over a
psycopg connection — the caller owns the transaction (commit on success, roll
back on failure), which is what makes the SKIP-LOCKED contention test possible
(both connections hold their row locks until they commit).

The claim predicate mirrors the ``jobs_claimable_idx`` partial index:

    state = 'queued'
    AND (NOT requires_approval OR approved)          -- approval gate
    AND (cost_estimate_cents IS NULL                 -- free work, or
         OR cost_estimate_cents <= :max_cost_cents)  -- within the worker budget

so a metered job whose estimate exceeds the worker's ``max_cost_cents`` budget
(or that has no budget at all) is left on the queue.
"""
from __future__ import annotations

from typing import Any

import psycopg
from psycopg.rows import dict_row

_CLAIM_SQL = """
update jobs
set state          = 'running',
    worker_id      = %(worker_id)s,
    started_at     = now(),
    last_heartbeat = now()
where id = (
    select id
    from jobs
    where state = 'queued'
      and (not requires_approval or approved)
      and (cost_estimate_cents is null
           or cost_estimate_cents <= %(max_cost_cents)s)
    order by created_at
    for update skip locked
    limit 1
)
returning *
"""


def claim_one(
    conn: psycopg.Connection,
    *,
    worker_id: str | None = None,
    max_cost_cents: int | None = None,
) -> dict[str, Any] | None:
    """Claim the oldest runnable job, or return ``None`` if none is claimable.

    Does not commit — the caller's transaction boundary holds the row lock (see
    module docstring). Returns the claimed row as a dict (``state`` is already
    flipped to ``'running'`` with ``worker_id`` / ``started_at`` / heartbeat set).
    """
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            _CLAIM_SQL,
            {"worker_id": worker_id, "max_cost_cents": max_cost_cents},
        )
        return cur.fetchone()


def heartbeat(conn: psycopg.Connection, job_id: int) -> None:
    """Bump ``last_heartbeat`` on a running job so the reaper leaves it alone."""
    with conn.cursor() as cur:
        cur.execute(
            "update jobs set last_heartbeat = now() where id = %s",
            (job_id,),
        )

"""Requeue stale-heartbeat jobs.

The reaper is the entire retry story: a worker that dies mid-job (Railway
restart, crash) stops heartbeating, so its in-flight job's ``last_heartbeat``
goes stale; ``requeue_stale`` flips it back to ``'queued'`` (clearing worker_id
/ started_at) so another worker picks it up. Safe to re-run because stage writes
are idempotent UPSERTs and the state filter makes a second pass a no-op — a job
already back at ``'queued'`` no longer matches ``state in ('claimed','running')``.

Pure function over a psycopg connection; the caller owns the transaction. On an
autocommit connection each call is its own transaction.
"""
from __future__ import annotations

import psycopg

_REQUEUE_SQL = """
update jobs
set state      = 'queued',
    worker_id  = null,
    started_at = null
where state in ('claimed', 'running')
  and last_heartbeat is not null
  and last_heartbeat < now() - make_interval(secs => %(secs)s)
returning id
"""


def requeue_stale(
    conn: psycopg.Connection,
    *,
    older_than_seconds: float = 120,
) -> int:
    """Requeue every claimed/running job whose heartbeat is older than
    ``older_than_seconds``. Returns the number of jobs requeued."""
    with conn.cursor() as cur:
        cur.execute(_REQUEUE_SQL, {"secs": float(older_than_seconds)})
        return len(cur.fetchall())

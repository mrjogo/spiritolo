"""Postgres-as-queue client helpers (WS-B22).

Thin, pure functions over a psycopg connection — no broker, no scheduler. The
worker (WS-B23) composes them into its claim/heartbeat/reap loop; tests drive
them against a real Postgres via TEST_DB_URL.

- ``claim_one`` — atomically claim the oldest runnable job (FOR UPDATE SKIP
  LOCKED), respecting the approval + max-cost gates.
- ``heartbeat`` — bump ``last_heartbeat`` on a running job.
- ``requeue_stale`` — the reaper: put stale-heartbeat jobs back on the queue.
"""
from __future__ import annotations

from ingredients.queue.claim import claim_one, heartbeat
from ingredients.queue.reaper import requeue_stale

__all__ = ["claim_one", "heartbeat", "requeue_stale"]

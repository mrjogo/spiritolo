"""Worker actor-context helper for the audit log.

The audit trigger (``audit.log_change``) derives ``actor_kind='worker'`` from
the transaction-local GUC ``app.job_id`` and records ``app.source`` verbatim.
A worker job transaction calls :func:`set_job_context` at the top of the txn so
every mutation it makes is attributed to the originating job (and, through the
``jobs`` row, to the ``stage_runs`` row that caused it) rather than to 'system'.

The GUCs are set with ``set_config(..., is_local => true)`` — i.e. ``SET LOCAL``
— so the attribution is transaction-scoped and clears automatically at
commit/rollback. A job therefore cannot leak its identity onto a later
transaction sharing the same pooled connection.
"""
from __future__ import annotations

from typing import Any


def set_job_context(conn: Any, job_id: Any, source: str) -> None:
    """Attribute subsequent writes in the CURRENT transaction to a worker job.

    Issues ``SET LOCAL app.job_id`` / ``app.source`` (via ``set_config(...,
    true)``) so the audit trigger records ``actor_kind='worker'``,
    ``actor_id=<job_id>``, ``source=<source>``.

    Must be called inside an open transaction — ``is_local => true`` is a no-op
    outside one (and the audit attribution would silently fall back to
    'system'). ``job_id`` is coerced to text; ``source`` is stored verbatim
    (convention: ``'job:<stage>'``).
    """
    conn.execute(
        "select set_config('app.job_id', %s, true), "
        "       set_config('app.source', %s, true)",
        (str(job_id), source),
    )

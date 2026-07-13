"""Boot-time reconciliation of open ``job_batches``.

A metered stage can submit its per-item requests to a hosted provider's async
Batch API — half price, ~24h SLA — instead of paying real-time. Each submission
is a ``job_batches`` row (state ``submitted``) whose ``custom_id_map`` ties every
request's opaque ``custom_id`` back to a descriptor of the entity + stage the
answer belongs to::

    {"<custom_id>": {"entity_type": "recipe", "entity_id": 101,
                     "stage": "map", "version": "v1"}}

On boot the worker calls :func:`reconcile`, which polls each *open* batch
(``submitted`` / ``in_progress``) through an injected provider ``client``:

- a batch the provider still reports open stays open (its DB state is advanced
  to what the provider reports) and writes nothing;
- a ``completed`` batch is ingested — one ``stage_runs`` UPSERT per resolved
  ``custom_id`` (keyed through ``custom_id_map``, reusing the ledger writer) —
  and the batch flips to ``ingested``. A ``custom_id`` the provider dropped or
  errored on gets no ledger row, so its entity falls back onto the normal work
  queue (a missing run row re-queues the entity); the count is reported in the
  returned summary;
- a ``failed`` batch flips to ``failed``.

Reconcile is idempotent by the state guard: only open batches are selected, so
a batch that already reached a terminal state is never re-polled — a Railway
restart mid-reconcile is safe. The provider ``client`` is injected (a fake in
tests); the only OpenAI wiring lives in :class:`OpenAIBatchReconcileClient`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

import psycopg

from ingredients.pipeline.ledger import record_run

_OPEN_STATES = ("submitted", "in_progress")


@dataclass
class BatchItemResult:
    """One line of a completed batch's output, mapped by ``custom_id``.

    ``output`` is the provider's answer for this item (any JSON-able value);
    ``error`` is set instead when the provider errored on the line. An item
    absent from a completed batch's results is treated the same as an errored
    one — parked, not ingested.
    """

    custom_id: str
    output: Any | None = None
    error: str | None = None


@dataclass
class BatchPoll:
    """The provider's current view of a batch: its ``state`` and, once
    ``completed``, its per-item ``results``."""

    state: str
    results: list[BatchItemResult] = field(default_factory=list)


class BatchClient(Protocol):
    """The reconcile client seam: one method mapping a provider batch id to its
    current :class:`BatchPoll`. Injected — a fake in tests, the OpenAI adapter
    in production."""

    def get_batch(self, provider_batch_id: str) -> BatchPoll: ...


@dataclass
class ReconcileSummary:
    """What one :func:`reconcile` pass did — returned for logging/assertions."""

    batches_polled: int = 0
    batches_ingested: int = 0
    batches_failed: int = 0
    runs_written: int = 0
    parked: int = 0


def reconcile(conn: psycopg.Connection, client: BatchClient) -> ReconcileSummary:
    """Poll every open batch and ingest the completed ones. Idempotent."""
    summary = ReconcileSummary()
    open_batches = conn.execute(
        "select id, provider_batch_id, custom_id_map from job_batches "
        "where state in ('submitted', 'in_progress') order by id"
    ).fetchall()

    for batch_id, provider_batch_id, custom_id_map in open_batches:
        summary.batches_polled += 1
        poll = client.get_batch(provider_batch_id)

        if poll.state in _OPEN_STATES:
            _set_state(conn, batch_id, poll.state)
            continue
        if poll.state == "completed":
            written, parked = _ingest(conn, batch_id, custom_id_map, poll.results)
            summary.runs_written += written
            summary.parked += parked
            _set_state(conn, batch_id, "ingested")
            summary.batches_ingested += 1
            continue
        # Anything else the provider reports (failed / expired / cancelled) is
        # terminal; park the whole batch so it isn't polled again.
        _set_state(conn, batch_id, "failed")
        summary.batches_failed += 1

    if not conn.autocommit:
        conn.commit()
    return summary


def _ingest(
    conn: psycopg.Connection,
    batch_id: int,
    custom_id_map: dict[str, dict[str, Any]],
    results: list[BatchItemResult],
) -> tuple[int, int]:
    """UPSERT one stage_run per resolved custom_id; park the rest. Returns
    ``(written, parked)``."""
    by_custom_id = {r.custom_id: r for r in results}
    written = 0
    parked = 0
    for custom_id, desc in custom_id_map.items():
        result = by_custom_id.get(custom_id)
        if result is None or result.error is not None or result.output is None:
            parked += 1  # dropped/errored -> no row, entity re-queues
            continue
        record_run(
            conn,
            entity_type=desc["entity_type"],
            entity_id=int(desc["entity_id"]),
            stage=desc["stage"],
            version=desc["version"],
            outcome=desc.get("outcome", "resolved"),
            method=desc.get("method", "llm"),
            model_id=desc.get("model_id"),
            cost_cents=desc.get("cost_cents"),
            batch_id=batch_id,
            payload={"result": result.output},
        )
        written += 1
    return written, parked


def _set_state(conn: psycopg.Connection, batch_id: int, state: str) -> None:
    conn.execute(
        "update job_batches set state=%s, updated_at=now() where id=%s",
        (state, batch_id),
    )


def build_reconcile_hook(client: BatchClient):
    """Bind ``client`` into a ``reconcile_hook(conn)`` for ``loop.boot`` /
    ``loop.serve`` — the seam that runs reconcile before the claim loop."""

    def _hook(conn: psycopg.Connection) -> ReconcileSummary:
        return reconcile(conn, client)

    return _hook


# --- OpenAI wiring (the only provider wired; others carry a column but no code)


_OPENAI_STATE = {
    "validating": "in_progress",
    "in_progress": "in_progress",
    "finalizing": "in_progress",
    "completed": "completed",
    "failed": "failed",
    "expired": "failed",
    "cancelling": "in_progress",
    "cancelled": "failed",
}


@dataclass
class OpenAIBatchReconcileClient:
    """Adapt ``common.llm.openai_batch.OpenAIBatchProvider`` to the reconcile
    client seam.

    ``get_batch`` maps the OpenAI batch status to the reconcile state vocabulary
    and, when completed, materializes the output file into
    :class:`BatchItemResult`s (``raw_text`` carried as ``output``)."""

    provider: Any

    @classmethod
    def from_env(cls) -> "OpenAIBatchReconcileClient":
        from common.llm.openai_batch import OpenAIBatchProvider

        return cls(provider=OpenAIBatchProvider.from_env())

    def get_batch(self, provider_batch_id: str) -> BatchPoll:
        status = self.provider.status(provider_batch_id)
        state = _OPENAI_STATE.get(status.state, status.state)
        if state != "completed":
            return BatchPoll(state=state)
        results = [
            BatchItemResult(custom_id=r.custom_id, output=r.raw_text, error=r.error)
            for r in self.provider.fetch_results(provider_batch_id)
        ]
        return BatchPoll(state="completed", results=results)

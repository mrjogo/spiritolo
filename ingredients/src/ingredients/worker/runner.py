"""In-process run executor: claim one ``queued`` job, run its stage, finalize.

This replaces the always-on polling worker. The app owns a single executor
thread that calls :func:`run_next` whenever a run is started (and once at boot
to drain anything left ``queued``). There is exactly one writer process, so the
claim needs no ``SKIP LOCKED``, no heartbeat and no reaper: a job found
``running`` at boot was interrupted by a restart and is simply requeued
(:func:`requeue_interrupted`); its already-applied items stay terminal and the
rest are still ``pending``, so the re-run picks up where it stopped.

The lifecycle mirrors the old loop so the ``jobs`` row reads the same in /ops:

    queued -> running -> done | failed | cancelled

- ``progress`` is the stage_fn's returned counts; ``cost_actual_cents`` is the
  SUM of the job's ``job_items.cost_cents`` (recomputed, so a re-run overwrites
  rather than accumulates).
- Failures never escape: an unknown stage, a cost-cap abort, an unavailable
  provider or a stage exception each finalize the job ``failed`` with an
  ``error_code``.
- Cancellation is cooperative: ``cancel_run`` flips the row to ``cancelling``
  and trips the in-memory :class:`JobControl` event; the stage sees it as
  ``job["should_stop"]`` and bails at the next item boundary, after which the
  job finalizes ``cancelled`` with partial work kept.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Mapping
from typing import Any

from common.db import SQL_NOW, Connection, jdump, jload
from common.db.audit import set_actor

from ingredients.worker import dispatch
from ingredients.worker.cost import CostCapExceeded, CostMeter
from ingredients.worker.dispatch import UnknownStage
from ingredients.worker.providers import ProviderChain, ProviderUnavailable, pack_size_for
from ingredients.worker.providers_local import build_provider_for_run

log = logging.getLogger("ingredients.worker.runner")

# How often ``JobControl.should_stop`` re-reads ``jobs.state`` (a cancel issued
# from another process — the CLI — is only visible in the row).
CANCEL_POLL_SECONDS = 2.0


class JobControl:
    """Cooperative cancel signal for one running job: an in-memory event the
    API trips directly, backed by a throttled read of ``jobs.state`` so a
    cancel written by another process is seen too."""

    def __init__(self, conn: Connection, job_id: int, *, poll_seconds: float = CANCEL_POLL_SECONDS) -> None:
        self._conn = conn
        self._job_id = job_id
        self._poll = poll_seconds
        self._last_poll = 0.0
        self.event = threading.Event()

    def cancel(self) -> None:
        self.event.set()

    def should_stop(self) -> bool:
        if self.event.is_set():
            return True
        now = time.monotonic()
        if now - self._last_poll >= self._poll:
            self._last_poll = now
            try:
                row = self._conn.execute(
                    "select state from jobs where id = ?", (self._job_id,)
                ).fetchone()
            except Exception:  # noqa: BLE001 - a failed poll must not kill the run
                return False
            if row is not None and row[0] == "cancelling":
                self.event.set()
                return True
        return False


def requeue_interrupted(conn: Connection) -> int:
    """Put every ``running`` / ``cancelling`` job back to ``queued`` (boot-time
    recovery after a restart). Returns the count requeued."""
    cur = conn.execute(
        "update jobs set state = 'queued', worker_id = null, started_at = null "
        "where state in ('running', 'cancelling')"
    )
    if cur.rowcount:
        log.info("requeued %d interrupted job(s)", cur.rowcount)
    return cur.rowcount


def _job_row(row: Any) -> dict[str, Any]:
    job = row.asdict()
    job["payload"] = jload(job.get("payload"), {}) or {}
    job["progress"] = jload(job.get("progress"), {}) or {}
    return job


def claim_next(conn: Connection, *, worker_id: str | None = None) -> dict[str, Any] | None:
    """Move the oldest ``queued`` job to ``running`` and return it (or ``None``)."""
    with conn.transaction():
        row = conn.execute(
            "select * from jobs where state = 'queued' order by created_at, id limit 1"
        ).fetchone()
        if row is None:
            return None
        conn.execute(
            f"update jobs set state = 'running', started_at = {SQL_NOW}, worker_id = ?, "
            "finished_at = null, error_code = null, error_detail = null "
            "where id = ?",
            (worker_id, row["id"]),
        )
        row = conn.execute("select * from jobs where id = ?", (row["id"],)).fetchone()
    return _job_row(row)


def build_providers(
    job: Mapping[str, Any],
    *,
    env: Mapping[str, str] | None = None,
    client_factory: Callable[..., Any] | None = None,
) -> ProviderChain | None:
    """The run's ``ProviderChain`` from its chosen LLM tier, or ``None``.

    A run carries its tier on the job row: ``llm_provider`` selects the provider
    and ``llm_model`` the model (both set at run assembly). When the run names
    no provider — or its API key is absent from ``env`` — it runs
    deterministic-only (the alias/lexical tiers inside each stage_fn)."""
    provider_id = job.get("llm_provider")
    impl = build_provider_for_run(
        provider_id, job.get("llm_model"), env=env, client_factory=client_factory
    )
    if impl is None:
        return None
    return ProviderChain(
        tiers=[(provider_id, impl)],
        pack_size=pack_size_for(job["stage"]),
        meter=CostMeter(job.get("max_cost_cents")),
    )


def run_job(
    conn: Connection,
    job: dict[str, Any],
    *,
    stage_fns: dict[str, Callable[..., Any]] | None = None,
    providers_builder: Callable[[dict[str, Any]], Any] | None = None,
    env: Mapping[str, str] | None = None,
    client_factory: Callable[..., Any] | None = None,
    control: JobControl | None = None,
) -> str:
    """Dispatch an already-claimed ``running`` job and finalize it. Returns the
    terminal state (``done`` / ``failed`` / ``cancelled``)."""
    control = control or JobControl(conn, job["id"])
    job["should_stop"] = control.should_stop
    set_actor(conn, "worker", str(job["id"]), f"job:{job['stage']}")
    log.info(
        "running job %s (stage %s, provider %s)",
        job["id"], job["stage"], job.get("llm_provider") or "deterministic",
    )
    try:
        providers = (
            providers_builder(job) if providers_builder is not None
            else build_providers(job, env=env, client_factory=client_factory)
        )
        if providers is not None and hasattr(providers, "should_stop"):
            providers.should_stop = control.should_stop
        result = dispatch.run(job, conn, providers, stage_fns=stage_fns)
        if control.event.is_set():
            _finalize(conn, job, "cancelled")
        else:
            _finalize(conn, job, "done", progress=result if isinstance(result, dict) else {})
    except UnknownStage as exc:
        _finalize(conn, job, "failed", error_code="unknown_stage", detail=str(exc))
    except CostCapExceeded as exc:
        _finalize(conn, job, "failed", error_code="cost_cap_exceeded", detail=str(exc))
    except ProviderUnavailable as exc:
        _finalize(conn, job, "failed", error_code="provider_unavailable", detail=str(exc))
    except Exception as exc:  # noqa: BLE001 - a stage error must fail the job, never the executor
        log.exception("job %s (%s) failed", job["id"], job["stage"])
        _finalize(conn, job, "failed", error_code="stage_error", detail=_error_detail(exc))
    finally:
        set_actor(conn, "system", None, "executor")
    state = conn.execute("select state from jobs where id = ?", (job["id"],)).fetchone()[0]
    log.info("job %s (%s) -> %s", job["id"], job["stage"], state)
    return state


def run_next(conn: Connection, *, worker_id: str | None = None, **kwargs: Any) -> bool:
    """Claim + run one queued job. Returns ``False`` when the queue is empty."""
    job = claim_next(conn, worker_id=worker_id)
    if job is None:
        return False
    run_job(conn, job, **kwargs)
    return True


def drain(conn: Connection, **kwargs: Any) -> int:
    """Run queued jobs until none remain. Returns how many ran."""
    n = 0
    while run_next(conn, **kwargs):
        n += 1
    return n


def _error_detail(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}".splitlines()[0][:500]


def _finalize(
    conn: Connection,
    job: dict[str, Any],
    state: str,
    *,
    progress: dict[str, Any] | None = None,
    error_code: str | None = None,
    detail: str | None = None,
) -> None:
    # A stage may have died mid-transaction: roll back the open one first so the
    # finalize commits on its own. Items already committed survive.
    if conn.in_transaction:
        conn.rollback()
    conn.execute(
        f"""
        update jobs set
            state             = ?,
            finished_at       = {SQL_NOW},
            progress          = coalesce(?, progress),
            error_code        = ?,
            error_detail      = ?,
            cost_actual_cents = cast(round(coalesce(
                (select sum(cost_cents) from job_items where job_id = ?), 0)) as integer)
        where id = ?
        """,
        (state, jdump(progress) if progress is not None else None, error_code, detail,
         job["id"], job["id"]),
    )

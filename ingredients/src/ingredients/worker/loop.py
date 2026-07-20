"""Worker loop: boot + claim/dispatch/heartbeat/finalize tick.

``boot`` runs once at process start: it invokes the optional boot hook and
then the reaper (requeue jobs whose heartbeat went stale — the Railway-restart
retry story). ``tick`` is one pass of the run loop:

    claim_one  ->  commit the claim  ->  start a heartbeat thread
               ->  dispatch to the stage_fn  ->  stop the heartbeat
               ->  set terminal state + progress + cost_actual roll-up

``serve`` is the always-on process: boot, then tick forever, sleeping briefly
when the queue is empty. Everything is driven with fake stage_fns / fake
providers in tests — no live model, no live network.

Idempotency + safety come from the pieces this composes: the claim is
``FOR UPDATE SKIP LOCKED`` (queue/claim), the reaper is a no-op on a job already
requeued (queue/reaper), stage writes are latest-only ``job_items`` UPSERTs
(pipeline/ledger), and ``cost_actual_cents`` is recomputed as the SUM of the
job's ``job_items.cost_cents`` — so a rerun overwrites rather than accumulates.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Mapping
from typing import Any

import psycopg
from psycopg.types.json import Json

from ingredients.queue import claim_one, heartbeat as _heartbeat, requeue_stale
from ingredients.worker import dispatch
from ingredients.worker.cost import CostCapExceeded, CostMeter
from ingredients.worker.dispatch import UnknownStage
from ingredients.worker.providers import ProviderChain, ProviderUnavailable, pack_size_for
from ingredients.worker.providers_local import build_provider_for_run

log = logging.getLogger("ingredients.worker.loop")

DEFAULT_REAPER_SECONDS = 120.0
DEFAULT_HEARTBEAT_SECONDS = 15.0
DEFAULT_POLL_SECONDS = 2.0
DEFAULT_CANCEL_POLL_SECONDS = 3.0


class Heartbeat:
    """Background thread that bumps ``jobs.last_heartbeat`` while a job runs.

    It owns its OWN connection (psycopg connections are not shareable across
    threads) built from ``conn_factory``, and beats every ``interval`` seconds
    until ``stop()``. A dead worker simply stops beating, and the reaper takes
    over — so a swallowed error here degrades to the same retry path.
    """

    def __init__(
        self,
        conn_factory: Callable[[], psycopg.Connection],
        job_id: int,
        interval: float,
    ) -> None:
        self._conn_factory = conn_factory
        self._job_id = job_id
        self._interval = interval
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self.beats = 0

    def start(self) -> "Heartbeat":
        self._thread.start()
        return self

    def _run(self) -> None:
        conn = self._conn_factory()
        try:
            while not self._stop.wait(self._interval):
                try:
                    _heartbeat(conn, self._job_id)
                    if not conn.autocommit:
                        conn.commit()
                    self.beats += 1
                except Exception:
                    break  # a heartbeat failure degrades to the reaper path
        finally:
            conn.close()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=self._interval + 5)


class CancelWatcher:
    """Background thread that watches a running job for a cancel request and
    trips ``stop_event`` so the stage can bail out cooperatively.

    Like ``Heartbeat`` it owns its own connection. It polls ``jobs.state`` every
    ``interval`` seconds; the moment it reads ``'cancelling'`` it sets the event
    and exits. A read error is swallowed and retried — worst case the cancel just
    isn't observed and the run completes normally (the operator can retry).
    """

    def __init__(
        self,
        conn_factory: Callable[[], psycopg.Connection],
        job_id: int,
        stop_event: threading.Event,
        interval: float,
    ) -> None:
        self._conn_factory = conn_factory
        self._job_id = job_id
        self._stop_event = stop_event
        self._interval = interval
        self._done = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> "CancelWatcher":
        self._thread.start()
        return self

    def _run(self) -> None:
        conn = self._conn_factory()
        try:
            while not self._done.wait(self._interval):
                try:
                    row = conn.execute(
                        "select state from jobs where id = %s", (self._job_id,)
                    ).fetchone()
                    if not conn.autocommit:
                        conn.commit()
                except Exception:
                    continue  # transient read error: try again next tick
                if row and str(row[0]) == "cancelling":
                    self._stop_event.set()
                    return
        finally:
            conn.close()

    def stop(self) -> None:
        self._done.set()
        self._thread.join(timeout=self._interval + 5)


def boot(
    conn: psycopg.Connection,
    *,
    reaper_older_than_seconds: float = DEFAULT_REAPER_SECONDS,
    reconcile_hook: Callable[[psycopg.Connection], Any] | None = None,
) -> int:
    """Run the boot sequence once; return the number of jobs the reaper requeued.

    Order matters: the boot hook (``reconcile_hook``) runs BEFORE the
    reaper/claim loop so any rows it produces exist before a dependent stage
    claims. This function only guarantees the seam is invoked — it has no logic
    of its own.
    """
    if reconcile_hook is not None:
        reconcile_hook(conn)
    n = requeue_stale(conn, older_than_seconds=reaper_older_than_seconds)
    if not conn.autocommit:
        conn.commit()
    return n


def tick(
    conn: psycopg.Connection,
    *,
    stage_fns: dict[str, Callable[..., Any]] | None = None,
    env: Mapping[str, str] | None = None,
    client_factory: Callable[..., Any] | None = None,
    providers_builder: Callable[[dict[str, Any]], Any] | None = None,
    worker_id: str | None = None,
    max_cost_cents: int | None = None,
    conn_factory: Callable[[], psycopg.Connection] | None = None,
    heartbeat_interval: float = DEFAULT_HEARTBEAT_SECONDS,
    cancel_poll_interval: float = DEFAULT_CANCEL_POLL_SECONDS,
) -> bool:
    """Run one loop pass. Return ``True`` if a job was processed, else ``False``.

    Claims the oldest runnable job (respecting the approval + max-cost gates),
    commits the claim, dispatches it under a heartbeat thread + a cancel-watcher,
    then finalizes the job to ``succeeded`` / ``failed`` / ``cancelled``. An empty
    queue is a no-op.

    The claimed job's LLM tier is built from its own ``llm_provider`` /
    ``llm_model`` (see ``_build_providers``); ``env`` supplies the API keys and
    ``client_factory`` the httpx transport. ``providers_builder`` overrides that
    wiring wholesale (tests inject a fake-provider chain through it).

    Cancellation is cooperative: a ``CancelWatcher`` flips a stop ``Event`` when
    the run goes ``cancelling``; the stage sees it via ``job['should_stop']`` (and
    the LLM tier via ``ProviderChain.should_stop``) and bails at the next item
    boundary, after which the run finalizes ``cancelled`` with partial work kept.
    """
    job = claim_one(conn, worker_id=worker_id, max_cost_cents=max_cost_cents)
    if job is None:
        conn.rollback()  # release the (empty) claim transaction
        return False
    conn.commit()  # release the row lock; the job is now 'running'
    log.info(
        "claimed job %s (stage %s, provider %s)",
        job["id"], job["stage"], job.get("llm_provider") or "deterministic",
    )

    # Cooperative-cancel signal: the watcher trips it, the stage + LLM tier read it.
    stop_event = threading.Event()
    job["should_stop"] = stop_event.is_set

    if providers_builder is not None:
        providers = providers_builder(job)
    else:
        providers = _build_providers(job, env=env, client_factory=client_factory)
    if providers is not None and hasattr(providers, "should_stop"):
        providers.should_stop = stop_event.is_set

    hb: Heartbeat | None = None
    cancel_watch: CancelWatcher | None = None
    if conn_factory is not None:
        hb = Heartbeat(conn_factory, job["id"], heartbeat_interval).start()
        cancel_watch = CancelWatcher(
            conn_factory, job["id"], stop_event, cancel_poll_interval
        ).start()

    try:
        result = dispatch.run(job, conn, providers, stage_fns=stage_fns)
        conn.commit()  # flush any stage_fn writes not yet committed
        if stop_event.is_set():
            _finalize_cancelled(conn, job)
            log.info("job %s cancelled (partial results kept)", job["id"])
        else:
            _finalize_success(conn, job, result)
            log.info("job %s (%s) done: %s", job["id"], job["stage"], result)
    except UnknownStage as exc:
        log.error("job %s: %s", job["id"], exc)
        _finalize_failed(conn, job, "unknown_stage", detail=str(exc))
    except CostCapExceeded as exc:
        log.warning("job %s stopped at cost cap: %s", job["id"], exc)
        _finalize_failed(conn, job, "cost_cap_exceeded", detail=str(exc))
    except ProviderUnavailable as exc:
        log.error("job %s provider unavailable: %s", job["id"], exc)
        _finalize_failed(conn, job, "provider_unavailable", detail=str(exc))
    except Exception as exc:  # noqa: BLE001 - a stage error must fail the job, never crash the loop
        log.exception("job %s (%s) failed", job["id"], job["stage"])
        _finalize_failed(conn, job, "stage_error", detail=_error_detail(exc))
    finally:
        if hb is not None:
            hb.stop()
        if cancel_watch is not None:
            cancel_watch.stop()
    return True


def _error_detail(exc: BaseException) -> str:
    """A short, single-line reason for ``jobs.error_detail`` — the full
    traceback goes to the log. Truncated so a giant provider body can't bloat
    the row."""
    return f"{type(exc).__name__}: {exc}".splitlines()[0][:500]


def _build_providers(
    job: dict[str, Any],
    *,
    env: Mapping[str, str] | None = None,
    client_factory: Callable[..., Any] | None = None,
) -> Any:
    """Build the run's ``ProviderChain`` from its chosen LLM tier, or ``None``.

    A run carries its tier on the job row: ``llm_provider`` selects the provider
    and ``llm_model`` the model (both set at run assembly via ``set_run_llm``).
    When the run names no provider — or its API key is absent from ``env`` —
    ``build_provider_for_run`` returns ``None`` and so do we: that run has no LLM
    tier and runs deterministic-only (the alias/lexical tiers inside each
    stage_fn). Otherwise the chain is that single LLM tier, its pack size a
    per-stage code constant, bound to the job's cost meter."""
    provider_id = job.get("llm_provider")
    model_id = job.get("llm_model")
    impl = build_provider_for_run(
        provider_id, model_id, env=env, client_factory=client_factory
    )
    if impl is None:
        return None
    return ProviderChain(
        tiers=[(provider_id, impl)],
        pack_size=pack_size_for(job["stage"]),
        meter=CostMeter(job.get("max_cost_cents")),
    )


def _finalize_success(conn: psycopg.Connection, job: dict[str, Any], result: Any) -> None:
    progress = result if isinstance(result, dict) else {}
    conn.execute(
        """
        update jobs set
            state             = 'succeeded',
            finished_at       = now(),
            progress          = %s,
            cost_actual_cents = coalesce(
                (select sum(cost_cents) from job_items where job_id = %s), 0
            )::int
        where id = %s
        """,
        (Json(progress), job["id"], job["id"]),
    )
    conn.commit()


def _finalize_cancelled(conn: psycopg.Connection, job: dict[str, Any]) -> None:
    """Finalize a cooperatively-stopped run. Items already processed stay
    terminal (their content is live); the rest stay ``pending`` for a re-run.
    Cost rolls up from what was actually spent before the stop."""
    conn.execute(
        """
        update jobs set
            state             = 'cancelled',
            finished_at       = now(),
            cost_actual_cents = coalesce(
                (select sum(cost_cents) from job_items where job_id = %s), 0
            )::int
        where id = %s
        """,
        (job["id"], job["id"]),
    )
    conn.commit()


def _finalize_failed(
    conn: psycopg.Connection,
    job: dict[str, Any],
    error_code: str,
    detail: str | None = None,
) -> None:
    # Clear any aborted-transaction state first; already-committed job_items
    # (e.g. items paid for before a cost abort) survive the rollback.
    conn.rollback()
    conn.execute(
        """
        update jobs set
            state             = 'failed',
            finished_at       = now(),
            error_code        = %s,
            error_detail      = %s,
            cost_actual_cents = coalesce(
                (select sum(cost_cents) from job_items where job_id = %s), 0
            )::int
        where id = %s
        """,
        (error_code, detail, job["id"], job["id"]),
    )
    conn.commit()


def serve(
    conn: psycopg.Connection,
    *,
    stage_fns: dict[str, Callable[..., Any]] | None = None,
    env: Mapping[str, str] | None = None,
    client_factory: Callable[..., Any] | None = None,
    providers_builder: Callable[[dict[str, Any]], Any] | None = None,
    worker_id: str | None = None,
    max_cost_cents: int | None = None,
    conn_factory: Callable[[], psycopg.Connection] | None = None,
    heartbeat_interval: float = DEFAULT_HEARTBEAT_SECONDS,
    cancel_poll_interval: float = DEFAULT_CANCEL_POLL_SECONDS,
    reaper_older_than_seconds: float = DEFAULT_REAPER_SECONDS,
    reconcile_hook: Callable[[psycopg.Connection], Any] | None = None,
    poll_interval: float = DEFAULT_POLL_SECONDS,
    stop_event: threading.Event | None = None,
) -> None:
    """Always-on loop: boot once, then tick forever (sleep when the queue drains).

    Stops when ``stop_event`` is set — otherwise runs until the process is
    killed (Railway restarts it; ``boot``'s reaper recovers any in-flight job).
    """
    boot(
        conn,
        reaper_older_than_seconds=reaper_older_than_seconds,
        reconcile_hook=reconcile_hook,
    )
    while stop_event is None or not stop_event.is_set():
        ran = tick(
            conn,
            stage_fns=stage_fns,
            env=env,
            client_factory=client_factory,
            providers_builder=providers_builder,
            worker_id=worker_id,
            max_cost_cents=max_cost_cents,
            conn_factory=conn_factory,
            heartbeat_interval=heartbeat_interval,
            cancel_poll_interval=cancel_poll_interval,
        )
        if not ran:
            if stop_event is not None and stop_event.wait(poll_interval):
                break
            if stop_event is None:
                time.sleep(poll_interval)

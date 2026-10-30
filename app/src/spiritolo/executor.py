"""The in-process pipeline executor.

One daemon thread with its own SQLite connection claims ``queued`` jobs and
runs them to completion through :mod:`ingredients.worker.runner`. The API
wakes it (``wake``) when a run is started or retried and can trip a running
job's cancel event directly (``cancel``), so no polling loop, heartbeat
table or reaper is needed — the process *is* the worker. ``requeue_interrupted``
at boot puts back whatever a previous process was running when it died.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, Callable, Mapping

from common.db import Connection

import ingredients.pipeline.stages  # noqa: F401 -- registers every stage_fn into STAGE_FNS
from ingredients.worker import runner
from ingredients.worker.dispatch import STAGE_FNS

from .db import Database

log = logging.getLogger("spiritolo.executor")

PROVIDER_KEYS = {
    "openai": "OPENAI_API_KEY",
    "claude": "ANTHROPIC_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
}


def available_providers(env: Mapping[str, str] | None = None) -> list[str]:
    """Provider ids this process can build a client for (``local`` always)."""
    e = os.environ if env is None else env
    out = ["local"]
    for pid, key in PROVIDER_KEYS.items():
        if e.get(key) and pid not in out:
            out.append(pid)
    return out


class Executor:
    def __init__(self, db: Database, *, poll_seconds: float = 5.0, worker_id: str | None = None,
                 run_kwargs: dict[str, Any] | None = None) -> None:
        self._db = db
        self._poll = poll_seconds
        self._worker_id = worker_id or f"executor:{os.getpid()}"
        self._run_kwargs = run_kwargs or {}
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._controls: dict[int, runner.JobControl] = {}
        self.current_job_id: int | None = None
        self.last_tick: float | None = None
        self.jobs_run = 0
        self.last_error: str | None = None

    # -- lifecycle ----------------------------------------------------------

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._loop, name="spiritolo-executor", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 10.0) -> None:
        self._stop.set()
        self._wake.set()
        with self._lock:
            for c in self._controls.values():
                c.cancel()
        if self._thread is not None:
            self._thread.join(timeout)
            self._thread = None
        self._stop.clear()
        self._wake.clear()

    @property
    def alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # -- signals ------------------------------------------------------------

    def wake(self) -> None:
        self._wake.set()

    def cancel(self, job_id: int) -> bool:
        """Trip the in-memory cancel for a running job (the DB state flip to
        ``cancelling`` is done by ``runs.cancel_run``). Returns whether that
        job is running here."""
        with self._lock:
            c = self._controls.get(job_id)
        if c is None:
            return False
        c.cancel()
        return True

    def health(self) -> dict[str, Any]:
        return {
            "alive": self.alive,
            "worker_id": self._worker_id,
            "current_job_id": self.current_job_id,
            "last_tick_age_seconds": None if self.last_tick is None else round(time.time() - self.last_tick, 1),
            "jobs_run": self.jobs_run,
            "last_error": self.last_error,
            "providers": available_providers(self._run_kwargs.get("env")),
            "stages": sorted(STAGE_FNS),
        }

    # -- the loop -----------------------------------------------------------

    def _loop(self) -> None:
        conn = self._db.new_connection(actor=("system", None, "executor"))
        try:
            while not self._stop.is_set():
                self.last_tick = time.time()
                try:
                    ran = self._run_one(conn)
                except Exception as exc:  # noqa: BLE001 - keep the executor alive
                    log.exception("executor tick failed")
                    self.last_error = f"{type(exc).__name__}: {exc}"
                    ran = False
                if ran:
                    continue  # drain the queue before sleeping
                self._wake.wait(self._poll)
                self._wake.clear()
        finally:
            conn.close()

    def _run_one(self, conn: Connection) -> bool:
        job = runner.claim_next(conn, worker_id=self._worker_id)
        if job is None:
            return False
        control = runner.JobControl(conn, job["id"])
        with self._lock:
            self._controls[job["id"]] = control
        self.current_job_id = job["id"]
        try:
            runner.run_job(conn, job, control=control, **self._run_kwargs)
        finally:
            with self._lock:
                self._controls.pop(job["id"], None)
            self.current_job_id = None
            self.jobs_run += 1
        return True


def run_inline(db: Database, **kwargs: Any) -> int:
    """Drain the queue on the calling thread (tests, the CLI)."""
    conn = db.new_connection(actor=("system", None, "executor"))
    try:
        return runner.drain(conn, **kwargs)
    finally:
        conn.close()

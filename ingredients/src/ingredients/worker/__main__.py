"""``python -m ingredients.worker`` — the always-on worker entrypoint.

Wires the runtime to the real environment and hands off to ``loop.serve``: it
connects via ``SUPABASE_DB_URL``, installs SIGINT/SIGTERM handlers for a clean
Railway restart, and serves the global ``STAGE_FNS`` registry (stages register
themselves at import; empty until stages register).

Which model a run uses is the run's own choice — ``jobs.llm_provider`` +
``jobs.llm_model``, set at run assembly in ``/ops``. The loop builds that single
provider per job from ``os.environ`` (API keys for the hosted providers; the
local-provider proxy transport is wired in by the Docker/Tailscale image). A run
that names no provider — or whose key is absent — runs deterministic-only.
"""

from __future__ import annotations

import os
import signal
import threading

import psycopg
from dotenv import load_dotenv

import ingredients.pipeline.stages  # noqa: F401 -- registers stage_fns into STAGE_FNS

from ingredients.worker.dispatch import STAGE_FNS
from ingredients.worker.loop import serve


def main() -> None:
    load_dotenv()
    db_url = os.environ.get("SUPABASE_DB_URL")
    if not db_url:
        raise SystemExit("SUPABASE_DB_URL is not set; cannot start the worker")

    stop_event = threading.Event()

    def _handle(signum, frame):  # noqa: ANN001 - signal handler signature
        stop_event.set()

    signal.signal(signal.SIGINT, _handle)
    signal.signal(signal.SIGTERM, _handle)

    conn = psycopg.connect(db_url)
    try:
        serve(
            conn,
            stage_fns=STAGE_FNS,
            env=os.environ,  # API keys for the run's chosen hosted provider
            worker_id=os.environ.get("WORKER_ID"),
            conn_factory=lambda: psycopg.connect(db_url, autocommit=True),
            stop_event=stop_event,
        )
    finally:
        conn.close()


if __name__ == "__main__":
    main()

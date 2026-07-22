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

import logging
import os
import signal
import socket
import threading

import psycopg
from dotenv import load_dotenv

import ingredients.pipeline.stages  # noqa: F401 -- registers stage_fns into STAGE_FNS

from ingredients.worker.dispatch import STAGE_FNS
from ingredients.worker.loop import serve
from ingredients.worker.providers_local import available_providers

log = logging.getLogger("ingredients.worker")


def main() -> None:
    load_dotenv()
    # The worker's only console is Railway's log stream, so configure logging up
    # front — without this the loop's claim/finish/failure lines go nowhere and a
    # stuck run looks (as run #7 did) like a dead worker.
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    db_url = os.environ.get("SUPABASE_DB_URL")
    if not db_url:
        raise SystemExit("SUPABASE_DB_URL is not set; cannot start the worker")

    stop_event = threading.Event()

    def _handle(signum, frame):  # noqa: ANN001 - signal handler signature
        stop_event.set()

    signal.signal(signal.SIGINT, _handle)
    signal.signal(signal.SIGTERM, _handle)

    # A stable id keys this worker's worker_status row (health + capabilities).
    worker_id = os.environ.get("WORKER_ID") or socket.gethostname()
    providers = available_providers(os.environ)
    stages = sorted(STAGE_FNS)
    log.info("worker %s starting; providers=%s; stages=%s", worker_id, providers, stages)
    conn = psycopg.connect(db_url)
    try:
        serve(
            conn,
            stage_fns=STAGE_FNS,
            env=os.environ,  # API keys for the run's chosen hosted provider
            worker_id=worker_id,
            conn_factory=lambda: psycopg.connect(db_url, autocommit=True),
            status_providers=providers,
            status_stages=stages,
            stop_event=stop_event,
        )
    finally:
        conn.close()


if __name__ == "__main__":
    main()

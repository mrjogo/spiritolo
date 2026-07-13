"""``python -m ingredients.worker`` — the always-on worker entrypoint.

Wires the runtime to the real environment and hands off to ``loop.serve``: it
connects via ``SUPABASE_DB_URL``, installs SIGINT/SIGTERM handlers for a clean
Railway restart, and serves the global ``STAGE_FNS`` registry (stages register
themselves at import; empty until stages register).

The provider implementations and the local-provider proxy transport are wired
in by the Docker/Tailscale image. The batch-reconcile boot hook is bound here
when a batch provider is configured — otherwise it stays ``None`` and boot just
runs the reaper.
"""

from __future__ import annotations

import json
import os
import pathlib
import signal
import threading

import psycopg
from dotenv import load_dotenv

import ingredients.pipeline.stages  # noqa: F401 -- registers stage_fns into STAGE_FNS

from ingredients.worker.batches import OpenAIBatchReconcileClient, build_reconcile_hook
from ingredients.worker.dispatch import STAGE_FNS
from ingredients.worker.loop import serve
from ingredients.worker.providers import load_configs


def _build_reconcile_hook():
    """Bind the OpenAI async-Batch reconciler when a key is configured.

    Batch is an opt-in accelerator; with no ``OPENAI_API_KEY`` the worker skips
    reconciliation entirely (returns ``None``) and boot just runs the reaper.
    """
    if not os.environ.get("OPENAI_API_KEY"):
        return None
    return build_reconcile_hook(OpenAIBatchReconcileClient.from_env())


def _load_chain_configs() -> dict:
    """Load the provider-chain config from ``PROVIDER_CHAIN_CONFIG`` (a JSON file
    path), or return an empty map. Config-not-code: the owner rewires this file,
    never the schema."""
    path = os.environ.get("PROVIDER_CHAIN_CONFIG")
    if not path:
        return {}
    return load_configs(json.loads(pathlib.Path(path).read_text()))


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
            configs=_load_chain_configs(),
            provider_impls={},  # the real provider clients are wired in here
            worker_id=os.environ.get("WORKER_ID"),
            conn_factory=lambda: psycopg.connect(db_url, autocommit=True),
            reconcile_hook=_build_reconcile_hook(),
            stop_event=stop_event,
        )
    finally:
        conn.close()


if __name__ == "__main__":
    main()

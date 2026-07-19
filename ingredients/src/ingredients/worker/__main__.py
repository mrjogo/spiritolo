"""``python -m ingredients.worker`` — the always-on worker entrypoint.

Wires the runtime to the real environment and hands off to ``loop.serve``: it
connects via ``SUPABASE_DB_URL``, installs SIGINT/SIGTERM handlers for a clean
Railway restart, and serves the global ``STAGE_FNS`` registry (stages register
themselves at import; empty until stages register).

Provider implementations are built from the environment by
``build_provider_impls`` (Ollama always; OpenAI / Claude / DeepSeek when their
API keys are set); the local-provider proxy transport is wired in by the
Docker/Tailscale image. Which providers a stage actually uses — and in what
order — is the ``PROVIDER_CHAIN_CONFIG`` file, not this wiring.
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

from ingredients.worker.dispatch import STAGE_FNS
from ingredients.worker.loop import serve
from ingredients.worker.providers import load_configs
from ingredients.worker.providers_local import build_provider_impls


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
            provider_impls=build_provider_impls(),  # {id -> impl}, keyed on env keys
            worker_id=os.environ.get("WORKER_ID"),
            conn_factory=lambda: psycopg.connect(db_url, autocommit=True),
            stop_event=stop_event,
        )
    finally:
        conn.close()


if __name__ == "__main__":
    main()

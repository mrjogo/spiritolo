"""Worker daemon runtime.

A single always-on process that claims jobs off the Postgres-as-queue, dispatches
each to a registered ``stage_fn`` over a config-not-code provider chain,
heartbeats while running, writes results as idempotent ``stage_run`` UPSERTs,
rolls up cost, and hard-aborts past ``max_cost_cents``.

This package owns the *runtime* + the seam contracts; the pipeline stages
register their ``stage_fn`` bodies into ``dispatch.STAGE_FNS``. Everything here
is exercised with fake providers / fake stage_fns — never a live model.
"""

from __future__ import annotations

from ingredients.worker.batches import (
    BatchItemResult,
    BatchPoll,
    ReconcileSummary,
    build_reconcile_hook,
    reconcile,
)
from ingredients.worker.cost import CostCapExceeded, CostMeter
from ingredients.worker.dispatch import STAGE_FNS, UnknownStage, register, run
from ingredients.worker.loop import boot, serve, tick
from ingredients.worker.providers import ProviderChain, build_chain, load_configs

__all__ = [
    "BatchItemResult",
    "BatchPoll",
    "CostCapExceeded",
    "CostMeter",
    "ProviderChain",
    "ReconcileSummary",
    "STAGE_FNS",
    "UnknownStage",
    "boot",
    "build_chain",
    "build_reconcile_hook",
    "load_configs",
    "reconcile",
    "register",
    "run",
    "serve",
    "tick",
]

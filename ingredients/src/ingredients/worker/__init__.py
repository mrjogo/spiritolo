"""Worker daemon runtime.

A single always-on process that claims jobs off the Postgres-as-queue, dispatches
each to a registered ``stage_fn`` over the run's chosen provider chain (built from
``jobs.llm_provider`` / ``jobs.llm_model``), heartbeats while running, writes
results as idempotent ``job_items`` UPSERTs,
rolls up cost, and hard-aborts past ``max_cost_cents``.

This package owns the *runtime* + the seam contracts; the pipeline stages
register their ``stage_fn`` bodies into ``dispatch.STAGE_FNS``. Everything here
is exercised with fake providers / fake stage_fns — never a live model.
"""

from __future__ import annotations

from ingredients.worker.cost import CostCapExceeded, CostMeter
from ingredients.worker.dispatch import STAGE_FNS, UnknownStage, register, run
from ingredients.worker.loop import boot, serve, tick
from ingredients.worker.providers import ProviderChain

__all__ = [
    "CostCapExceeded",
    "CostMeter",
    "ProviderChain",
    "STAGE_FNS",
    "UnknownStage",
    "boot",
    "register",
    "run",
    "serve",
    "tick",
]

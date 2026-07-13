"""Worker daemon runtime.

A single always-on process that claims jobs off the Postgres-as-queue, dispatches
each to a registered ``stage_fn`` over a config-not-code provider chain,
heartbeats while running, writes results as idempotent ``stage_run`` UPSERTs,
rolls up cost, and hard-aborts past ``max_cost_cents``.

This package owns the *runtime* + the seam contracts; the pipeline stages
register their ``stage_fn`` bodies into ``dispatch.STAGE_FNS``. Everything here
is exercised with fake providers / fake stage_fns — never a live model.

``build_rows_for_recipe`` is the legacy per-recipe parsing helper (this used to
be ``ingredients/worker.py``); it is re-exported here so existing importers keep
working.
"""

from __future__ import annotations

from ingredients.worker.cost import CostCapExceeded, CostMeter
from ingredients.worker.dispatch import STAGE_FNS, UnknownStage, register, run
from ingredients.worker.loop import boot, serve, tick
from ingredients.worker.parsing import build_rows_for_recipe
from ingredients.worker.providers import ProviderChain, build_chain, load_configs

__all__ = [
    "CostCapExceeded",
    "CostMeter",
    "ProviderChain",
    "STAGE_FNS",
    "UnknownStage",
    "boot",
    "build_chain",
    "build_rows_for_recipe",
    "load_configs",
    "register",
    "run",
    "serve",
    "tick",
]

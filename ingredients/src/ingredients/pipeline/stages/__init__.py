"""Pipeline stages as `stage_fn(job, conn, providers)` callables.

Each stage is a versioned function over the `stage_runs` ledger: it resolves its
work queue ("content qualifies AND no run at the current version"), does its
work over a provider chain (deterministic tier first, LLM tier for abstains),
writes its content rows, and UPSERTs one `stage_runs` row per entity. Importing
this package registers every stage into `worker.dispatch.STAGE_FNS`, so the
worker can dispatch a claimed job to the right one by name.
"""

from __future__ import annotations

from ingredients.worker import dispatch

from . import export as _export
from . import parse as _parse

dispatch.register("parse", _parse.parse_stage_fn)
dispatch.register("export", _export.export_stage_fn)

__all__ = ["_parse", "_export"]

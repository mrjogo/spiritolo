"""Pipeline stages as `stage_fn(job, conn, providers)` callables.

Each stage is a versioned function over the `stage_runs` ledger: it resolves its
work queue ("content qualifies AND no run at the current version"), does its
work over a provider chain (deterministic tier first, LLM tier for abstains),
writes its content rows, and UPSERTs one `stage_runs` row per entity. Importing
this package registers every stage into `worker.dispatch.STAGE_FNS`, so the
worker (and the cold-build orchestrator) can dispatch by stage name.
"""

from __future__ import annotations

from ingredients.worker import dispatch

from . import cluster as _cluster
from . import convert as _convert
from . import export as _export
from . import extract as _extract
from . import map as _map
from . import parse as _parse

dispatch.register("extract", _extract.extract_stage_fn)
dispatch.register("parse", _parse.parse_stage_fn)
dispatch.register("map", _map.map_stage_fn)
dispatch.register("convert", _convert.convert_stage_fn)
dispatch.register("cluster", _cluster.cluster_stage_fn)
dispatch.register("export", _export.export_stage_fn)

# The order the cold build drives the stages in: page -> recipe rows ->
# resolution -> verb-frame steps -> cluster identity -> frozen bundle.
STAGE_ORDER = ["extract", "parse", "map", "convert", "cluster", "export"]

__all__ = ["STAGE_ORDER"]

"""Pipeline stages as `stage_fn(job, conn, providers)` callables.

Each stage is a versioned function over the `job_items` ledger: it resolves its
work queue ("content qualifies AND no run at the current version"), does its
work over a provider chain (deterministic tier first, LLM tier for abstains),
writes its content rows, and UPSERTs one `job_items` row per entity. Importing
this package registers every stage into `worker.dispatch.STAGE_FNS`, so the
worker (and the cold-build orchestrator) can dispatch by stage name.
"""

from __future__ import annotations

from ingredients.worker import dispatch

from . import cluster as _cluster
from . import combine as _combine
from . import connect as _connect
from . import convert as _convert
from . import export as _export
from . import extract as _extract
from . import map as _map
from . import parse as _parse

dispatch.register(_extract.STAGE, _extract.extract_stage_fn)
dispatch.register(_parse.STAGE, _parse.parse_stage_fn)
dispatch.register(_map.STAGE, _map.map_stage_fn)
dispatch.register(_combine.STAGE, _combine.combine_stage_fn)
dispatch.register(_connect.STAGE, _connect.connect_stage_fn)
dispatch.register(_convert.STAGE, _convert.convert_stage_fn)
dispatch.register(_cluster.STAGE, _cluster.cluster_stage_fn)
dispatch.register(_export.STAGE, _export.export_stage_fn)

# The order the cold build drives the stages in: page -> recipe rows ->
# resolution -> merge/place provisional nodes -> verb-frame steps -> cluster
# identity -> frozen bundle. combine-nodes + connect-nodes harmonize the
# provisional taxonomy map-ingredient minted and promote it to live, so they run
# before the downstream stages that gate on live nodes. Keyed by each stage
# module's canonical STAGE name so the registry and order can't drift.
STAGE_ORDER = [
    _extract.STAGE,
    _parse.STAGE,
    _map.STAGE,
    _combine.STAGE,
    _connect.STAGE,
    _convert.STAGE,
    _cluster.STAGE,
    _export.STAGE,
]

__all__ = ["STAGE_ORDER"]

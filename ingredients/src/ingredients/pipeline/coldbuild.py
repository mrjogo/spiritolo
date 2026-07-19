"""Cold-build orchestration: drive every stage in order from {pages, corpus}.

Runs the stages left-to-right over the whole queue, so a fresh corpus builds all
the way to frozen bundles in one call: extract-recipe (pages -> recipes) ->
parse-ingredients -> map-ingredient -> convert-steps -> cluster-recipes ->
export-recipegf. Each stage is idempotent over its
`job_items` queue, so a re-run only touches what a prior run left undone.
"""

from __future__ import annotations

from typing import Any

import psycopg

from ingredients.pipeline.stages import STAGE_ORDER
from ingredients.worker import dispatch


def run_cold_build(
    conn: psycopg.Connection,
    *,
    site: str | None = None,
    limit: int | None = None,
    providers: Any = None,
    stage_fns: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run every stage in ``STAGE_ORDER`` once and return each stage's counts.

    ``providers`` may be a single chain applied to every stage, a
    ``{stage: chain}`` map, or ``None`` for a fully deterministic build.
    ``stage_fns`` overrides the global registry (tests inject fakes).
    """
    registry = dispatch.STAGE_FNS if stage_fns is None else stage_fns
    job = {"id": None, "payload": {"site": site, "limit": limit}}
    results: dict[str, Any] = {}
    for stage in STAGE_ORDER:
        chain = providers.get(stage) if isinstance(providers, dict) else providers
        results[stage] = registry[stage](job, conn, chain)
    return results

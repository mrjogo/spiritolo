"""Phase 1 orchestrator. Walks the unique-pending-names list through
alias -> lexical, batch-updating recipe_ingredients per name.

Phase 2 (LLM) lives in llm_resolver.py and is triggered separately by
the operator; nothing in this module makes external calls.
"""

from __future__ import annotations

import logging
from collections import Counter

import psycopg
from spiritolo_common.progress import make_progress

from .alias_layer import resolve_alias
from .db import (
    fetch_unique_pending_names, write_pending, write_resolution,
)
from .lexical_layer import resolve_lexical
from .normalize import normalize_name
from .types import Resolved

MAPPER_VERSION = "v1"

log = logging.getLogger("mapper")


def run_phase1(
    conn: psycopg.Connection,
    *,
    site: str | None = None,
    limit: int | None = None,
    dry_run: bool = False,
) -> dict[str, int]:
    """Resolve every distinct pending name through alias -> lexical.
    Returns a Counter-shaped summary keyed by mapper_source."""
    counts: Counter[str] = Counter(alias=0, lexical=0, pending_llm=0)
    names = fetch_unique_pending_names(
        conn, mapper_version=MAPPER_VERSION, site=site, limit=limit,
    )
    total = len(names)
    if total == 0:
        log.info("nothing to map")
        return dict(counts)
    log.info("mapping %d distinct names (mapper_version=%s)", total, MAPPER_VERSION)

    progress = make_progress(total=total)
    for idx, raw in enumerate(names, start=1):
        normalized = normalize_name(raw)
        result = resolve_alias(conn, normalized)
        if isinstance(result, Resolved):
            counts["alias"] += 1
            if not dry_run:
                write_resolution(
                    conn, normalized_name=normalized,
                    taxonomy_node_id=result.taxonomy_node_id,
                    source="alias", mapper_version=MAPPER_VERSION,
                )
            progress(idx)
            continue

        result = resolve_lexical(conn, normalized)
        if isinstance(result, Resolved):
            counts["lexical"] += 1
            if not dry_run:
                write_resolution(
                    conn, normalized_name=normalized,
                    taxonomy_node_id=result.taxonomy_node_id,
                    source="lexical", mapper_version=MAPPER_VERSION,
                )
            progress(idx)
            continue

        counts["pending_llm"] += 1
        if not dry_run:
            write_pending(
                conn, normalized_name=normalized, mapper_version=MAPPER_VERSION,
            )
        progress(idx)
    return dict(counts)

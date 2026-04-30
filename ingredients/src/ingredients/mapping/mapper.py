"""Phase 1 orchestrator. Walks the unique-pending-names list through
alias -> lexical, batch-updating recipe_ingredients per name.

Phase 2 (LLM) lives in llm_resolver.py and is triggered separately by
the operator; nothing in this module makes external calls.
"""

from __future__ import annotations

import logging
from collections import Counter

import psycopg
from spiritolo_common.interrupt import InterruptHandler
from spiritolo_common.progress import make_progress

from .alias_layer import fetch_aliases_dict
from .db import (
    fetch_unique_pending_names,
    write_pendings_batch,
    write_resolutions_batch,
)
from .lexical_layer import resolve_lexical
from .normalize import normalize_name
from .types import Resolved

MAPPER_VERSION = "v1"

# How many names to buffer before flushing to the DB. Small enough that
# Ctrl-C only loses a fraction of a second of work; large enough that
# round-trip overhead doesn't dominate the loop.
BATCH_FLUSH_SIZE = 500

log = logging.getLogger("mapper")


def _flush(
    conn: psycopg.Connection,
    *,
    alias_resolutions: list[tuple[str, int]],
    lexical_resolutions: list[tuple[str, int]],
    pendings: list[str],
) -> None:
    """Write all buffered decisions in one transaction, then clear buffers."""
    if not (alias_resolutions or lexical_resolutions or pendings):
        return
    write_resolutions_batch(
        conn, items=alias_resolutions,
        source="alias", mapper_version=MAPPER_VERSION,
    )
    write_resolutions_batch(
        conn, items=lexical_resolutions,
        source="lexical", mapper_version=MAPPER_VERSION,
    )
    write_pendings_batch(
        conn, names=pendings, mapper_version=MAPPER_VERSION,
    )
    conn.commit()
    alias_resolutions.clear()
    lexical_resolutions.clear()
    pendings.clear()


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

    # Snapshot aliases once; the alias layer is just an exact-match lookup,
    # so eliminating ~1 round-trip per name on a 9k-name run is a big win.
    aliases = fetch_aliases_dict(conn)

    alias_resolutions: list[tuple[str, int]] = []
    lexical_resolutions: list[tuple[str, int]] = []
    pendings: list[str] = []

    progress = make_progress(total=total)
    with InterruptHandler() as interrupt:
        try:
            for idx, raw in enumerate(names, start=1):
                if interrupt.requested:
                    break
                normalized = normalize_name(raw)
                if normalized and (node_id := aliases.get(normalized)) is not None:
                    counts["alias"] += 1
                    alias_resolutions.append((normalized, node_id))
                else:
                    result = resolve_lexical(conn, normalized)
                    if isinstance(result, Resolved):
                        counts["lexical"] += 1
                        lexical_resolutions.append(
                            (normalized, result.taxonomy_node_id),
                        )
                    else:
                        counts["pending_llm"] += 1
                        pendings.append(normalized)
                progress(idx)
                if not dry_run and (idx % BATCH_FLUSH_SIZE == 0):
                    _flush(
                        conn,
                        alias_resolutions=alias_resolutions,
                        lexical_resolutions=lexical_resolutions,
                        pendings=pendings,
                    )
        except KeyboardInterrupt:
            # Second Ctrl-C: do NOT flush; abort with whatever has been
            # written so far (the most recent partial batch is lost).
            raise
        if not dry_run:
            _flush(
                conn,
                alias_resolutions=alias_resolutions,
                lexical_resolutions=lexical_resolutions,
                pendings=pendings,
            )

    return dict(counts)

"""Phase 1 orchestrator for cocktail-name normalization.

Fetches every distinct unresolved recipes.name, runs each through
normalize_cocktail_name, walks alias_layer → lexical_layer cascade,
and writes the result back to every recipes row sharing that raw name.
"""

from __future__ import annotations

import logging
from collections import Counter

import psycopg
from spiritolo_common.interrupt import InterruptHandler
from spiritolo_common.progress import make_progress

from .alias_layer import fetch_aliases_dict
from .db import (
    fetch_unresolved_recipe_names,
    write_normalizations_batch,
    write_pending_normalize_batch,
)
from .lexical_layer import resolve_lexical
from .normalize import normalize_cocktail_name
from .types import Resolved
from .version import NORMALIZER_VERSION

# How many names to buffer before flushing to the DB. Same trade-off as
# the mapper: small enough that Ctrl-C only loses a fraction of a second
# of work; large enough that round-trip overhead doesn't dominate.
BATCH_FLUSH_SIZE = 500

log = logging.getLogger("dedup.normalizer")


def _flush(
    conn: psycopg.Connection,
    *,
    alias_resolutions: list[tuple[str, str]],
    lexical_resolutions: list[tuple[str, str]],
    pendings: list[str],
) -> None:
    """Write all buffered decisions in one transaction, then clear buffers."""
    if not (alias_resolutions or lexical_resolutions or pendings):
        return
    write_normalizations_batch(
        conn, items=alias_resolutions,
        source="alias", normalizer_version=NORMALIZER_VERSION,
    )
    write_normalizations_batch(
        conn, items=lexical_resolutions,
        source="lexical", normalizer_version=NORMALIZER_VERSION,
    )
    write_pending_normalize_batch(
        conn, raw_names=pendings, normalizer_version=NORMALIZER_VERSION,
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
    """Return Counter-shaped dict keyed by 'alias' | 'lexical' | 'pending_llm'."""
    counts: Counter[str] = Counter()
    raw_names = fetch_unresolved_recipe_names(
        conn, normalizer_version=NORMALIZER_VERSION, site=site, limit=limit,
    )
    total = len(raw_names)
    if total == 0:
        log.info("nothing to normalize")
        return dict(counts)
    log.info(
        "normalizing %d distinct names (normalizer_version=%s)",
        total, NORMALIZER_VERSION,
    )

    # Snapshot aliases once; the alias layer is just an exact-match lookup,
    # so eliminating ~1 round-trip per name is a big win.
    aliases = fetch_aliases_dict(conn)

    alias_resolutions: list[tuple[str, str]] = []
    lexical_resolutions: list[tuple[str, str]] = []
    pendings: list[str] = []

    progress = make_progress(total=total)
    with InterruptHandler() as interrupt:
        try:
            for idx, raw in enumerate(raw_names, start=1):
                if interrupt.requested:
                    break
                normalized = normalize_cocktail_name(raw)
                if not normalized:
                    counts["pending_llm"] += 1
                    pendings.append(raw)
                elif (canonical := aliases.get(normalized)) is not None:
                    counts["alias"] += 1
                    alias_resolutions.append((raw, canonical))
                else:
                    result = resolve_lexical(conn, normalized)
                    if isinstance(result, Resolved):
                        counts["lexical"] += 1
                        lexical_resolutions.append((raw, result.canonical_name))
                    else:
                        counts["pending_llm"] += 1
                        pendings.append(raw)
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

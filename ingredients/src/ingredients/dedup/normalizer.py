"""Phase 1 orchestrator for cocktail-name normalization.

Fetches every distinct unresolved recipes.name, runs each through
normalize_cocktail_name, walks alias_layer → lexical_layer cascade,
and writes the result back to every recipes row sharing that raw name.
"""

from __future__ import annotations

import logging
from collections import Counter

import psycopg

from .alias_layer import resolve_alias
from .db import (
    fetch_unresolved_recipe_names,
    write_normalization,
    write_pending_normalize,
)
from .lexical_layer import resolve_lexical
from .normalize import normalize_cocktail_name
from .types import Pending, Resolved
from .version import NORMALIZER_VERSION

log = logging.getLogger("dedup.normalizer")


def run_phase1(
    conn: psycopg.Connection,
    *,
    site: str | None = None,
    limit: int | None = None,
) -> dict[str, int]:
    """Return Counter-shaped dict keyed by 'alias' | 'lexical' | 'pending_llm'."""
    counts: Counter[str] = Counter()
    raw_names = fetch_unresolved_recipe_names(
        conn, normalizer_version=NORMALIZER_VERSION, site=site, limit=limit,
    )
    for raw in raw_names:
        normalized = normalize_cocktail_name(raw)
        if not normalized:
            write_pending_normalize(conn, raw_name=raw, normalizer_version=NORMALIZER_VERSION)
            counts["pending_llm"] += 1
            continue

        result = resolve_alias(conn, normalized)
        if isinstance(result, Resolved):
            write_normalization(
                conn, raw_name=raw, normalized=normalized,
                canonical_name=result.canonical_name, source=result.source,
                normalizer_version=NORMALIZER_VERSION,
            )
            counts["alias"] += 1
            continue

        result = resolve_lexical(conn, normalized)
        if isinstance(result, Resolved):
            write_normalization(
                conn, raw_name=raw, normalized=normalized,
                canonical_name=result.canonical_name, source=result.source,
                normalizer_version=NORMALIZER_VERSION,
            )
            counts["lexical"] += 1
            continue

        # Pending → queue for Phase 2.
        write_pending_normalize(conn, raw_name=raw, normalizer_version=NORMALIZER_VERSION)
        counts["pending_llm"] += 1

    return dict(counts)

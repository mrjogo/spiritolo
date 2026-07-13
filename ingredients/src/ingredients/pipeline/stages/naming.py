"""Deterministic canonical drink-name resolution, shared by convert + cluster.

Both stages need the recipe's canonical drink name — convert to mint the drink
slug, cluster to seed the cluster key. This resolves it once, deterministically:
the cocktail-name normalizer, then the shared cocktail_aliases (exact, then
lexical), falling back to the normalized form so case/editorial variants of one
drink collapse to the same canonical name.
"""

from __future__ import annotations

import psycopg

from ingredients.dedup.lexical_layer import resolve_lexical
from ingredients.dedup.normalize import normalize_cocktail_name
from ingredients.dedup.types import Resolved


def canonical_name_for(
    conn: psycopg.Connection, aliases: dict[str, str], raw_name: str | None
) -> str | None:
    """The canonical drink name for a raw title, or None when it normalizes to
    nothing. ``aliases`` is a snapshot of cocktail_aliases (normalized alias ->
    canonical name); pass ``{}`` to skip the exact-alias tier."""
    normalized = normalize_cocktail_name(raw_name)
    if not normalized:
        return None
    canonical = aliases.get(normalized)
    if canonical is not None:
        return canonical
    result = resolve_lexical(conn, normalized)
    if isinstance(result, Resolved):
        return result.canonical_name
    return normalized

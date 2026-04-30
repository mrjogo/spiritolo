"""Phase 1, Layer 1 — exact match against cocktail_aliases.

Caller passes a name already through normalize_cocktail_name. Returns
Resolved(source='alias') or Pending. Never raises on miss.

Mirrors mapping/alias_layer.py shape.
"""

from __future__ import annotations

import psycopg

from .types import Pending, Phase1Result, Resolved


def resolve_alias(conn: psycopg.Connection, normalized_name: str) -> Phase1Result:
    if not normalized_name:
        return Pending()
    row = conn.execute(
        "select canonical_name from cocktail_aliases where alias = %s limit 1",
        (normalized_name,),
    ).fetchone()
    if row is None:
        return Pending()
    return Resolved(canonical_name=row[0], source="alias")


def fetch_aliases_dict(conn: psycopg.Connection) -> dict[str, str]:
    """Snapshot every alias -> canonical_name pair for in-memory lookup.
    The table is small; pulling once and matching in Python beats one
    round-trip per name in the Phase 1 hot loop."""
    return {
        row[0]: row[1]
        for row in conn.execute(
            "select alias, canonical_name from cocktail_aliases"
        ).fetchall()
    }

"""Phase 1, Layer 1 — exact match against taxonomy_aliases.

Caller is expected to pass a normalized name (see normalize.normalize_name).
Returns Resolved(source='alias') or Pending. Never raises on miss.
"""

from __future__ import annotations

import psycopg

from .types import Pending, Phase1Result, Resolved


def resolve_alias(conn: psycopg.Connection, normalized_name: str) -> Phase1Result:
    if not normalized_name:
        return Pending()
    row = conn.execute(
        "select node_id from taxonomy_aliases where alias = %s limit 1",
        (normalized_name,),
    ).fetchone()
    if row is None:
        return Pending()
    return Resolved(taxonomy_node_id=row[0], source="alias")


def fetch_aliases_dict(conn: psycopg.Connection) -> dict[str, int]:
    """Snapshot every alias -> node_id pair for in-memory lookup.
    The table is small (~hundreds of rows); pulling once and matching in
    Python beats one round-trip per name in the Phase 1 hot loop."""
    return {
        row[0]: row[1]
        for row in conn.execute(
            "select alias, node_id from taxonomy_aliases"
        ).fetchall()
    }

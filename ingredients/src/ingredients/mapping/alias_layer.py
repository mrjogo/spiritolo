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

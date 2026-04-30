"""Phase 1, Layer 2 — pg_trgm similarity over cocktail_aliases.

Mirrors mapping/lexical_layer.py. Differences:
  * Searches cocktail_aliases.alias (instead of taxonomy_nodes.display_name +
    taxonomy_aliases.alias).
  * Returns canonical_name (text) on hit, not taxonomy_node_id.
  * Same fail-closed thresholds (LEXICAL_MIN_SIM, LEXICAL_RATIO). Tune via
    eval-set if cocktail-name distribution differs materially from
    ingredient-name distribution.
"""

from __future__ import annotations

from typing import Any

import psycopg

from .types import Pending, Phase1Result, Resolved

LEXICAL_MIN_SIM = 0.75
LEXICAL_RATIO = 1.5

_CANDIDATE_LIMIT_DEFAULT = 20


def _candidates_sql(limit: int) -> str:
    return f"""
        select canonical_name,
               max(similarity(alias, %s)) as sim
        from cocktail_aliases
        group by canonical_name
        order by sim desc
        limit {int(limit)}
    """


def lexical_candidates(
    conn: psycopg.Connection, normalized_name: str, *, limit: int = _CANDIDATE_LIMIT_DEFAULT,
) -> list[dict[str, Any]]:
    if not normalized_name:
        return []
    rows = conn.execute(
        _candidates_sql(limit), (normalized_name,),
    ).fetchall()
    return [
        {"canonical_name": r[0], "similarity": float(r[1])}
        for r in rows
    ]


def resolve_lexical(conn: psycopg.Connection, normalized_name: str) -> Phase1Result:
    cands = lexical_candidates(conn, normalized_name, limit=2)
    if not cands or cands[0]["similarity"] < LEXICAL_MIN_SIM:
        return Pending()
    if len(cands) >= 2:
        top1, top2 = cands[0]["similarity"], cands[1]["similarity"]
        if top2 > 0 and top1 < LEXICAL_RATIO * top2:
            return Pending()
    return Resolved(canonical_name=cands[0]["canonical_name"], source="lexical")

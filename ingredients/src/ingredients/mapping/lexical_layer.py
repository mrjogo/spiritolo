"""Phase 1, Layer 2 — pg_trgm similarity over taxonomy display names + aliases.

Fail-closed thresholds: accept only when top-1 similarity clears
LEXICAL_MIN_SIM AND is at least LEXICAL_RATIO times top-2. Anything
ambiguous falls through to Pending so Phase 2 can decide.

The SQL groups by node_id (not by node_id + matching text) so that a
node matching via both its display_name and an alias contributes a
single candidate. Otherwise the ratio guard mis-fires when the same
node legitimately matches two ways at the same score.
"""

from __future__ import annotations

from typing import Any

import psycopg

from .types import Pending, Phase1Result, Resolved

# Empirically tuned against fixture + corpus. Keep both knobs conservative;
# the cost of falling through to Phase 2 is small, the cost of a confidently
# wrong mapping is high.
LEXICAL_MIN_SIM = 0.75
LEXICAL_RATIO = 1.5

# Top-N candidates surfaced to Phase 2 even when this layer abstains.
_CANDIDATE_LIMIT_DEFAULT = 20


def _candidates_sql(limit: int) -> str:
    return f"""
        with hits as (
            select n.id as node_id, n.display_name as display_name,
                   similarity(n.display_name, %s) as sim
            from taxonomy_nodes n
            union all
            select a.node_id, n.display_name,
                   similarity(a.alias, %s) as sim
            from taxonomy_aliases a
            join taxonomy_nodes n on n.id = a.node_id
        )
        select node_id, max(display_name) as display_name, max(sim) as sim
        from hits
        group by node_id
        order by sim desc
        limit {int(limit)}
    """


def lexical_candidates(
    conn: psycopg.Connection, normalized_name: str, *, limit: int = _CANDIDATE_LIMIT_DEFAULT,
) -> list[dict[str, Any]]:
    if not normalized_name:
        return []
    rows = conn.execute(
        _candidates_sql(limit), (normalized_name, normalized_name),
    ).fetchall()
    return [
        {"node_id": r[0], "display_name": r[1], "similarity": float(r[2])}
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
    return Resolved(taxonomy_node_id=cands[0]["node_id"], source="lexical")

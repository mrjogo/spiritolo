"""Phase 1, Layer 2 — trigram similarity over taxonomy display names + aliases.

Fail-closed thresholds: accept only when top-1 similarity clears
LEXICAL_MIN_SIM AND is at least LEXICAL_RATIO times top-2. Anything
ambiguous falls through to Pending so Phase 2 can decide.

Scoring is pg_trgm-compatible (``common.text.similarity``) so the thresholds
tuned against Postgres carry over unchanged. Candidates are grouped by node
(not by node + matching text) so a node matching via both its display_name and
an alias contributes a single candidate; otherwise the ratio guard mis-fires
when the same node legitimately matches two ways at the same score.

The index over the taxonomy is built from the connection on demand; a stage
processing many names builds it once (``TaxonomyIndex.load``) and passes it in.
"""

from __future__ import annotations

from typing import Any

from common.db import Connection
from common.text import TrigramIndex

from .types import Pending, Phase1Result, Resolved

# Empirically tuned against fixture + corpus. Keep both knobs conservative;
# the cost of falling through to Phase 2 is small, the cost of a confidently
# wrong mapping is high.
LEXICAL_MIN_SIM = 0.75
LEXICAL_RATIO = 1.5

# Top-N candidates surfaced to Phase 2 even when this layer abstains.
_CANDIDATE_LIMIT_DEFAULT = 20


class TaxonomyIndex:
    """Trigram index over every taxonomy node's display name + aliases."""

    def __init__(self, entries: list[tuple[int, str | None]], names: dict[int, str]) -> None:
        self._index: TrigramIndex[int] = TrigramIndex(entries)
        self.display_names = names

    @classmethod
    def load(cls, conn: Connection) -> "TaxonomyIndex":
        names = {
            r[0]: r[1] for r in conn.execute("select id, display_name from taxonomy_nodes").fetchall()
        }
        entries: list[tuple[int, str | None]] = list(names.items())
        entries.extend(
            (r[0], r[1])
            for r in conn.execute("select node_id, alias from taxonomy_aliases").fetchall()
            if r[0] in names
        )
        return cls(entries, names)

    def candidates(self, normalized_name: str, limit: int) -> list[dict[str, Any]]:
        return [
            {"node_id": node_id, "display_name": self.display_names.get(node_id), "similarity": sim}
            for node_id, sim in self._index.top(normalized_name, limit)
        ]


def lexical_candidates(
    conn: Connection, normalized_name: str, *,
    limit: int = _CANDIDATE_LIMIT_DEFAULT, index: TaxonomyIndex | None = None,
) -> list[dict[str, Any]]:
    """Top-``limit`` nodes by trigram similarity to ``normalized_name``
    (one entry per node, scored by its best-matching name or alias)."""
    if not normalized_name:
        return []
    idx = index if index is not None else TaxonomyIndex.load(conn)
    return idx.candidates(normalized_name, limit)


def bulk_lexical_candidates(
    conn: Connection, names: list[str], *,
    limit: int = _CANDIDATE_LIMIT_DEFAULT, index: TaxonomyIndex | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """``lexical_candidates`` for many names against one index build. Returns a
    dict keyed by input name; names with no matches appear with an empty list."""
    out: dict[str, list[dict[str, Any]]] = {n: [] for n in names if n}
    if not out:
        return out
    idx = index if index is not None else TaxonomyIndex.load(conn)
    for n in out:
        out[n] = idx.candidates(n, limit)
    return out


def resolve_lexical(
    conn: Connection, normalized_name: str, *, index: TaxonomyIndex | None = None
) -> Phase1Result:
    cands = lexical_candidates(conn, normalized_name, limit=2, index=index)
    if not cands or cands[0]["similarity"] < LEXICAL_MIN_SIM:
        return Pending()
    if len(cands) >= 2:
        top1, top2 = cands[0]["similarity"], cands[1]["similarity"]
        if top2 > 0 and top1 < LEXICAL_RATIO * top2:
            return Pending()
    return Resolved(taxonomy_node_id=cands[0]["node_id"], source="lexical")

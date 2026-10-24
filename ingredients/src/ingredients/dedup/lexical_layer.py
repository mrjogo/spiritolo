"""Phase 1, Layer 2 — trigram similarity over cocktail_aliases.

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

from common.db import Connection
from common.text import TrigramIndex

from .types import Pending, Phase1Result, Resolved

LEXICAL_MIN_SIM = 0.75
LEXICAL_RATIO = 1.5

_CANDIDATE_LIMIT_DEFAULT = 20


class CocktailIndex:
    """Trigram index over cocktail aliases, keyed by canonical name."""

    def __init__(self, entries: list[tuple[str, str]]) -> None:
        self._index: TrigramIndex[str] = TrigramIndex(entries)

    @classmethod
    def load(cls, conn: Connection) -> "CocktailIndex":
        rows = conn.execute("select canonical_name, alias from cocktail_aliases").fetchall()
        return cls([(r[0], r[1]) for r in rows])

    def candidates(self, normalized_name: str, limit: int) -> list[dict[str, Any]]:
        return [
            {"canonical_name": canonical, "similarity": sim}
            for canonical, sim in self._index.top(normalized_name, limit)
        ]


def lexical_candidates(
    conn: Connection, normalized_name: str, *,
    limit: int = _CANDIDATE_LIMIT_DEFAULT, index: CocktailIndex | None = None,
) -> list[dict[str, Any]]:
    if not normalized_name:
        return []
    idx = index if index is not None else CocktailIndex.load(conn)
    return idx.candidates(normalized_name, limit)


def resolve_lexical(
    conn: Connection, normalized_name: str, *, index: CocktailIndex | None = None
) -> Phase1Result:
    cands = lexical_candidates(conn, normalized_name, limit=2, index=index)
    if not cands or cands[0]["similarity"] < LEXICAL_MIN_SIM:
        return Pending()
    if len(cands) >= 2:
        top1, top2 = cands[0]["similarity"], cands[1]["similarity"]
        if top2 > 0 and top1 < LEXICAL_RATIO * top2:
            return Pending()
    return Resolved(canonical_name=cands[0]["canonical_name"], source="lexical")

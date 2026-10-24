"""Trigram similarity, pg_trgm-compatible.

The mapping and dedup lexical layers were tuned against Postgres's
``similarity()`` (``LEXICAL_MIN_SIM = 0.75`` etc.). This reproduces pg_trgm's
definition exactly so those thresholds carry over unchanged:

- lowercase, split into words on non-alphanumerics;
- each word is padded with two spaces in front and one behind;
- every 3-character window of each padded word is a trigram;
- similarity is Jaccard: ``|A ∩ B| / |A ∪ B|`` over the trigram sets.

``TrigramIndex`` is the in-memory analogue of a GIN index: build it once over
the few thousand taxonomy names and ask for the top-k matches per query. It is
faster than the SQL path was and needs no extension.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable, Hashable
from typing import Generic, TypeVar

_WORD = re.compile(r"[^0-9a-z]+")

K = TypeVar("K", bound=Hashable)


def trigrams(text: str | None) -> frozenset[str]:
    """pg_trgm's trigram set for ``text`` (empty for empty/None input)."""
    if not text:
        return frozenset()
    out: set[str] = set()
    for word in _WORD.split(text.lower()):
        if not word:
            continue
        padded = f"  {word} "
        for i in range(len(padded) - 2):
            out.add(padded[i : i + 3])
    return frozenset(out)


def similarity(a: str | None, b: str | None) -> float:
    """pg_trgm ``similarity(a, b)``: Jaccard over trigram sets, 0.0 when either
    side has none."""
    ta, tb = trigrams(a), trigrams(b)
    if not ta or not tb:
        return 0.0
    inter = len(ta & tb)
    if inter == 0:
        return 0.0
    return inter / len(ta | tb)


class TrigramIndex(Generic[K]):
    """Inverted trigram index over ``(key, text)`` entries.

    ``top(query, k)`` returns ``[(key, best_similarity), ...]`` sorted by
    similarity descending, one entry per key (a key with several texts — a
    node's display name and its aliases — scores by its best text), matching
    the ``group by node_id ... max(sim)`` the SQL version did.
    """

    def __init__(self, entries: Iterable[tuple[K, str | None]] = ()) -> None:
        self._sets: list[tuple[K, frozenset[str]]] = []
        self._postings: dict[str, list[int]] = defaultdict(list)
        for key, text in entries:
            self.add(key, text)

    def add(self, key: K, text: str | None) -> None:
        tg = trigrams(text)
        if not tg:
            return
        idx = len(self._sets)
        self._sets.append((key, tg))
        for t in tg:
            self._postings[t].append(idx)

    def __len__(self) -> int:
        return len(self._sets)

    def top(self, query: str | None, k: int = 20, *, floor: float = 0.0) -> list[tuple[K, float]]:
        """Best ``k`` keys for ``query`` with similarity ``>= floor`` (and > 0)."""
        tq = trigrams(query)
        if not tq:
            return []
        shared: dict[int, int] = defaultdict(int)
        for t in tq:
            for idx in self._postings.get(t, ()):
                shared[idx] += 1
        best: dict[K, float] = {}
        nq = len(tq)
        for idx, inter in shared.items():
            key, tg = self._sets[idx]
            sim = inter / (nq + len(tg) - inter)
            if sim < floor:
                continue
            if sim > best.get(key, -1.0):
                best[key] = sim
        ranked = sorted(best.items(), key=lambda kv: (-kv[1], str(kv[0])))
        return ranked[:k]

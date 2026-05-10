"""Typed cascade results for cocktail-name resolution.

Mirrors the shape of mapping/types.py; the difference is that the resolved
value is a `canonical_name: str` rather than a `taxonomy_node_id: int`,
because cocktail names have no taxonomy node — they're the keys of an
alias-only universe.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

NormalizerSource = Literal[
    "alias", "lexical", "pending_llm", "pending_llm_tried", "llm", "abstain",
]


@dataclass(frozen=True)
class Resolved:
    canonical_name: str
    source: NormalizerSource     # 'alias' | 'lexical' | 'llm'


@dataclass(frozen=True)
class Pending:
    """Phase 1 didn't resolve; row is queued for Phase 2."""


@dataclass(frozen=True)
class Abstain:
    """Phase 2 considered the name and declined to assign a canonical."""


@dataclass(frozen=True)
class NameProposal:
    """LLM proposed a new canonical name not yet in cocktail_aliases.

    The orchestrator auto-adds the alias with source='llm' and emits the
    Resolved result downstream. Hallucination concerns are surfaced via
    the audit pass, not via a human-review queue (form-style proposals
    aren't needed at v1; see spec).
    """
    canonical_name: str


Phase1Result = Resolved | Pending
Phase2Result = Resolved | NameProposal | Abstain

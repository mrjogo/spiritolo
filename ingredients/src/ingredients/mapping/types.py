"""Typed cascade results. Layer modules return one of these; the
orchestrator records the chosen variant on each recipe_ingredients row.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

# Source values match the recipe_ingredients.mapper_source check constraint.
MapperSource = Literal[
    "alias", "lexical", "pending_llm", "pending_llm_tried", "llm", "abstain",
]


@dataclass(frozen=True)
class Resolved:
    """The string mapped to a node."""
    taxonomy_node_id: int
    source: MapperSource          # 'alias' | 'lexical' | 'llm'


@dataclass(frozen=True)
class Pending:
    """Phase 1 didn't resolve; row will be picked up by Phase 2."""


@dataclass(frozen=True)
class Abstain:
    """Phase 2 considered the string and declined; no node assigned."""


# Phase 1 layer return type.
Phase1Result = Resolved | Pending

"""Per-stage review adapters.

A stage joins the review system with one adapter: it declares the `entity_kind`
its reviews point at and how to `load_context` (the current live output + machine
context the ReviewCard renders). The *write* side of a resolved override is the
SQL `apply_review()` function, so it is reachable from both the web RPC (no
backend) and the worker — the adapter here is the read/metadata side.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class StageReviewAdapter(Protocol):
    stage: str
    entity_kind: str

    def load_context(self, conn: Any, entity_id: str) -> dict[str, Any]:
        """Current live output + machine context for `entity_id`, for the card."""
        ...


ADAPTERS: dict[str, StageReviewAdapter] = {}


def register(adapter: StageReviewAdapter) -> None:
    """Register `adapter` under its `stage` (idempotent — last wins)."""
    ADAPTERS[adapter.stage] = adapter


def adapter_for(stage: str) -> StageReviewAdapter:
    """The adapter registered for `stage`. Raises KeyError if none."""
    return ADAPTERS[stage]

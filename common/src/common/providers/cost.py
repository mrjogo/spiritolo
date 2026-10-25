"""Per-call cost for the provider chain, priced from ``common.providers.pricing``.

A call's cost is its pack's token estimate at the model's price in force when
the call is made (fractional cents: a packed call on a cheap model costs well
under a cent). The `deterministic` heuristic tier and the local LLM cost nothing
and are *not metered*. A provider may self-report its per-call cost via a
`cost_per_call` attribute (the fake seam uses this so tests control cost).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from . import pricing


def call_cost_cents(
    provider_id: str,
    provider: Any | None = None,
    *,
    items: int | None = None,
    now: datetime | None = None,
) -> float:
    """Cents for one packed call of ``items`` items (a full default pack when
    omitted) on ``provider``'s model: self-reported `cost_per_call` wins, else
    the price table (0 for local and unknown providers)."""
    if provider is not None:
        self_reported = getattr(provider, "cost_per_call", None)
        if self_reported is not None:
            return self_reported
    model_id = getattr(provider, "model_id", None) if provider is not None else None
    n = pricing.DEFAULT_PACK_ITEMS if items is None else items
    return pricing.estimate_call_cents(
        provider_id, model_id,
        n * pricing.ITEM_INPUT_TOKENS, n * pricing.ITEM_OUTPUT_TOKENS, at=now,
    )


def is_metered(unit_cost_cents: float) -> bool:
    """A tier is metered iff each call costs money."""
    return unit_cost_cents > 0

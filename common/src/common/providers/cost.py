"""Per-provider unit-cost lookup for the provider chain.

A tier's cost is `calls * unit_cost`. The `deterministic` heuristic tier and the
local `ollama` LLM cost nothing and are *not metered*; hosted providers (openai,
claude, deepseek) carry a positive per-call cost and are metered. A provider may
self-report its per-call cost via a `cost_per_call` attribute (the fake seam
uses this so tests control cost); otherwise the id-keyed default table applies.
"""
from __future__ import annotations

from typing import Any

# Cents per provider.resolve call. Defaults only — real numbers are wired
# through config/self-report, not baked into stage code.
UNIT_COST_CENTS: dict[str, int] = {
    "deterministic": 0,
    "ollama": 0,
    "openai": 1,
    "claude": 2,
    "deepseek": 1,
}


def call_cost_cents(provider_id: str, provider: Any | None = None) -> int:
    """Per-call cost for a provider: self-reported `cost_per_call` wins, else
    the id-keyed default (0 for unknown ids)."""
    if provider is not None:
        self_reported = getattr(provider, "cost_per_call", None)
        if self_reported is not None:
            return int(self_reported)
    return UNIT_COST_CENTS.get(provider_id, 0)


def is_metered(unit_cost_cents: int) -> bool:
    """A tier is metered iff each call costs money."""
    return unit_cost_cents > 0

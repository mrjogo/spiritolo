"""Result shapes for a provider chain.

``TierResult`` is one tier's contribution (which ids it resolved, its call count
and cost, whether it was metered); ``ChainResult`` is the aggregate a chain's
``resolve`` returns. These are plain data shapes shared by the worker's
``ProviderChain`` and its tests — no chain logic lives here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class TierResult:
    provider_id: str
    kind: str  # 'deterministic' | 'local' | 'hosted'
    calls: int
    resolved_ids: tuple[str, ...]
    cost_cents: int
    metered: bool


@dataclass
class ChainResult:
    resolved: dict[str, Any]
    parked: list[str]
    cost_cents: int
    metered: bool
    tiers: list[TierResult] = field(default_factory=list)
    # Per-item LLM telemetry, keyed by item id. A stage whose job_item entity IS
    # the resolved LLM item (extract / combine / connect) reads these to persist
    # per-item tokens/cost/model onto the job_item, which the finalize roll-up
    # then sums to the parent job. All three default empty (a deterministic-only
    # or provider-less resolve populates none):
    # - ``per_item_tokens`` — {id: (prompt_tokens, completion_tokens)}, each
    #   packed call's usage split evenly across its items (remainder on the first).
    # - ``per_item_cost`` — {id: cost_cents}, each tier's cost split evenly across
    #   that tier's resolved ids (remainder on the first; free tiers contribute 0).
    # - ``per_item_model`` — {id: model_id} of the provider that resolved the id.
    per_item_tokens: dict[str, tuple[int | None, int | None]] = field(
        default_factory=dict
    )
    per_item_cost: dict[str, int] = field(default_factory=dict)
    per_item_model: dict[str, str] = field(default_factory=dict)

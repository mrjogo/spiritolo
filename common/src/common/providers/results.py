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

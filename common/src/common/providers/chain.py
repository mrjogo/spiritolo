"""run_chain — walk a stage's ordered provider tiers, short-circuiting on
resolve, packing LLM tiers, and aggregating cost + metered flags.

A tier is either:
  - deterministic: a pure `resolve_items(items) -> {id: output}` function
    (alias/lexical). Free, unmetered, no provider call.
  - LLM (local or hosted): the existing `LLMProvider` Protocol, driven through
    request packing. Local tiers cost nothing (metered=false); hosted tiers cost
    money per call (metered=true).

The returned `resolved[id]` is the exact structured output a downstream stage
stores and hashes — tier-independent, so the same item resolved deterministically
or by an LLM yields byte-identical stored output.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from . import cost, packing
from .config import StageChainConfig
from .packing import Item


@dataclass
class DeterministicProvider:
    """Adapter wrapping a stage's pure resolver as a chain tier.

    `resolve_fn(items)` returns {id: output} for the items it resolves and omits
    (or maps to None) the ones it abstains on — those fall through to the next
    tier.
    """

    resolve_fn: Callable[[list[Item]], dict[str, Any]]
    kind: str = "deterministic"

    def resolve_items(self, items: list[Item]) -> dict[str, Any]:
        return self.resolve_fn(items)


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


def run_chain(
    items: list[Item],
    config: StageChainConfig,
    providers: dict[str, Any],
    *,
    system_prompt: str = "",
) -> ChainResult:
    """Resolve `items` through `config.provider_ids` in order.

    Short-circuits: once every item is resolved, later tiers' providers are
    never touched. Returns the aggregate ChainResult.
    """
    pending: list[Item] = list(items)
    resolved: dict[str, Any] = {}
    tiers: list[TierResult] = []
    total_cost = 0
    any_metered = False

    for provider_id in config.provider_ids:
        if not pending:
            break  # short-circuit: nothing left to resolve
        provider = providers[provider_id]

        if hasattr(provider, "resolve_items"):
            tier_resolved = provider.resolve_items(pending)
            calls = 0
            tier_cost = 0
            metered = False
            kind = getattr(provider, "kind", "deterministic")
        else:
            unit = cost.call_cost_cents(provider_id, provider)
            tier_resolved, _parked, calls = packing.run_packed(
                provider, pending, config.pack_size, system_prompt=system_prompt
            )
            tier_cost = calls * unit
            metered = cost.is_metered(unit)
            kind = "hosted" if metered else "local"

        newly: list[str] = []
        for item_id, output in tier_resolved.items():
            if output is None:
                continue  # abstain
            resolved[item_id] = output
            newly.append(item_id)

        pending = [it for it in pending if it.id not in resolved]
        total_cost += tier_cost
        any_metered = any_metered or metered
        tiers.append(
            TierResult(
                provider_id=provider_id,
                kind=kind,
                calls=calls,
                resolved_ids=tuple(newly),
                cost_cents=tier_cost,
                metered=metered,
            )
        )

    return ChainResult(
        resolved=resolved,
        parked=[it.id for it in pending],
        cost_cents=total_cost,
        metered=any_metered,
        tiers=tiers,
    )

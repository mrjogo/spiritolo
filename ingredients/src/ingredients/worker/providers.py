"""Config-not-code provider chain for the worker.

``ProviderChain`` wires a stage's ordered provider tiers (from external config,
never DB schema) into a single ``resolve(items)`` call that:

- **short-circuits** — once every item is resolved, later tiers' providers are
  never touched;
- **packs** LLM tiers — many items per request, re-mapped to entity ids by
  custom id (order-independent), so a partial provider failure parks only the
  failed items;
- **meters cost** — before each metered call it charges the job's ``CostMeter``,
  which raises ``CostCapExceeded`` if the call would breach ``max_cost_cents``.
  Deterministic / local tiers are free and never consult the cap.

It reuses the ``common.providers`` primitives (cost table, request packing, the
``ChainResult``/``TierResult`` shapes) rather than re-deriving them — the worker
layer only adds per-call cost enforcement on top of the shared chain semantics.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from common.providers import ChainResult, TierResult, cost as _cost, packing as _packing
from common.providers.config import StageChainConfig, load_chain_configs
from common.providers.packing import Item

from ingredients.worker.cost import CostMeter


@dataclass
class ProviderChain:
    """A stage's provider chain, bound to an optional per-job cost meter.

    ``providers`` maps a provider id to its implementation — a deterministic
    tier exposes ``resolve_items(items) -> {id: output}``; an LLM tier exposes
    the ``LLMProvider.resolve(*, system_prompt, user_prompt)`` protocol and is
    driven through packing. ``meter`` (default: unbounded) enforces the cost cap.
    """

    config: StageChainConfig
    providers: dict[str, Any]
    meter: CostMeter = field(default_factory=CostMeter)

    def resolve(self, items: list[Item], *, system_prompt: str = "") -> ChainResult:
        """Resolve ``items`` through the configured tiers in order.

        Returns a ``ChainResult`` (resolved map, parked ids, aggregate cost,
        metered flag, per-tier breakdown). May raise ``CostCapExceeded`` from a
        metered tier — see module docstring.
        """
        pending: list[Item] = list(items)
        resolved: dict[str, Any] = {}
        parked: list[str] = []
        tiers: list[TierResult] = []
        total_cost = 0
        any_metered = False

        for provider_id in self.config.provider_ids:
            if not pending:
                break  # short-circuit: everything resolved
            provider = self.providers[provider_id]

            if hasattr(provider, "resolve_items"):
                newly = self._run_deterministic(provider, pending, resolved)
                tiers.append(
                    TierResult(
                        provider_id=provider_id,
                        kind=getattr(provider, "kind", "deterministic"),
                        calls=0,
                        resolved_ids=tuple(newly),
                        cost_cents=0,
                        metered=False,
                    )
                )
            else:
                newly, tier_parked, calls, tier_cost, metered = self._run_llm(
                    provider_id, provider, pending, resolved, system_prompt
                )
                parked.extend(tier_parked)
                total_cost += tier_cost
                any_metered = any_metered or metered
                tiers.append(
                    TierResult(
                        provider_id=provider_id,
                        kind="hosted" if metered else "local",
                        calls=calls,
                        resolved_ids=tuple(newly),
                        cost_cents=tier_cost,
                        metered=metered,
                    )
                )

            pending = [
                it for it in pending
                if it.id not in resolved and it.id not in parked
            ]

        # Anything no tier resolved or parked falls through as unresolved.
        parked.extend(it.id for it in pending if it.id not in parked)
        return ChainResult(
            resolved=resolved,
            parked=parked,
            cost_cents=total_cost,
            metered=any_metered,
            tiers=tiers,
        )

    @staticmethod
    def _run_deterministic(
        provider: Any, pending: list[Item], resolved: dict[str, Any]
    ) -> list[str]:
        newly: list[str] = []
        for item_id, output in provider.resolve_items(pending).items():
            if output is None:
                continue  # abstain -> fall through
            resolved[item_id] = output
            newly.append(item_id)
        return newly

    def _run_llm(
        self,
        provider_id: str,
        provider: Any,
        pending: list[Item],
        resolved: dict[str, Any],
        system_prompt: str,
    ) -> tuple[list[str], list[str], int, int, bool]:
        unit = _cost.call_cost_cents(provider_id, provider)
        metered = _cost.is_metered(unit)
        newly: list[str] = []
        parked: list[str] = []
        calls = 0
        tier_cost = 0

        for group in _packing.chunk(pending, self.config.pack_size):
            if metered:
                # Cost cap is enforced BEFORE the call, so a breaching chunk is
                # never spent and its items stay unprocessed (raises out).
                self.meter.charge(unit)
            result = provider.resolve(
                system_prompt=system_prompt,
                user_prompt=_packing.encode_request(group),
            )
            calls += 1
            tier_cost += unit
            answers = _packing.decode_response(result.raw_text)
            for it in group:
                if it.id in answers:
                    resolved[it.id] = answers[it.id]
                    newly.append(it.id)
                else:
                    parked.append(it.id)  # dropped/errored -> park this item

        return newly, parked, calls, tier_cost, metered


def build_chain(
    stage: str,
    *,
    configs: dict[str, StageChainConfig],
    provider_impls: dict[str, Any],
    meter: CostMeter | None = None,
) -> ProviderChain:
    """Build the ``ProviderChain`` for ``stage`` from external config.

    ``configs`` is the parsed ``{stage -> StageChainConfig}`` map (see
    ``load_configs``); ``provider_impls`` is the flat ``{provider_id -> impl}``
    registry the chain references by id. ``meter`` binds the per-job cost cap
    (default: unbounded).
    """
    return ProviderChain(
        config=configs[stage],
        providers=provider_impls,
        meter=meter if meter is not None else CostMeter(),
    )


def load_configs(raw: dict[str, dict[str, Any]]) -> dict[str, StageChainConfig]:
    """Parse the external chain config (``{stage: {providers, pack_size}}``).

    A thin pass-through to ``common.providers.load_chain_configs`` so callers
    build the worker's config from the same small dict/JSON the owner rewires.
    """
    return load_chain_configs(raw)

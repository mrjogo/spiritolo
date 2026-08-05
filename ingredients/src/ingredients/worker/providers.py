"""The worker's run-driven provider chain.

A run selects its LLM tier at assembly time (``jobs.llm_provider`` +
``jobs.llm_model``); the worker builds exactly that one provider and wraps it in
a ``ProviderChain``. Deterministic tiers (alias / lexical) are NOT wired here —
they live inside each stage_fn (e.g. ``map._resolve_names``), which resolves
what it can deterministically first and only hands the residue to the chain. So
the chain is a single LLM tier plus per-call cost enforcement.

``ProviderChain.resolve(items)``:

- **short-circuits** — once every item is resolved, later tiers are never
  touched (with one LLM tier this simply means an empty ``items`` is a no-op);
- **packs** LLM tiers — many items per request, re-mapped to entity ids by
  custom id (order-independent), so a partial provider failure parks only the
  failed items;
- **meters cost** — before each metered call it charges the job's ``CostMeter``,
  which raises ``CostCapExceeded`` if the call would breach ``max_cost_cents``.
  Local (``ollama``) tiers are free and never consult the cap.

It reuses the ``common.providers`` primitives (cost table, request packing, the
``ChainResult`` / ``TierResult`` shapes) rather than re-deriving them.

``pack_size`` — how many items an LLM tier bundles per call — is a per-stage code
constant (``STAGE_PACK_SIZE``, default ``DEFAULT_PACK_SIZE``), the one knob the
old external chain config carried that survives.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from common.llm.provider import ProviderResult
from common.providers import ChainResult, TierResult, cost as _cost, packing as _packing
from common.providers.packing import Item

from ingredients.worker.cost import CostMeter

log = logging.getLogger("ingredients.worker.providers")

# LLM call resilience. A hosted provider call fails either transiently (rate
# limit / 5xx / timeout) or fatally (auth / billing / bad request). A transient
# failure is retried a few times with exponential backoff; if it still fails,
# that one pack's items are PARKED and the run continues — one blip must not
# lose the other thousands of items. A *fatal* error, or too many consecutive
# pack failures (the circuit breaker), aborts the whole run fast with a surfaced
# message rather than grinding every remaining pack into the same wall — this is
# what run #7's DeepSeek `402 Insufficient Balance` should have done.
_MAX_LLM_ATTEMPTS = 3
_BACKOFF_BASE_SECONDS = 2.0  # sleeps of 1s, 2s between attempts
_CONSECUTIVE_FAIL_ABORT = 3
_FATAL_STATUS_CODES = frozenset({400, 401, 402, 403, 404, 422})


class ProviderUnavailable(Exception):
    """The run's LLM provider is systemically unusable — a fatal auth/billing/
    config error, or a persistent failure that tripped the circuit breaker. The
    worker fails the run with this message rather than parking every pack."""


def _is_fatal(exc: Exception) -> bool:
    """A provider error not worth retrying — an explicit non-retryable status."""
    return getattr(exc, "status_code", None) in _FATAL_STATUS_CODES


def _provider_unavailable(provider_id: str, exc: Exception) -> "ProviderUnavailable":
    code = getattr(exc, "status_code", None)
    where = f"{provider_id} error" + (f" {code}" if code else "")
    return ProviderUnavailable(f"{where}: {exc}"[:500])


def _even_split(total: int | None, n: int) -> list[int | None]:
    """Split ``total`` into ``n`` integer parts, giving the whole remainder to
    the first part, so the parts sum back to exactly ``total``. A ``None`` total
    (the provider reported no usage) yields ``None`` parts."""
    if total is None or n <= 0:
        return [None] * n
    per, rem = divmod(total, n)
    return [per + rem if i == 0 else per for i in range(n)]


def _split_usage(
    ids: list[str], prompt_tokens: int | None, completion_tokens: int | None
) -> dict[str, tuple[int | None, int | None]]:
    """Attribute one packed call's token usage evenly across its ``ids`` (the
    remainder on the first id), so the per-item counts sum to the call totals.
    Returns ``{id: (prompt_tokens, completion_tokens)}``."""
    p = _even_split(prompt_tokens, len(ids))
    c = _even_split(completion_tokens, len(ids))
    return {iid: (p[i], c[i]) for i, iid in enumerate(ids)}


def _split_cost(total: int, ids: Sequence[str]) -> dict[str, int]:
    """Split a tier's ``total`` cost_cents evenly across the ids it resolved (the
    whole remainder on the first id), so the per-item costs sum to the tier total.
    A free tier (``total == 0``) gives every id 0."""
    parts = _even_split(total, len(ids))
    return {iid: (parts[i] or 0) for i, iid in enumerate(ids)}

# How many items an LLM tier packs per call, per stage. LLM stages default to
# DEFAULT_PACK_SIZE; a stage not listed here uses the default. (This is the one
# knob the removed external chain config carried — now a code constant.)
DEFAULT_PACK_SIZE = 10
STAGE_PACK_SIZE: dict[str, int] = {
    "extract-recipe": DEFAULT_PACK_SIZE,
    "parse-ingredients": DEFAULT_PACK_SIZE,
    "map-ingredient": DEFAULT_PACK_SIZE,
    "combine-nodes": DEFAULT_PACK_SIZE,
    "connect-nodes": DEFAULT_PACK_SIZE,
    "convert-steps": DEFAULT_PACK_SIZE,
    "cluster-recipes": DEFAULT_PACK_SIZE,
    "export-recipegf": DEFAULT_PACK_SIZE,
}


def pack_size_for(stage: str) -> int:
    """The LLM pack size for ``stage`` (``DEFAULT_PACK_SIZE`` if unlisted)."""
    return STAGE_PACK_SIZE.get(stage, DEFAULT_PACK_SIZE)


@dataclass
class ProviderChain:
    """A run's provider chain, bound to an optional per-job cost meter.

    ``tiers`` is an ordered list of ``(provider_id, impl)`` pairs — keeping the
    ``provider_id`` alongside the impl so cost metering can look up the per-call
    cost. A deterministic tier's impl exposes ``resolve_items(items) -> {id:
    output}``; an LLM tier's impl exposes the ``LLMProvider.resolve(*,
    system_prompt, user_prompt)`` protocol and is driven through packing.
    ``pack_size`` governs LLM bundling; ``meter`` (default: unbounded) enforces
    the cost cap.
    """

    tiers: list[tuple[str, Any]]
    pack_size: int = DEFAULT_PACK_SIZE
    meter: CostMeter = field(default_factory=CostMeter)
    # Cooperative-cancel hook: when it returns True the LLM tier stops between
    # packs, parking the remaining items. The worker wires this to the run's
    # cancel signal so a cancelled run stops promptly instead of draining every
    # pack. None (the default) means never stop.
    should_stop: Callable[[], bool] | None = None

    def resolve(self, items: list[Item], *, system_prompt: str = "") -> ChainResult:
        """Resolve ``items`` through the tiers in order.

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
        # Per-item LLM telemetry a stage persists onto each job_item (id-keyed):
        # token usage, the tier-cost split across a tier's resolved ids, and the
        # model that resolved each id. See ChainResult for the split semantics.
        per_item_tokens: dict[str, tuple[int | None, int | None]] = {}
        per_item_cost: dict[str, int] = {}
        per_item_model: dict[str, str] = {}

        for provider_id, provider in self.tiers:
            if not pending:
                break  # short-circuit: everything resolved

            if hasattr(provider, "resolve_items"):
                newly = self._run_deterministic(provider, pending, resolved)
                tier = TierResult(
                    provider_id=provider_id,
                    kind=getattr(provider, "kind", "deterministic"),
                    calls=0,
                    resolved_ids=tuple(newly),
                    cost_cents=0,
                    metered=False,
                )
            else:
                (
                    newly, tier_parked, calls, tier_cost, metered,
                    tier_tokens, tier_models,
                ) = self._run_llm(
                    provider_id, provider, pending, resolved, system_prompt
                )
                parked.extend(tier_parked)
                total_cost += tier_cost
                any_metered = any_metered or metered
                per_item_tokens.update(tier_tokens)
                per_item_model.update(tier_models)
                tier = TierResult(
                    provider_id=provider_id,
                    kind="hosted" if metered else "local",
                    calls=calls,
                    resolved_ids=tuple(newly),
                    cost_cents=tier_cost,
                    metered=metered,
                )
            tiers.append(tier)
            # Split this tier's cost evenly across the ids it resolved (0 each for
            # a free/deterministic tier), so per-item costs sum to the tier total.
            per_item_cost.update(_split_cost(tier.cost_cents, tier.resolved_ids))

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
            per_item_tokens=per_item_tokens,
            per_item_cost=per_item_cost,
            per_item_model=per_item_model,
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
    ) -> tuple[
        list[str], list[str], int, int, bool,
        dict[str, tuple[int | None, int | None]], dict[str, str],
    ]:
        unit = _cost.call_cost_cents(provider_id, provider)
        metered = _cost.is_metered(unit)
        newly: list[str] = []
        parked: list[str] = []
        calls = 0
        tier_cost = 0
        consecutive_failures = 0
        tokens: dict[str, tuple[int | None, int | None]] = {}
        models: dict[str, str] = {}

        for group in _packing.chunk(pending, self.pack_size):
            if self.should_stop is not None and self.should_stop():
                # Cancel requested: park the rest of the residue and stop. What's
                # already resolved this tier stands; the parked items stay
                # pending for a later re-run.
                parked.extend(it.id for it in group)
                break
            if metered:
                # Cost cap is enforced BEFORE the call, so a breaching chunk is
                # never spent and its items stay unprocessed (raises out).
                self.meter.charge(unit)
            try:
                call = self._resolve_group(provider, group, system_prompt)
            except Exception as exc:  # noqa: BLE001 - the provider transport surface
                # Fatal (auth/billing/config) -> abort the run fast, message and
                # all. Otherwise park this pack and keep going, but trip the
                # breaker if failures pile up back-to-back (systemic outage).
                if _is_fatal(exc):
                    raise _provider_unavailable(provider_id, exc) from exc
                consecutive_failures += 1
                parked.extend(it.id for it in group)
                log.warning("LLM pack of %d items failed after retries: %s", len(group), exc)
                if consecutive_failures >= _CONSECUTIVE_FAIL_ABORT:
                    raise _provider_unavailable(provider_id, exc) from exc
                continue

            consecutive_failures = 0
            calls += 1
            tier_cost += unit
            # Attribute this packed call's token usage evenly across its items,
            # so the per-item counts sum to exactly the call totals.
            tokens.update(
                _split_usage(
                    [it.id for it in group],
                    call.prompt_tokens,
                    call.completion_tokens,
                )
            )
            answers = _packing.decode_response(call.raw_text)
            for it in group:
                if it.id in answers:
                    resolved[it.id] = answers[it.id]
                    newly.append(it.id)
                    models[it.id] = call.model_id  # the model that answered this id
                else:
                    parked.append(it.id)  # dropped/errored -> park this item

        return newly, parked, calls, tier_cost, metered, tokens, models

    @staticmethod
    def _resolve_group(
        provider: Any, group: list[Item], system_prompt: str
    ) -> ProviderResult:
        """One packed provider call, with bounded exponential backoff on
        transient errors. A fatal error (see ``_is_fatal``) is re-raised
        immediately without retrying; a transient error is retried up to
        ``_MAX_LLM_ATTEMPTS`` and then re-raised for the caller to park. Returns
        the full ``ProviderResult`` so the caller can read its token usage."""
        user_prompt = _packing.encode_request(group)
        for attempt in range(_MAX_LLM_ATTEMPTS):
            try:
                return provider.resolve(
                    system_prompt=system_prompt, user_prompt=user_prompt
                )
            except Exception as exc:  # noqa: BLE001 - the provider transport surface
                if _is_fatal(exc) or attempt + 1 == _MAX_LLM_ATTEMPTS:
                    raise
                time.sleep(_BACKOFF_BASE_SECONDS**attempt)
        raise AssertionError("unreachable")  # pragma: no cover
